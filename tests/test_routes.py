from types import SimpleNamespace
from uuid import uuid4

from app import db
from app.models import User


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
