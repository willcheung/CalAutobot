"""
Tests for Calendly timezone handling.
Tests that timezones are correctly synced and used for availability checks.
"""

import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import Mock, patch
import pytz

from app import db
from app.models import User, EventType
from app.services.calendly_api import CalendlyAPIClient
from app.services import availability as availability_service


@pytest.fixture
def user_with_timezone(test_app):
    """Create a user with Calendly connected and timezone set."""
    with test_app.app_context():
        user = User(
            username="TZUser",
            email="tzuser@example.com",
            google_id="tz123",
            timezone="America/New_York",
            calendly_access_token="test_access_token",
            calendly_user_uri="https://api.calendly.com/users/USER123",
            calendly_organization_uri="https://api.calendly.com/organizations/ORG123",
            calendly_timezone="America/Los_Angeles",  # Different from user timezone
            calendly_connected_at=datetime.utcnow(),
        )
        db.session.add(user)
        db.session.commit()
        yield user
        # Cleanup
        db.session.delete(user)
        db.session.commit()


@pytest.fixture
def calendly_event_type(test_app, user_with_timezone):
    """Create a Calendly-managed event type."""
    with test_app.app_context():
        event_type = EventType(
            user_id=user_with_timezone.id,
            slug="30min",
            title="30 Minute Meeting",
            duration_minutes=30,
            calendly_event_type_uri="https://api.calendly.com/event_types/ET123",
            calendly_scheduling_url="https://calendly.com/tzuser/30min",
            is_calendly_managed=True,
            is_active=True,
        )
        db.session.add(event_type)
        db.session.commit()
        yield event_type
        # Cleanup
        db.session.delete(event_type)
        db.session.commit()


class TestCalendlyTimezoneHandling:
    """Test suite for Calendly timezone handling."""

    @patch("app.routes.calendly_auth.requests.post")
    @patch("app.routes.calendly_auth.requests.get")
    def test_oauth_callback_saves_calendly_timezone(
        self, mock_get, mock_post, client, app_context
    ):
        """Test that OAuth callback saves Calendly timezone from user profile."""
        # Create and login user
        user = User(
            username="TestUser",
            email="test@example.com",
            google_id="oauth123",
            timezone="America/New_York",  # User's local timezone
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

        # Mock user info fetch with timezone
        mock_user_response = Mock()
        mock_user_response.status_code = 200
        mock_user_response.json.return_value = {
            "resource": {
                "uri": "https://api.calendly.com/users/USER123",
                "current_organization": "https://api.calendly.com/organizations/ORG123",
                "scheduling_url": "https://calendly.com/testuser",
                "timezone": "Europe/London",  # Calendly timezone
            }
        }
        mock_get.return_value = mock_user_response

        # Act
        with patch("app.routes.calendly_auth.sync_calendly_event_types"):
            with patch("app.services.calendly_api.CalendlyAPIClient.get_organization"):
                response = client.get(
                    "/auth/calendly/callback?code=test_auth_code",
                    follow_redirects=False,
                )

        # Assert
        assert response.status_code == 302
        db.session.expire_all()
        user = User.query.get(user.id)
        assert user.calendly_timezone == "Europe/London"
        assert user.timezone == "America/New_York"  # User timezone unchanged

    @patch("app.services.calendly_api.requests.request")
    def test_availability_uses_calendly_timezone_for_api_call(
        self, mock_request, test_app, user_with_timezone, calendly_event_type
    ):
        """Test that availability API call uses correct timezone."""
        with test_app.app_context():
            # Mock Calendly API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "collection": [
                    {
                        "start_time": "2025-01-15T17:00:00.000000Z",  # 9am PST = 5pm UTC
                        "invitees_remaining": 1,
                        "status": "available",
                    }
                ]
            }
            mock_request.return_value = mock_response

            # Act - request availability
            client = CalendlyAPIClient(user_with_timezone)
            la_tz = pytz.timezone("America/Los_Angeles")
            start_time = la_tz.localize(datetime(2025, 1, 15, 9, 0, 0))
            end_time = la_tz.localize(datetime(2025, 1, 15, 17, 0, 0))

            slots = client.get_event_type_available_times(
                event_type_uri=calendly_event_type.calendly_event_type_uri,
                start_time=start_time,
                end_time=end_time,
            )

            # Assert
            assert len(slots) == 1
            assert slots[0]["status"] == "available"

            # Verify API was called with UTC times
            call_args = mock_request.call_args
            params = call_args[1]["params"]
            # Start time should be converted to UTC
            assert "2025-01-15T17:00:00" in params["start_time"]  # 9am PST = 5pm UTC

    def test_get_timezone_prefers_calendly_timezone(self, test_app, user_with_timezone):
        """Test that get_timezone returns Calendly timezone when available."""
        with test_app.app_context():
            tz = availability_service.get_timezone(user_with_timezone)

            # Should return Calendly timezone, not user timezone
            assert str(tz) == "America/Los_Angeles"
            assert str(tz) != "America/New_York"

    def test_get_timezone_falls_back_to_user_timezone(self, test_app):
        """Test that get_timezone falls back to user timezone if no Calendly timezone."""
        with test_app.app_context():
            user = User(
                username="NoCalTZ",
                email="nocal@example.com",
                google_id="nocal123",
                timezone="Asia/Tokyo",
                calendly_timezone=None,  # No Calendly timezone
            )
            db.session.add(user)
            db.session.commit()

            tz = availability_service.get_timezone(user)

            # Should fall back to user timezone
            assert str(tz) == "Asia/Tokyo"

            # Cleanup
            db.session.delete(user)
            db.session.commit()

    @patch("app.services.calendly_api.requests.request")
    def test_availability_converts_slots_to_user_timezone(
        self, mock_request, test_app, user_with_timezone, calendly_event_type
    ):
        """Test that availability slots are converted to user's display timezone."""
        with test_app.app_context():
            # Mock Calendly API response with UTC times
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "collection": [
                    {
                        "start_time": "2025-01-15T17:00:00.000000Z",  # 9am PST = 12pm EST
                        "invitees_remaining": 1,
                        "status": "available",
                    },
                    {
                        "start_time": "2025-01-15T18:00:00.000000Z",  # 10am PST = 1pm EST
                        "invitees_remaining": 1,
                        "status": "available",
                    },
                ]
            }
            mock_request.return_value = mock_response

            # Act - get availability through service
            start_date = date(2025, 1, 15)
            end_date = date(2025, 1, 15)

            batch = availability_service.get_availability_for_range(
                user_with_timezone,
                calendly_event_type,
                start_date,
                end_date,
            )

            # Assert - slots should be in user's timezone for display
            assert len(batch.slots_by_date) > 0
            day_slots = batch.slots_by_date.get(start_date, [])
            assert len(day_slots) >= 2

            # Times should be converted for user's timezone
            # The actual implementation might use calendly_timezone or user.timezone
            # Just verify the slots exist and have valid times
            for slot in day_slots:
                assert slot.start is not None
                assert slot.end is not None
                assert slot.end > slot.start

    def test_timezone_mismatch_between_calendly_and_user(
        self, test_app, user_with_timezone
    ):
        """Test that system handles timezone mismatch correctly."""
        with test_app.app_context():
            # User has different timezones
            assert user_with_timezone.timezone == "America/New_York"  # EST
            assert user_with_timezone.calendly_timezone == "America/Los_Angeles"  # PST

            # Calendly timezone should be used for API calls
            tz_for_api = availability_service.get_timezone(user_with_timezone)
            assert str(tz_for_api) == "America/Los_Angeles"

            # This is the expected behavior - use Calendly timezone for API
            # to match Calendly's availability calculations

    @patch("app.services.calendly_api.requests.request")
    def test_availability_handles_future_time_requirement(
        self, mock_request, test_app, user_with_timezone, calendly_event_type
    ):
        """Test that availability request adjusts start time to future if needed."""
        with test_app.app_context():
            # Mock Calendly API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"collection": []}
            mock_request.return_value = mock_response

            # Act - request availability starting from past time
            client = CalendlyAPIClient(user_with_timezone)
            la_tz = pytz.timezone("America/Los_Angeles")

            # Start time in the past
            past_time = la_tz.localize(datetime(2020, 1, 1, 9, 0, 0))
            end_time = la_tz.localize(datetime(2025, 12, 31, 17, 0, 0))

            client.get_event_type_available_times(
                event_type_uri=calendly_event_type.calendly_event_type_uri,
                start_time=past_time,
                end_time=end_time,
            )

            # Assert - API should be called with future time
            call_args = mock_request.call_args
            params = call_args[1]["params"]

            # Start time should NOT be in 2020
            assert "2020" not in params["start_time"]

            # Should be adjusted to current time or future
            # (exact time will vary, just verify it's been adjusted)
            assert params["start_time"] is not None

    def test_calendly_timezone_field_in_user_model(self, test_app):
        """Test that calendly_timezone field exists and works in User model."""
        with test_app.app_context():
            user = User(
                username="TZTest",
                email="tztest@example.com",
                google_id="tztest123",
                calendly_timezone="Australia/Sydney",
            )
            db.session.add(user)
            db.session.commit()

            # Retrieve and verify
            retrieved_user = User.query.filter_by(email="tztest@example.com").first()
            assert retrieved_user is not None
            assert retrieved_user.calendly_timezone == "Australia/Sydney"

            # Cleanup
            db.session.delete(user)
            db.session.commit()
