"""Tests for Calendly webhook handlers."""

import json
from datetime import datetime

import pytest

from app import db
from app.models import Event, EventType, User, Contact


@pytest.fixture()
def calendly_user(app_context):
    """Create a user with Calendly integration."""
    user = User(
        username="TestUser",
        email="test@example.com",
        calendly_access_token="test_token",
        calendly_user_uri="https://api.calendly.com/users/USER123",
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def calendly_event_type(app_context, calendly_user):
    """Create an event type linked to Calendly."""
    event_type = EventType(
        user_id=calendly_user.id,
        title="30 Minute Meeting",
        slug="30min",
        duration_minutes=30,
        calendly_event_type_uri="https://api.calendly.com/event_types/ET123",
        is_calendly_managed=True,
    )
    db.session.add(event_type)
    db.session.commit()
    return event_type


def test_invitee_created_webhook(client, calendly_event_type):
    """Test handling of invitee.created webhook."""
    payload = {
        "event": "invitee.created",
        "payload": {
            "event": "https://api.calendly.com/scheduled_events/EVENT123",
            "uri": "https://api.calendly.com/scheduled_events/EVENT123/invitees/INV123",
            "name": "30 Minute Meeting",
            "email": "invitee@example.com",
            "status": "active",
            "start_time": "2025-11-15T09:00:00Z",
            "end_time": "2025-11-15T09:30:00Z",
            "event_type": calendly_event_type.calendly_event_type_uri,
            "location": {
                "type": "zoom",
                "join_url": "https://zoom.us/j/123456789",
            },
        }
    }

    response = client.post(
        "/webhooks/calendly",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Calendly-Webhook-Signature": "test_signature"},
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "created"

    # Verify event was created in database
    event = Event.query.filter_by(calendly_event_uri=payload["payload"]["event"]).first()
    assert event is not None
    assert event.event_name == "30 Minute Meeting"
    assert event.invitee_email == "invitee@example.com"
    assert event.status == "scheduled"
    assert event.source == "calendly"
    assert event.conference_url == "https://zoom.us/j/123456789"


def test_invitee_created_creates_contact(client, calendly_event_type):
    """Test that invitee.created webhook creates a contact."""
    payload = {
        "event": "invitee.created",
        "payload": {
            "event": "https://api.calendly.com/scheduled_events/EVENT456",
            "uri": "https://api.calendly.com/scheduled_events/EVENT456/invitees/INV456",
            "name": "Test Meeting",
            "email": "newcontact@example.com",
            "status": "active",
            "start_time": "2025-11-16T10:00:00Z",
            "end_time": "2025-11-16T10:30:00Z",
            "event_type": calendly_event_type.calendly_event_type_uri,
            "location": {"type": "physical", "location": "Office 123"},
        }
    }

    response = client.post(
        "/webhooks/calendly",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Calendly-Webhook-Signature": "test_signature"},
    )

    assert response.status_code == 201

    # Verify contact was created
    contact = Contact.query.filter_by(email="newcontact@example.com").first()
    assert contact is not None
    assert contact.first_seen_source == "calendly"
    assert contact.last_interaction_at is not None


def test_invitee_created_duplicate_event(client, calendly_event_type):
    """Test that duplicate events are handled gracefully."""
    event_uri = "https://api.calendly.com/scheduled_events/DUPLICATE123"

    # Create existing event
    existing_event = Event(
        user_id=calendly_event_type.user_id,
        event_name="Existing",
        start_datetime="2025-11-15T09:00:00Z",
        end_datetime="2025-11-15T09:30:00Z",
        calendly_event_uri=event_uri,
        status="scheduled",
        source="calendly",
    )
    db.session.add(existing_event)
    db.session.commit()

    payload = {
        "event": "invitee.created",
        "payload": {
            "event": event_uri,
            "uri": "https://api.calendly.com/scheduled_events/DUPLICATE123/invitees/INV",
            "name": "Meeting",
            "email": "test@example.com",
            "status": "active",
            "start_time": "2025-11-15T09:00:00Z",
            "end_time": "2025-11-15T09:30:00Z",
            "event_type": calendly_event_type.calendly_event_type_uri,
        }
    }

    response = client.post(
        "/webhooks/calendly",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Calendly-Webhook-Signature": "test_signature"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "already_exists"

    # Should still only have one event
    events = Event.query.filter_by(calendly_event_uri=event_uri).all()
    assert len(events) == 1


def test_invitee_canceled_webhook(client, calendly_event_type):
    """Test handling of invitee.canceled webhook."""
    invitee_uri = "https://api.calendly.com/scheduled_events/EVENT789/invitees/INV789"

    # Create existing event
    event = Event(
        user_id=calendly_event_type.user_id,
        event_name="To Be Cancelled",
        start_datetime="2025-11-20T14:00:00Z",
        end_datetime="2025-11-20T14:30:00Z",
        calendly_event_uri="https://api.calendly.com/scheduled_events/EVENT789",
        calendly_invitee_uri=invitee_uri,
        status="scheduled",
        source="calendly",
    )
    db.session.add(event)
    db.session.commit()
    event_id = event.id

    payload = {
        "event": "invitee.canceled",
        "payload": {
            "uri": invitee_uri,
            "cancel_reason": "User requested cancellation",
        }
    }

    response = client.post(
        "/webhooks/calendly",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Calendly-Webhook-Signature": "test_signature"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "cancelled"
    assert data["event_id"] == event_id

    # Verify event was cancelled in database
    db.session.expire_all()
    event = Event.query.get(event_id)
    assert event.status == "cancelled"
    assert event.calendly_last_synced_at is not None


def test_invitee_canceled_event_not_found(client):
    """Test cancellation webhook when event doesn't exist."""
    payload = {
        "event": "invitee.canceled",
        "payload": {
            "uri": "https://api.calendly.com/scheduled_events/NONEXISTENT/invitees/INV",
        }
    }

    response = client.post(
        "/webhooks/calendly",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Calendly-Webhook-Signature": "test_signature"},
    )

    assert response.status_code == 404
    data = response.get_json()
    assert "not found" in data["error"].lower()


def test_webhook_unknown_event_type(client):
    """Test that unknown webhook events are ignored gracefully."""
    payload = {
        "event": "unknown.event.type",
        "payload": {"some": "data"},
    }

    response = client.post(
        "/webhooks/calendly",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Calendly-Webhook-Signature": "test_signature"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ignored"


def test_webhook_missing_event_type(client, calendly_event_type):
    """Test webhook when event type is not found."""
    payload = {
        "event": "invitee.created",
        "payload": {
            "event": "https://api.calendly.com/scheduled_events/EVENT",
            "uri": "https://api.calendly.com/scheduled_events/EVENT/invitees/INV",
            "name": "Meeting",
            "email": "test@example.com",
            "status": "active",
            "start_time": "2025-11-15T09:00:00Z",
            "end_time": "2025-11-15T09:30:00Z",
            "event_type": "https://api.calendly.com/event_types/NONEXISTENT",
        }
    }

    response = client.post(
        "/webhooks/calendly",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Calendly-Webhook-Signature": "test_signature"},
    )

    assert response.status_code == 404
    data = response.get_json()
    assert "not found" in data["error"].lower()
