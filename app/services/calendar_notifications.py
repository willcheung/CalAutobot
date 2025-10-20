import logging
from typing import Optional

from app.services.gmail_service import gmail_service

logger = logging.getLogger(__name__)


OWNER_ALERT_MESSAGES = {
    "availability_fetch_error": "I couldn't load your calendar availability for the latest request.",
    "availability_verify_error": "I couldn't confirm that the selected meeting slot is still available.",
    "availability_refresh_error": "I couldn't refresh your up-to-date availability from Google Calendar.",
    "calendar_access_error": "I couldn't access Google Calendar to manage events. Please reconnect your account.",
}


def notify_owner_calendar_issue(user, note: Optional[str]):
    if not note or note not in OWNER_ALERT_MESSAGES:
        return

    owner_email = getattr(user, "email", None)
    if not owner_email:
        return

    owner_name = getattr(user, "username", None) or owner_email
    message = OWNER_ALERT_MESSAGES[note]
    subject = "Action needed: Restore Google Calendar access"
    body = (
        f"Hi {owner_name},\n\n"
        f"This is Cal. {message} Please visit Settings → Calendars "
        "to reconnect Google Calendar access so I can keep scheduling meetings for you.\n\n"
        "You can go straight there at https://calautobot.com/settings/calendars\n\n"
        "Thanks,\nCal"
    )

    try:
        gmail_service.send_email(owner_email, subject, text_body=body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unable to notify owner about calendar issue: %s", exc)

