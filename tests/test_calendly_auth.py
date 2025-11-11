"""Tests for Calendly OAuth authentication."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from app import db
from app.models import User


@pytest.fixture()
def auth_user(app_context, client):
    """Create and login a test user."""
    user = User(
        username="AuthUser",
        email="authuser@example.com",
        google_id="google123",
    )
    db.session.add(user)
    db.session.commit()

    # Login the user
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)

    return user


def test_connect_calendly_redirects_to_oauth(client, auth_user):
    """Test that /auth/calendly redirects to Calendly OAuth."""
    response = client.get("/auth/calendly", follow_redirects=False)

    assert response.status_code == 302
    assert "auth.calendly.com/oauth/authorize" in response.location
    assert "client_id" in response.location
    assert "response_type=code" in response.location


@patch.dict("os.environ", {}, clear=False)
def test_connect_calendly_without_config(client, auth_user):
    """Test that connect fails gracefully without Calendly config."""
    # Clear Calendly config
    import os
    os.environ.pop("CALENDLY_CLIENT_ID", None)
    os.environ.pop("CALENDLY_CLIENT_SECRET", None)

    response = client.get("/auth/calendly", follow_redirects=True)

    # Should redirect back to onboarding with error
    assert response.status_code == 200
    # Flash message should indicate configuration issue


@patch("app.routes.calendly_auth.requests.post")
@patch("app.routes.calendly_auth.requests.get")
def test_callback_success(mock_get, mock_post, client, auth_user, app_context):
    """Test successful OAuth callback."""
    # Mock token exchange
    mock_token_response = Mock()
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
    }
    mock_post.return_value = mock_token_response

    # Mock user info fetch
    mock_user_response = Mock()
    mock_user_response.status_code = 200
    mock_user_response.json.return_value = {
        "resource": {
            "uri": "https://api.calendly.com/users/USER123",
            "current_organization": "https://api.calendly.com/organizations/ORG123",
            "scheduling_url": "https://calendly.com/authuser",
        }
    }
    mock_get.return_value = mock_user_response

    response = client.get(
        "/auth/calendly/callback?code=test_auth_code",
        follow_redirects=False,
    )

    assert response.status_code == 302

    # Verify user was updated in database
    db.session.expire_all()
    user = User.query.get(auth_user.id)
    assert user.calendly_access_token == "new_access_token"
    assert user.calendly_refresh_token == "new_refresh_token"
    assert user.calendly_user_uri == "https://api.calendly.com/users/USER123"
    assert user.calendly_organization_uri == "https://api.calendly.com/organizations/ORG123"
    assert user.calendly_scheduling_url == "https://calendly.com/authuser"
    assert user.calendly_connected_at is not None


def test_callback_without_code(client, auth_user):
    """Test callback without authorization code."""
    response = client.get("/auth/calendly/callback", follow_redirects=True)

    # Should redirect with error message
    assert response.status_code == 200


def test_callback_with_error(client, auth_user):
    """Test callback when user denies authorization."""
    response = client.get(
        "/auth/calendly/callback?error=access_denied",
        follow_redirects=True,
    )

    # Should redirect with error message
    assert response.status_code == 200

    # User should not have Calendly credentials
    db.session.expire_all()
    user = User.query.get(auth_user.id)
    assert user.calendly_access_token is None


@patch("app.routes.calendly_auth.requests.post")
def test_callback_token_exchange_failure(mock_post, client, auth_user):
    """Test callback when token exchange fails."""
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.raise_for_status.side_effect = Exception("Bad Request")
    mock_post.return_value = mock_response

    response = client.get(
        "/auth/calendly/callback?code=test_code",
        follow_redirects=True,
    )

    # Should redirect with error
    assert response.status_code == 200

    # User should not have Calendly credentials
    db.session.expire_all()
    user = User.query.get(auth_user.id)
    assert user.calendly_access_token is None


def test_disconnect_calendly(client, auth_user, app_context):
    """Test disconnecting Calendly account."""
    # Set up user with Calendly connection
    auth_user.calendly_access_token = "test_token"
    auth_user.calendly_refresh_token = "test_refresh"
    auth_user.calendly_user_uri = "https://api.calendly.com/users/USER123"
    auth_user.calendly_organization_uri = "https://api.calendly.com/organizations/ORG123"
    auth_user.calendly_scheduling_url = "https://calendly.com/authuser"
    auth_user.calendly_webhook_subscription_uri = "https://api.calendly.com/webhook_subscriptions/WH123"
    auth_user.calendly_connected_at = datetime.utcnow()
    db.session.commit()

    response = client.post("/auth/calendly/disconnect", follow_redirects=False)

    assert response.status_code == 302

    # Verify all Calendly fields were cleared
    db.session.expire_all()
    user = User.query.get(auth_user.id)
    assert user.calendly_access_token is None
    assert user.calendly_refresh_token is None
    assert user.calendly_user_uri is None
    assert user.calendly_organization_uri is None
    assert user.calendly_scheduling_url is None
    assert user.calendly_webhook_subscription_uri is None
    assert user.calendly_connected_at is None


@patch("app.routes.calendly_auth.requests.post")
def test_refresh_calendly_token(mock_post, auth_user, app_context):
    """Test token refresh functionality."""
    from app.routes.calendly_auth import refresh_calendly_token

    auth_user.calendly_refresh_token = "old_refresh_token"
    db.session.commit()

    # Mock successful token refresh
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
    }
    mock_post.return_value = mock_response

    result = refresh_calendly_token(auth_user)

    assert result is True
    db.session.expire_all()
    user = User.query.get(auth_user.id)
    assert user.calendly_access_token == "new_access_token"
    assert user.calendly_refresh_token == "new_refresh_token"


@patch("app.routes.calendly_auth.requests.post")
def test_refresh_calendly_token_failure(mock_post, auth_user, app_context):
    """Test token refresh failure."""
    from app.routes.calendly_auth import refresh_calendly_token

    auth_user.calendly_refresh_token = "old_refresh_token"
    db.session.commit()

    # Mock failed token refresh
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.raise_for_status.side_effect = Exception("Bad Request")
    mock_post.return_value = mock_response

    result = refresh_calendly_token(auth_user)

    assert result is False


def test_refresh_token_without_refresh_token(auth_user, app_context):
    """Test that refresh fails if user has no refresh token."""
    from app.routes.calendly_auth import refresh_calendly_token

    auth_user.calendly_refresh_token = None
    db.session.commit()

    result = refresh_calendly_token(auth_user)

    assert result is False
