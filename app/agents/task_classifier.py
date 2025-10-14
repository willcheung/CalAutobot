import logging
import os
from typing import Dict, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "your-openai-api-key")
openai = OpenAI(api_key=OPENAI_API_KEY)

ASSISTANT_EMAILS = {
    "go@calautobot.com",
    "cal@calautobot.com",
}

CLASSIFIER_SYSTEM_PROMPT = """You are the routing brain that classifies incoming email intent.
Decide whether an inbound email thread requires extracting events, coordinating a meeting, or needs no action.
Respond ONLY with a JSON object containing these keys:
{
  "task_type": "schedule_meeting" | "extract_event" | "no_action",
  "reason": "<short justification>"
}

Guidelines:
- Choose "schedule_meeting" when the sender asks the assistant to coordinate or reschedule a meeting and there are other human recipients in To/CC (besides the assistant aliases).
- Choose "extract_event" when the email contains itineraries, confirmations, agendas, or other details that should be turned into calendar events; a single-recipient message with a travel confirmation, PDF, or image attachment still counts.
- Choose "no_action" when the message is marketing, spam, a generic greeting, or anything unrelated to meetings or calendar events. Also use this when you truly cannot tell what the sender wants.
- If in doubt, prefer "no_action" to avoid false positives.
"""


def _normalized_addresses(addresses) -> set:
    normalized = set()
    for value in addresses or []:
        if not value:
            continue
        normalized.add(value.strip().lower())
    return normalized


def classify_email_task(email_metadata: Dict[str, Optional[str]]) -> str:
    """
    Determine which workflow should handle an inbound email.

    Args:
        email_metadata: Dict containing 'subject', 'body_text', 'from', 'to', 'cc'

    Returns:
        str: "schedule_meeting", "extract_event", or "no_action"
    """
    subject = (email_metadata.get("subject") or "").strip()
    body_text = (email_metadata.get("body_text") or "").strip()
    from_email = (email_metadata.get("from") or "").strip().lower()
    to_addresses = _normalized_addresses(email_metadata.get("to") or [])
    cc_addresses = _normalized_addresses(email_metadata.get("cc") or [])

    participants = (to_addresses | cc_addresses) - {""}
    external_participants = {
        addr for addr in participants if addr not in ASSISTANT_EMAILS
    }

    # Heuristic routing: if there are external participants beyond the assistant, schedule a meeting.
    if external_participants and any(
        keyword in body_text.lower()
        for keyword in ["schedule", "meet", "availability", "reschedule", "coordinat"]
    ):
        logger.debug(
            "Classifier heuristic routed to schedule_meeting based on participants: %s",
            external_participants,
        )
        return "schedule_meeting"

    # If the sender isn't a known assistant address but asks for help scheduling, escalate.
    scheduling_keywords = [
        "schedule",
        "find a time",
        "set up a time",
        "meet",
        "availability",
        "reschedule",
        "coordinate",
    ]
    if any(keyword in body_text.lower() for keyword in scheduling_keywords):
        logger.debug("Classifier heuristic detected scheduling keywords.")
        return "schedule_meeting"

    # Run lightweight LLM classification for ambiguous cases.
    prompt = f"""
Subject: {subject or '[no subject]'}
From: {from_email or '[unknown]'}
To: {', '.join(sorted(to_addresses)) or '[none]'}
Cc: {', '.join(sorted(cc_addresses)) or '[none]'}

Body:
{body_text[:2000]}
"""

    try:
        response = openai.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=20,
        )
        content = response.choices[0].message.content or "{}"
        import json

        result = json.loads(content)
        task_type = result.get("task_type", "no_action")
        reason = result.get("reason")
        logger.debug("Classifier LLM result: %s (%s)", task_type, reason)
        if task_type not in {"schedule_meeting", "extract_event", "no_action"}:
            return "no_action"
        return task_type
    except Exception as exc:
        logger.warning("Classifier LLM fallback failed: %s", exc)
        # Default to no action if classification fails.
        return "no_action"
