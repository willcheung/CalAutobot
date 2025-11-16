"""
Tests for Calendly booking creation and error handling.
Tests the create_invitee API, 403 error handling, and Google Calendar fallback.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import pytz

from app import db
from app.models import User, EventType, Event, Contact
from app.services.calendly_api import CalendlyAPIClient, CalendlyAPIError
from app.services import public_booking


@pytest.fixture
def paid_plan_user(test_app):
    """Create a user with Calendly Standard plan (can use Scheduling API)."""
    with test_app.app_context():
        user = User(
            username="PaidUser",
            email="paid@example.com",
            google_id="paid123",
            timezone="America/New_York",
            calendly_access_token="test_access_token",
            calendly_user_uri="https://api.calendly.com/users/USER123",
            calendly_organization_uri="https://api.calendly.com/organizations/ORG123",
            calendly_plan="standard",  # Paid plan
            calendly_connected_at=datetime.utcnow(),
            google_credentials_json='{"token": "test"}',
        )
        db.session.add(user)
        db.session.commit()
        yield user
        # Cleanup
        db.session.delete(user)
        db.session.commit()


@pytest.fixture
def free_plan_user(test_app):
    """Create a user with Calendly Free plan (cannot use Scheduling API)."""
    with test_app.app_context():
        user = User(
            username="FreeUser",
            email="free@example.com",
            google_id="free123",
            timezone="America/New_York",
            calendly_access_token="test_access_token",
            calendly_user_uri="https://api.calendly.com/users/USER456",
            calendly_organization_uri="https://api.calendly.com/organizations/ORG456",
            calendly_plan="free",  # Free plan
            calendly_connected_at=datetime.utcnow(),
            google_credentials_json='{"token": "test"}',
        )
        db.session.add(user)
        db.session.commit()
        yield user
        # Cleanup
        db.session.delete(user)
        db.session.commit()


@pytest.fixture
def calendly_event_type_paid(test_app, paid_plan_user):
    """Create a Calendly-managed event type for paid user."""
    with test_app.app_context():
        event_type = EventType(
            user_id=paid_plan_user.id,
            slug="30min",
            title="30 Minute Meeting",
            duration_minutes=30,
            calendly_event_type_uri="https://api.calendly.com/event_types/ET123",
            calendly_scheduling_url="https://calendly.com/paid/30min",
            is_calendly_managed=True,
            is_active=True,
        )
        db.session.add(event_type)
        db.session.commit()
        yield event_type
        # Cleanup
        db.session.delete(event_type)
        db.session.commit()


@pytest.fixture
def calendly_event_type_free(test_app, free_plan_user):
    """Create a Calendly-managed event type for free user."""
    with test_app.app_context():
        event_type = EventType(
            user_id=free_plan_user.id,
            slug="15min",
            title="15 Minute Chat",
            duration_minutes=15,
            calendly_event_type_uri="https://api.calendly.com/event_types/ET456",
            calendly_scheduling_url="https://calendly.com/free/15min",
            is_calendly_managed=True,
            is_active=True,
        )
        db.session.add(event_type)
        db.session.commit()
        yield event_type
        # Cleanup
        db.session.delete(event_type)
        db.session.commit()


class TestCalendlyBookingCreation:
    """Test suite for Calendly booking creation."""

    @patch("app.services.calendly_api.requests.request")
    def test_create_invitee_success(
        self, mock_request, test_app, paid_plan_user, calendly_event_type_paid
    ):
        """Test successful booking creation via Calendly Scheduling API."""
        with test_app.app_context():
            # Mock successful API response
            ny_tz = pytz.timezone("America/New_York")
            start_time = ny_tz.localize(datetime(2025, 2, 15, 10, 0, 0))
            end_time = start_time + timedelta(minutes=30)

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "resource": {
                    "uri": "https://api.calendly.com/scheduled_events/EVENT123",
                    "name": "30 Minute Meeting",
                    "status": "active",
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "event_type": calendly_event_type_paid.calendly_event_type_uri,
                    "location": {
                        "type": "zoom",
                        "join_url": "https://zoom.us/j/123456",
                    },
                    "invitees": [
                        {
                            "uri": "https://api.calendly.com/scheduled_events/EVENT123/invitees/INV123",
                            "email": "guest@example.com",
                            "name": "Guest User",
                        }
                    ],
                }
            }
            mock_request.return_value = mock_response

            # Act
            client = CalendlyAPIClient(paid_plan_user)
            result = client.create_invitee(
                event_type_uri=calendly_event_type_paid.calendly_event_type_uri,
                start_time=start_time,
                email="guest@example.com",
                name="Guest User",
                timezone="America/New_York",
            )

            # Assert
            assert result["uri"] == "https://api.calendly.com/scheduled_events/EVENT123"
            assert result["status"] == "active"
            assert result["location"]["type"] == "zoom"
            assert len(result["invitees"]) == 1

            # Verify API call
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert "/invitees" in call_args[0][1]

            # Verify payload
            payload = call_args[1]["json"]
            assert payload["event_type"] == calendly_event_type_paid.calendly_event_type_uri
            assert payload["invitee"]["email"] == "guest@example.com"
            assert payload["invitee"]["name"] == "Guest User"

    @patch("app.services.calendly_api.requests.request")
    def test_create_invitee_with_guests(
        self, mock_request, test_app, paid_plan_user, calendly_event_type_paid
    ):
        """Test booking creation with additional guests."""
        with test_app.app_context():
            ny_tz = pytz.timezone("America/New_York")
            start_time = ny_tz.localize(datetime(2025, 2, 15, 10, 0, 0))

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"resource": {}}
            mock_request.return_value = mock_response

            # Act
            client = CalendlyAPIClient(paid_plan_user)
            client.create_invitee(
                event_type_uri=calendly_event_type_paid.calendly_event_type_uri,
                start_time=start_time,
                email="primary@example.com",
                name="Primary Guest",
                timezone="America/New_York",
                guests=["guest1@example.com", "guest2@example.com"],
            )

            # Assert - verify guests are in payload
            call_args = mock_request.call_args
            payload = call_args[1]["json"]
            assert "guests" in payload["invitee"]
            assert len(payload["invitee"]["guests"]) == 2
            assert "guest1@example.com" in payload["invitee"]["guests"]

    @patch("app.services.calendly_api.requests.request")
    def test_create_invitee_with_questions(
        self, mock_request, test_app, paid_plan_user, calendly_event_type_paid
    ):
        """Test booking creation with custom questions and answers."""
        with test_app.app_context():
            ny_tz = pytz.timezone("America/New_York")
            start_time = ny_tz.localize(datetime(2025, 2, 15, 10, 0, 0))

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"resource": {}}
            mock_request.return_value = mock_response

            # Act
            client = CalendlyAPIClient(paid_plan_user)
            client.create_invitee(
                event_type_uri=calendly_event_type_paid.calendly_event_type_uri,
                start_time=start_time,
                email="guest@example.com",
                name="Guest User",
                timezone="America/New_York",
                questions_and_answers=[
                    {"question": "What would you like to discuss?", "answer": "Project planning"},
                    {"question": "Company name", "answer": "Acme Corp"},
                ],
            )

            # Assert - verify questions are in payload
            call_args = mock_request.call_args
            payload = call_args[1]["json"]
            assert "questions_and_answers" in payload["invitee"]
            assert len(payload["invitee"]["questions_and_answers"]) == 2

    @patch("app.services.calendly_api.requests.request")
    def test_create_invitee_403_forbidden_free_plan(
        self, mock_request, test_app, free_plan_user, calendly_event_type_free
    ):
        """Test that 403 Forbidden error is raised for free plan users."""
        with test_app.app_context():
            # Mock 403 Forbidden response
            ny_tz = pytz.timezone("America/New_York")
            start_time = ny_tz.localize(datetime(2025, 2, 15, 10, 0, 0))

            mock_response = Mock()
            mock_response.status_code = 403
            mock_response.json.return_value = {
                "message": "This feature requires a Standard plan or above"
            }
            mock_response.raise_for_status.side_effect = Exception("403 Forbidden")
            mock_request.return_value = mock_response

            # Act & Assert
            client = CalendlyAPIClient(free_plan_user)
            with pytest.raises(CalendlyAPIError) as exc_info:
                client.create_invitee(
                    event_type_uri=calendly_event_type_free.calendly_event_type_uri,
                    start_time=start_time,
                    email="guest@example.com",
                    name="Guest User",
                    timezone="America/New_York",
                )

            # Verify error message mentions the issue
            assert "403" in str(exc_info.value) or "Forbidden" in str(exc_info.value)

    @patch("app.services.calendly_api.CalendlyAPIClient.create_invitee")
    @patch("app.services.public_booking.create_google_calendar_event")
    def test_booking_fallback_to_google_calendar_on_403(
        self, mock_gcal, mock_create_invitee, test_app, free_plan_user, calendly_event_type_free
    ):
        """Test that booking falls back to Google Calendar when Calendly returns 403."""
        with test_app.app_context():
            # Mock Calendly API to return 403
            mock_create_invitee.side_effect = CalendlyAPIError("403 Forbidden", 403)

            # Mock Google Calendar success
            mock_gcal.return_value = {
                "id": "gcal_event_123",
                "htmlLink": "https://calendar.google.com/event/123",
            }

            # Create contact
            contact = Contact(
                user_id=free_plan_user.id,
                email="guest@example.com",
                name="Guest User",
            )
            db.session.add(contact)
            db.session.commit()

            # Act
            ny_tz = pytz.timezone("America/New_York")
            start_time = ny_tz.localize(datetime(2025, 2, 15, 10, 0, 0))

            event = public_booking.create_booking_event(
                user=free_plan_user,
                event_type=calendly_event_type_free,
                start_datetime=start_time,
                invitee_email="guest@example.com",
                invitee_name="Guest User",
            )

            # Assert - event should be created via Google Calendar
            assert event is not None
            assert event.calendly_event_uri is None  # Not created via Calendly
            assert event.google_event_id == "gcal_event_123"

            # Verify Google Calendar was called
            mock_gcal.assert_called_once()

            # Cleanup
            db.session.delete(contact)
            db.session.delete(event)
            db.session.commit()

    @patch("app.services.calendly_api.CalendlyAPIClient.create_invitee")
    @patch("app.services.public_booking.create_google_calendar_event")
    def test_booking_fallback_to_google_calendar_on_network_error(
        self, mock_gcal, mock_create_invitee, test_app, paid_plan_user, calendly_event_type_paid
    ):
        """Test that booking falls back to Google Calendar on network errors."""
        with test_app.app_context():
            # Mock Calendly API to fail with network error
            mock_create_invitee.side_effect = CalendlyAPIError("Network timeout")

            # Mock Google Calendar success
            mock_gcal.return_value = {
                "id": "gcal_event_456",
                "htmlLink": "https://calendar.google.com/event/456",
            }

            # Create contact
            contact = Contact(
                user_id=paid_plan_user.id,
                email="guest@example.com",
                name="Guest User",
            )
            db.session.add(contact)
            db.session.commit()

            # Act
            ny_tz = pytz.timezone("America/New_York")
            start_time = ny_tz.localize(datetime(2025, 2, 15, 10, 0, 0))

            event = public_booking.create_booking_event(
                user=paid_plan_user,
                event_type=calendly_event_type_paid,
                start_datetime=start_time,
                invitee_email="guest@example.com",
                invitee_name="Guest User",
            )

            # Assert - should fall back to Google Calendar
            assert event is not None
            assert event.google_event_id == "gcal_event_456"
            mock_gcal.assert_called_once()

            # Cleanup
            db.session.delete(contact)
            db.session.delete(event)
            db.session.commit()

    @patch("app.services.calendly_api.requests.request")
    def test_create_invitee_formats_start_time_correctly(
        self, mock_request, test_app, paid_plan_user, calendly_event_type_paid
    ):
        """Test that start_time is formatted correctly as ISO 8601."""
        with test_app.app_context():
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"resource": {}}
            mock_request.return_value = mock_response

            # Act
            ny_tz = pytz.timezone("America/New_York")
            start_time = ny_tz.localize(datetime(2025, 2, 15, 14, 30, 0))

            client = CalendlyAPIClient(paid_plan_user)
            client.create_invitee(
                event_type_uri=calendly_event_type_paid.calendly_event_type_uri,
                start_time=start_time,
                email="guest@example.com",
                name="Guest User",
                timezone="America/New_York",
            )

            # Assert - verify ISO format with timezone
            call_args = mock_request.call_args
            payload = call_args[1]["json"]
            assert "start_time" in payload
            # Should be ISO 8601 format
            assert "2025-02-15" in payload["start_time"]
            assert "T" in payload["start_time"]

    @patch("app.services.calendly_api.CalendlyAPIClient.create_invitee")
    def test_booking_saves_calendly_event_uri_on_success(
        self, mock_create_invitee, test_app, paid_plan_user, calendly_event_type_paid
    ):
        """Test that successful Calendly booking saves event URI to database."""
        with test_app.app_context():
            # Mock successful Calendly creation
            ny_tz = pytz.timezone("America/New_York")
            start_time = ny_tz.localize(datetime(2025, 2, 15, 10, 0, 0))

            mock_create_invitee.return_value = {
                "uri": "https://api.calendly.com/scheduled_events/EVENT789",
                "name": "30 Minute Meeting",
                "status": "active",
                "start_time": start_time.isoformat(),
                "end_time": (start_time + timedelta(minutes=30)).isoformat(),
            }

            # Create contact
            contact = Contact(
                user_id=paid_plan_user.id,
                email="guest@example.com",
                name="Guest User",
            )
            db.session.add(contact)
            db.session.commit()

            # Act
            event = public_booking.create_booking_event(
                user=paid_plan_user,
                event_type=calendly_event_type_paid,
                start_datetime=start_time,
                invitee_email="guest@example.com",
                invitee_name="Guest User",
            )

            # Assert
            assert event is not None
            assert event.calendly_event_uri == "https://api.calendly.com/scheduled_events/EVENT789"

            # Cleanup
            db.session.delete(contact)
            db.session.delete(event)
            db.session.commit()

    def test_calendly_event_uri_field_in_event_model(self, test_app):
        """Test that calendly_event_uri field exists in Event model."""
        with test_app.app_context():
            user = User(
                username="EventTest",
                email="event@example.com",
                google_id="event123",
            )
            db.session.add(user)
            db.session.commit()

            event = Event(
                user_id=user.id,
                event_name="Test Event",
                start_date=datetime.utcnow().date(),
                start_time=datetime.utcnow().time(),
                end_date=(datetime.utcnow() + timedelta(hours=1)).date(),
                end_time=(datetime.utcnow() + timedelta(hours=1)).time(),
                calendly_event_uri="https://api.calendly.com/scheduled_events/TEST123",
            )
            db.session.add(event)
            db.session.commit()

            # Retrieve and verify
            retrieved_event = Event.query.filter_by(
                calendly_event_uri="https://api.calendly.com/scheduled_events/TEST123"
            ).first()
            assert retrieved_event is not None
            assert retrieved_event.calendly_event_uri == "https://api.calendly.com/scheduled_events/TEST123"

            # Cleanup
            db.session.delete(event)
            db.session.delete(user)
            db.session.commit()
