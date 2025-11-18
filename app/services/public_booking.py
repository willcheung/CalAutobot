from datetime import datetime, timedelta
from typing import Optional
import logging
import secrets

from flask import current_app, has_request_context, url_for
import sentry_sdk

from app import db
from app.helpers.text_processing import sanitize_text_for_db
from app.models import Event, EventType, User
from app.services.google_calendar import create_calendar_event, delete_calendar_event
from app.services.availability import clear_availability_cache
from app.services import contacts as contact_service

logger = logging.getLogger(__name__)


class BookingCreationError(Exception):
    """Raised when a booking cannot be created."""


def _create_calendly_booking(
    user: User,
    event_type: EventType,
    start_dt: datetime,
    end_dt: datetime,
    invitee_name: str,
    invitee_email: str,
    notes: Optional[str],
    source: str,
    meeting_request_id: Optional[int],
) -> Event:
    """Create a booking via Calendly API."""
    from app.services.calendly_api import CalendlyAPIClient
    import pytz
    import json

    logger.info(f"Creating Calendly booking for user {user.id}, event type {event_type.id}")

    # Ensure start_dt has timezone
    if start_dt.tzinfo is None:
        user_tz = pytz.timezone(user.timezone or "UTC")
        start_dt = user_tz.localize(start_dt)

    client = CalendlyAPIClient(user)

    # Parse location from event type if available
    # Stored JSON is the Calendly "locations" array (or single dict) from sync
    location_config = None
    if event_type.calendly_location_json:
        try:
            location_data = json.loads(event_type.calendly_location_json)
            # If we stored an array of locations, pick the first entry
            if isinstance(location_data, list) and location_data:
                location_data = location_data[0]

            if isinstance(location_data, dict):
                location_config = dict(location_data)
                if "type" not in location_config and "kind" in location_config:
                    location_config["type"] = location_config["kind"]
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse calendly_location_json for event type {event_type.id}")

    # Create booking via Calendly API
    calendly_response = client.create_invitee(
        event_type_uri=event_type.calendly_event_type_uri,
        start_time=start_dt,
        email=invitee_email,
        name=invitee_name,
        timezone=user.timezone or "UTC",
        questions_and_answers=[{"question": "Notes", "answer": notes}] if notes else None,
        location=location_config,
    )

    # Extract data from Calendly response
    event_uri = calendly_response.get("uri")
    event_name = calendly_response.get("name", event_type.title)
    event_start_time = calendly_response.get("start_time")
    event_end_time = calendly_response.get("end_time")
    location_data = calendly_response.get("location", {})
    invitees = calendly_response.get("invitees", [])

    # Extract location and conference URL
    location_str = None
    conference_url = None
    if location_data:
        location_type = location_data.get("type")
        if location_type == "physical":
            location_str = location_data.get("location")
        elif location_type in ["zoom", "google_meet", "microsoft_teams", "custom"]:
            conference_url = location_data.get("join_url")
            location_str = f"{location_type.replace('_', ' ').title()} Meeting"

    # Extract invitee URI
    invitee_uri = invitees[0].get("uri") if invitees else None

    # Parse datetimes
    from dateutil import parser as date_parser
    start_dt_parsed = date_parser.isoparse(event_start_time) if event_start_time else start_dt
    end_dt_parsed = date_parser.isoparse(event_end_time) if event_end_time else end_dt

    # Create Event record
    event = Event(
        user_id=user.id,
        event_name=sanitize_text_for_db(event_name),
        event_description=f"Booked via Calendly",
        start_date=start_dt_parsed.date(),
        start_time=start_dt_parsed.time(),
        end_date=end_dt_parsed.date(),
        end_time=end_dt_parsed.time(),
        start_datetime=start_dt_parsed.isoformat(),
        end_datetime=end_dt_parsed.isoformat(),
        location=sanitize_text_for_db(location_str) if location_str else None,
        conference_url=sanitize_text_for_db(conference_url) if conference_url else None,
        invitee_email=invitee_email.strip().lower() if invitee_email else None,
        invitee_name=invitee_name.strip() or None,
        calendly_event_uri=event_uri,
        calendly_invitee_uri=invitee_uri,
        calendly_last_synced_at=datetime.utcnow(),
        duration_minutes=event_type.duration_minutes,
        status="scheduled",
        source=source or "public_booking",
        is_synced=True,
        meeting_request_id=meeting_request_id,
    )

    # Generate public token
    token = None
    for _ in range(5):
        candidate = secrets.token_urlsafe(16)
        if not Event.query.filter_by(public_token=candidate).first():
            token = candidate
            break

    if token is None:
        raise BookingCreationError("We couldn't schedule that meeting. Please try again.")

    event.public_token = token

    db.session.add(event)

    # Create/update contact
    contact = contact_service.ensure_contact(
        user,
        invitee_email,
        display_name=invitee_name,
        first_seen_source=source or "public_booking",
        first_seen_at=start_dt_parsed,
    )
    contact_service.record_interaction(
        contact,
        occurred_at=start_dt_parsed,
        incoming=True,
    )

    try:
        db.session.commit()
        clear_availability_cache()
    except Exception as exc:
        logger.error(f"Database error while saving Calendly booking for user {user.id}: {exc}", exc_info=True)
        db.session.rollback()
        raise BookingCreationError("We couldn't schedule that meeting. Please try again.") from exc

    logger.info(f"Created Calendly booking: event_id={event.id}, calendly_event_uri={event_uri}")
    return event


def create_booking_event(
    user: User,
    event_type: EventType,
    start_dt: datetime,
    invitee_name: str,
    invitee_email: str,
    notes: Optional[str] = None,
    source: str = "public_booking",
    meeting_request_id: Optional[int] = None,
) -> Event:
    """Create a calendar event and persist it in the Event table."""
    end_dt = start_dt + timedelta(minutes=event_type.duration_minutes)

    # Try Calendly first if configured
    if user.calendly_access_token and event_type.calendly_event_type_uri:
        logger.info(f"Creating booking via Calendly for event type '{event_type.title}' (uri: {event_type.calendly_event_type_uri})")
        try:
            return _create_calendly_booking(
                user, event_type, start_dt, end_dt, invitee_name, invitee_email, notes, source, meeting_request_id
            )
        except Exception as exc:
            error_msg = str(exc)
            if "403" in error_msg or "Forbidden" in error_msg:
                # Expected for free plan users - just log and fallback
                logger.warning(f"Calendly booking failed (likely requires paid plan): {exc}. Falling back to Google Calendar.")
            else:
                # Unexpected error - log, report to Sentry, and fallback
                logger.error(f"Unexpected Calendly booking error (non-403): {exc}", exc_info=True)
                sentry_sdk.capture_exception(
                    exc,
                    extras={
                        "user_id": user.id,
                        "event_type_id": event_type.id,
                        "event_type_title": event_type.title,
                        "calendly_event_type_uri": event_type.calendly_event_type_uri,
                        "start_dt": start_dt.isoformat(),
                        "source": source,
                        "error_message": error_msg,
                    },
                    tags={
                        "calendly_error": "booking_creation_failed",
                        "fallback": "google_calendar",
                    }
                )
            # Fall through to Google Calendar
    elif user.calendly_access_token and not event_type.calendly_event_type_uri:
        logger.warning(f"User has Calendly connected but event type '{event_type.title}' (id={event_type.id}) has no calendly_event_type_uri. Falling back to Google Calendar.")

    # Fall back to Google Calendar
    booking_calendar_id = getattr(user, "default_booking_calendar_id", None)
    if not booking_calendar_id:
        raise BookingCreationError(
            "No booking calendar configured. Please choose one in Settings -> Calendars before scheduling."
        )

    host_name = (
        getattr(user, "display_name", None)
        or getattr(user, "username", None)
        or (user.email or "Host")
    )

    invitee_display = invitee_name.strip() if invitee_name.strip() else invitee_email
    event_title = event_type.title or "Meeting"
    calendar_event_title = f"{host_name} // {invitee_display}: {event_title}"

    event_payload = {
        "event_name": calendar_event_title,
        "start_datetime": start_dt.isoformat(),
        "end_datetime": end_dt.isoformat(),
        "location": None,
        "attendees": [invitee_email, user.email],
    }

    event = Event(
        user_id=user.id,
        event_name=sanitize_text_for_db(calendar_event_title),
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
        status="scheduled",
        source=source or "public_booking",
        invitee_email=invitee_email.strip().lower() if invitee_email else None,
        invitee_name=invitee_name.strip() or None,
        meeting_request_id=meeting_request_id,
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

    handle = getattr(user, "handle", None) or str(user.id)
    slug = getattr(event_type, "slug", None)

    def _build_management_links():
        nonlocal cancel_url, reschedule_url
        if not slug or not handle:
            return
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

    if slug and handle:
        if has_request_context():
            _build_management_links()
        else:
            try:
                app_obj = current_app._get_current_object()
            except RuntimeError:
                app_obj = None

            if app_obj and app_obj.config.get("SERVER_NAME"):
                try:
                    with app_obj.test_request_context():
                        _build_management_links()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to build booking management links outside request for booking %s: %s",
                        event.id,
                        exc,
                    )
            else:
                logger.debug(
                    "Skipping booking management link generation for booking %s (no request context and SERVER_NAME not set)",
                    event.id,
                )

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

    description_sections.append("Powered by CalAutobot.com")

    description = "\n\n".join(description_sections)

    event.event_description = sanitize_text_for_db(description)
    sanitized_location = sanitize_text_for_db(location_value) if location_value else None
    event.location = sanitized_location

    event_payload["event_description"] = description
    if sanitized_location:
        event_payload["location"] = sanitized_location

    try:
        google_event_id, conference_url = create_calendar_event(
            user,
            event_payload,
            calendar_id=booking_calendar_id,
            add_google_meet=True,
            return_conference_link=True,
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

    contact = contact_service.ensure_contact(
        user,
        invitee_email,
        display_name=invitee_name,
        first_seen_source=source or "public_booking",
        first_seen_at=start_dt,
    )
    contact_service.record_interaction(
        contact,
        occurred_at=start_dt,
        incoming=True,
    )
    event.is_synced = bool(google_event_id)
    event.google_event_id = google_event_id
    sanitized_conference = sanitize_text_for_db(conference_url) if conference_url else None
    event.conference_url = sanitized_conference or None

    try:
        db.session.commit()
        clear_availability_cache()
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
    """Remove a booking from the database and Calendly/Google Calendar if applicable."""
    if event.status == "cancelled":
        return

    # Try Calendly first if this is a Calendly event
    if event.calendly_invitee_uri:
        try:
            from app.services.calendly_api import CalendlyAPIClient

            logger.info(f"Cancelling Calendly booking: event_id={event.id}, invitee_uri={event.calendly_invitee_uri}")
            client = CalendlyAPIClient(user)
            client.cancel_invitee(event.calendly_invitee_uri, reason="Cancelled by host")
            logger.info(f"Successfully cancelled Calendly booking: event_id={event.id}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to cancel Calendly event {event.calendly_invitee_uri}: {exc}")
            # Continue to mark as cancelled locally even if Calendly fails

    # Fall back to Google Calendar if this is a Google event
    elif event.google_event_id:
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

    event.status = "cancelled"
    event.is_synced = False
    event.google_event_id = None
    event.calendly_event_uri = None
    event.calendly_invitee_uri = None
    event.updated_at = datetime.utcnow()

    db.session.commit()
    clear_availability_cache()
