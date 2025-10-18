from datetime import datetime, timedelta

from flask import url_for

from app import db
from app.models import Event, EventType, User
from app.services import event_types as event_types_service
from app.services import availability as availability_service
from app.services.users import assign_unique_handle


def login(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def test_public_booking_flow(client, app_context):
    user = User(username="Host", email=f"host-{datetime.utcnow().timestamp()}@example.com", timezone="UTC")
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

    reschedule_resp = client.get(
        url_for(
            "public_booking.event_type_page",
            handle=user.handle,
            slug=event_type.slug,
            former_slot=chosen_slot,
            cancel_event_id=booked_event.id,
        )
    )
    assert reschedule_resp.status_code == 200
    assert b"Former time" in reschedule_resp.data
    assert Event.query.filter_by(user_id=user.id).count() == 0

    alternative_slot = next(s for s in slots if s.start.isoformat() != chosen_slot)

    confirm_resp_two = client.get(
        f"/u/{user.handle}/{event_type.slug}/confirm",
        query_string={"slot": alternative_slot.start.isoformat()},
    )
    assert confirm_resp_two.status_code == 200
    booking_resp_two = client.post(
        f"/u/{user.handle}/{event_type.slug}/confirm",
        data={
            "slot": alternative_slot.start.isoformat(),
            "invitee_name": "Guest",
            "invitee_email": "guest@example.com",
            "notes": "Trying a new time",
        },
        follow_redirects=True,
    )
    assert booking_resp_two.status_code == 200
    assert b"This meeting is scheduled" in booking_resp_two.data
    new_event = Event.query.filter_by(user_id=user.id).first()
    assert new_event is not None


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
