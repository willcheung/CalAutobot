from datetime import datetime, date

import pytz
import pytest

from app import db
from app.models import User, EventType, Contact
from app.services.availability import Slot, AvailabilityBatch


@pytest.fixture
def user_with_event_type(test_app):
    with test_app.app_context():
        user = User(
            username="TestUser",
            email="test@example.com",
            handle="testhandle",
            timezone="America/Los_Angeles",
        )
        db.session.add(user)
        db.session.commit()

        event_type = EventType(
            user_id=user.id,
            slug="demo",
            title="Demo Meeting",
            duration_minutes=30,
            is_active=True,
            is_calendly_managed=False,
        )
        db.session.add(event_type)
        db.session.commit()

        return {
            "email": user.email,
            "handle": user.handle,
            "event_type_slug": event_type.slug,
            "event_type_title": event_type.title,
        }


def test_extension_availability_requires_auth(client):
    resp = client.get("/api/extension/availability_text")
    assert resp.status_code == 401


def test_extension_availability_returns_slots(client, monkeypatch, test_app, user_with_event_type):
    tz = pytz.timezone("America/Los_Angeles")
    day = date(2025, 11, 18)
    slot1 = Slot(start=tz.localize(datetime(2025, 11, 18, 10, 0)), end=tz.localize(datetime(2025, 11, 18, 10, 30)))
    slot2 = Slot(start=tz.localize(datetime(2025, 11, 18, 11, 0)), end=tz.localize(datetime(2025, 11, 18, 11, 30)))
    batch = AvailabilityBatch(slots_by_date={day: [slot1, slot2]}, availability_map={day: True})

    import app.services.availability as availability_service
    monkeypatch.setattr(availability_service, "get_availability_for_range", lambda *args, **kwargs: batch)

    resp = client.get(
        f"/api/extension/availability_text?count=1&user_email={user_with_event_type['email']}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert len(data["slots"]) == 1
    assert "10:00" in data["slots"][0]["display"]
    assert user_with_event_type["event_type_title"] in data["text"]


def test_extension_booking_link_requires_auth(client):
    resp = client.get("/api/extension/booking_link")
    assert resp.status_code == 401


def test_extension_booking_link_returns_url(client, test_app, user_with_event_type):
    with test_app.app_context():
        test_app.config["SERVER_NAME"] = "calautobot.test"
        resp = client.get(
            f"/api/extension/booking_link?user_email={user_with_event_type['email']}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert user_with_event_type["event_type_slug"] in data["booking_link"]
        assert user_with_event_type["handle"] in data["booking_link"]


def test_extension_contacts_requires_auth(client):
    resp = client.post('/api/extension/contacts', json={})
    assert resp.status_code == 401


def test_extension_contacts_saved(client, test_app, user_with_event_type):
    with test_app.app_context():
        resp = client.post(
            f"/api/extension/contacts?user_email={user_with_event_type['email']}",
            headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            json={
                'contacts': [
                    {'email': 'newperson@example.com', 'name': 'New Person'},
                    {'email': 'test@example.com', 'name': 'Existing'},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['processed'] == 2
        assert data['created'] >= 1
        assert Contact.query.filter_by(email='newperson@example.com').count() == 1
