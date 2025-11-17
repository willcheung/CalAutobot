from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from flask import current_app

from app.models import Contact, Event, EventType, MeetingMessage, MeetingParticipant, MeetingRequest, TextInput, User
from app.services import contacts as contact_service
from app.services import public_booking as public_booking_service
from app.services.scheduling_agent import handle_scheduling_email
from app.services.users import assign_unique_handle


def test_confirm_slot_creates_calendar_event(monkeypatch, app_context):
    unique_suffix = datetime.utcnow().strftime("%f")
    owner = User(
        username=f"Owner-{unique_suffix}",
        email=f"owner-{unique_suffix}@example.com",
        timezone="UTC",
        google_id=f"gid-{unique_suffix}",
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
    monkeypatch.setattr("app.services.public_booking.delete_calendar_event", lambda *_, **__: None)
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
    assert owner.email in to_header
    assert "participant@example.com" in to_header
    cc_list = sorted(extra.get("cc_recipients") or [])
    assert cc_list == []
    body = extra.get("text_body") or ""
    assert "https://meet.google.com/test-link" in body

    meeting_request = (
        MeetingRequest.query.filter_by(user_id=owner.id)
        .order_by(MeetingRequest.id.desc())
        .first()
    )
    assert meeting_request is not None
    confirmed_slot = meeting_request.confirmed_slot or {}
    assert confirmed_slot.get("conference_url") == "https://meet.google.com/test-link"

    current_app.config["SERVER_NAME"] = original_server_name


def test_reschedule_meeting_creates_new_event(monkeypatch, app_context):
    unique_suffix = datetime.utcnow().strftime("%f")
    owner = User(
        username=f"Owner-{unique_suffix}",
        email=f"owner-{unique_suffix}@example.com",
        timezone="UTC",
        google_id=f"gid-confirm-{unique_suffix}",
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
        slug=f"project-sync-{unique_suffix}",
        duration_minutes=30,
        is_active=True,
        is_public=True,
    )
    db.session.add(event_type)
    db.session.commit()

    original_server_name = current_app.config.get("SERVER_NAME")
    current_app.config["SERVER_NAME"] = "calautobot.test"

    old_start = "2025-02-01T10:00:00+00:00"
    old_end = "2025-02-01T10:30:00+00:00"

    meeting_request = MeetingRequest(
        user_id=owner.id,
        subject="Project Sync",
        status="confirmed",
        current_step="confirm_slot",
    )
    meeting_request.confirmed_slot = {
        "start": old_start,
        "end": old_end,
        "google_event_id": "evt-123",
    }
    db.session.add(meeting_request)
    db.session.flush()

    existing_event = Event(
        user_id=owner.id,
        event_name="Project Sync",
        start_datetime=old_start,
        end_datetime=old_end,
        start_date=datetime.fromisoformat(old_start).date(),
        start_time=datetime.fromisoformat(old_start).time(),
        end_date=datetime.fromisoformat(old_end).date(),
        end_time=datetime.fromisoformat(old_end).time(),
        duration_minutes=30,
        status="scheduled",
        source="ai_booking",
        google_event_id="evt-123",
        meeting_request_id=meeting_request.id,  # Link to meeting request
    )
    db.session.add(existing_event)
    db.session.commit()

    db.session.add(
        MeetingMessage(
            meeting_request_id=meeting_request.id,
            sender_email="participant@example.com",
            thread_id="thread-reschedule",
            message_id="prior-msg",
            body_text="Previous",
            received_at=datetime.utcnow(),
        )
    )
    db.session.commit()

    booking_call = {}

    real_create_booking_event = public_booking_service.create_booking_event

    def fake_create_booking_event(user, event_type, start_dt, invitee_name, invitee_email, notes, source="public_booking", meeting_request_id=None):
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
        return "calendar-event-new", "https://meet.google.com/new-link"

    monkeypatch.setattr("app.services.public_booking.create_calendar_event", fake_create_calendar_event)
    monkeypatch.setattr("app.services.public_booking.delete_calendar_event", lambda *_, **__: None)
    monkeypatch.setattr(
        "app.services.scheduling_agent.gmail_service.send_email",
        lambda *_, **__: True,
    )

    new_start = "2025-02-01T11:00:00+00:00"
    new_end = "2025-02-01T11:30:00+00:00"

    response = {
        "meeting_request_id": meeting_request.id,
        "reply": "Rescheduled",
        "action": "reschedule",
        "proposed_slots": [],
        "confirmed_slot": {
            "start": new_start,
            "end": new_end,
        },
        "rescheduled_from": {
            "start": old_start,
            "end": old_end,
            "google_event_id": "evt-123",
        },
        "notes": "reschedule",
    }

    monkeypatch.setattr(
        "app.services.scheduling_agent.run_meeting_scheduler_agent",
        lambda *args, **kwargs: response,
    )

    email_data = {
        "sender": "participant@example.com",
        "sender_name": "Participant",
        "subject": "Reschedule",
        "body_text": "Let's move to 11am.",
        "body_html": "",
        "to": [owner.email],
        "cc": ["participant@example.com"],
        "thread_id": "thread-reschedule",
        "message_id": "reschedule-msg",
        "received_at": datetime.utcnow(),
        "raw_headers": {},
        "attachments": [],
    }

    handle_scheduling_email(email_data, owner)

    db.session.refresh(existing_event)
    assert existing_event.status == "cancelled"

    assert booking_call["start"].isoformat() == new_start

    db.session.refresh(meeting_request)
    assert meeting_request.status == "confirmed"
    assert meeting_request.confirmed_slot["start"] == new_start
    assert meeting_request.confirmed_slot.get("google_event_id") == "calendar-event-new"

    assert booking_call["source"] == "ai_booking"

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
        meeting_request_id=meeting_request.id,  # Link to meeting request
    )
    db.session.add(existing_event)
    db.session.commit()

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

    # Mock delete_calendar_event so it doesn't try to actually cancel in Google
    monkeypatch.setattr("app.services.public_booking.delete_calendar_event", lambda *_, **__: None)
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
    to_header = captured_emails[-1][0]
    assert owner.email in to_header
    assert "participant@example.com" in to_header
    body = captured_emails[-1][2].get("text_body") or ""
    assert "manually" not in body


def test_confirm_slot_with_contact_race_condition_still_creates_event(monkeypatch, app_context):
    """
    Test that when a contact creation race condition occurs (IntegrityError),
    the meeting event is still successfully created.
    
    This validates the fix for the contacts upsert race condition where
    concurrent workers trying to create the same contact caused the entire
    transaction to fail.
    """
    unique_suffix = datetime.utcnow().strftime("%f")
    owner = User(
        username=f"Owner-{unique_suffix}",
        email=f"owner-{unique_suffix}@example.com",
        timezone="UTC",
        google_id=f"gid-race-{unique_suffix}",
        google_token='{"access_token": "abc", "refresh_token": "def"}'
    )
    db.session.add(owner)
    db.session.commit()

    owner.default_booking_calendar_id = "booking-calendar"
    assign_unique_handle(owner)
    db.session.commit()

    event_type = EventType(
        user_id=owner.id,
        title="Team Standup",
        slug=f"standup-{unique_suffix}",
        duration_minutes=30,
        is_active=True,
        is_public=True,
    )
    db.session.add(event_type)
    db.session.commit()

    # Track whether ensure_contact was called and if it hit the race condition
    ensure_contact_calls = []
    real_ensure_contact = contact_service.ensure_contact
    
    def fake_ensure_contact(user, email, **kwargs):
        ensure_contact_calls.append(email)
        # Simulate race condition on first call only
        if len(ensure_contact_calls) == 1:
            # Pre-create the contact to simulate another worker creating it
            existing = Contact.query.filter_by(user_id=user.id, email=email).first()
            if not existing:
                contact = Contact(
                    user_id=user.id,
                    email=email,
                    display_name=kwargs.get('display_name'),
                    first_seen_source=kwargs.get('first_seen_source', 'scheduler'),
                    first_seen_at=kwargs.get('first_seen_at') or datetime.utcnow(),
                )
                db.session.add(contact)
                db.session.commit()
        # Call real function which should handle the existing contact gracefully
        return real_ensure_contact(user, email, **kwargs)

    monkeypatch.setattr(contact_service, "ensure_contact", fake_ensure_contact)

    # Mock calendar creation
    def fake_create_calendar_event(user, payload, **_kwargs):
        return "calendar-event-race-test", "https://meet.google.com/race-test"

    monkeypatch.setattr("app.services.public_booking.create_calendar_event", fake_create_calendar_event)

    # Mock email sending
    captured_emails = []
    def fake_send_email(to, subject, **kwargs):
        captured_emails.append((to, subject, kwargs))
        return True

    monkeypatch.setattr("app.services.scheduling_agent.gmail_service.send_email", fake_send_email)

    # Mock the agent to return a confirm_slot action
    def fake_agent(agent_input, history, latest_message, **kwargs):
        return {
            "action": "confirm_slot",
            "reply": "Meeting confirmed for Tuesday at 2pm.",
            "proposed_slots": [],
            "confirmed_slot": {
                "start": "2025-03-15T14:00:00-07:00",
                "end": "2025-03-15T14:30:00-07:00",
            },
        }

    monkeypatch.setattr("app.services.scheduling_agent.run_meeting_scheduler_agent", fake_agent)

    # Simulate incoming email that will trigger meeting confirmation
    email_data = {
        "sender": "participant@example.com",
        "sender_name": "External Participant",
        "subject": "Re: Team Standup",
        "body_text": "Tuesday at 2pm works great!",
        "body_html": "<p>Tuesday at 2pm works great!</p>",
        "to": [owner.email],
        "cc": ["another@example.com"],
        "to_participants": [
            {"email": owner.email, "name": owner.username}
        ],
        "cc_participants": [
            {"email": "another@example.com", "name": "Another Person"}
        ],
        "thread_id": f"thread-race-{unique_suffix}",
        "message_id": f"msg-race-{unique_suffix}",
        "received_at": datetime.utcnow(),
        "raw_headers": {},
        "attachments": [],
    }

    # This should not raise an exception despite the contact race condition
    result = handle_scheduling_email(email_data, owner)

    # Verify the meeting was successfully processed
    assert result is not None, "handle_scheduling_email should return a result"
    assert result["action"] == "confirm_slot"

    # Verify meeting request was created
    meeting_request = MeetingRequest.query.filter_by(
        user_id=owner.id,
        thread_id=email_data["thread_id"]
    ).first()
    assert meeting_request is not None, "MeetingRequest should be created"
    assert meeting_request.status == "confirmed"

    # Verify the event was created in the database
    event = Event.query.filter_by(
        user_id=owner.id,
        source="ai_booking",
        google_event_id="calendar-event-race-test"
    ).first()
    assert event is not None, "Calendar event should be created despite contact race condition"
    assert "Team Standup" in event.event_name, f"Event name should contain 'Team Standup', got: {event.event_name}"
    assert event.status == "scheduled"

    # Verify participants were created
    participants = MeetingParticipant.query.filter_by(
        meeting_request_id=meeting_request.id
    ).all()
    assert len(participants) > 0, "Participants should be created"

    # Verify contacts were created (despite race condition)
    participant_contact = Contact.query.filter_by(
        user_id=owner.id,
        email="participant@example.com"
    ).first()
    assert participant_contact is not None, "Contact should exist after race condition handling"

    # Verify ensure_contact was called (proving the race condition path was tested)
    assert len(ensure_contact_calls) > 0, "ensure_contact should have been called"
    
    # Verify email was sent
    assert len(captured_emails) > 0, "Confirmation email should be sent"

    print(f"✅ Test passed: Meeting created successfully despite contact race condition")


def test_confirm_slot_does_not_send_email_when_booking_fails(monkeypatch, app_context):
    """
    Test that when calendar event creation fails during confirm_slot,
    the scheduler agent does NOT send a confirmation email to participants.

    This validates the bug fix where previously the agent would send
    confirmation emails even when the calendar event creation failed,
    causing participants to think the meeting was confirmed when it wasn't.
    """
    unique_suffix = datetime.utcnow().strftime("%f")
    owner = User(
        username=f"Owner-{unique_suffix}",
        email=f"owner-{unique_suffix}@example.com",
        timezone="UTC",
        google_id=f"gid-fail-{unique_suffix}",
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
        slug=f"project-sync-fail-{unique_suffix}",
        duration_minutes=30,
        is_active=True,
        is_public=True,
    )
    db.session.add(event_type)
    db.session.commit()

    # Mock create_booking_event to FAIL
    def fake_create_booking_event_that_fails(*args, **kwargs):
        raise Exception("Calendar API error: Unable to create event")

    monkeypatch.setattr(
        "app.services.scheduling_agent.create_booking_event",
        fake_create_booking_event_that_fails
    )

    # Track emails sent
    captured_emails = []
    def fake_send_email(to, subject, **kwargs):
        captured_emails.append((to, subject, kwargs))
        return True

    monkeypatch.setattr("app.services.scheduling_agent.gmail_service.send_email", fake_send_email)

    # Mock the agent to return a confirm_slot action
    def fake_agent(agent_input, history, latest_message, **kwargs):
        return {
            "action": "confirm_slot",
            "reply": "Meeting confirmed for Feb 1 at 10am.",
            "proposed_slots": [],
            "confirmed_slot": {
                "start": "2025-02-01T10:00:00+00:00",
                "end": "2025-02-01T10:30:00+00:00",
            },
            "notes": None,
        }

    monkeypatch.setattr("app.services.scheduling_agent.run_meeting_scheduler_agent", fake_agent)

    email_data = {
        "sender": "participant@example.com",
        "sender_name": "Participant",
        "subject": "Meeting confirmation",
        "body_text": "Feb 1 at 10am works!",
        "body_html": "",
        "to": [owner.email],
        "cc": ["participant@example.com"],
        "thread_id": f"thread-fail-{unique_suffix}",
        "message_id": f"msg-fail-{unique_suffix}",
        "received_at": datetime.utcnow(),
        "raw_headers": {},
        "attachments": [],
    }

    # Process the email
    result = handle_scheduling_email(email_data, owner)

    # Verify the agent returned confirm_slot
    assert result is not None
    assert result["action"] == "confirm_slot"

    # CRITICAL: Verify NO confirmation email was sent to participants
    # Only owner notification email should be sent
    participant_emails = [
        email for email in captured_emails
        if "participant@example.com" in email[0]
    ]
    assert len(participant_emails) == 0, (
        "Confirmation email should NOT be sent to participants when booking creation fails. "
        f"Found {len(participant_emails)} emails sent to participants."
    )

    # Verify owner WAS notified about the failure
    owner_notifications = [
        email for email in captured_emails
        if owner.email in email[0] and "Action needed" in email[1]
    ]
    assert len(owner_notifications) > 0, (
        "Owner should be notified when booking creation fails"
    )

    # Verify the notification mentions calendar/booking issue
    notification_body = owner_notifications[0][2].get("text_body", "")
    assert "calendar" in notification_body.lower() or "booking" in notification_body.lower(), (
        "Owner notification should mention calendar or booking issue"
    )

    # Verify meeting request exists but has no google_event_id
    meeting_request = MeetingRequest.query.filter_by(
        user_id=owner.id,
        thread_id=email_data["thread_id"]
    ).first()
    assert meeting_request is not None
    confirmed_slot = meeting_request.confirmed_slot or {}
    assert "google_event_id" not in confirmed_slot or confirmed_slot.get("google_event_id") is None, (
        "MeetingRequest should not have google_event_id when booking creation fails"
    )

    # Verify no Event record was created
    event = Event.query.filter_by(user_id=owner.id, source="ai_booking").first()
    assert event is None, "No Event record should be created when booking creation fails"

    print(f"✅ Test passed: No confirmation email sent when booking creation fails")
