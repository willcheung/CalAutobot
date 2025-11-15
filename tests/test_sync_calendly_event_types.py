"""
Tests for Calendly event type syncing service.
Following TDD - tests written before implementation.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import json

from app import db
from app.models import User, EventType
from app.services.sync_calendly import sync_calendly_event_types


@pytest.fixture
def calendly_user(test_app):
    """Create a user with Calendly connected."""
    with test_app.app_context():
        user = User(
            username="testuser",
            email="test@example.com",
            google_id="123",
            calendly_access_token="test_access_token",
            calendly_user_uri="https://api.calendly.com/users/USER123",
            calendly_connected_at=datetime.utcnow(),
        )
        db.session.add(user)
        db.session.commit()
        yield user
        # Cleanup
        db.session.delete(user)
        db.session.commit()


@pytest.fixture
def mock_calendly_event_types():
    """Mock Calendly API response for event types."""
    return [
        {
            "uri": "https://api.calendly.com/event_types/ET001",
            "name": "30 Minute Meeting",
            "slug": "30min",
            "active": True,
            "duration": 30,
            "description_plain": "Quick 30 minute chat",
            "scheduling_url": "https://calendly.com/testuser/30min",
            "kind": "solo",
            "location": {
                "type": "zoom",
                "join_url": "https://zoom.us/j/123"
            }
        },
        {
            "uri": "https://api.calendly.com/event_types/ET002",
            "name": "60 Minute Consultation",
            "slug": "60min",
            "active": False,
            "duration": 60,
            "description_plain": "In-depth consultation",
            "scheduling_url": "https://calendly.com/testuser/60min",
            "kind": "solo",
            "location": {
                "type": "physical",
                "location": "123 Main St"
            }
        },
    ]


class TestSyncCalendlyEventTypes:
    """Test suite for sync_calendly_event_types function."""

    @patch("app.services.sync_calendly.CalendlyAPIClient")
    def test_sync_creates_new_event_types(self, mock_client_class, test_app, calendly_user, mock_calendly_event_types):
        """Test that sync creates new event types from Calendly."""
        # Arrange
        mock_client = Mock()
        mock_client.get_event_types.return_value = mock_calendly_event_types
        mock_client_class.return_value = mock_client

        # Act
        with test_app.app_context():
            sync_calendly_event_types(calendly_user)

            # Assert
            event_types = EventType.query.filter_by(user_id=calendly_user.id).all()
            assert len(event_types) == 2

            # Check first event type
            et1 = EventType.query.filter_by(calendly_event_type_uri=mock_calendly_event_types[0]['uri']).first()
            assert et1 is not None
            assert et1.title == "30 Minute Meeting"
            assert et1.slug == "30min"
            assert et1.is_active is True
            assert et1.duration_minutes == 30
            assert et1.description == "Quick 30 minute chat"
            assert et1.calendly_scheduling_url == "https://calendly.com/testuser/30min"
            assert et1.calendly_kind == "solo"
            assert et1.is_calendly_managed is True
            assert et1.calendly_last_synced_at is not None

            # Check location stored as JSON
            location = json.loads(et1.calendly_location_json)
            assert location["type"] == "zoom"
            assert location["join_url"] == "https://zoom.us/j/123"

    @patch("app.services.sync_calendly.CalendlyAPIClient")
    def test_sync_updates_existing_event_types(self, mock_client_class, test_app, calendly_user):
        """Test that sync updates existing event types."""
        with test_app.app_context():
            # Arrange - create existing event type
            existing_et = EventType(
                user_id=calendly_user.id,
                slug="30min",
                title="Old Title",
                duration_minutes=25,
                calendly_event_type_uri="https://api.calendly.com/event_types/ET001",
                is_calendly_managed=True,
                is_active=False,
            )
            db.session.add(existing_et)
            db.session.commit()

            # Mock Calendly response with updated data
            mock_client = Mock()
            mock_client.get_event_types.return_value = [
                {
                    "uri": "https://api.calendly.com/event_types/ET001",
                    "name": "New Title",
                    "slug": "30min-updated",
                    "active": True,
                    "duration": 30,
                    "description_plain": "Updated description",
                    "scheduling_url": "https://calendly.com/testuser/30min",
                    "kind": "group",
                    "location": {"type": "ask_invitee"}
                }
            ]
            mock_client_class.return_value = mock_client

            # Act
            sync_calendly_event_types(calendly_user)

            # Assert
            db.session.refresh(existing_et)
            assert existing_et.title == "New Title"
            assert existing_et.slug == "30min-updated"
            assert existing_et.is_active is True
            assert existing_et.duration_minutes == 30
            assert existing_et.description == "Updated description"
            assert existing_et.calendly_kind == "group"

    @patch("app.services.sync_calendly.CalendlyAPIClient")
    def test_sync_handles_no_event_types(self, mock_client_class, test_app, calendly_user):
        """Test that sync handles user with no event types."""
        with test_app.app_context():
            # Arrange
            mock_client = Mock()
            mock_client.get_event_types.return_value = []
            mock_client_class.return_value = mock_client

            # Act
            sync_calendly_event_types(calendly_user)

            # Assert
            event_types = EventType.query.filter_by(user_id=calendly_user.id).all()
            assert len(event_types) == 0

    @patch("app.services.sync_calendly.CalendlyAPIClient")
    def test_sync_handles_missing_optional_fields(self, mock_client_class, test_app, calendly_user):
        """Test that sync handles event types missing optional fields."""
        with test_app.app_context():
            # Arrange
            mock_client = Mock()
            mock_client.get_event_types.return_value = [
                {
                    "uri": "https://api.calendly.com/event_types/ET001",
                    "name": "Minimal Event Type",
                    "slug": "minimal",
                    "active": True,
                    "duration": 15,
                    "scheduling_url": "https://calendly.com/testuser/minimal",
                    # Missing: description_plain, kind, location
                }
            ]
            mock_client_class.return_value = mock_client

            # Act
            sync_calendly_event_types(calendly_user)

            # Assert
            et = EventType.query.filter_by(calendly_event_type_uri="https://api.calendly.com/event_types/ET001").first()
            assert et is not None
            assert et.title == "Minimal Event Type"
            assert et.description is None
            assert et.calendly_kind is None
            assert et.calendly_location_json is None

    @patch("app.services.sync_calendly.CalendlyAPIClient")
    def test_sync_handles_api_error_gracefully(self, mock_client_class, test_app, calendly_user):
        """Test that sync handles Calendly API errors gracefully."""
        with test_app.app_context():
            # Arrange
            mock_client = Mock()
            mock_client.get_event_types.side_effect = Exception("API Error")
            mock_client_class.return_value = mock_client

            # Act & Assert - should raise exception or handle it (depending on implementation)
            with pytest.raises(Exception) as exc_info:
                sync_calendly_event_types(calendly_user)

            assert "API Error" in str(exc_info.value)

    @patch("app.services.sync_calendly.CalendlyAPIClient")
    def test_sync_preserves_local_settings(self, mock_client_class, test_app, calendly_user):
        """Test that sync doesn't overwrite local-only settings like is_public."""
        with test_app.app_context():
            # Arrange - create event type with custom local settings
            existing_et = EventType(
                user_id=calendly_user.id,
                slug="30min",
                title="Old Title",
                duration_minutes=30,
                calendly_event_type_uri="https://api.calendly.com/event_types/ET001",
                is_calendly_managed=True,
                is_public=False,  # Local setting
            )
            db.session.add(existing_et)
            db.session.commit()

            # Mock Calendly response
            mock_client = Mock()
            mock_client.get_event_types.return_value = [
                {
                    "uri": "https://api.calendly.com/event_types/ET001",
                    "name": "30 Minute Meeting",
                    "slug": "30min",
                    "active": True,
                    "duration": 30,
                    "scheduling_url": "https://calendly.com/testuser/30min",
                }
            ]
            mock_client_class.return_value = mock_client

            # Act
            sync_calendly_event_types(calendly_user)

            # Assert - is_public should remain unchanged
            db.session.refresh(existing_et)
            assert existing_et.is_public is False  # Should not be changed by sync

    def test_sync_requires_calendly_connected_user(self, test_app):
        """Test that sync requires user to have Calendly connected."""
        with test_app.app_context():
            # Arrange - user without Calendly
            user = User(
                username="no_calendly",
                email="nocal@example.com",
                google_id="456",
            )
            db.session.add(user)
            db.session.commit()

            # Act & Assert
            with pytest.raises(Exception):
                sync_calendly_event_types(user)

    @patch("app.services.sync_calendly.CalendlyAPIClient")
    def test_sync_handles_complex_location_types(self, mock_client_class, test_app, calendly_user):
        """Test that sync correctly stores various location types."""
        with test_app.app_context():
            # Arrange
            mock_client = Mock()
            mock_client.get_event_types.return_value = [
                {
                    "uri": "https://api.calendly.com/event_types/ET001",
                    "name": "Physical Meeting",
                    "slug": "physical",
                    "active": True,
                    "duration": 30,
                    "scheduling_url": "https://calendly.com/testuser/physical",
                    "location": {
                        "type": "physical",
                        "location": "123 Main St, Office 5"
                    }
                },
                {
                    "uri": "https://api.calendly.com/event_types/ET002",
                    "name": "Phone Call",
                    "slug": "phone",
                    "active": True,
                    "duration": 15,
                    "scheduling_url": "https://calendly.com/testuser/phone",
                    "location": {
                        "type": "outbound_call",
                        "location": "+1234567890"
                    }
                },
                {
                    "uri": "https://api.calendly.com/event_types/ET003",
                    "name": "Google Meet",
                    "slug": "meet",
                    "active": True,
                    "duration": 45,
                    "scheduling_url": "https://calendly.com/testuser/meet",
                    "location": {
                        "type": "google_meet"
                    }
                },
            ]
            mock_client_class.return_value = mock_client

            # Act
            sync_calendly_event_types(calendly_user)

            # Assert
            et1 = EventType.query.filter_by(slug="physical").first()
            location1 = json.loads(et1.calendly_location_json)
            assert location1["type"] == "physical"
            assert location1["location"] == "123 Main St, Office 5"

            et2 = EventType.query.filter_by(slug="phone").first()
            location2 = json.loads(et2.calendly_location_json)
            assert location2["type"] == "outbound_call"

            et3 = EventType.query.filter_by(slug="meet").first()
            location3 = json.loads(et3.calendly_location_json)
            assert location3["type"] == "google_meet"
