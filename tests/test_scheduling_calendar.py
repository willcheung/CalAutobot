from datetime import datetime

import pytest

from app import db
from flask import current_app

from app.models import Event, EventType, MeetingMessage, MeetingParticipant, MeetingRequest, TextInput, User
from app.services import public_booking as public_booking_service
from app.services.scheduling_agent import handle_scheduling_email
from app.services.users import assign_unique_handle


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

    owner.default_booking_calendar_id = "booking-calendar"
    assign_unique_handle(owner)
    db.session.commit()

    event_type = EventType(
        user_id=owner.id,
        title="Project Sync",
        slug="project-sync",
        duration_minutes=30,
        is_active=True,
        is_public=True,
    )
    db.session.add(event_type)
    db.session.commit()

    original_server_name = current_app.config.get("SERVER_NAME")
    current_app.config["SERVER_NAME"] = "calautobot.test"

    booking_call = {}

    real_create_booking_event = public_booking_service.create_booking_event

    def fake_create_booking_event(user, event_type, start_dt, invitee_name, invitee_email, notes, source="public_booking"):
        booking_call.update(
            {
                "user_id": user.id,
                "title": event_type.title,
                "start": start_dt,
                "invitee": invitee_email,
                "source": source,
            }
        )
        return real_create_booking_event(
            user,
            event_type,
            start_dt,
            invitee_name,
            invitee_email,
            notes,
            source=source,
        )

    monkeypatch.setattr(public_booking_service, "create_booking_event", fake_create_booking_event)
    monkeypatch.setattr("app.services.scheduling_agent.create_booking_event", fake_create_booking_event)

    def fake_create_calendar_event(user, payload, **_kwargs):
        return "calendar-event-xyz", "https://meet.google.com/test-link"

    monkeypatch.setattr("app.services.public_booking.create_calendar_event", fake_create_calendar_event)
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
    handle_scheduling_email(email_data, owner)

    assert booking_call["title"] == "Project Sync"
    assert booking_call["start"].isoformat() == "2025-02-01T10:00:00+00:00"
    assert booking_call["invitee"] == "participant@example.com"
    assert booking_call["source"] == "ai_booking"

    stored_event = Event.query.filter_by(user_id=owner.id).order_by(Event.id.desc()).first()
    assert stored_event is not None
    assert "Cancel:" in (stored_event.event_description or "")
    assert "Reschedule:" in (stored_event.event_description or "")

    assert captured_emails, "Expected scheduler to send a reply email"
    to_header, subject, extra = captured_emails[-1]
    assert to_header == "owner@example.com"
    cc_list = sorted(extra.get("cc_recipients") or [])
    assert cc_list == ["participant@example.com"]
    body = extra.get("text_body") or ""
    assert "https://meet.google.com/test-link" in body

    meeting_request = MeetingRequest.query.one()
    confirmed_slot = meeting_request.confirmed_slot or {}
    assert confirmed_slot.get("conference_url") == "https://meet.google.com/test-link"

    current_app.config["SERVER_NAME"] = original_server_name
