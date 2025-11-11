"""
TDD tests for Calendly public booking integration.

These tests should FAIL initially, then pass after implementing Calendly integration.
"""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from app import db
from app.models import Event, EventType, User, Contact
from app.services.public_booking import (
    create_booking_event,
    cancel_booking_event,
    BookingCreationError,
)


@pytest.fixture()
def calendly_user(app_context):
    """Create a user with Calendly integration."""
    user = User(
        username="CalendlyUser",
        email="calendly@example.com",
        timezone="America/New_York",
        calendly_access_token="test_access_token",
        calendly_refresh_token="test_refresh_token",
        calendly_user_uri="https://api.calendly.com/users/USER123",
        default_booking_calendar_id="primary",  # Still needed as fallback
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def non_calendly_user(app_context):
    """Create a user without Calendly integration."""
    user = User(
        username="RegularUser",
        email="regular@example.com",
        timezone="America/New_York",
        google_token='{"access_token": "test_token"}',
        default_booking_calendar_id="primary",
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def calendly_event_type(app_context, calendly_user):
    """Create an event type linked to Calendly."""
    event_type = EventType(
        user_id=calendly_user.id,
        title="30 Minute Meeting",
        slug="30min",
        duration_minutes=30,
        is_active=True,
        calendly_event_type_uri="https://api.calendly.com/event_types/ET123",
        is_calendly_managed=True,
    )
    db.session.add(event_type)
    db.session.commit()
    return event_type


@pytest.fixture()
def regular_event_type(app_context, non_calendly_user):
    """Create a regular event type (not Calendly-managed)."""
    event_type = EventType(
        user_id=non_calendly_user.id,
        title="60 Minute Meeting",
        slug="60min",
        duration_minutes=60,
        is_active=True,
    )
    db.session.add(event_type)
    db.session.commit()
    return event_type


@patch("app.services.calendly_api.CalendlyAPIClient.create_invitee")
def test_create_booking_uses_calendly_when_connected(mock_create_invitee, calendly_user, calendly_event_type):
    """Test that booking creation uses Calendly API when user is connected."""
    # Mock Calendly API response
    mock_create_invitee.return_value = {
        "uri": "https://api.calendly.com/scheduled_events/EVENT123",
        "name": "30 Minute Meeting",
        "status": "active",
        "start_time": "2025-11-15T14:00:00.000000Z",
        "end_time": "2025-11-15T14:30:00.000000Z",
        "location": {
            "type": "zoom",
            "join_url": "https://zoom.us/j/123456789",
        },
        "invitees": [
            {
                "uri": "https://api.calendly.com/scheduled_events/EVENT123/invitees/INV123",
                "email": "invitee@example.com",
                "name": "John Doe",
            }
        ],
    }

    start_dt = datetime(2025, 11, 15, 9, 0)  # 9am EST = 2pm UTC
    start_dt = start_dt.replace(tzinfo=None)  # Remove timezone for test

    event = create_booking_event(
        user=calendly_user,
        event_type=calendly_event_type,
        start_dt=start_dt,
        invitee_name="John Doe",
        invitee_email="invitee@example.com",
        notes="Test booking",
        source="public_booking",
    )

    # Verify Calendly API was called
    mock_create_invitee.assert_called_once()

    # Verify event was created with Calendly URIs
    assert event.calendly_event_uri == "https://api.calendly.com/scheduled_events/EVENT123"
    assert event.calendly_invitee_uri == "https://api.calendly.com/scheduled_events/EVENT123/invitees/INV123"
    assert event.conference_url == "https://zoom.us/j/123456789"
    assert event.source == "public_booking"
    assert event.is_synced is True
    assert event.invitee_email == "invitee@example.com"
    assert event.invitee_name == "John Doe"


@patch("app.services.calendly_api.CalendlyAPIClient.create_invitee")
def test_create_booking_creates_contact(mock_create_invitee, calendly_user, calendly_event_type):
    """Test that Calendly booking creates a contact."""
    mock_create_invitee.return_value = {
        "uri": "https://api.calendly.com/scheduled_events/EVENT456",
        "name": "Meeting",
        "status": "active",
        "start_time": "2025-11-16T15:00:00.000000Z",
        "end_time": "2025-11-16T15:30:00.000000Z",
        "invitees": [
            {
                "uri": "https://api.calendly.com/scheduled_events/EVENT456/invitees/INV456",
                "email": "newcontact@example.com",
                "name": "Jane Smith",
            }
        ],
    }

    start_dt = datetime(2025, 11, 16, 10, 0)

    event = create_booking_event(
        user=calendly_user,
        event_type=calendly_event_type,
        start_dt=start_dt,
        invitee_name="Jane Smith",
        invitee_email="newcontact@example.com",
    )

    # Verify contact was created
    contact = Contact.query.filter_by(
        user_id=calendly_user.id,
        email="newcontact@example.com"
    ).first()
    assert contact is not None
    assert contact.display_name == "Jane Smith"
    assert contact.first_seen_source == "public_booking"


@patch("app.services.google_calendar.create_calendar_event")
def test_create_booking_falls_back_without_calendly(mock_google_create, non_calendly_user, regular_event_type):
    """Test that booking falls back to Google Calendar when no Calendly."""
    mock_google_create.return_value = ("google_event_123", "https://meet.google.com/abc-def-ghi")

    start_dt = datetime(2025, 11, 15, 10, 0)

    event = create_booking_event(
        user=non_calendly_user,
        event_type=regular_event_type,
        start_dt=start_dt,
        invitee_name="Test User",
        invitee_email="test@example.com",
    )

    # Should have called Google Calendar API, not Calendly
    mock_google_create.assert_called_once()

    # Should NOT have Calendly URIs
    assert event.calendly_event_uri is None
    assert event.calendly_invitee_uri is None
    assert event.google_event_id == "google_event_123"


@patch("app.services.calendly_api.CalendlyAPIClient.create_invitee")
def test_create_booking_falls_back_on_calendly_error(mock_create_invitee, calendly_user, calendly_event_type):
    """Test that booking falls back to Google Calendar if Calendly fails."""
    from app.services.calendly_api import CalendlyAPIError

    # Mock Calendly API to raise an error
    mock_create_invitee.side_effect = CalendlyAPIError("API unavailable")

    start_dt = datetime(2025, 11, 15, 10, 0)

    # Should raise error since no Google Calendar configured for fallback
    with pytest.raises(BookingCreationError):
        create_booking_event(
            user=calendly_user,
            event_type=calendly_event_type,
            start_dt=start_dt,
            invitee_name="Test User",
            invitee_email="test@example.com",
        )


@patch("app.services.calendly_api.CalendlyAPIClient.create_invitee")
def test_create_booking_without_event_type_uri_falls_back(mock_create_invitee, calendly_user):
    """Test booking without Calendly event type URI falls back to local."""
    # Create event type WITHOUT Calendly URI
    event_type_no_uri = EventType(
        user_id=calendly_user.id,
        title="No URI Meeting",
        slug="no-uri",
        duration_minutes=30,
        is_active=True,
        # No calendly_event_type_uri
    )
    db.session.add(event_type_no_uri)
    db.session.commit()

    # Configure user with Google Calendar as fallback
    calendly_user.google_token = '{"access_token": "test_token"}'
    db.session.commit()

    start_dt = datetime(2025, 11, 15, 10, 0)

    with patch("app.services.google_calendar.create_calendar_event") as mock_google:
        mock_google.return_value = ("google_event_123", None)

        event = create_booking_event(
            user=calendly_user,
            event_type=event_type_no_uri,
            start_dt=start_dt,
            invitee_name="Test User",
            invitee_email="test@example.com",
        )

        # Should have used Google Calendar, not Calendly
        mock_google.assert_called_once()
        mock_create_invitee.assert_not_called()


@patch("app.services.calendly_api.CalendlyAPIClient.cancel_invitee")
def test_cancel_booking_uses_calendly_when_connected(mock_cancel_invitee, calendly_user, calendly_event_type):
    """Test that cancellation uses Calendly API for Calendly events."""
    # Create a Calendly event
    event = Event(
        user_id=calendly_user.id,
        event_name="Test Meeting",
        start_datetime="2025-11-15T14:00:00Z",
        end_datetime="2025-11-15T14:30:00Z",
        calendly_event_uri="https://api.calendly.com/scheduled_events/EVENT789",
        calendly_invitee_uri="https://api.calendly.com/scheduled_events/EVENT789/invitees/INV789",
        status="scheduled",
        source="calendly",
    )
    db.session.add(event)
    db.session.commit()

    mock_cancel_invitee.return_value = True

    cancel_booking_event(calendly_user, event)

    # Verify Calendly API was called
    mock_cancel_invitee.assert_called_once_with(event.calendly_invitee_uri)

    # Verify event was marked as cancelled
    db.session.expire_all()
    event = Event.query.get(event.id)
    assert event.status == "cancelled"
    assert event.is_synced is False


@patch("app.services.google_calendar.delete_calendar_event")
def test_cancel_booking_falls_back_without_calendly(mock_google_delete, non_calendly_user):
    """Test that cancellation falls back to Google Calendar for non-Calendly events."""
    event = Event(
        user_id=non_calendly_user.id,
        event_name="Google Meeting",
        start_datetime="2025-11-15T14:00:00Z",
        end_datetime="2025-11-15T14:30:00Z",
        google_event_id="google_event_123",
        status="scheduled",
        source="public_booking",
    )
    db.session.add(event)
    db.session.commit()

    cancel_booking_event(non_calendly_user, event)

    # Should have called Google Calendar API, not Calendly
    mock_google_delete.assert_called_once()

    # Verify event was marked as cancelled
    db.session.expire_all()
    event = Event.query.get(event.id)
    assert event.status == "cancelled"


def test_cancel_booking_already_cancelled(calendly_user):
    """Test that cancelling an already-cancelled event is idempotent."""
    event = Event(
        user_id=calendly_user.id,
        event_name="Already Cancelled",
        start_datetime="2025-11-15T14:00:00Z",
        end_datetime="2025-11-15T14:30:00Z",
        status="cancelled",
        source="calendly",
    )
    db.session.add(event)
    db.session.commit()

    # Should not raise an error
    cancel_booking_event(calendly_user, event)

    # Should still be cancelled
    db.session.expire_all()
    event = Event.query.get(event.id)
    assert event.status == "cancelled"


@patch("app.services.calendly_api.CalendlyAPIClient.cancel_invitee")
def test_cancel_booking_handles_calendly_error(mock_cancel_invitee, calendly_user):
    """Test that cancellation handles Calendly API errors gracefully."""
    from app.services.calendly_api import CalendlyAPIError

    event = Event(
        user_id=calendly_user.id,
        event_name="To Cancel",
        start_datetime="2025-11-15T14:00:00Z",
        end_datetime="2025-11-15T14:30:00Z",
        calendly_invitee_uri="https://api.calendly.com/scheduled_events/EVENT/invitees/INV",
        status="scheduled",
        source="calendly",
    )
    db.session.add(event)
    db.session.commit()

    # Mock Calendly error
    mock_cancel_invitee.side_effect = CalendlyAPIError("API unavailable")

    # Should still mark event as cancelled locally even if Calendly fails
    cancel_booking_event(calendly_user, event)

    db.session.expire_all()
    event = Event.query.get(event.id)
    assert event.status == "cancelled"


@patch("app.services.calendly_api.CalendlyAPIClient.create_invitee")
def test_create_booking_clears_availability_cache(mock_create_invitee, calendly_user, calendly_event_type):
    """Test that creating a booking clears the availability cache."""
    from app.services.availability import clear_availability_cache

    mock_create_invitee.return_value = {
        "uri": "https://api.calendly.com/scheduled_events/EVENT",
        "name": "Meeting",
        "status": "active",
        "start_time": "2025-11-15T14:00:00.000000Z",
        "end_time": "2025-11-15T14:30:00.000000Z",
        "invitees": [{"uri": "https://api.calendly.com/scheduled_events/EVENT/invitees/INV"}],
    }

    start_dt = datetime(2025, 11, 15, 9, 0)

    with patch("app.services.public_booking.clear_availability_cache") as mock_clear_cache:
        event = create_booking_event(
            user=calendly_user,
            event_type=calendly_event_type,
            start_dt=start_dt,
            invitee_name="Test",
            invitee_email="test@example.com",
        )

        # Verify cache was cleared
        mock_clear_cache.assert_called_once()
