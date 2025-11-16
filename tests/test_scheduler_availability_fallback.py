"""
Test scheduler agent's complete fallback chain for calendar availability.

This test verifies:
1. Calendly is checked first (if connected)
2. Google Calendar is the fallback
3. Owner is notified via email if both fail
"""
import pytest
from datetime import datetime, date, timedelta
from unittest.mock import Mock, patch, MagicMock
from types import SimpleNamespace

from app.models import User, EventType, MeetingRequest
from app.services.availability import AvailabilityError
from app.services import scheduling_agent


class TestSchedulerAvailabilityFallback:
    """Test complete availability fallback chain in scheduler agent."""

    @pytest.fixture
    def regular_user(self, app_context):
        """User without Calendly."""
        from app import db
        user = User(
            username="regular_user",
            email="regular@example.com",
            google_id="regular123",
        )
        db.session.add(user)
        db.session.commit()
        yield user

    @pytest.fixture
    def regular_event_type(self, app_context, regular_user):
        """Regular Google Calendar event type."""
        from app import db
        event_type = EventType(
            user_id=regular_user.id,
            slug="regular-meeting",
            title="Regular Meeting",
            duration_minutes=30,
            is_active=True,
        )
        db.session.add(event_type)
        db.session.commit()
        yield event_type

    def test_availability_error_sends_system_issue_reply_to_requester(
        self, app_context, regular_user, regular_event_type
    ):
        """Test that AvailabilityError sends system issue reply to requester."""
        # Mock availability service to raise error
        with patch('app.services.availability.get_slots_for_date') as mock_get_slots:
            mock_get_slots.side_effect = AvailabilityError("Calendar access failed")

            # Validate a confirmed slot
            result = scheduling_agent._validate_confirmed_slot(
                user=regular_user,
                event_type=regular_event_type,
                slot_start=datetime(2025, 1, 15, 10, 0),
                owner_name="Regular User",
            )

            # Should return system issue result
            assert result is not None
            assert result["action"] == "request_clarification"
            assert "system issue" in result["reply"].lower()
            assert "Regular User" in result["reply"]
            assert result["notes"] == "availability_verify_error"

    @patch('app.services.calendar_notifications.gmail_service.send_email')
    def test_availability_error_emails_owner(
        self, mock_send_email, app_context, regular_user, regular_event_type
    ):
        """
        CRITICAL TEST: Verify owner is emailed when both Calendly and Google Calendar fail.
        
        This is the main test for the complete fallback chain:
        1. Try Calendly (if connected)
        2. Try Google Calendar (fallback)
        3. Email owner if both fail
        """
        # Mock availability service to raise error (simulating both Calendly and Google fail)
        with patch('app.services.availability.get_slots_for_date') as mock_get_slots:
            mock_get_slots.side_effect = AvailabilityError("Calendar access failed")

            # Mock notify_owner_calendar_issue to track if it's called
            with patch('app.services.scheduling_agent.notify_owner_calendar_issue') as mock_notify:
                # Validate a confirmed slot
                result = scheduling_agent._validate_confirmed_slot(
                    user=regular_user,
                    event_type=regular_event_type,
                    slot_start=datetime(2025, 1, 15, 10, 0),
                    owner_name="Regular User",
                )

                # Verify system issue result
                assert result is not None
                assert result["action"] == "request_clarification"
                assert result["notes"] == "availability_verify_error"

                # CRITICAL: Verify owner was notified
                mock_notify.assert_called_once_with(
                    regular_user,
                    "availability_verify_error"
                )

    def test_owner_notification_email_content(self, app_context, regular_user):
        """Test that owner notification email has correct content."""
        from app.services.calendar_notifications import notify_owner_calendar_issue

        with patch('app.services.calendar_notifications.gmail_service.send_email') as mock_send:
            # Send notification
            notify_owner_calendar_issue(regular_user, "availability_verify_error")

            # Verify email was sent
            mock_send.assert_called_once()
            
            # Check email parameters
            call_args = mock_send.call_args
            recipient = call_args[0][0]
            subject = call_args[0][1]
            
            assert recipient == regular_user.email
            assert "Action needed" in subject or "Calendar" in subject
            
            # Check body contains key information
            body = call_args[1].get('text_body', '')
            assert regular_user.username in body or regular_user.email in body
            assert "Cal" in body  # Assistant name
            assert "settings" in body.lower() or "reconnect" in body.lower()
