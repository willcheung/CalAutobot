import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "your-openai-api-key")
openai = OpenAI(api_key=OPENAI_API_KEY)

SCHEDULER_SYSTEM_PROMPT = """You are Cal, a professional executive assistant specialized in scheduling and coordinating meetings via email.  
Your goal is to determine and execute the next best scheduling action based on the conversation history and the latest message.

---

Primary Objective
Analyze the email thread and decide whether to:
1. Propose new meeting slots (using provided availability windows)
2. Confirm a slot (if all parties have agreed)
3. Request clarification (if information is incomplete or ambiguous)
4. Acknowledge and handle reschedule requests (propose new times accordingly)

---

Key Rules & Constraints
- Temporal validity: Only propose slots in the future relative to '{current_date}'.
- Timezone handling:
  - Always specify timezones explicitly.
  - User's timezone is '{timezone}'.
  - If other participants mention their timezones, show slots in both their timezone and the user’s.
- Relative date resolution:  
  Resolve references like "tomorrow" or “next Monday” using the email's sent date if available; otherwise, assume `{current_date}`.
- Commute buffer:
  For in-person meetings, include a 30-minute commute buffer before the meeting start.
- Availability logic:
  - Use the provided availability roster to select valid windows.
  - Each slot must include precise ISO 8601 start and end times (UTC acceptable).
- Politeness & tone:
  Include a friendly, concise, professional email body in plain text (no markdown, no HTML).
- Data integrity:
  Never invent information. If no availability exists in the next two weeks, politely notify all parties and ask if scheduling **after two weeks** works.

---

Output Format
Return your decision as a JSON object in the following structure:
{
  "action": "propose_slots" | "confirm_slot" | "request_clarification",
  "reply": "<friendly email body text>",
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
→ politely suggest scheduling after two weeks.

---

Inputs You Will Receive:
- conversation_history: full email thread (chronological order)
- latest_message: most recent message text
- availability_roster: list of available windows (ISO 8601)
- timezone: user's timezone string (e.g., “America/Los_Angeles”)
- current_date: ISO 8601 current date (e.g., “2025-10-13”)

---

Your Task:
Given these inputs, analyze the conversation and produce the next scheduling step using the JSON schema above — ensuring your email body sounds natural, helpful, and contextually appropriate.
"""

# Hard-coded availability windows (UTC) for initial testing.
DEFAULT_AVAILABILITY = {
    "weekday_mornings": [
        {"start": "2025-02-03T16:00:00Z", "end": "2025-02-03T17:00:00Z"},
        {"start": "2025-02-04T17:00:00Z", "end": "2025-02-04T18:00:00Z"},
        {"start": "2025-02-05T16:00:00Z", "end": "2025-02-05T17:00:00Z"},
    ],
    "weekday_afternoons": [
        {"start": "2025-02-03T21:00:00Z", "end": "2025-02-03T22:00:00Z"},
        {"start": "2025-02-04T20:30:00Z", "end": "2025-02-04T21:30:00Z"},
    ],
}


def get_testing_availability(user_timezone: str = "UTC") -> List[Dict[str, str]]:
    """
    Retrieve hard-coded availability and filter out past times.
    """
    now = datetime.utcnow()
    slots = []
    for bucket in DEFAULT_AVAILABILITY.values():
        for slot in bucket:
            try:
                # Interpret as UTC
                start_dt = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(slot["end"].replace("Z", "+00:00"))
            except Exception:
                continue
            if start_dt >= now:
                slots.append(
                    {
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat(),
                    }
                )
    # Sort chronologically
    slots.sort(key=lambda s: s["start"])
    return slots[:5]


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
    availability = availability or get_testing_availability()
    conversation_text = build_conversation_history(messages)
    latest_body = latest_message.get("body") or ""

    timezone = meeting_context.get("timezone") or "UTC"
    current_date = meeting_context.get("current_date") or datetime.utcnow().date().isoformat()
    system_prompt = (
        SCHEDULER_SYSTEM_PROMPT
        .replace("{timezone}", timezone)
        .replace("{current_date}", current_date)
    )

    payload = f"""
Input: '''
Meeting context:
Subject: {meeting_context.get('subject') or '[no subject]'}
Owner: {meeting_context.get('owner_email') or '[unknown]'}
Participants: {', '.join(meeting_context.get('participants') or [])}
Status: {meeting_context.get('status') or 'pending'}
Timezone: {timezone}
Current date: {current_date}

Conversation so far:
{conversation_text or '[no prior messages]'}

Latest message from {latest_message.get('sender')} at {latest_message.get('timestamp')}:
{latest_body}

Available slots:
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
