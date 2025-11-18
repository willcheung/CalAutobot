"""Tests for Calendly API client."""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
import requests

from app import db
from app.models import User
from app.services.calendly_api import CalendlyAPIClient, CalendlyAPIError


@pytest.fixture()
def calendly_user(app_context):
    """Create a user with Calendly credentials."""
    user = User(
        username="TestUser",
        email="test@example.com",
        calendly_access_token="test_access_token",
        calendly_refresh_token="test_refresh_token",
        calendly_user_uri="https://api.calendly.com/users/TEST123",
        calendly_organization_uri="https://api.calendly.com/organizations/ORG123",
    )
    db.session.add(user)
    db.session.commit()
    return user


def test_client_initialization_without_token(app_context):
    """Test that client raises error when user has no access token."""
    user = User(username="NoToken", email="notoken@example.com")
    db.session.add(user)
    db.session.commit()

    with pytest.raises(CalendlyAPIError, match="no Calendly access token"):
        CalendlyAPIClient(user)


def test_client_headers(calendly_user):
    """Test that client sets correct authorization headers."""
    client = CalendlyAPIClient(calendly_user)
    headers = client._get_headers()

    assert headers["Authorization"] == "Bearer test_access_token"
    assert headers["Content-Type"] == "application/json"


@patch("app.services.calendly_api.requests.request")
def test_get_current_user(mock_request, calendly_user):
    """Test getting current user info."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "resource": {
            "uri": "https://api.calendly.com/users/TEST123",
            "name": "Test User",
            "email": "test@example.com",
            "scheduling_url": "https://calendly.com/testuser",
        }
    }
    mock_request.return_value = mock_response

    client = CalendlyAPIClient(calendly_user)
    result = client.get_current_user()

    assert result["resource"]["uri"] == "https://api.calendly.com/users/TEST123"
    assert result["resource"]["name"] == "Test User"
    mock_request.assert_called_once()


@patch("app.services.calendly_api.requests.request")
def test_get_event_types(mock_request, calendly_user):
    """Test getting event types for a user."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "collection": [
            {
                "uri": "https://api.calendly.com/event_types/ET1",
                "name": "30 Minute Meeting",
                "slug": "30min",
                "duration": 30,
            },
            {
                "uri": "https://api.calendly.com/event_types/ET2",
                "name": "60 Minute Meeting",
                "slug": "60min",
                "duration": 60,
            },
        ]
    }
    mock_request.return_value = mock_response

    client = CalendlyAPIClient(calendly_user)
    event_types = client.get_event_types()

    assert len(event_types) == 2
    assert event_types[0]["name"] == "30 Minute Meeting"
    assert event_types[1]["duration"] == 60


@patch("app.services.calendly_api.requests.request")
def test_get_event_type_available_times(mock_request, calendly_user):
    """Test getting available time slots for an event type."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "collection": [
            {
                "start_time": "2025-11-15T09:00:00Z",
                "invitees_remaining": 1,
                "status": "available",
            },
            {
                "start_time": "2025-11-15T09:30:00Z",
                "invitees_remaining": 1,
                "status": "available",
            },
        ]
    }
    mock_request.return_value = mock_response

    client = CalendlyAPIClient(calendly_user)
    start_time = datetime(2025, 11, 15, 0, 0)
    end_time = start_time + timedelta(days=1)

    slots = client.get_event_type_available_times(
        event_type_uri="https://api.calendly.com/event_types/ET1",
        start_time=start_time,
        end_time=end_time,
    )

    assert len(slots) == 2
    assert slots[0]["start_time"] == "2025-11-15T09:00:00Z"
    assert slots[0]["status"] == "available"


@patch("app.services.calendly_api.requests.request")
def test_create_invitee(mock_request, calendly_user):
    """Test creating a new booking (invitee)."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "resource": {
            "uri": "https://api.calendly.com/scheduled_events/EVENT123",
            "name": "30 Minute Meeting",
            "status": "active",
            "start_time": "2025-11-15T09:00:00Z",
            "end_time": "2025-11-15T09:30:00Z",
            "invitees": [
                {
                    "uri": "https://api.calendly.com/scheduled_events/EVENT123/invitees/INV123",
                    "email": "invitee@example.com",
                    "name": "John Doe",
                }
            ],
        }
    }
    mock_request.return_value = mock_response

    client = CalendlyAPIClient(calendly_user)
    start_time = datetime(2025, 11, 15, 9, 0)

    event = client.create_invitee(
        event_type_uri="https://api.calendly.com/event_types/ET1",
        start_time=start_time,
        email="invitee@example.com",
        name="John Doe",
        location={"kind": "zoom_conference"},
    )

    assert event["uri"] == "https://api.calendly.com/scheduled_events/EVENT123"
    assert event["status"] == "active"
    assert len(event["invitees"]) == 1
    # Verify location kind normalized to type/kind in payload
    call_args = mock_request.call_args
    assert call_args[1]["json"]["location"] == {"kind": "zoom_conference"}


@patch("app.services.calendly_api.requests.request")
def test_cancel_invitee(mock_request, calendly_user):
    """Test cancelling a booking."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}
    mock_request.return_value = mock_response

    client = CalendlyAPIClient(calendly_user)
    invitee_uri = "https://api.calendly.com/scheduled_events/EVENT123/invitees/INV123"

    result = client.cancel_invitee(invitee_uri, reason="Testing cancellation")

    assert result is True
    # Verify the correct endpoint was called
    call_args = mock_request.call_args
    assert "/scheduled_events/EVENT123/cancellation" in call_args[0][1]


@patch("app.services.calendly_api.requests.request")
def test_api_error_handling(mock_request, calendly_user):
    """Test that API errors are properly raised."""
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"message": "Invalid request"}
    mock_response.raise_for_status.side_effect = requests.HTTPError(
        "Bad Request", response=mock_response
    )
    mock_request.return_value = mock_response

    client = CalendlyAPIClient(calendly_user)

    with pytest.raises(CalendlyAPIError) as exc:
        client.get_current_user()
    assert "Invalid request" in str(exc.value)


@patch("app.services.calendly_api.requests.request")
@patch("app.routes.calendly_auth.refresh_calendly_token")
def test_token_refresh_on_401(mock_refresh, mock_request, calendly_user, app_context):
    """Test that client automatically refreshes token on 401."""
    # First call returns 401
    mock_401_response = Mock()
    mock_401_response.status_code = 401
    mock_401_response.raise_for_status.side_effect = Exception("Unauthorized")

    # Second call (after refresh) returns 200
    mock_200_response = Mock()
    mock_200_response.status_code = 200
    mock_200_response.json.return_value = {"resource": {"uri": "test"}}

    mock_request.side_effect = [mock_401_response, mock_200_response]

    # Mock successful token refresh
    def refresh_side_effect(user):
        user.calendly_access_token = "new_token"
        return "new_token"

    mock_refresh.side_effect = refresh_side_effect

    client = CalendlyAPIClient(calendly_user)
    result = client.get_current_user()

    # Should have refreshed token and retried
    assert mock_request.call_count == 2
    assert mock_refresh.call_count == 1
    assert result["resource"]["uri"] == "test"


@patch("app.services.calendly_api.requests.request")
def test_list_scheduled_events(mock_request, calendly_user):
    """Test listing scheduled events for a user."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "collection": [
            {
                "uri": "https://api.calendly.com/scheduled_events/EVENT1",
                "name": "Meeting 1",
                "start_time": "2025-11-15T09:00:00Z",
            },
            {
                "uri": "https://api.calendly.com/scheduled_events/EVENT2",
                "name": "Meeting 2",
                "start_time": "2025-11-15T10:00:00Z",
            },
        ]
    }
    mock_request.return_value = mock_response

    client = CalendlyAPIClient(calendly_user)
    events = client.list_scheduled_events(user_uri=calendly_user.calendly_user_uri)

    assert len(events) == 2
    assert events[0]["name"] == "Meeting 1"


@patch("app.services.calendly_api.requests.request")
def test_create_webhook_subscription(mock_request, calendly_user):
    """Test creating a webhook subscription."""
    mock_response = Mock()
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "resource": {
            "uri": "https://api.calendly.com/webhook_subscriptions/WEBHOOK123",
            "url": "https://example.com/webhooks/calendly",
            "events": ["invitee.created", "invitee.canceled"],
        }
    }
    mock_request.return_value = mock_response

    client = CalendlyAPIClient(calendly_user)
    webhook = client.create_webhook_subscription(
        webhook_url="https://example.com/webhooks/calendly",
        events=["invitee.created", "invitee.canceled"],
        organization_uri=calendly_user.calendly_organization_uri,
        signing_key="test_secret",
    )

    assert webhook["uri"] == "https://api.calendly.com/webhook_subscriptions/WEBHOOK123"
    assert len(webhook["events"]) == 2
