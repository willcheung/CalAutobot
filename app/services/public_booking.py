from datetime import datetime, timedelta
from typing import Optional
import logging
import secrets

from flask import has_request_context, url_for

from app import db
from app.helpers.text_processing import sanitize_text_for_db
from app.models import Event, EventType, User
from app.services.google_calendar import create_calendar_event, delete_calendar_event

logger = logging.getLogger(__name__)


class BookingCreationError(Exception):
    """Raised when a booking cannot be created."""


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

    booking_calendar_id = getattr(user, "default_booking_calendar_id", None)
    if not booking_calendar_id:
        raise BookingCreationError(
            "No booking calendar configured. Please choose one in Settings -> Calendars before scheduling."
        )

    event_payload = {
        "event_name": event_type.title,
        "start_datetime": start_dt.isoformat(),
        "end_datetime": end_dt.isoformat(),
        "location": None,
        "attendees": [invitee_email, user.email],
    }

    event = Event(
        user_id=user.id,
        event_name=sanitize_text_for_db(event_type.title),
        event_description=None,
        start_date=start_dt.date(),
        start_time=start_dt.time(),
        end_date=end_dt.date(),
        end_time=end_dt.time(),
        start_datetime=start_dt.isoformat(),
        end_datetime=end_dt.isoformat(),
        is_synced=False,
        google_event_id=None,
        location=None,
        duration_minutes=event_type.duration_minutes,
    )

    db.session.add(event)
    db.session.flush()

    token = None
    for _ in range(5):
        candidate = secrets.token_urlsafe(16)
        if not Event.query.filter_by(public_token=candidate).first():
            token = candidate
            break

    if token is None:
        db.session.rollback()
        raise BookingCreationError("We couldn't schedule that meeting. Please try again.")

    event.public_token = token

    location_value = getattr(event_type, "location", None) or getattr(user, "default_location", None)

    cancel_url = None
    reschedule_url = None

    if has_request_context():
        handle = getattr(user, "handle", None) or str(user.id)
        slug = getattr(event_type, "slug", None)
        if slug and handle:
            try:
                cancel_url = url_for(
                    "public_booking.cancel_booking",
                    handle=handle,
                    slug=slug,
                    token=event.public_token,
                    _external=True,
                )
                reschedule_url = url_for(
                    "public_booking.event_type_page",
                    handle=handle,
                    slug=slug,
                    former_slot=start_dt.isoformat(),
                    date=start_dt.date().isoformat(),
                    reschedule_token=event.public_token,
                    _external=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to build booking management links for booking %s: %s",
                    event.id,
                    exc,
                )
                cancel_url = None
                reschedule_url = None

    description_sections = []

    if notes:
        description_sections.append(notes.strip())

    description_sections.append(f"Event Name: {event_type.title}")

    location_line = location_value or "Not specified"
    description_sections.append(f"Location: {location_line}")

    if cancel_url:
        description_sections.append(f"Cancel: {cancel_url}")

    if reschedule_url:
        description_sections.append(f"Reschedule: {reschedule_url}")

    description_sections.append("Created by Cal Autobot")

    description = "\n\n".join(description_sections)

    event.event_description = sanitize_text_for_db(description)
    sanitized_location = sanitize_text_for_db(location_value) if location_value else None
    event.location = sanitized_location

    event_payload["event_description"] = description
    if sanitized_location:
        event_payload["location"] = sanitized_location

    try:
        google_event_id = create_calendar_event(
            user,
            event_payload,
            calendar_id=booking_calendar_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to create Google Calendar booking for user %s: %s",
            user.id,
            exc,
            exc_info=True,
        )
        db.session.rollback()
        raise BookingCreationError("We couldn't schedule that meeting. Please try again.") from exc

    event.is_synced = bool(google_event_id)
    event.google_event_id = google_event_id

    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("Database error while saving booking for user %s: %s", user.id, exc, exc_info=True)
        db.session.rollback()
        if google_event_id:
            try:
                delete_calendar_event(
                    user,
                    google_event_id,
                    calendar_id=booking_calendar_id,
                    use_extraction_calendar=False,
                )
            except Exception as cleanup_exc:  # noqa: BLE001
                logger.warning(
                    "Failed to roll back Google event %s after DB error: %s",
                    google_event_id,
                    cleanup_exc,
                )
        raise BookingCreationError("We couldn't schedule that meeting. Please try again.") from exc
    return event


def cancel_booking_event(user: User, event: Event) -> None:
    """Remove a booking from the database and Google Calendar if applicable."""
    if event.google_event_id:
        try:
            booking_calendar_id = getattr(user, "default_booking_calendar_id", None)
            delete_calendar_event(
                user,
                event.google_event_id,
                calendar_id=booking_calendar_id,
                use_extraction_calendar=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete Google Calendar event %s: %s", event.google_event_id, exc)

    db.session.delete(event)
    db.session.commit()
