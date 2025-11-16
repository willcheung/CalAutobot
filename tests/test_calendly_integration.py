"""
Integration tests for Calendly features.
Tests complete workflows from OAuth to booking creation.
"""

import pytest
from datetime import datetime, timedelta, date
from unittest.mock import Mock, patch
import pytz

from app import db
from app.models import User, EventType, Contact
from app.services.calendly_api import CalendlyAPIClient
from app.services import availability as availability_service
from app.services import public_booking


@pytest.fixture
def complete_calendly_user(test_app):
    """Create a fully configured Calendly user for integration testing."""
    with test_app.app_context():
        user = User(
            username="IntegrationUser",
            email="integration@example.com",
            google_id="int123",
            timezone="America/New_York",
            calendly_access_token="test_access_token",
            calendly_refresh_token="test_refresh_token",
            calendly_user_uri="https://api.calendly.com/users/INT123",
            calendly_organization_uri="https://api.calendly.com/organizations/INTORG",
            calendly_scheduling_url="https://calendly.com/integration",
            calendly_timezone="America/New_York",
            calendly_plan="standard",
            calendly_connected_at=datetime.utcnow(),
            google_credentials_json='{"token": "test"}',
        )
        db.session.add(user)
        db.session.commit()

        # Create event types
        event_type = EventType(
            user_id=user.id,
            slug="meeting-30",
            title="30 Minute Meeting",
            duration_minutes=30,
            calendly_event_type_uri="https://api.calendly.com/event_types/INT_ET",
            calendly_scheduling_url="https://calendly.com/integration/30min",
            is_calendly_managed=True,
            is_active=True,
        )
        db.session.add(event_type)
        db.session.commit()

        yield user

        # Cleanup
        EventType.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()


class TestCalendlyIntegration:
    """Integration tests for complete Calendly workflows."""

    @patch("app.routes.calendly_auth.requests.post")
    @patch("app.routes.calendly_auth.requests.get")
    @patch("app.services.calendly_api.CalendlyAPIClient.get_organization")
    @patch("app.services.sync_calendly.CalendlyAPIClient.get_event_types")
    def test_complete_oauth_flow_with_sync(
        self, mock_get_event_types, mock_get_org, mock_get, mock_post, client, app_context
    ):
        """Test complete OAuth flow from connect to event type sync."""
        # Create user
        user = User(
            username="OAuthTest",
            email="oauth@example.com",
            google_id="oauth123",
        )
        db.session.add(user)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)

        # Mock token exchange
        mock_token_response = Mock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            "access_token": "oauth_access_token",
            "refresh_token": "oauth_refresh_token",
        }
        mock_post.return_value = mock_token_response

        # Mock user info
        mock_user_response = Mock()
        mock_user_response.status_code = 200
        mock_user_response.json.return_value = {
            "resource": {
                "uri": "https://api.calendly.com/users/OAUTH_USER",
                "current_organization": "https://api.calendly.com/organizations/OAUTH_ORG",
                "scheduling_url": "https://calendly.com/oauthtest",
                "timezone": "America/Chicago",
            }
        }
        mock_get.return_value = mock_user_response

        # Mock organization
        mock_get_org.return_value = {
            "uri": "https://api.calendly.com/organizations/OAUTH_ORG",
            "plan": "teams",
        }

        # Mock event types
        mock_get_event_types.return_value = [
            {
                "uri": "https://api.calendly.com/event_types/OAUTH_ET1",
                "name": "Quick Chat",
                "slug": "quick-chat",
                "active": True,
                "duration": 15,
                "scheduling_url": "https://calendly.com/oauthtest/quick",
            },
            {
                "uri": "https://api.calendly.com/event_types/OAUTH_ET2",
                "name": "Strategy Session",
                "slug": "strategy",
                "active": True,
                "duration": 60,
                "scheduling_url": "https://calendly.com/oauthtest/strategy",
            },
        ]

        # Act - complete OAuth flow
        response = client.get(
            "/auth/calendly/callback?code=oauth_code",
            follow_redirects=False,
        )

        # Assert - user should be fully configured
        assert response.status_code == 302
        db.session.expire_all()
        user = User.query.get(user.id)

        assert user.calendly_access_token == "oauth_access_token"
        assert user.calendly_refresh_token == "oauth_refresh_token"
        assert user.calendly_user_uri == "https://api.calendly.com/users/OAUTH_USER"
        assert user.calendly_timezone == "America/Chicago"
        assert user.calendly_plan == "teams"

        # Event types should be synced
        event_types = EventType.query.filter_by(user_id=user.id).all()
        assert len(event_types) == 2

        quick_chat = EventType.query.filter_by(slug="quick-chat").first()
        assert quick_chat is not None
        assert quick_chat.duration_minutes == 15
        assert quick_chat.is_calendly_managed is True

        # Cleanup
        EventType.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()

    @patch("app.services.calendly_api.requests.request")
    def test_availability_to_booking_workflow(
        self, mock_request, test_app, complete_calendly_user
    ):
        """Test complete workflow from checking availability to creating booking."""
        with test_app.app_context():
            event_type = EventType.query.filter_by(
                user_id=complete_calendly_user.id
            ).first()

            # Step 1: Check availability
            ny_tz = pytz.timezone("America/New_York")
            tomorrow = datetime.now(ny_tz) + timedelta(days=1)
            start_time = ny_tz.localize(
                datetime(tomorrow.year, tomorrow.month, tomorrow.day, 10, 0, 0)
            )

            # Mock availability response
            mock_avail_response = Mock()
            mock_avail_response.status_code = 200
            mock_avail_response.json.return_value = {
                "collection": [
                    {
                        "start_time": start_time.isoformat(),
                        "invitees_remaining": 1,
                        "status": "available",
                    },
                    {
                        "start_time": (start_time + timedelta(hours=1)).isoformat(),
                        "invitees_remaining": 1,
                        "status": "available",
                    },
                ]
            }

            # Mock booking creation response
            mock_booking_response = Mock()
            mock_booking_response.status_code = 200
            mock_booking_response.json.return_value = {
                "resource": {
                    "uri": "https://api.calendly.com/scheduled_events/WORKFLOW_EVENT",
                    "name": "30 Minute Meeting",
                    "status": "active",
                    "start_time": start_time.isoformat(),
                    "end_time": (start_time + timedelta(minutes=30)).isoformat(),
                }
            }

            # Set up mock to return different responses
            mock_request.side_effect = [mock_avail_response, mock_booking_response]

            # Step 1: Check availability
            client = CalendlyAPIClient(complete_calendly_user)
            available_slots = client.get_event_type_available_times(
                event_type_uri=event_type.calendly_event_type_uri,
                start_time=start_time,
                end_time=start_time + timedelta(hours=8),
            )

            assert len(available_slots) == 2
            assert available_slots[0]["status"] == "available"

            # Step 2: Create booking at first available slot
            first_slot_time = datetime.fromisoformat(
                available_slots[0]["start_time"].replace("Z", "+00:00")
            )

            # Create contact
            contact = Contact(
                user_id=complete_calendly_user.id,
                email="workflow@example.com",
                name="Workflow Guest",
            )
            db.session.add(contact)
            db.session.commit()

            # Create booking
            event = public_booking.create_booking_event(
                user=complete_calendly_user,
                event_type=event_type,
                start_datetime=first_slot_time,
                invitee_email="workflow@example.com",
                invitee_name="Workflow Guest",
            )

            # Assert - booking should be created
            assert event is not None
            assert event.calendly_event_uri == "https://api.calendly.com/scheduled_events/WORKFLOW_EVENT"

            # Cleanup
            db.session.delete(contact)
            db.session.delete(event)
            db.session.commit()

    @patch("app.services.calendly_api.CalendlyAPIClient.get_organization")
    @patch("app.services.sync_calendly.CalendlyAPIClient.get_event_types")
    def test_manual_sync_updates_plan_and_event_types(
        self, mock_get_event_types, mock_get_org, client, complete_calendly_user, app_context
    ):
        """Test that manual sync updates both plan and event types."""
        with client.session_transaction() as sess:
            sess["_user_id"] = str(complete_calendly_user.id)

        # Initial state
        assert complete_calendly_user.calendly_plan == "standard"

        # Mock updated organization (plan upgrade)
        mock_get_org.return_value = {
            "uri": "https://api.calendly.com/organizations/INTORG",
            "plan": "enterprise",  # Upgraded!
        }

        # Mock updated event types (new event type added)
        mock_get_event_types.return_value = [
            {
                "uri": "https://api.calendly.com/event_types/INT_ET",
                "name": "30 Minute Meeting",
                "slug": "meeting-30",
                "active": True,
                "duration": 30,
                "scheduling_url": "https://calendly.com/integration/30min",
            },
            {
                "uri": "https://api.calendly.com/event_types/INT_ET_NEW",
                "name": "45 Minute Consultation",
                "slug": "consult-45",
                "active": True,
                "duration": 45,
                "scheduling_url": "https://calendly.com/integration/45min",
            },
        ]

        # Act - manual sync
        response = client.post("/auth/calendly/sync", follow_redirects=False)

        # Assert
        assert response.status_code == 302

        db.session.expire_all()
        user = User.query.get(complete_calendly_user.id)
        assert user.calendly_plan == "enterprise"  # Should be updated

        # Event types should be updated
        event_types = EventType.query.filter_by(user_id=user.id).all()
        assert len(event_types) == 2  # Old + new

        new_et = EventType.query.filter_by(slug="consult-45").first()
        assert new_et is not None
        assert new_et.duration_minutes == 45

    def test_disconnect_clears_all_calendly_data(
        self, client, complete_calendly_user, app_context
    ):
        """Test that disconnect clears all Calendly-related data."""
        with client.session_transaction() as sess:
            sess["_user_id"] = str(complete_calendly_user.id)

        # Verify initial state
        assert complete_calendly_user.calendly_access_token is not None
        assert complete_calendly_user.calendly_plan is not None

        # Act - disconnect
        response = client.post("/auth/calendly/disconnect", follow_redirects=False)

        # Assert
        assert response.status_code == 302

        db.session.expire_all()
        user = User.query.get(complete_calendly_user.id)

        assert user.calendly_access_token is None
        assert user.calendly_refresh_token is None
        assert user.calendly_user_uri is None
        assert user.calendly_organization_uri is None
        assert user.calendly_scheduling_url is None
        assert user.calendly_webhook_subscription_uri is None
        assert user.calendly_connected_at is None

        # Note: calendly_plan and calendly_timezone are NOT cleared
        # This is intentional - they're historical data

    @patch("app.services.calendly_api.requests.request")
    def test_token_refresh_on_401(self, mock_request, test_app, complete_calendly_user):
        """Test that API client automatically refreshes token on 401."""
        with test_app.app_context():
            # First request returns 401
            mock_401_response = Mock()
            mock_401_response.status_code = 401
            mock_401_response.raise_for_status.side_effect = Exception("Unauthorized")

            # Token refresh request
            mock_token_response = Mock()
            mock_token_response.status_code = 200
            mock_token_response.json.return_value = {
                "access_token": "refreshed_token",
                "refresh_token": "new_refresh_token",
            }

            # Retry request after refresh
            mock_success_response = Mock()
            mock_success_response.status_code = 200
            mock_success_response.json.return_value = {
                "resource": {
                    "uri": "https://api.calendly.com/users/INT123",
                    "name": "Test User",
                }
            }

            # Set up sequence of responses
            with patch("app.routes.calendly_auth.requests.post") as mock_post:
                mock_post.return_value = mock_token_response
                mock_request.side_effect = [mock_401_response, mock_success_response]

                # Act
                client = CalendlyAPIClient(complete_calendly_user)
                result = client.get_current_user()

                # Assert - request should succeed after refresh
                assert result["resource"]["uri"] == "https://api.calendly.com/users/INT123"

                # Verify token was refreshed
                db.session.expire_all()
                user = User.query.get(complete_calendly_user.id)
                assert user.calendly_access_token == "refreshed_token"

    def test_calendly_fields_persisted_in_database(self, test_app):
        """Test that all Calendly fields are properly persisted."""
        with test_app.app_context():
            # Create user with all Calendly fields
            user = User(
                username="PersistTest",
                email="persist@example.com",
                google_id="persist123",
                calendly_access_token="access_123",
                calendly_refresh_token="refresh_123",
                calendly_user_uri="https://api.calendly.com/users/PERSIST",
                calendly_organization_uri="https://api.calendly.com/organizations/PERSISTORG",
                calendly_scheduling_url="https://calendly.com/persist",
                calendly_timezone="Europe/Paris",
                calendly_plan="enterprise",
                calendly_webhook_subscription_uri="https://api.calendly.com/webhook_subscriptions/WH",
                calendly_connected_at=datetime.utcnow(),
            )
            db.session.add(user)
            db.session.commit()

            # Retrieve from database
            retrieved = User.query.filter_by(email="persist@example.com").first()

            # Verify all fields
            assert retrieved.calendly_access_token == "access_123"
            assert retrieved.calendly_refresh_token == "refresh_123"
            assert retrieved.calendly_user_uri == "https://api.calendly.com/users/PERSIST"
            assert retrieved.calendly_organization_uri == "https://api.calendly.com/organizations/PERSISTORG"
            assert retrieved.calendly_scheduling_url == "https://calendly.com/persist"
            assert retrieved.calendly_timezone == "Europe/Paris"
            assert retrieved.calendly_plan == "enterprise"
            assert retrieved.calendly_webhook_subscription_uri == "https://api.calendly.com/webhook_subscriptions/WH"
            assert retrieved.calendly_connected_at is not None

            # Cleanup
            db.session.delete(user)
            db.session.commit()
