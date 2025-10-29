from types import SimpleNamespace
from uuid import uuid4

from app import db
from datetime import datetime, timedelta

from app.models import Event, User, Contact, MeetingRequest, MeetingParticipant


def login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_extract_events_route_success(monkeypatch, client, app_context):
    user = User(username="route-user", email=f"route-{uuid4().hex}@example.com", timezone="UTC")
    db.session.add(user)
    db.session.commit()

    login(client, user.id)

    captured = {}

    def fake_process_text(text, current_user, source_type="manual", auto_sync=True):
        captured["text"] = text
        captured["user_id"] = current_user.id
        captured["auto_sync"] = auto_sync
        return {
            "events": [SimpleNamespace()],
            "synced_count": 1,
            "text_input": SimpleNamespace(id=123),
            "from_email": None,
        }

    monkeypatch.setattr("app.routes.main_routes.process_text_to_events", fake_process_text)

    response = client.post("/extract_events", data={"text": "Weekly sync notes"})

    assert response.status_code == 302
    assert captured["text"] == "Weekly sync notes"
    assert captured["user_id"] == user.id
    assert captured["auto_sync"] is True

    with client.session_transaction() as session:
        flashes = session.get("_flashes", [])

    assert any("Successfully extracted 1 event(s)" in message for _, message in flashes)


def test_api_extract_events_returns_payload(monkeypatch, client, app_context):
    user = User(username="api-user", email=f"api-{uuid4().hex}@example.com", timezone="UTC")
    db.session.add(user)
    db.session.commit()

    login(client, user.id)

    dummy_event = SimpleNamespace(id=1)
    captured_request = {}

    def fake_process_text(text, current_user, source_type="api", auto_sync=True):
        captured_request.update({
            "text": text,
            "user_id": current_user.id,
            "source_type": source_type,
            "auto_sync": auto_sync,
        })
        return {
            "events": [dummy_event],
            "synced_count": 0,
            "text_input": SimpleNamespace(id=456),
            "from_email": "sender@example.com",
        }

    def fake_format_event(event):
        assert event is dummy_event
        return {"id": event.id, "event_name": "Demo"}

    monkeypatch.setattr("app.routes.main_routes.process_text_to_events", fake_process_text)
    monkeypatch.setattr("app.routes.main_routes.format_event_for_api", fake_format_event)

    response = client.post(
        "/api/extract_events",
        json={"text": "Parse this", "auto_sync": False},
    )

    assert response.status_code == 200
    payload = response.get_json()

    assert payload["success"] is True
    assert payload["events_count"] == 1
    assert payload["events"][0]["event_name"] == "Demo"
    assert captured_request == {
        "text": "Parse this",
        "user_id": user.id,
        "source_type": "api",
        "auto_sync": False,
    }


def test_bookings_view_filters_by_status(client, app_context):
    user = User(username="bookings-user", email=f"bookings-{uuid4().hex}@example.com", timezone="UTC")
    db.session.add(user)
    db.session.commit()

    login(client, user.id)

    today = datetime.utcnow()
    upcoming = Event(
        user_id=user.id,
        event_name="Upcoming Session",
        start_date=(today + timedelta(days=2)).date(),
        start_time=(today + timedelta(days=2)).time(),
        status="scheduled",
        source="public_booking",
    )
    past = Event(
        user_id=user.id,
        event_name="Past Session",
        start_date=(today - timedelta(days=3)).date(),
        start_time=(today - timedelta(days=3)).time(),
        status="scheduled",
        source="extracted",
    )
    cancelled = Event(
        user_id=user.id,
        event_name="Cancelled Session",
        start_date=(today + timedelta(days=5)).date(),
        start_time=(today + timedelta(days=5)).time(),
        status="cancelled",
        source="ai_booking",
    )

    db.session.add_all([upcoming, past, cancelled])
    db.session.commit()

    resp_upcoming = client.get("/bookings")
    assert resp_upcoming.status_code == 200
    html = resp_upcoming.data.decode()
    assert "Upcoming Session" in html
    assert "Past Session" not in html
    assert "Cancelled Session" not in html

    resp_past = client.get("/bookings", query_string={"status": "past"})
    assert resp_past.status_code == 200
    html = resp_past.data.decode()
    assert "Past Session" in html
    assert "Upcoming Session" not in html

    resp_cancelled = client.get("/bookings", query_string={"status": "cancelled"})
    assert resp_cancelled.status_code == 200
    html = resp_cancelled.data.decode()
    assert "Cancelled Session" in html
    assert "Upcoming Session" not in html


def test_delete_contact_clears_participants(client, app_context):
    user = User(username="contacts-user", email=f"contacts-{uuid4().hex}@example.com", timezone="UTC")
    db.session.add(user)
    db.session.commit()

    login(client, user.id)

    contact = Contact(
        user_id=user.id,
        display_name="Prospect",
        email="prospect@example.com",
    )
    db.session.add(contact)
    db.session.commit()

    meeting_request = MeetingRequest(user_id=user.id, subject="Intro")
    db.session.add(meeting_request)
    db.session.commit()

    participant = MeetingParticipant(
        meeting_request_id=meeting_request.id,
        email="prospect@example.com",
        contact_id=contact.id,
    )
    db.session.add(participant)
    db.session.commit()

    response = client.delete(f"/contacts/{contact.id}")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"

    assert Contact.query.filter_by(id=contact.id).first() is None

    refreshed_participant = MeetingParticipant.query.filter_by(id=participant.id).first()
    assert refreshed_participant is not None
    assert refreshed_participant.contact_id is None


def test_contacts_page_localizes_last_interaction(client, app_context):
    user = User(username="timezone-user", email=f"tz-{uuid4().hex}@example.com", timezone="America/New_York")
    db.session.add(user)
    db.session.commit()

    contact = Contact(
        user_id=user.id,
        display_name="Late Night Guest",
        email="guest@example.com",
        last_interaction_at=datetime(2024, 5, 1, 3, 0, 0),  # Naive UTC
    )
    db.session.add(contact)
    db.session.commit()

    login(client, user.id)

    response = client.get("/contacts")
    assert response.status_code == 200
    html = response.data.decode()

    assert "Apr 30, 2024" in html
    assert "May 01, 2024" not in html
