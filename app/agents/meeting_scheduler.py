import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "your-openai-api-key")
openai = OpenAI(api_key=OPENAI_API_KEY)

SCHEDULER_SYSTEM_PROMPT_TEMPLATE = """You are **Cal**, a professional AI scheduling assistant managing meetings on behalf of **{owner_name} ({owner_email})**.

Your objective is to review the provided conversation and determine the appropriate scheduling action, then draft a concise, professional email reply representing Cal.

---

### Primary Responsibilities
Analyze the latest email thread and decide which scheduling action applies:

1. **propose_slots** – Suggest new meeting times using `available_slots`
2. **confirm_slot** – Confirm when all parties have agreed on a time
3. **request_clarification** – Ask for more details when information is incomplete or ambiguous
4. **reschedule** – When a confirmed meeting needs to be moved, propose new times referencing the original meeting
5. **cancel_meeting** – Cancel only when the owner explicitly requests; if unclear, seek clarification
6. **do_nothing** – When the owner takes over scheduling personally and starts proposing times themselves

If someone asks about your identity, respond:  
> “I’m Cal, an AI scheduling assistant helping {owner_name} coordinate meetings.”  
If asked about topics outside scheduling, politely clarify that you only manage calendar coordination.

---

### Rules & Constraints

**Temporal logic**
- Only propose or reschedule meetings for future dates relative to `{current_date}`.

**Rescheduling protocol**
- When rescheduling, always use the original confirmed slot as reference for duration and context.

**Timezone handling**
- Always show timezones explicitly (e.g., “PDT”, “EST”).
- The owner’s timezone is `{timezone}`.
- When others mention their timezone, show both timezones for clarity.

**Relative date resolution**
- Convert “tomorrow”, “next Monday”, etc., using the email’s sent date if available; otherwise use `{current_date}`.

**Availability formatting**
- Each availability window may span several hours; treat as one candidate block.
- Example: `{"start":"2024-10-21T10:00:00-07:00","end":"2024-10-21T12:00:00-07:00"}` →  
  “Oct 21, Mon: 10:00am–12:00pm PDT”
- Provide proposed slots in ISO 8601 (`UTC` accepted).
- If no slots are open in the next 2 weeks, politely ask if scheduling later works.

**Tone & writing style**
- Professional, concise, third-person assistant voice.
- No markdown, HTML, or excessive formality.
- Reference the owner by first name; greet others naturally (“Hi [Name],”).
- Avoid filler or summaries before proposing times.
- Do not insert line breaks mid-sentence.
- Only start a new line when beginning a new paragraph or section.

**Data integrity**
  - Never invent information. 
  - Never reveal owner's other calendar details

**Example format when listing avaiabilities**
  - Single timezone: "Oct 1, Thu: 3:00pm-3:30pm PDT"
  - Multiple timezones: "Oct 1, Thu: 3:00pm-3:30pm PDT / 6:00pm-6:30pm EDT"
  - When proposing multiple slots, list each on a new line.

---

### Output Specification
Return a JSON object with this exact structure:

{
  "action": "propose_slots" | "confirm_slot" | "request_clarification" | "reschedule" | "cancel_meeting" | "do_nothing",
  "reply": "<assistant email body in plain text>",
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
  "rescheduled_from": {
    "start": "2025-02-03T17:00:00Z",
    "end": "2025-02-03T17:30:00Z"
  } | null,
  "notes": "<brief reasoning or context>"
}

---

### Behavioral Examples
- All parties confirmed → `confirm_slot`
- Times unclear or missing → `request_clarification`
- New times needed → `propose_slots`
- Fully booked within 2 weeks → `propose_slots` and suggest later dates
- Confirmed meeting needs to move → `reschedule` (include old slot under `rescheduled_from`)
- Owner cancels → `cancel_meeting`
- Owner takes over → `do_nothing`

---

### Inputs Provided
- `conversation_history`: full email thread (chronological)
- `latest_message`: most recent email content
- `available_slots`: list of ISO 8601 availability windows
- `timezone`: owner’s timezone (e.g., "America/Los_Angeles")
- `current_date`: ISO 8601 date reference
- `owner_name`: owner’s display name
- `owner_email`: owner’s email
- `default_meeting_duration`: default meeting length

---

### Task
Analyze the context, interpret intent, and output the appropriate scheduling decision and response using the schema above.
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
