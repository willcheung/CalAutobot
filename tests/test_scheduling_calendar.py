from datetime import datetime

import pytest

from app import db
from flask import current_app

from app.models import Event, EventType, MeetingMessage, MeetingParticipant, MeetingRequest, TextInput, User
from app.services import public_booking as public_booking_service
from app.services.scheduling_agent import handle_scheduling_email
from app.services.users import assign_unique_handle


def test_confirm_slot_creates_calendar_event(monkeypatch, app_context):
    unique_suffix = datetime.utcnow().strftime("%f")
    owner = User(
        username=f"Owner-{unique_suffix}",
        email=f"owner-{unique_suffix}@example.com",
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

    def fake_create_booking_event(
        user,
        event_type,
        start_dt,
        invitee_name,
        invitee_email,
        notes,
        source="public_booking",
        meeting_request_id=None,
    ):
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
            meeting_request_id=meeting_request_id,
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
        "sender": owner.email,
        "sender_name": "Owner",
        "subject": "Project Sync",
        "body_text": "Confirmed",
        "body_html": "",
        "to": [owner.email],
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
    assert to_header == owner.email
    cc_list = sorted(extra.get("cc_recipients") or [])
    assert cc_list == ["participant@example.com"]
    body = extra.get("text_body") or ""
    assert "https://meet.google.com/test-link" in body

    meeting_request = MeetingRequest.query.one()
    confirmed_slot = meeting_request.confirmed_slot or {}
    assert confirmed_slot.get("conference_url") == "https://meet.google.com/test-link"

    current_app.config["SERVER_NAME"] = original_server_name


def test_cancel_meeting_cancels_existing_event(monkeypatch, app_context):
    unique_suffix = datetime.utcnow().strftime("%f")
    owner = User(
        username=f"Owner-{unique_suffix}",
        email=f"owner-{unique_suffix}@example.com",
        timezone="UTC",
    )
    db.session.add(owner)
    db.session.commit()
    assign_unique_handle(owner)
    db.session.commit()

    event_type = EventType(
        user_id=owner.id,
        title="Project Sync",
        slug=f"project-sync-{unique_suffix}",
        duration_minutes=30,
        is_active=True,
        is_public=True,
    )
    db.session.add(event_type)
    db.session.commit()

    start_iso = "2025-02-01T10:00:00+00:00"
    end_iso = "2025-02-01T10:30:00+00:00"

    existing_event = Event(
        user_id=owner.id,
        event_name="Project Sync",
        start_datetime=start_iso,
        end_datetime=end_iso,
        start_date=datetime.fromisoformat(start_iso).date(),
        start_time=datetime.fromisoformat(start_iso).time(),
        end_date=datetime.fromisoformat(end_iso).date(),
        end_time=datetime.fromisoformat(end_iso).time(),
        duration_minutes=30,
        status="scheduled",
        source="ai_booking",
        google_event_id="evt-123",
    )
    db.session.add(existing_event)
    db.session.commit()

    meeting_request = MeetingRequest(
        user_id=owner.id,
        subject="Project Sync",
        status="confirmed",
        current_step="confirm_slot",
    )
    meeting_request.confirmed_slot = {
        "start": start_iso,
        "end": end_iso,
        "google_event_id": "evt-123",
    }
    db.session.add(meeting_request)
    db.session.flush()

    db.session.add(
        MeetingMessage(
            meeting_request_id=meeting_request.id,
            sender_email=owner.email,
            thread_id="thread-cancel",
            message_id="prior-msg",
            body_text="Previous",
            received_at=datetime.utcnow(),
        )
    )
    db.session.commit()

    captured_emails = []

    def fake_send_email(to, subject, **kwargs):
        captured_emails.append((to, subject, kwargs))
        return True

    monkeypatch.setattr("app.services.scheduling_agent.gmail_service.send_email", fake_send_email)
    monkeypatch.setattr(
        "app.services.scheduling_agent.run_meeting_scheduler_agent",
        lambda *args, **kwargs: {
            "meeting_request_id": meeting_request.id,
            "reply": "Cancelled",
            "action": "cancel_meeting",
            "proposed_slots": [],
            "confirmed_slot": None,
            "notes": "cancel_request",
        },
    )

    email_data = {
        "sender": "participant@example.com",
        "sender_name": "Participant",
        "subject": "Please cancel",
        "body_text": "Please cancel the meeting.",
        "body_html": "",
        "to": [owner.email],
        "cc": [],
        "thread_id": "thread-cancel",
        "message_id": "cancel-msg",
        "received_at": datetime.utcnow(),
        "raw_headers": {},
        "attachments": [],
    }

    handle_scheduling_email(email_data, owner)

    db.session.refresh(existing_event)
    assert existing_event.status == "cancelled"
    assert existing_event.google_event_id is None

    db.session.refresh(meeting_request)
    assert meeting_request.status == "cancelled"
    assert meeting_request.confirmed_slot == {
        "start": start_iso,
        "end": end_iso,
        "google_event_id": "evt-123",
    }
    assert captured_emails, "Expected cancellation email to be sent"
    body = captured_emails[-1][2].get("text_body") or ""
    assert "manually" not in body
