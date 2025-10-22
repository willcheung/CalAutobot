import datetime

import pytest

from app.agents.event_extractor import validate_and_clean_event
from app.helpers.event_utils import (
    calculate_event_duration_minutes,
    truncate_text,
    extract_meeting_link,
)
from app.helpers.text_processing import sanitize_text_for_db


def test_validate_and_clean_event_normalizes_fields():
    event_data = {
        "event_name": "  Team Sync  ",
        "event_description": " Weekly update ",
        "start_date": "2025-01-05",
        "start_time": "2:30 PM",
        "end_date": None,
        "end_time": None,
        "location": "  HQ  ",
        "start_datetime": "2025-01-05T14:30:00+00:00",
        "end_datetime": "2025-01-05T15:30:00+00:00",
    }

    cleaned = validate_and_clean_event(event_data)

    assert cleaned["event_name"] == "Team Sync"
    assert cleaned["event_description"] == "Weekly update"
    assert cleaned["start_time"] == "14:30"
    assert cleaned["end_date"] == "2025-01-05"
    assert cleaned["location"] == "HQ"
    assert cleaned.get("start_datetime") is None
    assert cleaned.get("end_datetime") is None


def test_validate_and_clean_event_invalid_time_raises():
    event_data = {
        "event_name": "Event",
        "event_description": "",
        "start_date": "2025-01-05",
        "start_time": "25:61",
        "end_date": "2025-01-05",
        "end_time": None,
        "location": "",
    }

    with pytest.raises(ValueError):
        validate_and_clean_event(event_data)


def test_calculate_event_duration_from_datetimes():
    class DummyEvent:
        start_datetime = "2025-01-01T10:00:00+00:00"
        end_datetime = "2025-01-01T11:45:00+00:00"
        start_date = None
        start_time = None
        end_date = None
        end_time = None
        id = 1

    duration = calculate_event_duration_minutes(DummyEvent())
    assert duration == 105


def test_calculate_event_duration_from_dates_and_times():
    class DummyEvent:
        start_datetime = None
        end_datetime = None
        start_date = datetime.date(2025, 1, 1)
        start_time = datetime.time(9, 0)
        end_date = datetime.date(2025, 1, 1)
        end_time = datetime.time(10, 15)
        id = 2

    duration = calculate_event_duration_minutes(DummyEvent())
    assert duration == 75


def test_sanitize_text_for_db_strips_harmful_content():
    raw_text = "Hello <script>alert('x')</script> \x00"
    sanitized = sanitize_text_for_db(raw_text)

    assert sanitized == "Hello <script>alert('x')</script> "
    assert "\x00" not in sanitized


def test_truncate_text_limits_length():
    text = "abc" * 100
    preview, truncated = truncate_text(text, limit=50)

    assert truncated is True
    assert len(preview) == 50


def test_extract_meeting_link_prefers_conference_field():
    class DummyEvent:
        conference_url = "https://meet.google.com/cde-fghi-jkl"
        location = "https://zoom.us/j/123456789"
        event_description = "Join call: https://zoom.us/j/123456789"

    link = extract_meeting_link(DummyEvent())

    assert link is not None
    assert link["url"] == "https://meet.google.com/cde-fghi-jkl"
    assert link["label"] == "Join Google Meet"


def test_extract_meeting_link_returns_none_without_conference_field():
    class DummyEvent:
        conference_url = None
        location = "https://meet.google.com/abc-defg-hij"
        event_description = "Join here"

    link = extract_meeting_link(DummyEvent())

    assert link is None
