from datetime import datetime, timedelta
from typing import Optional

from app import db
from app.helpers.text_processing import sanitize_text_for_db
from app.models import Event, EventType, User
from app.services.google_calendar import create_calendar_event


def create_booking_event(
    user: User,
    event_type: EventType,
    start_dt: datetime,
    invitee_name: str,
    invitee_email: str,
    notes: Optional[str] = None,
) -> Event:
    """Create a calendar event and persist it in the Event table."""
    end_dt = start_dt + timedelta(minutes=event_type.duration_minutes)

    description_parts = [event_type.description or ""]
    if notes:
        description_parts.append(notes.strip())
    description_parts.append("- Created by CalAutobot.com")
    description = "\n\n".join(part for part in description_parts if part)

    event_payload = {
        "event_name": event_type.title,
        "event_description": description,
        "start_datetime": start_dt.isoformat(),
        "end_datetime": end_dt.isoformat(),
        "location": None,
        "attendees": [invitee_email, user.email],
    }

    google_event_id = None
    try:
        google_event_id = create_calendar_event(user, event_payload)
    except Exception:
        google_event_id = None

    event = Event(
        user_id=user.id,
        event_name=sanitize_text_for_db(event_type.title),
        event_description=sanitize_text_for_db(description),
        start_date=start_dt.date(),
        start_time=start_dt.time(),
        end_date=end_dt.date(),
        end_time=end_dt.time(),
        start_datetime=start_dt.isoformat(),
        end_datetime=end_dt.isoformat(),
        is_synced=bool(google_event_id),
        google_event_id=google_event_id,
        location=None,
        duration_minutes=event_type.duration_minutes,
    )

    db.session.add(event)
    db.session.commit()
    return event
