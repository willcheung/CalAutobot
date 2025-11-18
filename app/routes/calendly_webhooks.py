"""
Calendly webhook handler for CalAutobot.

Handles webhook events from Calendly to sync bookings made through Calendly UI.
"""

import hashlib
import hmac
import os
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify
from dateutil import parser

from app import db
from app.models import User, Event, EventType
from app.services import contacts as contact_service

logger = logging.getLogger(__name__)

CALENDLY_WEBHOOK_SECRET = os.environ.get("CALENDLY_WEBHOOK_SECRET", "")

calendly_webhooks = Blueprint("calendly_webhooks", __name__)


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify Calendly webhook signature."""
    if not CALENDLY_WEBHOOK_SECRET:
        logger.warning("CALENDLY_WEBHOOK_SECRET not configured, skipping signature verification")
        return True  # In dev, allow if secret not set

    expected_signature = hmac.new(
        CALENDLY_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature, expected_signature)


@calendly_webhooks.route("/webhooks/calendly", methods=["POST"])
def handle_webhook():
    """Handle Calendly webhook events."""

    # Verify webhook signature
    signature = request.headers.get("Calendly-Webhook-Signature", "")
    if not verify_webhook_signature(request.data, signature):
        logger.warning("Invalid Calendly webhook signature")
        return jsonify({"error": "Invalid signature"}), 401

    payload = request.json
    event_type = payload.get("event")

    logger.info(f"Received Calendly webhook: {event_type}")

    if event_type == "invitee.created":
        return handle_invitee_created(payload)
    elif event_type == "invitee.canceled":
        return handle_invitee_canceled(payload)
    else:
        logger.info(f"Unhandled webhook event type: {event_type}")
        return jsonify({"status": "ignored"}), 200


def handle_invitee_created(payload: dict):
    """Handle invitee.created webhook event."""
    try:
        event_data = payload.get("payload", {})
        event_uri = event_data.get("event")
        invitee_uri = event_data.get("uri")

        # Extract event details
        name = event_data.get("name", "")
        start_time_str = event_data.get("start_time")
        end_time_str = event_data.get("end_time")
        status = event_data.get("status", "active")
        location = event_data.get("location", {})

        # Extract invitee details
        invitee_email = event_data.get("email", "")
        invitee_name = event_data.get("name", "")

        # Extract event type URI
        event_type_uri = event_data.get("event_type")

        # Find user by event type
        event_type = EventType.query.filter_by(calendly_event_type_uri=event_type_uri).first()
        if not event_type:
            logger.warning(f"No event type found for Calendly URI: {event_type_uri}")
            return jsonify({"error": "Event type not found"}), 404

        user = event_type.user

        # Parse datetimes
        start_dt = parser.isoparse(start_time_str)
        end_dt = parser.isoparse(end_time_str)
        duration_minutes = int((end_dt - start_dt).total_seconds() / 60)

        # Check if event already exists
        existing_event = Event.query.filter_by(calendly_event_uri=event_uri).first()
        if existing_event:
            logger.info(f"Event already exists: {event_uri}")
            return jsonify({"status": "already_exists"}), 200

        # Extract location info
        location_str = None
        conference_url = None
        if location:
            location_type = location.get("type")
            if location_type == "physical":
                location_str = location.get("location")
            elif location_type in ["zoom", "google_meet", "microsoft_teams", "custom"]:
                conference_url = location.get("join_url")
                location_str = f"{location_type.replace('_', ' ').title()} Meeting"

        # Create event in database
        event = Event(
            user_id=user.id,
            event_name=name,
            event_description=f"Managed via Calendly",
            start_date=start_dt.date(),
            start_time=start_dt.time(),
            end_date=end_dt.date(),
            end_time=end_dt.time(),
            start_datetime=start_dt.isoformat(),
            end_datetime=end_dt.isoformat(),
            location=location_str,
            conference_url=conference_url,
            invitee_email=invitee_email,
            invitee_name=invitee_name,
            calendly_event_uri=event_uri,
            calendly_invitee_uri=invitee_uri,
            calendly_last_synced_at=datetime.utcnow(),
            duration_minutes=duration_minutes,
            status="scheduled" if status == "active" else "cancelled",
            source="calendly",
            is_synced=True,
        )

        db.session.add(event)

        # Create/update contact
        if invitee_email:
            contact = contact_service.ensure_contact(
                user,
                invitee_email,
                display_name=invitee_name,
                first_seen_source="calendly",
                first_seen_at=start_dt,
            )
            contact_service.record_interaction(
                contact,
                occurred_at=start_dt,
                incoming=True,
            )

        db.session.commit()

        logger.info(f"Created event from Calendly webhook: {event.id}")
        return jsonify({"status": "created", "event_id": event.id}), 201

    except Exception as e:
        logger.error(f"Error handling invitee.created webhook: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


def handle_invitee_canceled(payload: dict):
    """Handle invitee.canceled webhook event."""
    try:
        event_data = payload.get("payload", {})
        invitee_uri = event_data.get("uri")

        # Find event by invitee URI
        event = Event.query.filter_by(calendly_invitee_uri=invitee_uri).first()
        if not event:
            logger.warning(f"No event found for Calendly invitee URI: {invitee_uri}")
            return jsonify({"error": "Event not found"}), 404

        # Update event status
        event.status = "cancelled"
        event.calendly_last_synced_at = datetime.utcnow()

        db.session.commit()

        logger.info(f"Cancelled event from Calendly webhook: {event.id}")
        return jsonify({"status": "cancelled", "event_id": event.id}), 200

    except Exception as e:
        logger.error(f"Error handling invitee.canceled webhook: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
