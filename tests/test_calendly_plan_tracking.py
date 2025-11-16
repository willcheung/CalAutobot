"""
Tests for Calendly plan tracking functionality.
Tests the new features added for tracking user's Calendly subscription plan.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from app import db
from app.models import User
from app.services.calendly_api import CalendlyAPIClient


@pytest.fixture
def calendly_user_with_plan(test_app):
    """Create a user with Calendly connected and plan tracked."""
    with test_app.app_context():
        user = User(
            username="PlanUser",
            email="planuser@example.com",
            google_id="plan123",
            calendly_access_token="test_access_token",
            calendly_user_uri="https://api.calendly.com/users/USER123",
            calendly_organization_uri="https://api.calendly.com/organizations/ORG123",
            calendly_plan="standard",
            calendly_connected_at=datetime.utcnow(),
        )
        db.session.add(user)
        db.session.commit()
        yield user
        # Cleanup
        db.session.delete(user)
        db.session.commit()


class TestCalendlyPlanTracking:
    """Test suite for Calendly plan tracking during OAuth and manual sync."""

    @patch("app.routes.calendly_auth.requests.post")
    @patch("app.routes.calendly_auth.requests.get")
    @patch("app.services.calendly_api.CalendlyAPIClient.get_organization")
    def test_oauth_callback_fetches_and_saves_plan(
        self, mock_get_org, mock_get, mock_post, client, app_context
    ):
        """Test that OAuth callback fetches organization plan and saves it."""
        # Create and login user
        user = User(
            username="TestUser",
            email="test@example.com",
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
                "scheduling_url": "https://calendly.com/testuser",
                "timezone": "America/Los_Angeles",
            }
        }
        mock_get.return_value = mock_user_response

        # Mock organization data fetch
        mock_get_org.return_value = {
            "uri": "https://api.calendly.com/organizations/ORG123",
            "name": "Test Organization",
            "plan": "teams",  # Testing "plan" field
        }

        # Act
        with patch("app.routes.calendly_auth.sync_calendly_event_types"):
            response = client.get(
                "/auth/calendly/callback?code=test_auth_code",
                follow_redirects=False,
            )

        # Assert
        assert response.status_code == 302
        db.session.expire_all()
        user = User.query.get(user.id)
        assert user.calendly_plan == "teams"
        assert user.calendly_timezone == "America/Los_Angeles"

    @patch("app.routes.calendly_auth.requests.post")
    @patch("app.routes.calendly_auth.requests.get")
    @patch("app.services.calendly_api.CalendlyAPIClient.get_organization")
    def test_oauth_callback_handles_different_plan_field_names(
        self, mock_get_org, mock_get, mock_post, client, app_context
    ):
        """Test that OAuth callback tries multiple field names for plan."""
        # Create and login user
        user = User(
            username="TestUser",
            email="test@example.com",
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
                "scheduling_url": "https://calendly.com/testuser",
                "timezone": "UTC",
            }
        }
        mock_get.return_value = mock_user_response

        # Mock organization data with alternative field name
        mock_get_org.return_value = {
            "uri": "https://api.calendly.com/organizations/ORG123",
            "name": "Test Organization",
            "subscription_tier": "enterprise",  # Testing alternative field name
        }

        # Act
        with patch("app.routes.calendly_auth.sync_calendly_event_types"):
            response = client.get(
                "/auth/calendly/callback?code=test_auth_code",
                follow_redirects=False,
            )

        # Assert
        assert response.status_code == 302
        db.session.expire_all()
        user = User.query.get(user.id)
        assert user.calendly_plan == "enterprise"

    @patch("app.routes.calendly_auth.requests.post")
    @patch("app.routes.calendly_auth.requests.get")
    @patch("app.services.calendly_api.CalendlyAPIClient.get_organization")
    def test_oauth_callback_defaults_to_unknown_if_no_plan_field(
        self, mock_get_org, mock_get, mock_post, client, app_context
    ):
        """Test that OAuth callback sets plan to 'unknown' if no plan field found."""
        # Create and login user
        user = User(
            username="TestUser",
            email="test@example.com",
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
                "scheduling_url": "https://calendly.com/testuser",
                "timezone": "UTC",
            }
        }
        mock_get.return_value = mock_user_response

        # Mock organization data WITHOUT any plan field
        mock_get_org.return_value = {
            "uri": "https://api.calendly.com/organizations/ORG123",
            "name": "Test Organization",
            # No plan, tier, subscription_tier, or plan_tier field
        }

        # Act
        with patch("app.routes.calendly_auth.sync_calendly_event_types"):
            response = client.get(
                "/auth/calendly/callback?code=test_auth_code",
                follow_redirects=False,
            )

        # Assert
        assert response.status_code == 302
        db.session.expire_all()
        user = User.query.get(user.id)
        assert user.calendly_plan == "unknown"

    @patch("app.routes.calendly_auth.requests.post")
    @patch("app.routes.calendly_auth.requests.get")
    @patch("app.services.calendly_api.CalendlyAPIClient.get_organization")
    def test_oauth_callback_handles_org_fetch_failure_gracefully(
        self, mock_get_org, mock_get, mock_post, client, app_context
    ):
        """Test that OAuth callback continues even if org fetch fails."""
        # Create and login user
        user = User(
            username="TestUser",
            email="test@example.com",
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
                "scheduling_url": "https://calendly.com/testuser",
                "timezone": "UTC",
            }
        }
        mock_get.return_value = mock_user_response

        # Mock organization fetch to fail
        mock_get_org.side_effect = Exception("API Error")

        # Act
        with patch("app.routes.calendly_auth.sync_calendly_event_types"):
            response = client.get(
                "/auth/calendly/callback?code=test_auth_code",
                follow_redirects=False,
            )

        # Assert - OAuth should still succeed
        assert response.status_code == 302
        db.session.expire_all()
        user = User.query.get(user.id)
        assert user.calendly_access_token == "new_access_token"
        assert user.calendly_plan == "unknown"  # Should default to unknown

    @patch("app.services.calendly_api.CalendlyAPIClient.get_organization")
    @patch("app.services.sync_calendly.sync_calendly_event_types")
    def test_manual_sync_updates_plan(
        self, mock_sync_event_types, mock_get_org, client, calendly_user_with_plan, app_context
    ):
        """Test that manual sync endpoint updates the plan."""
        # Login user
        with client.session_transaction() as sess:
            sess["_user_id"] = str(calendly_user_with_plan.id)

        # Mock organization data with updated plan
        mock_get_org.return_value = {
            "uri": "https://api.calendly.com/organizations/ORG123",
            "name": "Test Organization",
            "tier": "enterprise",  # Testing "tier" field and plan upgrade
        }

        # Mock event type sync
        mock_sync_event_types.return_value = 3

        # Act
        response = client.post("/auth/calendly/sync", follow_redirects=False)

        # Assert
        assert response.status_code == 302
        db.session.expire_all()
        user = User.query.get(calendly_user_with_plan.id)
        assert user.calendly_plan == "enterprise"  # Should be updated from "standard"

    @patch("app.services.calendly_api.CalendlyAPIClient.get_organization")
    @patch("app.services.sync_calendly.sync_calendly_event_types")
    def test_manual_sync_handles_plan_fetch_failure(
        self, mock_sync_event_types, mock_get_org, client, calendly_user_with_plan, app_context
    ):
        """Test that manual sync continues if plan fetch fails."""
        # Login user
        with client.session_transaction() as sess:
            sess["_user_id"] = str(calendly_user_with_plan.id)

        # Mock organization fetch to fail
        mock_get_org.side_effect = Exception("API Error")

        # Mock event type sync to succeed
        mock_sync_event_types.return_value = 2

        # Act
        response = client.post("/auth/calendly/sync", follow_redirects=False)

        # Assert - sync should still complete
        assert response.status_code == 302
        # Plan should remain unchanged
        db.session.expire_all()
        user = User.query.get(calendly_user_with_plan.id)
        assert user.calendly_plan == "standard"  # Should remain unchanged

    @patch("app.services.calendly_api.requests.request")
    def test_get_organization_api_call(self, mock_request, test_app, calendly_user_with_plan):
        """Test that get_organization makes correct API call."""
        with test_app.app_context():
            # Mock successful API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "resource": {
                    "uri": "https://api.calendly.com/organizations/ORG123",
                    "name": "Test Org",
                    "plan": "standard",
                }
            }
            mock_request.return_value = mock_response

            # Act
            client = CalendlyAPIClient(calendly_user_with_plan)
            org_data = client.get_organization(
                "https://api.calendly.com/organizations/ORG123"
            )

            # Assert
            assert org_data["uri"] == "https://api.calendly.com/organizations/ORG123"
            assert org_data["name"] == "Test Org"
            assert org_data["plan"] == "standard"

            # Verify API call
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "/organizations/ORG123" in call_args[0][1]

    def test_get_organization_extracts_uuid_correctly(
        self, test_app, calendly_user_with_plan
    ):
        """Test that get_organization correctly extracts UUID from URI."""
        with test_app.app_context():
            with patch("app.services.calendly_api.requests.request") as mock_request:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "resource": {"uri": "https://api.calendly.com/organizations/ABC123XYZ"}
                }
                mock_request.return_value = mock_response

                client = CalendlyAPIClient(calendly_user_with_plan)
                client.get_organization("https://api.calendly.com/organizations/ABC123XYZ")

                # Verify correct endpoint was called
                call_args = mock_request.call_args
                assert "/organizations/ABC123XYZ" in call_args[0][1]
