from datetime import datetime

import pytest

from app import db
from app.models import Event, TextInput, User
from app.services.event_processing import process_text_to_events


def test_event_extractor_creates_calendar_event(monkeypatch, app_context):
    user = User(
        username="Extractor",
        email="extractor@example.com",
        timezone="UTC",
        google_id="abc",
        google_token='{"access_token": "abc", "refresh_token": "def"}'
    )
    db.session.add(user)
    db.session.commit()

    captured_payload = {}

    def fake_create_calendar_event(user_arg, payload):
        assert user_arg.id == user.id
        captured_payload.update(payload)
        return "event-extractor-123"

    def fake_extract_events(text, current_date=None, user_timezone="UTC", image_data=None):
        return ([{
            "event_name": "Client Call",
            "event_description": "Discuss progress",
            "start_date": "2025-03-10",
            "end_date": "2025-03-10",
            "start_time": "09:00",
            "end_time": "10:00",
            "start_datetime": "2025-03-10T09:00:00+00:00",
            "end_datetime": "2025-03-10T10:00:00+00:00",
            "location": "Zoom",
            "emoji": "📞",
        }], None, False, "success", None)

    monkeypatch.setattr("app.services.event_processing.create_calendar_event", fake_create_calendar_event)
    monkeypatch.setattr("app.services.event_processing.extract_events_from_text", fake_extract_events)

    result = process_text_to_events("Schedule call", user, source_type="email", auto_sync=True)

    assert result["synced_count"] == 1
    assert captured_payload["event_name"] == "Client Call"
    assert (
        captured_payload.get("start_datetime") == "2025-03-10T09:00:00+00:00"
        or (
            captured_payload.get("start_date") == "2025-03-10"
            and captured_payload.get("start_time") == "09:00"
        )
    )
