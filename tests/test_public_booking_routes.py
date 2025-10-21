from datetime import datetime, timedelta

from app import db
from app.models import Event, EventType, User
from app.services import event_types as event_types_service
from app.services import availability as availability_service
from app.services.users import assign_unique_handle


def login(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def test_public_booking_flow(client, app_context, monkeypatch):
    captured = {}

    def _capture_calendar_event(_user, payload, **_kwargs):
        captured["payload"] = payload
        captured["calendar_id"] = _kwargs.get("calendar_id")
        return "fake-google-id"

    monkeypatch.setattr(
        "app.services.public_booking.create_calendar_event",
        _capture_calendar_event,
    )
    user = User(username="Host", email=f"host-{datetime.utcnow().timestamp()}@example.com", timezone="UTC")
    user.default_booking_calendar_id = "booking-calendar"
    db.session.add(user)
    db.session.commit()
    assign_unique_handle(user)
    db.session.commit()

    target_date = datetime.utcnow().date() + timedelta(days=1)
    availability_service.set_weekly_windows(
        user,
        [
            {"weekday": target_date.weekday(), "start": "09:00", "end": "12:00", "is_active": True}
        ],
    )

    event_type = EventType(
        user_id=user.id,
        title="Quick Chat",
        slug="quick-chat",
        duration_minutes=30,
        is_active=True,
        is_public=True,
    )
    db.session.add(event_type)
    db.session.commit()

    profile_resp = client.get(f"/u/{user.handle}")
    assert profile_resp.status_code == 200

    tz = availability_service.get_timezone(user)
    slots = availability_service.get_slots_for_date(user, event_type, target_date)
    assert slots, "Expected available slots"
    chosen_slot = slots[0].start.isoformat()
    assert len(slots) > 1, "Expected multiple slots to test rescheduling"

    confirm_resp = client.get(
        f"/u/{user.handle}/{event_type.slug}/confirm",
        query_string={"slot": chosen_slot},
    )
    assert confirm_resp.status_code == 200
    assert b"Your name" in confirm_resp.data

    booking_resp = client.post(
        f"/u/{user.handle}/{event_type.slug}/confirm",
        data={
            "slot": chosen_slot,
            "invitee_name": "Guest",
            "invitee_email": "guest@example.com",
            "notes": "Looking forward",
        },
        follow_redirects=True,
    )
    assert booking_resp.status_code == 200
    assert b"This meeting is scheduled" in booking_resp.data
    assert b"Reschedule" in booking_resp.data
    booked_event = Event.query.filter_by(user_id=user.id).first()
    assert booked_event is not None
    original_event_id = booked_event.id
    original_token = booked_event.public_token
    assert original_token
    assert booked_event.status == "scheduled"
    assert booked_event.source == "public_booking"
    assert "payload" in captured
    assert captured.get("calendar_id") == "booking-calendar"
    assert captured["payload"]["event_name"] == "Host // Guest: Quick Chat"
    description_text = captured["payload"]["event_description"]
    assert "Looking forward" in description_text
    assert "Event Name: Quick Chat" in description_text
    assert "Location: Not specified" in description_text
    assert "Cancel:" in description_text
    assert "Reschedule:" in description_text
    assert description_text.strip().endswith("Created by Cal Autobot")

    reschedule_resp = client.get(
        f"/u/{user.handle}/{event_type.slug}",
        query_string={
            "former_slot": chosen_slot,
            "reschedule_token": original_token,
            "date": slots[0].start.date().isoformat(),
        },
    )
    assert reschedule_resp.status_code == 200
    assert b"Former time" in reschedule_resp.data
    assert Event.query.filter_by(user_id=user.id).count() == 1

    alternative_slot = next(s for s in slots if s.start.isoformat() != chosen_slot)

    confirm_resp_two = client.get(
        f"/u/{user.handle}/{event_type.slug}/confirm",
        query_string={
            "slot": alternative_slot.start.isoformat(),
            "reschedule_token": original_token,
        },
    )
    assert confirm_resp_two.status_code == 200
    booking_resp_two = client.post(
        f"/u/{user.handle}/{event_type.slug}/confirm",
        data={
            "slot": alternative_slot.start.isoformat(),
            "invitee_name": "Guest",
            "invitee_email": "guest@example.com",
            "notes": "Trying a new time",
            "reschedule_token": original_token,
        },
        follow_redirects=True,
    )
    assert booking_resp_two.status_code == 200
    assert b"This meeting is scheduled" in booking_resp_two.data
    events = Event.query.filter_by(user_id=user.id).order_by(Event.id.asc()).all()
    assert len(events) == 2
    cancelled_event = next(e for e in events if e.id == original_event_id)
    new_event = next(e for e in events if e.id != original_event_id)

    assert cancelled_event.status == "cancelled"
    assert cancelled_event.source == "public_booking"
    assert new_event.status == "scheduled"
    assert new_event.source == "public_booking"
    assert new_event.event_name == "Host // Guest: Quick Chat"
    assert new_event.event_description is not None
    assert "Created by Cal Autobot" in new_event.event_description


def test_public_booking_flow_handles_calendar_failure(client, app_context, monkeypatch):
    def _raise_calendar_error(*_args, **_kwargs):
        raise Exception("calendar boom")

    monkeypatch.setattr(
        "app.services.public_booking.create_calendar_event",
        _raise_calendar_error,
    )
    monkeypatch.setattr(
        "app.services.public_booking.delete_calendar_event",
        lambda *args, **kwargs: None,
    )

    user = User(username="HostFail", email=f"host-fail-{datetime.utcnow().timestamp()}@example.com", timezone="UTC")
    user.default_booking_calendar_id = "booking-calendar"
    db.session.add(user)
    db.session.commit()
    assign_unique_handle(user)
    db.session.commit()

    target_date = datetime.utcnow().date() + timedelta(days=1)
    availability_service.set_weekly_windows(
        user,
        [
            {"weekday": target_date.weekday(), "start": "09:00", "end": "12:00", "is_active": True}
        ],
    )

    event_type = EventType(
        user_id=user.id,
        title="Quick Chat",
        slug="quick-chat",
        duration_minutes=30,
        is_active=True,
        is_public=True,
    )
    db.session.add(event_type)
    db.session.commit()

    slots = availability_service.get_slots_for_date(user, event_type, target_date)
    assert slots, "Expected available slots"
    chosen_slot = slots[0].start.isoformat()

    confirm_resp = client.get(
        f"/u/{user.handle}/{event_type.slug}/confirm",
        query_string={"slot": chosen_slot},
    )
    assert confirm_resp.status_code == 200

    booking_resp = client.post(
        f"/u/{user.handle}/{event_type.slug}/confirm",
        data={
            "slot": chosen_slot,
            "invitee_name": "Guest",
            "invitee_email": "guest@example.com",
            "notes": "Looking forward",
        },
        follow_redirects=True,
    )
    assert booking_resp.status_code == 200
    assert b"We couldn&#39;t schedule that meeting. Please try again." in booking_resp.data
    assert Event.query.filter_by(user_id=user.id).count() == 0


def test_event_type_creation_route(client, app_context):
    user = User(username="RouteUser", email="route@example.com", timezone="UTC")
    db.session.add(user)
    db.session.commit()
    assign_unique_handle(user)
    db.session.commit()

    login(client, user)

    response = client.post(
        "/event-types",
        data={
            "title": "Demo Meeting",
            "duration_minutes": "30",
            "description": "Route test",
            "is_public": "on",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    items = event_types_service.list_event_types(user.id)
    assert len(items) == 1
    assert items[0].title == "Demo Meeting"
