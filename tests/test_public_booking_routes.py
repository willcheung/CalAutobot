from datetime import datetime, timedelta

from app import db
from app.models import EventType, User
from app.services import event_types as event_types_service
from app.services import availability as availability_service


def login(client, user):
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True


def test_public_booking_flow(client, app_context):
    user = User(username="Host", email=f"host-{datetime.utcnow().timestamp()}@example.com", timezone="UTC")
    db.session.add(user)
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

    profile_resp = client.get(f"/u/{user.id}")
    assert profile_resp.status_code == 200

    tz = availability_service.get_timezone(user)
    slots = availability_service.get_slots_for_date(user, event_type, target_date)
    assert slots, "Expected available slots"
    chosen_slot = slots[0].start.isoformat()

    booking_resp = client.post(
        f"/u/{user.id}/{event_type.slug}",
        data={
            "slot": chosen_slot,
            "invitee_name": "Guest",
            "invitee_email": "guest@example.com",
            "notes": "Looking forward",
        },
        follow_redirects=True,
    )
    assert booking_resp.status_code == 200
    assert b"You're booked!" in booking_resp.data


def test_event_type_creation_route(client, app_context):
    user = User(username="RouteUser", email="route@example.com", timezone="UTC")
    db.session.add(user)
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
