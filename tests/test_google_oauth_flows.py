import json
from dataclasses import dataclass

import pytest

from app import db
from app.models import EventType, User
from app.routes.google_auth import CALENDAR_SCOPE, GOOGLE_DISCOVERY_URL
from app.services.users import assign_unique_handle


@dataclass
class DummyResponse:
    payload: dict
    status_code: int = 200

    @property
    def text(self) -> str:
        return json.dumps(self.payload)

    def json(self):
        return self.payload


def _mock_oauth_flow(monkeypatch, token_payload, userinfo_payload):
    token_endpoint = "https://oauth2.googleapis.com/token"
    userinfo_endpoint = "https://openidconnect.googleapis.com/v1/userinfo"

    def fake_get(url, *args, **kwargs):
        if url == GOOGLE_DISCOVERY_URL:
            return DummyResponse(
                {
                    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_endpoint": token_endpoint,
                    "userinfo_endpoint": userinfo_endpoint,
                }
            )
        if url == userinfo_endpoint:
            return DummyResponse(userinfo_payload)
        raise AssertionError(f"Unexpected GET {url}")

    def fake_post(url, *args, **kwargs):
        if url == token_endpoint:
            return DummyResponse(token_payload)
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr("app.routes.google_auth.requests.get", fake_get)
    monkeypatch.setattr("app.routes.google_auth.requests.post", fake_post)


@pytest.mark.usefixtures("app_context")
def test_new_google_signup_creates_default_event_type(client, monkeypatch):
    email = "new-user@example.com"
    timezone = "America/New_York"

    _mock_oauth_flow(
        monkeypatch,
        token_payload={
            "access_token": "access-123",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid email profile",
        },
        userinfo_payload={
            "email": email,
            "email_verified": True,
            "sub": "google-sub-123",
        },
    )

    with client.session_transaction() as sess:
        sess["user_timezone"] = timezone
        sess["oauth_flow"] = "basic"

    response = client.get("/google_login/callback?code=dummy-code")
    assert response.status_code == 302

    user = User.query.filter_by(email=email).one()
    assert user.timezone == timezone
    assert user.google_id == "google-sub-123"
    assert user.google_token is None  # Basic flow doesn't store token (no calendar scope)
    assert len(user.event_types) == 1
    assert user.event_types[0].title == "30 min chat"


@pytest.mark.usefixtures("app_context")
def test_provisional_upgrade_with_full_scope_gets_default_event_type(client, monkeypatch):
    email = "provisional@example.com"
    provisional_user = User(
        username=email,
        email=email,
        email_count=1,
        timezone="UTC",
    )
    db.session.add(provisional_user)
    db.session.flush()
    assign_unique_handle(provisional_user, email)
    db.session.commit()

    assert EventType.query.filter_by(user_id=provisional_user.id).count() == 0

    _mock_oauth_flow(
        monkeypatch,
        token_payload={
            "access_token": "access-456",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": f"openid email profile {CALENDAR_SCOPE}",
            "refresh_token": "refresh-token-456",
        },
        userinfo_payload={
            "email": email,
            "email_verified": True,
            "sub": "google-sub-456",
        },
    )

    with client.session_transaction() as sess:
        sess["user_timezone"] = "Europe/London"
        sess["oauth_flow"] = "calendar"

    response = client.get("/google_login/callback?code=upgrade-code")
    assert response.status_code == 302

    user = User.query.filter_by(email=email).one()
    # Upgrades should populate Google credentials but keep existing timezone
    assert user.google_id == "google-sub-456"
    assert user.google_refresh_token == "refresh-token-456"
    assert user.timezone == "UTC"
    assert len(user.event_types) == 1
    assert user.event_types[0].title == "30 min chat"
