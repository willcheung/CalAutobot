import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Set

import pytz

from app.helpers.datetime_utils import convert_to_timezone, ensure_timezone

from app import db
from app.models import Event, MeetingRequest, User
from app.services.gmail_service import gmail_service
from app.services.scheduling_agent import ASSISTANT_EMAILS

logger = logging.getLogger(__name__)


def _parse_event_start(event: Event) -> Optional[datetime]:
    iso_value = event.start_datetime
    if not iso_value:
        return None
    try:
        start_dt = datetime.fromisoformat(iso_value)
    except ValueError:
        try:
            start_dt = datetime.strptime(iso_value, "%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            logger.warning("Unable to parse event start for event %s (value=%s)", event.id, iso_value)
            return None
    if start_dt.tzinfo is None:
        return start_dt.replace(tzinfo=pytz.UTC)
    return start_dt


def _format_start_label(start_dt: datetime, timezone_name: Optional[str]) -> str:
    tz = ensure_timezone(timezone_name)
    local_dt = convert_to_timezone(start_dt, tz)
    if not local_dt:
        tz = pytz.UTC
        local_dt = convert_to_timezone(start_dt, tz) or start_dt
    return local_dt.strftime("%b %d (%a) at %I:%M %p %Z")


def _collect_recipient_emails(
    event: Event,
    meeting_request: Optional[MeetingRequest],
    owner_email: Optional[str],
) -> List[str]:
    recipients: Set[str] = set()
    if event.invitee_email:
        recipients.add(event.invitee_email.strip().lower())

    if meeting_request:
        for participant in meeting_request.participants:
            email = (participant.email or "").strip().lower()
            if email:
                recipients.add(email)

    if owner_email:
        owner_email = owner_email.strip().lower()

    recipients = {email for email in recipients if email and email not in ASSISTANT_EMAILS}
    if owner_email in recipients:
        recipients.discard(owner_email)

    return sorted(recipients)


def _compose_reminder_body(user, event: Event, start_label: str) -> str:
    owner_name = user.display_name if hasattr(user, "display_name") else (user.username or user.email)
    event_label = event.event_name or "your upcoming meeting"
    lines = [
        "Hi all,",
        "",
        f"This is Cal with a quick reminder about {event_label} on {start_label}.",
    ]
    if event.location:
        lines.append(f"Location: {event.location}")
    if event.conference_url:
        lines.append(f"Join link: {event.conference_url}")

    lines.extend(
        [
            "",
            "If you need to make changes, just reply to this email and I'll take care of it.",
            "",
            "Thanks!",
            "Cal",
        ]
    )
    return "\n".join(lines)


def _send_reminder_email(
    owner_email: Optional[str],
    participant_emails: Sequence[str],
    subject: str,
    body: str,
) -> bool:
    participant_list = [email for email in participant_emails if email]
    if participant_list:
        to_header = ", ".join(participant_list)
        cc_recipients = [owner_email] if owner_email else None
    elif owner_email:
        to_header = owner_email
        cc_recipients = None
    else:
        logger.warning("Skipping reminder email: no recipients available.")
        return False

    try:
        gmail_service.send_email(
            to_header,
            subject,
            text_body=body,
            thread_id=None,
            reply_to_message_id=None,
            cc_recipients=cc_recipients,
        )
        return True
    except Exception as exc:
        logger.error("Failed to send reminder email to %s: %s", to_header, exc)
        return False


def _should_send_reminder(now_utc: datetime, start_dt: datetime, lead_hours: int) -> bool:
    if lead_hours <= 0:
        return False
    send_at = start_dt - timedelta(hours=lead_hours)
    return send_at <= now_utc < start_dt


def send_due_reminders(limit: int = 25) -> Dict[str, int]:
    """
    Send reminder emails for events whose owners have opted in.
    """
    now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
    query = (
        Event.query.join(User, Event.user_id == User.id)
        .filter(
            Event.start_datetime.isnot(None),
            Event.status.in_(["scheduled", "confirmed"]),
            Event.reminder_sent_at.is_(None),
        )
        .order_by(Event.start_datetime.asc())
    )

    processed = 0
    sent = 0

    for event in query:
        user = event.user
        if not user or not user.meeting_reminder_lead_hours:
            continue

        lead_hours = max(0, user.meeting_reminder_lead_hours)
        start_dt = _parse_event_start(event)
        if not start_dt:
            continue

        if not _should_send_reminder(now_utc, start_dt, lead_hours):
            continue

        processed += 1
        meeting_request = event.meeting_request
        recipients = _collect_recipient_emails(event, meeting_request, user.email)
        start_label = _format_start_label(start_dt, user.timezone)
        subject = f"Reminder: {event.event_name or 'Upcoming meeting'}"
        body = _compose_reminder_body(user, event, start_label)

        success = _send_reminder_email(user.email, recipients, subject, body)
        if success:
            event.reminder_sent_at = datetime.utcnow()
            sent += 1

        if limit and processed >= limit:
            break

    db.session.commit()
    return {"processed": processed, "sent": sent}
