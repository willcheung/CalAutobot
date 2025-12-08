"""
Tests for email tracking service layer.

Tests the following core features:
- Creating tracking requests with contact linkage
- Recording tracking events with geolocation
- User agent parsing
- Contact engagement metric updates
- Privacy features (IP hashing)
"""

from datetime import datetime
import pytest
from unittest.mock import patch, MagicMock

from app import db
from app.models import User, Contact, TrackingRequest, TrackingRecipient, TrackingEvent
from app.services import tracking_service


@pytest.fixture
def service_user(test_app):
    """Create a test user for service tests."""
    with test_app.app_context():
        user = User(
            username="ServiceUser",
            email="service@example.com",
            handle="serviceuser",
            timezone="America/Chicago"
        )
        db.session.add(user)
        db.session.commit()
        return user


# ===== CREATE TRACKING REQUEST TESTS =====

def test_create_tracking_request_basic(test_app, service_user):
    """Test creating a basic tracking request."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='service_test_123',
            subject='Test Subject',
            recipients=[
                {'email': 'test1@example.com', 'name': 'Test One'},
                {'email': 'test2@example.com', 'name': 'Test Two'}
            ]
        )

        assert tr is not None
        assert tr.tracking_id == 'service_test_123'
        assert tr.subject == 'Test Subject'
        assert tr.user_id == user.id
        assert tr.recipients.count() == 2

        # Verify contacts were created
        contact1 = Contact.query.filter_by(email='test1@example.com').first()
        assert contact1 is not None
        assert contact1.display_name == 'Test One'
        assert contact1.emails_received == 1

        contact2 = Contact.query.filter_by(email='test2@example.com').first()
        assert contact2 is not None
        assert contact2.emails_received == 1


def test_create_tracking_request_with_cc_bcc(test_app, service_user):
    """Test creating tracking request with CC and BCC recipients."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='cc_bcc_test_456',
            subject='Test Email',
            recipients=[{'email': 'to@example.com', 'name': 'To Person'}],
            cc_recipients=[{'email': 'cc@example.com', 'name': 'CC Person'}],
            bcc_recipients=[{'email': 'bcc@example.com', 'name': 'BCC Person'}]
        )

        assert tr.recipients.count() == 3

        # Verify recipient types
        recipients = list(tr.recipients.all())
        types = [r.recipient_type for r in recipients]
        assert 'to' in types
        assert 'cc' in types
        assert 'bcc' in types


def test_create_tracking_request_with_gmail_context(test_app, service_user):
    """Test creating tracking request with Gmail metadata."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='gmail_context_789',
            subject='Gmail Email',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}],
            gmail_message_id='<message123@mail.gmail.com>',
            gmail_thread_id='thread_abc_xyz'
        )

        assert tr.gmail_message_id == '<message123@mail.gmail.com>'
        assert tr.gmail_thread_id == 'thread_abc_xyz'


def test_create_tracking_request_updates_existing_contact(test_app, service_user):
    """Test that creating tracking request updates existing contact metrics."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        # Create existing contact
        existing_contact = Contact(
            user_id=user.id,
            email='existing@example.com',
            display_name='Existing Contact',
            emails_received=5
        )
        db.session.add(existing_contact)
        db.session.commit()

        # Create tracking request for existing contact
        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='existing_contact_test',
            subject='Follow-up',
            recipients=[{'email': 'existing@example.com', 'name': 'Updated Name'}]
        )

        # Verify contact metrics updated
        contact = Contact.query.filter_by(email='existing@example.com').first()
        assert contact.emails_received == 6  # Should increment
        assert contact.last_outgoing_email_at is not None


# ===== RECORD TRACKING EVENT TESTS =====

def test_record_tracking_event_basic(test_app, service_user):
    """Test recording a basic tracking event."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        # Create tracking request
        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='event_basic_test',
            subject='Test',
            recipients=[{'email': 'recipient@example.com', 'name': 'Recipient'}]
        )

        # Mock geolocation API
        with patch('app.services.tracking_service.get_location_from_ip') as mock_geo:
            mock_geo.return_value = {
                'country_code': 'US',
                'city': 'New York',
                'timezone': 'America/New_York'
            }

            # Record event
            event = tracking_service.record_tracking_event(
                tracking_id='event_basic_test',
                ip_address='8.8.8.8',
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            )

            assert event is not None
            assert event.tracking_request_id == tr.id
            assert event.ip_hash is not None  # Should be hashed
            assert event.user_agent_parsed is not None
            assert event.country_code == 'US'
            assert event.city == 'New York'
            assert event.timezone == 'America/New_York'
            assert event.is_first_open is True


def test_record_tracking_event_updates_stats(test_app, service_user):
    """Test that recording event updates tracking request stats."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='stats_test_123',
            subject='Stats Test',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )

        # Record first event
        with patch('app.services.tracking_service.get_location_from_ip', return_value={}):
            tracking_service.record_tracking_event(
                tracking_id='stats_test_123',
                ip_address='8.8.8.8',
                user_agent='Test Agent'
            )

        # Check stats
        tr = TrackingRequest.query.filter_by(tracking_id='stats_test_123').first()
        assert tr.open_count == 1
        assert tr.unique_open_count == 1
        assert tr.first_opened_at is not None
        assert tr.last_opened_at is not None


def test_record_tracking_event_multiple_opens(test_app, service_user):
    """Test recording multiple opens tracks unique IPs correctly."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='multiple_opens_test',
            subject='Multiple Opens',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )

        with patch('app.services.tracking_service.get_location_from_ip', return_value={}):
            # Open from IP 1 twice
            tracking_service.record_tracking_event('multiple_opens_test', '1.1.1.1', 'Agent')
            tracking_service.record_tracking_event('multiple_opens_test', '1.1.1.1', 'Agent')

            # Open from IP 2 once
            tracking_service.record_tracking_event('multiple_opens_test', '2.2.2.2', 'Agent')

        tr = TrackingRequest.query.filter_by(tracking_id='multiple_opens_test').first()
        assert tr.open_count == 3
        assert tr.unique_open_count == 2  # Only 2 unique IPs


def test_record_tracking_event_updates_contact_engagement(test_app, service_user):
    """Test that recording event updates contact engagement metrics."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='contact_engagement_test',
            subject='Engagement Test',
            recipients=[{'email': 'engaged@example.com', 'name': 'Engaged User'}]
        )

        with patch('app.services.tracking_service.get_location_from_ip', return_value={}):
            tracking_service.record_tracking_event(
                tracking_id='contact_engagement_test',
                ip_address='8.8.8.8',
                user_agent='Test'
            )

        # Check contact metrics
        contact = Contact.query.filter_by(email='engaged@example.com').first()
        assert contact.emails_opened == 1
        assert contact.last_email_opened_at is not None

        # Check recipient metrics
        recipient = TrackingRecipient.query.filter_by(contact_id=contact.id).first()
        assert recipient.has_opened is True
        assert recipient.first_opened_at is not None
        assert recipient.open_count == 1


def test_record_tracking_event_nonexistent_tracking_id(test_app):
    """Test that recording event for nonexistent tracking ID returns None."""
    with test_app.app_context():
        event = tracking_service.record_tracking_event(
            tracking_id='nonexistent_id',
            ip_address='8.8.8.8',
            user_agent='Test'
        )

        assert event is None


def test_record_tracking_event_inactive_request(test_app, service_user):
    """Test that recording event for inactive tracking request returns None."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='inactive_test',
            subject='Inactive',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )

        # Deactivate tracking
        tr.is_active = False
        db.session.commit()

        # Try to record event
        event = tracking_service.record_tracking_event(
            tracking_id='inactive_test',
            ip_address='8.8.8.8',
            user_agent='Test'
        )

        assert event is None


# ===== USER AGENT PARSING TESTS =====

def test_parse_user_agent_chrome(test_app):
    """Test parsing Chrome user agent."""
    with test_app.app_context():
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        parsed = tracking_service.parse_user_agent(ua)

        assert 'Chrome' in parsed['browser']
        assert 'Windows' in parsed['os']
        assert parsed['device'] == 'Desktop'


def test_parse_user_agent_safari(test_app):
    """Test parsing Safari user agent."""
    with test_app.app_context():
        ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15'
        parsed = tracking_service.parse_user_agent(ua)

        assert 'Safari' in parsed['browser']
        assert 'Mac OS X' in parsed['os']
        assert parsed['device'] == 'Desktop'


def test_parse_user_agent_firefox(test_app):
    """Test parsing Firefox user agent."""
    with test_app.app_context():
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0'
        parsed = tracking_service.parse_user_agent(ua)

        assert 'Firefox' in parsed['browser']
        assert 'Windows' in parsed['os']


def test_parse_user_agent_mobile(test_app):
    """Test parsing mobile user agent."""
    with test_app.app_context():
        ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'
        parsed = tracking_service.parse_user_agent(ua)

        assert parsed['os'] == 'iOS'
        assert parsed['device'] == 'Mobile'


def test_parse_user_agent_android(test_app):
    """Test parsing Android user agent."""
    with test_app.app_context():
        ua = 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
        parsed = tracking_service.parse_user_agent(ua)

        assert 'Android' in parsed['os']
        assert parsed['device'] == 'Mobile'


def test_parse_user_agent_tablet(test_app):
    """Test parsing tablet user agent."""
    with test_app.app_context():
        ua = 'Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15'
        parsed = tracking_service.parse_user_agent(ua)

        assert parsed['os'] == 'iPad'
        assert parsed['device'] == 'Tablet'


# ===== GEOLOCATION TESTS =====

def test_get_location_from_ip_success(test_app):
    """Test successful geolocation lookup."""
    with test_app.app_context():
        with patch('app.services.tracking_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                'status': 'success',
                'countryCode': 'US',
                'city': 'Mountain View',
                'timezone': 'America/Los_Angeles'
            }
            mock_get.return_value = mock_response

            location = tracking_service.get_location_from_ip('8.8.8.8')

            assert location['country_code'] == 'US'
            assert location['city'] == 'Mountain View'
            assert location['timezone'] == 'America/Los_Angeles'


def test_get_location_from_ip_failure(test_app):
    """Test geolocation lookup failure returns None values."""
    with test_app.app_context():
        with patch('app.services.tracking_service.requests.get') as mock_get:
            mock_get.side_effect = Exception('API Error')

            location = tracking_service.get_location_from_ip('invalid')

            assert location['country_code'] is None
            assert location['city'] is None
            assert location['timezone'] is None


def test_get_location_from_ip_unsuccessful_response(test_app):
    """Test geolocation with unsuccessful API response."""
    with test_app.app_context():
        with patch('app.services.tracking_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {'status': 'fail'}
            mock_get.return_value = mock_response

            location = tracking_service.get_location_from_ip('127.0.0.1')

            assert location['country_code'] is None
            assert location['city'] is None
            assert location['timezone'] is None


# ===== PRIVACY TESTS =====

def test_ip_address_is_hashed(test_app, service_user):
    """Test that IP addresses are hashed for privacy."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='privacy_test_ip',
            subject='Privacy Test',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )

        with patch('app.services.tracking_service.get_location_from_ip', return_value={}):
            event = tracking_service.record_tracking_event(
                tracking_id='privacy_test_ip',
                ip_address='192.168.1.1',
                user_agent='Test'
            )

        # IP should be hashed, not stored raw
        assert event.ip_hash is not None
        assert event.ip_hash != '192.168.1.1'
        assert len(event.ip_hash) == 64  # SHA256 hex length

        # Verify it's a valid SHA256 hash
        import hashlib
        expected_hash = hashlib.sha256('192.168.1.1'.encode()).hexdigest()
        assert event.ip_hash == expected_hash


# ===== CONTACT ENGAGEMENT CALCULATION TESTS =====

def test_contact_open_rate_calculation(test_app, service_user):
    """Test that contact open rate is calculated correctly."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        contact = Contact(
            user_id=user.id,
            email='openrate@example.com',
            display_name='Open Rate Test',
            emails_received=10,
            emails_opened=3
        )
        db.session.add(contact)
        db.session.commit()

        # Check open rate property
        assert contact.email_open_rate == 0.3


def test_contact_open_rate_zero_emails(test_app, service_user):
    """Test that open rate is 0 when no emails received."""
    with test_app.app_context():
        user = User.query.filter_by(email='service@example.com').first()

        contact = Contact(
            user_id=user.id,
            email='zeroemails@example.com',
            display_name='Zero Emails',
            emails_received=0,
            emails_opened=0
        )
        db.session.add(contact)
        db.session.commit()

        assert contact.email_open_rate == 0.0
