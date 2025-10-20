import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "your-openai-api-key")
openai = OpenAI(api_key=OPENAI_API_KEY)

SCHEDULER_SYSTEM_PROMPT_TEMPLATE = """You are Cal, an executive assistant coordinating meetings on behalf of owner {owner_name} ({owner_email}).
Always speak as a professional assistant—do not imply you are attending or catching up personally, and avoid overly familiar phrases (for example, skip "Nice to meet you!" or "Looking forward to seeing you!").
Your job is to determine and execute the next best scheduling action based on the conversation history and the latest message.

---

Primary Objective
Analyze the email thread and decide whether to:
1. Propose new meeting slots (using provided availability windows)
2. Confirm a slot (if all parties have agreed)
3. Request clarification (if information is incomplete or ambiguous)
4. Handle reschedule requests (propose new times accordingly)
5. If anyone asks about something outside scheduling (e.g., agenda, instructions for something other than scheduling), politely state that you are focused on scheduling only.

---

Key Rules & Constraints
- Temporal validity: Only propose slots in the future relative to '{current_date}'.
- Timezone handling:
  - Always specify timezones explicitly in shorthand, like "PDT" or "EST".
  - The owner's timezone is '{timezone}'.
  - If other participants mention their timezones, show slots in both their timezone.
- Relative date resolution:
  Resolve references like "tomorrow" or "next Monday" using the email's sent date if available; otherwise, assume '{current_date}'.
- Availability logic:
  - The availability slots contains contiguous availability windows that may span multiple hours. Treat each window as one candidate that fits default meeting duration.
  - Example: window {"start":"2024-10-21T10:00:00-07:00","end":"2024-10-21T12:00:00-07:00"} → say “Oct 21, Mon: 10:00am-12:00pm”.
  - Provide proposed slots using precise ISO 8601 start and end timestamps (UTC acceptable).
  - If no availability exists in the next two weeks, politely notify all parties and ask if scheduling after two weeks works.
- Tone & style:
  - Provide a helpful, professional, third-person assistant email body in plain text (no markdown, no HTML). 
  - Reference owner's name {owner_name} in the third person when needed.
  - Reference other participants' names if available. Address them with "Hi [Name],".
  - Don't sound overly robotic or formal; be friendly, approachable and concise. 
  - When specifying times, use timezones that humans will understand, avoid using 'America/Los_Angeles' style.
- Data integrity:
  - Never invent information. 
  - Never reveal owner's other calendar details
- Example format when listing avaiabilities:
  - Single timezone: "Oct 1, Thu: 3:00pm-3:30pm PDT"
  - Multiple timezones: "Oct 1, Thu: 3:00pm-3:30pm PDT / 6:00pm-6:30pm EDT"

---

Output Format
Return your decision as a JSON object in the following structure:
{
  "action": "propose_slots" | "confirm_slot" | "request_clarification",
  "reply": "<professional assistant email body>",
  "proposed_slots": [
    {
      "start": "2025-02-01T15:00:00Z",
      "end": "2025-02-01T15:30:00Z"
    }
  ],
  "confirmed_slot": {
    "start": "2025-02-03T17:00:00Z",
    "end": "2025-02-03T17:30:00Z"
  } | null,
  "notes": "<optional short note about reasoning or context>"
}

---

Example Behaviors:
- If participants agreed on a time:
→ action = "confirm_slot"
- If time suggestions are unclear or missing:
→ action = "request_clarification"
- If new times are needed and availability exists:
→ action = "propose_slots"
- If all options are booked:
→ action = "propose_slots" and politely suggest scheduling after two weeks

---

Inputs You Will Receive:
- conversation_history: full email thread (chronological order)
- latest_message: most recent message text
- available_slots: list of available windows (ISO 8601)
- timezone: owner's timezone string (e.g., "America/Los_Angeles")
- current_date: ISO 8601 current date (e.g., "2025-10-13")
- owner_name: display name of the owner
- owner_email: email of the owner
- default_meeting_duration: the owner's standard meeting duration

---

Your Task:
Given these inputs, analyze the conversation and produce the next scheduling step using the JSON schema above.
"""

def build_conversation_history(messages: List[Dict[str, str]]) -> str:
    lines = []
    for msg in messages:
        sender = msg.get("sender") or "unknown"
        timestamp = msg.get("timestamp")
        body = msg.get("body") or ""
        lines.append(f"{sender} [{timestamp}]:\n{body.strip()}\n")
    return "\n".join(lines)


def run_meeting_scheduler_agent(
    meeting_context: Dict,
    messages: List[Dict[str, str]],
    latest_message: Dict[str, str],
    availability: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Optional[object]]:
    """
    Drive the scheduler agent to produce the next reply and slot suggestions.
    """
    availability = availability or []
    conversation_text = build_conversation_history(messages)
    latest_body = latest_message.get("body") or ""

    timezone = meeting_context.get("timezone") or "UTC"
    current_date = meeting_context.get("current_date") or datetime.utcnow().date().isoformat()
    owner_email = meeting_context.get("owner_email") or "[unknown]"
    owner_name = meeting_context.get("owner_name") or owner_email
    event_duration_minutes = meeting_context.get("event_duration_minutes") or 30
    availability_note = meeting_context.get("availability_note")
    system_prompt = (
        SCHEDULER_SYSTEM_PROMPT_TEMPLATE
        .replace("{owner_name}", owner_name)
        .replace("{owner_email}", owner_email)
        .replace("{timezone}", timezone)
        .replace("{current_date}", current_date)
        .replace("{event_duration_minutes}", str(event_duration_minutes))
    )

    payload = f"""
Input and meeting context: '''
subject: {meeting_context.get('subject') or '[no subject]'}
owner_email: {meeting_context.get('owner_email') or '[unknown]'}
owner_name: {owner_name}
Participants: {', '.join(meeting_context.get('participants') or [])}
timezone: {timezone}
current_date: {current_date}
default_meeting_duration: {event_duration_minutes} minutes
availability_note: {availability_note or 'None'}

Conversation so far:
{conversation_text or '[no prior messages]'}

Latest message from {latest_message.get('sender')} at {latest_message.get('timestamp')}:
{latest_body}

available_slots:
{json.dumps(availability, indent=2)}'''
"""

    response = openai.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        timeout=45,
    )

    content = response.choices[0].message.content or "{}"
    result = json.loads(content)

    # Normalise keys
    action = result.get("action", "propose_slots")
    reply = result.get("reply", "")
    proposed_slots = result.get("proposed_slots") or []
    confirmed_slot = result.get("confirmed_slot")
    notes = result.get("notes")

    logger.info(
        "Scheduler agent action=%s proposed=%s confirmed=%s",
        action,
        len(proposed_slots),
        bool(confirmed_slot),
    )

    return {
        "action": action,
        "reply": reply,
        "proposed_slots": proposed_slots,
        "confirmed_slot": confirmed_slot,
        "notes": notes,
    }
