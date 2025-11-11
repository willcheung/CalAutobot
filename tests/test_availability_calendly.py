"""
TDD tests for Calendly availability integration.

These tests should FAIL initially, then pass after implementing Calendly integration.
"""

from datetime import datetime, date, time, timedelta
from unittest.mock import Mock, patch

import pytest
import pytz

from app import db
from app.models import EventType, User
from app.services import availability as availability_service


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


@patch("app.services.calendly_api.CalendlyAPIClient.get_event_type_available_times")
def test_availability_uses_calendly_when_connected(mock_calendly_api, calendly_user, calendly_event_type):
    """Test that availability uses Calendly API when user is connected."""
    # Mock Calendly API response
    mock_calendly_api.return_value = [
        {
            "start_time": "2025-11-15T14:00:00.000000Z",  # 9am EST
            "invitees_remaining": 1,
            "status": "available",
        },
        {
            "start_time": "2025-11-15T14:30:00.000000Z",  # 9:30am EST
            "invitees_remaining": 1,
            "status": "available",
        },
        {
            "start_time": "2025-11-15T15:00:00.000000Z",  # 10am EST
            "invitees_remaining": 1,
            "status": "available",
        },
    ]

    # Get availability for a future date
    target_date = date(2025, 11, 15)

    slots = availability_service.get_slots_for_date(
        calendly_user,
        calendly_event_type,
        target_date
    )

    # Verify Calendly API was called
    mock_calendly_api.assert_called_once()

    # Verify we got slots from Calendly
    assert len(slots) == 3
    assert all(isinstance(slot, availability_service.Slot) for slot in slots)

    # Verify slots are correctly parsed
    tz = pytz.timezone("America/New_York")
    expected_start = tz.localize(datetime(2025, 11, 15, 9, 0))
    assert slots[0].start == expected_start


@patch("app.services.calendly_api.CalendlyAPIClient.get_event_type_available_times")
def test_availability_handles_calendly_7day_limit(mock_calendly_api, calendly_user, calendly_event_type):
    """Test that we handle Calendly's 7-day range limitation."""
    # Mock Calendly API to be called multiple times for ranges > 7 days
    mock_calendly_api.return_value = []

    start_date = date(2025, 11, 15)
    end_date = start_date + timedelta(days=14)  # 15 days

    batch = availability_service.get_availability_for_range(
        calendly_user,
        calendly_event_type,
        start_date,
        end_date
    )

    # Should have called Calendly API multiple times (for different 7-day chunks)
    assert mock_calendly_api.call_count >= 2


def test_availability_falls_back_without_calendly(non_calendly_user, regular_event_type):
    """Test that availability uses original logic when user has no Calendly."""
    # Set up availability windows
    availability_service.set_weekly_windows(
        non_calendly_user,
        [
            {"weekday": 0, "start": "09:00", "end": "17:00", "is_active": True},  # Monday
            {"weekday": 1, "start": "09:00", "end": "17:00", "is_active": True},  # Tuesday
        ],
    )

    # Get next Monday
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_monday = today + timedelta(days=days_ahead)

    slots = availability_service.get_slots_for_date(
        non_calendly_user,
        regular_event_type,
        next_monday
    )

    # Should get slots from availability windows (not Calendly)
    assert len(slots) > 0
    # Slots should respect the 9am-5pm window
    for slot in slots:
        assert slot.start.hour >= 9
        assert slot.end.hour <= 17


@patch("app.services.calendly_api.CalendlyAPIClient.get_event_type_available_times")
def test_availability_falls_back_on_calendly_error(mock_calendly_api, calendly_user, calendly_event_type):
    """Test that availability falls back to local logic if Calendly API fails."""
    from app.services.calendly_api import CalendlyAPIError

    # Mock Calendly API to raise an error
    mock_calendly_api.side_effect = CalendlyAPIError("API unavailable")

    # Set up availability windows as fallback
    availability_service.set_weekly_windows(
        calendly_user,
        [
            {"weekday": 0, "start": "09:00", "end": "17:00", "is_active": True},
        ],
    )

    # Get next Monday
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    next_monday = today + timedelta(days=days_ahead)

    # Should fall back to local availability windows
    slots = availability_service.get_slots_for_date(
        calendly_user,
        calendly_event_type,
        next_monday
    )

    # Should still get slots from fallback logic
    assert len(slots) > 0


def test_availability_requires_event_type_uri_for_calendly(calendly_user):
    """Test that Calendly availability requires event type URI."""
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

    # Set up fallback availability windows
    availability_service.set_weekly_windows(
        calendly_user,
        [
            {"weekday": 0, "start": "09:00", "end": "17:00", "is_active": True},
        ],
    )

    target_date = date.today() + timedelta(days=7)

    # Should fall back to local logic since event type has no Calendly URI
    slots = availability_service.get_slots_for_date(
        calendly_user,
        event_type_no_uri,
        target_date
    )

    # Should work with fallback
    assert isinstance(slots, list)


@patch("app.services.calendly_api.CalendlyAPIClient.get_event_type_available_times")
def test_cached_availability_works_with_calendly(mock_calendly_api, calendly_user, calendly_event_type):
    """Test that caching works correctly with Calendly integration."""
    mock_calendly_api.return_value = [
        {
            "start_time": "2025-11-15T14:00:00.000000Z",
            "invitees_remaining": 1,
            "status": "available",
        },
    ]

    target_date = date(2025, 11, 15)

    # First call
    slots1 = availability_service.get_cached_availability_for_range(
        calendly_user,
        calendly_event_type,
        target_date,
        target_date
    )

    # Second call (should use cache)
    slots2 = availability_service.get_cached_availability_for_range(
        calendly_user,
        calendly_event_type,
        target_date,
        target_date
    )

    # Should have only called Calendly API once (second was cached)
    assert mock_calendly_api.call_count == 1

    # Both results should be the same
    assert len(slots1.slots_by_date[target_date]) == len(slots2.slots_by_date[target_date])


@patch("app.services.calendly_api.CalendlyAPIClient.get_event_type_available_times")
def test_availability_handles_empty_calendly_response(mock_calendly_api, calendly_user, calendly_event_type):
    """Test handling of empty availability from Calendly."""
    mock_calendly_api.return_value = []

    target_date = date(2025, 11, 15)

    slots = availability_service.get_slots_for_date(
        calendly_user,
        calendly_event_type,
        target_date
    )

    # Should return empty list, not crash
    assert slots == []


@patch("app.services.calendly_api.CalendlyAPIClient.get_event_type_available_times")
def test_availability_converts_calendly_timezone(mock_calendly_api, calendly_user, calendly_event_type):
    """Test that Calendly times are converted to user's timezone."""
    # Calendly returns UTC times
    mock_calendly_api.return_value = [
        {
            "start_time": "2025-11-15T18:00:00.000000Z",  # 6pm UTC = 1pm EST
            "invitees_remaining": 1,
            "status": "available",
        },
    ]

    target_date = date(2025, 11, 15)

    slots = availability_service.get_slots_for_date(
        calendly_user,
        calendly_event_type,
        target_date
    )

    assert len(slots) == 1

    # Should be converted to user's timezone (EST)
    user_tz = pytz.timezone(calendly_user.timezone)
    assert slots[0].start.tzinfo is not None
    assert slots[0].start.hour == 13  # 1pm EST
