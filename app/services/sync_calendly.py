"""
Calendly event type syncing service.

Handles syncing event types from Calendly API to local database.
"""

import logging
from datetime import datetime
from typing import List
import json

from app import db
from app.models import User, EventType
from app.services.calendly_api import CalendlyAPIClient, CalendlyAPIError

logger = logging.getLogger(__name__)


def sync_calendly_event_types(user: User) -> int:
    """
    Sync ALL event types from Calendly to local database.

    Args:
        user: User with Calendly connected

    Returns:
        Number of event types synced

    Raises:
        CalendlyAPIError: If user doesn't have Calendly connected or API fails
    """
    if not user.calendly_access_token:
        raise CalendlyAPIError("User does not have Calendly connected")

    logger.info(f"Starting Calendly event type sync for user {user.id}")

    # Fetch all event types from Calendly (handles pagination)
    client = CalendlyAPIClient(user)
    calendly_event_types = client.get_event_types()

    logger.info(f"Fetched {len(calendly_event_types)} event types from Calendly")

    synced_count = 0

    # Sync each event type
    for calendly_et in calendly_event_types:
        try:
            _sync_single_event_type(user, calendly_et)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping Calendly event type due to error: %s", exc)
            continue
        synced_count += 1

    db.session.commit()

    logger.info(f"Successfully synced {synced_count} event types for user {user.id}")
    return synced_count


def _sync_single_event_type(user: User, calendly_data: dict) -> EventType:
    """Sync a single event type from Calendly data to local database."""
    calendly_uri = calendly_data.get("uri")
    if not calendly_uri:
        raise CalendlyAPIError("Calendly event type is missing URI")

    duration = calendly_data.get("duration")
    if duration is None:
        raise CalendlyAPIError(f"Calendly event type {calendly_uri} is missing duration")

    # Find existing event type by Calendly URI
    event_type = EventType.query.filter_by(
        calendly_event_type_uri=calendly_uri
    ).first()

    if not event_type:
        # Create new event type
        event_type = EventType(
            user_id=user.id,
            calendly_event_type_uri=calendly_uri,
            is_calendly_managed=True,
        )
        db.session.add(event_type)
        logger.info(f"Creating new event type from Calendly: {calendly_data['name']}")
    else:
        logger.info(f"Updating existing event type: {calendly_data['name']}")

    # Sync core fields from Calendly
    event_type.title = calendly_data['name']
    event_type.slug = calendly_data['slug']
    event_type.is_active = calendly_data['active']
    event_type.duration_minutes = duration
    event_type.description = calendly_data.get('description_plain')

    # Sync new fields
    event_type.calendly_scheduling_url = calendly_data['scheduling_url']
    event_type.calendly_kind = calendly_data.get('kind')

    # Store full locations payload (Calendly API v2 exposes "locations" array)
    # We keep the array so later we can choose the best match; fallback to legacy "location".
    locations_payload = calendly_data.get("locations")
    if not locations_payload and calendly_data.get("location"):
        locations_payload = calendly_data.get("location")
    event_type.calendly_location_json = json.dumps(locations_payload) if locations_payload else None

    # Update sync timestamp
    event_type.calendly_last_synced_at = datetime.utcnow()

    # Note: We intentionally DO NOT update these local-only fields:
    # - is_public (local visibility setting)
    # - user_id (never changes)

    return event_type
