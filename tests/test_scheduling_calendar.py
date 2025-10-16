from datetime import datetime
from types import SimpleNamespace

import pytest

from app import db
from app.models import MeetingMessage, MeetingParticipant, MeetingRequest, TextInput, User
from app.services.scheduling_agent import handle_scheduling_email


def test_confirm_slot_creates_calendar_event(monkeypatch, app_context):
    owner = User(
        username="Owner",
        email="owner@example.com",
        timezone="UTC",
        google_id="123",
        google_token='{"access_token": "abc", "refresh_token": "def"}'
    )
    db.session.add(owner)
    db.session.commit()

    booking_call = {}

    def fake_create_booking_event(user, event_type, start_dt, invitee_name, invitee_email, notes):
        booking_call.update(
            {
                "user_id": user.id,
                "title": event_type.title,
                "start": start_dt,
                "invitee": invitee_email,
            }
        )
        return SimpleNamespace(google_event_id="calendar-event-xyz")

    monkeypatch.setattr("app.services.scheduling_agent.create_booking_event", fake_create_booking_event)
    captured_emails = []

    def fake_send_email(to, subject, **kwargs):
        captured_emails.append((to, subject, kwargs))
        return True

    monkeypatch.setattr("app.services.scheduling_agent.gmail_service.send_email", fake_send_email)

    email_data = {
        "sender": "owner@example.com",
        "sender_name": "Owner",
        "subject": "Project Sync",
        "body_text": "Confirmed",
        "body_html": "",
        "to": ["owner@example.com"],
        "cc": ["participant@example.com"],
        "thread_id": "thread-1",
        "message_id": "msg-1",
        "received_at": datetime.utcnow(),
        "raw_headers": {},
        "attachments": [],
    }

    response = {
        "meeting_request_id": None,
        "reply": "All set",
        "action": "confirm_slot",
        "proposed_slots": [
            {"start": "2025-02-01T10:00:00+00:00", "end": "2025-02-01T10:30:00+00:00"}
        ],
        "confirmed_slot": {
            "start": "2025-02-01T10:00:00+00:00",
            "end": "2025-02-01T10:30:00+00:00",
        },
        "notes": "",
    }

    monkeypatch.setattr("app.services.scheduling_agent.run_meeting_scheduler_agent", lambda *args, **kwargs: response)
    monkeypatch.setattr("app.services.scheduling_agent.get_testing_availability", lambda *args, **kwargs: [])

    handle_scheduling_email(email_data, owner)

    assert booking_call["title"] == "Project Sync"
    assert booking_call["start"].isoformat() == "2025-02-01T10:00:00+00:00"
    assert booking_call["invitee"] == "participant@example.com"

    assert captured_emails, "Expected scheduler to send a reply email"
    to_header, subject, extra = captured_emails[-1]
    assert to_header == "owner@example.com"
    cc_list = sorted(extra.get("cc_recipients") or [])
    assert cc_list == ["participant@example.com"]
