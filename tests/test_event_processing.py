from datetime import datetime

from app import db
from app.services.event_processing import process_text_to_events
from app.models import Event, TextInput, User


def test_process_text_to_events_creates_records(monkeypatch, app_context):
    user = User(username="tester", email="tester@example.com", timezone="UTC")
    db.session.add(user)
    db.session.commit()

    captured_event_payload = {}

    def fake_extract_events(text, current_date=None, user_timezone="UTC", image_data=None):
        assert "Important update" in text
        events = [{
            "event_name": "Project Kickoff",
            "event_description": "Discuss roadmap",
            "start_date": "2025-02-01",
            "start_time": "10:00",
            "end_date": "2025-02-01",
            "end_time": "11:00",
            "start_datetime": "2025-02-01T10:00:00+00:00",
            "end_datetime": "2025-02-01T11:00:00+00:00",
            "location": "Zoom",
            "emoji": "🚀",
        }]
        return events, "sender@example.com", False, "success", None

    def fake_create_calendar_event(user_arg, event_data):
        captured_event_payload.update(event_data)
        return "google-event-123"

    monkeypatch.setattr("app.services.event_processing.extract_events_from_text", fake_extract_events)
    monkeypatch.setattr("app.services.event_processing.create_calendar_event", fake_create_calendar_event)

    raw_text = "Important update <b>today</b>"
    result = process_text_to_events(raw_text, user, source_type="manual", auto_sync=True)

    assert result["synced_count"] == 1
    assert len(result["events"]) == 1
    assert result["from_email"] == "sender@example.com"

    # Text input stored with sanitized text
    text_input = TextInput.query.filter_by(user_id=user.id).first()
    assert text_input is not None
    assert "&lt;b&gt;" in text_input.original_text

    # Event stored and sanitized
    stored_event = Event.query.filter_by(user_id=user.id).first()
    assert stored_event is not None
    assert stored_event.event_name == "Project Kickoff"
    assert stored_event.location == "Zoom"
    assert stored_event.google_event_id == "google-event-123"
    assert stored_event.is_synced is True

    # Calendar payload received scheduling information
    assert captured_event_payload["event_name"] == "Project Kickoff"
    assert (
        "start_datetime" in captured_event_payload
        or (
            "start_date" in captured_event_payload
            and "start_time" in captured_event_payload
        )
    )
