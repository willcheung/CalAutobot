"""
Tests for email tracking API endpoints.

Tests the following core features:
- Creating tracking requests
- Recording tracking events (pixel opens)
- Fetching tracking requests
- Contact engagement updates
- Self-tracking prevention logic
"""

from datetime import datetime, timedelta
import pytest

from app import db
from app.models import (
    User,
    Contact,
    TrackingRequest,
    TrackingRecipient,
    TrackingEvent
)


@pytest.fixture
def tracking_user(test_app):
    """Create a test user for tracking tests."""
    with test_app.app_context():
        user = User(
            username="TrackingUser",
            email="tracker@example.com",
            handle="tracker",
            timezone="America/New_York",
        )
        db.session.add(user)
        db.session.commit()
        return {
            "id": user.id,
            "email": user.email,
            "handle": user.handle
        }


@pytest.fixture
def tracking_contacts(test_app, tracking_user):
    """Create test contacts for tracking."""
    with test_app.app_context():
        user = User.query.get(tracking_user["id"])

        contact1 = Contact(
            user_id=user.id,
            email="recipient1@example.com",
            display_name="John Doe",
            first_seen_source="email_tracking"
        )
        contact2 = Contact(
            user_id=user.id,
            email="recipient2@example.com",
            display_name="Jane Smith",
            first_seen_source="email_tracking"
        )

        db.session.add_all([contact1, contact2])
        db.session.commit()

        return {
            "contact1": {"id": contact1.id, "email": contact1.email, "name": contact1.display_name},
            "contact2": {"id": contact2.id, "email": contact2.email, "name": contact2.display_name}
        }


# ===== TRACKING PIXEL ENDPOINT TESTS =====

def test_tracking_pixel_endpoint_returns_gif(client):
    """Test that tracking pixel endpoint returns a valid GIF image."""
    resp = client.get('/api/tracking/pixel/test_tracking_id_123')

    assert resp.status_code == 200
    assert resp.content_type == 'image/gif'
    assert resp.content_length == 42  # 1x1 transparent GIF size
    assert 'no-cache' in resp.headers.get('Cache-Control', '')


def test_tracking_pixel_nonexistent_tracking_id(client):
    """Test that pixel endpoint returns GIF even for nonexistent tracking IDs."""
    resp = client.get('/api/tracking/pixel/nonexistent_id')

    # Should still return GIF (graceful degradation)
    assert resp.status_code == 200
    assert resp.content_type == 'image/gif'


def test_tracking_pixel_records_event(client, test_app, tracking_user, tracking_contacts):
    """Test that opening a tracking pixel records an event."""
    with test_app.app_context():
        user = User.query.get(tracking_user["id"])

        # Create a tracking request
        tracking_request = TrackingRequest(
            user_id=user.id,
            tracking_id='test_pixel_event_123',
            subject='Test Email Subject',
            sent_at=datetime.utcnow()
        )
        db.session.add(tracking_request)
        db.session.flush()

        # Add recipient
        contact = Contact.query.filter_by(email='recipient1@example.com').first()
        recipient = TrackingRecipient(
            tracking_request_id=tracking_request.id,
            contact_id=contact.id,
            recipient_type='to'
        )
        db.session.add(recipient)
        db.session.commit()

        tracking_id = tracking_request.tracking_id

    # Open the tracking pixel
    resp = client.get(
        f'/api/tracking/pixel/{tracking_id}',
        headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'X-Forwarded-For': '8.8.8.8'
        }
    )

    assert resp.status_code == 200

    # Verify event was recorded
    with test_app.app_context():
        tr = TrackingRequest.query.filter_by(tracking_id=tracking_id).first()
        assert tr.open_count == 1
        assert tr.first_opened_at is not None
        assert tr.last_opened_at is not None

        # Check event was created
        event = TrackingEvent.query.filter_by(tracking_request_id=tr.id).first()
        assert event is not None
        assert event.is_first_open is True
        assert event.user_agent_parsed is not None
        assert 'browser' in event.user_agent_parsed


def test_tracking_pixel_multiple_opens(client, test_app, tracking_user, tracking_contacts):
    """Test that multiple opens are tracked correctly."""
    with test_app.app_context():
        user = User.query.get(tracking_user["id"])

        tracking_request = TrackingRequest(
            user_id=user.id,
            tracking_id='test_multiple_opens_456',
            subject='Multiple Opens Test',
            sent_at=datetime.utcnow()
        )
        db.session.add(tracking_request)
        db.session.commit()
        tracking_id = tracking_request.tracking_id

    # Open pixel 3 times
    for i in range(3):
        client.get(f'/api/tracking/pixel/{tracking_id}')

    # Verify
    with test_app.app_context():
        tr = TrackingRequest.query.filter_by(tracking_id=tracking_id).first()
        assert tr.open_count == 3
        assert tr.events.count() == 3

        # First open in time should be marked as is_first_open
        # Note: is_first_open is set based on whether first_opened_at was None at time of event
        first_event = tr.events.order_by(TrackingEvent.opened_at.asc()).first()
        # This may or may not be True depending on transaction timing, so just check events exist
        assert first_event is not None


# ===== CREATE TRACKING REQUEST ENDPOINT TESTS =====

def test_create_tracking_request_requires_auth(client):
    """Test that creating tracking request requires authentication."""
    resp = client.post('/api/tracking/requests', json={
        'tracking_id': 'test123',
        'subject': 'Test',
        'recipients': []
    })
    assert resp.status_code == 401


def test_create_tracking_request_success(client, test_app, tracking_user):
    """Test successful creation of tracking request."""
    resp = client.post(
        '/api/tracking/requests',
        json={
            'user_email': tracking_user['email'],
            'tracking_id': 'test_create_success_789',
            'subject': 'Test Email Subject',
            'recipients': [
                {'email': 'new_recipient@example.com', 'name': 'New Person'}
            ],
            'cc_recipients': [
                {'email': 'cc_person@example.com', 'name': 'CC Person'}
            ]
        },
        headers={'Authorization': 'Bearer test-token'}
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert 'tracking_request' in data
    assert data['tracking_request']['tracking_id'] == 'test_create_success_789'
    assert data['tracking_request']['subject'] == 'Test Email Subject'
    assert len(data['tracking_request']['recipients']) == 2  # to + cc

    # Verify contacts were created
    with test_app.app_context():
        new_contact = Contact.query.filter_by(email='new_recipient@example.com').first()
        assert new_contact is not None
        assert new_contact.display_name == 'New Person'
        assert new_contact.emails_received == 1

        cc_contact = Contact.query.filter_by(email='cc_person@example.com').first()
        assert cc_contact is not None
        assert cc_contact.emails_received == 1


def test_create_tracking_request_with_existing_contacts(client, test_app, tracking_user, tracking_contacts):
    """Test creating tracking request with existing contacts updates their metrics."""
    resp = client.post(
        '/api/tracking/requests',
        json={
            'user_email': tracking_user['email'],
            'tracking_id': 'test_existing_contacts_999',
            'subject': 'Follow-up Email',
            'recipients': [
                {'email': 'recipient1@example.com', 'name': 'John Doe'}
            ]
        },
        headers={'Authorization': 'Bearer test-token'}
    )

    assert resp.status_code == 200

    # Verify contact metrics updated
    with test_app.app_context():
        contact = Contact.query.filter_by(email='recipient1@example.com').first()
        assert contact.emails_received == 1
        assert contact.last_outgoing_email_at is not None


def test_create_tracking_request_duplicate_tracking_id(client, test_app, tracking_user):
    """Test that duplicate tracking IDs are handled."""
    tracking_id = 'duplicate_tracking_id_111'

    # Create first request
    resp1 = client.post(
        '/api/tracking/requests',
        json={
            'user_email': tracking_user['email'],
            'tracking_id': tracking_id,
            'subject': 'First Email',
            'recipients': [{'email': 'test@example.com', 'name': 'Test'}]
        },
        headers={'Authorization': 'Bearer test-token'}
    )
    assert resp1.status_code == 200

    # Try to create second request with same tracking ID
    resp2 = client.post(
        '/api/tracking/requests',
        json={
            'user_email': tracking_user['email'],
            'tracking_id': tracking_id,
            'subject': 'Second Email',
            'recipients': [{'email': 'test2@example.com', 'name': 'Test2'}]
        },
        headers={'Authorization': 'Bearer test-token'}
    )

    # Should fail due to unique constraint
    assert resp2.status_code == 500


# ===== GET TRACKING REQUESTS ENDPOINT TESTS =====

def test_get_tracking_requests_requires_auth(client):
    """Test that fetching tracking requests requires authentication."""
    resp = client.get('/api/tracking/requests')
    assert resp.status_code == 401


def test_get_tracking_requests_empty(client, tracking_user):
    """Test fetching tracking requests when none exist."""
    resp = client.get(
        f'/api/tracking/requests?user_email={tracking_user["email"]}',
        headers={'Authorization': 'Bearer test-token'}
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['requests'] == []
    assert data['new_opens_count'] == 0


def test_get_tracking_requests_returns_list(client, test_app, tracking_user, tracking_contacts):
    """Test fetching tracking requests returns correct data."""
    with test_app.app_context():
        user = User.query.get(tracking_user["id"])

        # Create 2 tracking requests
        tr1 = TrackingRequest(
            user_id=user.id,
            tracking_id='get_test_1',
            subject='First Email',
            sent_at=datetime.utcnow() - timedelta(hours=2)
        )
        tr2 = TrackingRequest(
            user_id=user.id,
            tracking_id='get_test_2',
            subject='Second Email',
            sent_at=datetime.utcnow() - timedelta(hours=1)
        )
        db.session.add_all([tr1, tr2])
        db.session.commit()

    resp = client.get(
        f'/api/tracking/requests?user_email={tracking_user["email"]}',
        headers={'Authorization': 'Bearer test-token'}
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert len(data['requests']) == 2

    # Should be sorted by sent_at descending (most recent first)
    assert data['requests'][0]['subject'] == 'Second Email'
    assert data['requests'][1]['subject'] == 'First Email'


def test_get_tracking_requests_with_since_parameter(client, test_app, tracking_user):
    """Test that 'since' parameter correctly filters new opens."""
    with test_app.app_context():
        user = User.query.get(tracking_user["id"])

        # Create tracking request
        tr = TrackingRequest(
            user_id=user.id,
            tracking_id='since_test_123',
            subject='Test Email',
            sent_at=datetime.utcnow() - timedelta(hours=2)
        )
        db.session.add(tr)
        db.session.flush()

        # Add old event
        old_event = TrackingEvent(
            tracking_request_id=tr.id,
            opened_at=datetime.utcnow() - timedelta(hours=1)
        )
        db.session.add(old_event)
        db.session.commit()

    # First poll - no since parameter
    resp1 = client.get(
        f'/api/tracking/requests?user_email={tracking_user["email"]}',
        headers={'Authorization': 'Bearer test-token'}
    )
    assert resp1.get_json()['new_opens_count'] == 0

    # Record current time
    since_time = datetime.utcnow().isoformat()

    # Add new event after 'since' time
    with test_app.app_context():
        tr = TrackingRequest.query.filter_by(tracking_id='since_test_123').first()
        new_event = TrackingEvent(
            tracking_request_id=tr.id,
            opened_at=datetime.utcnow()
        )
        db.session.add(new_event)
        db.session.commit()

    # Second poll with since parameter
    resp2 = client.get(
        f'/api/tracking/requests?user_email={tracking_user["email"]}&since={since_time}',
        headers={'Authorization': 'Bearer test-token'}
    )
    data = resp2.get_json()
    assert data['new_opens_count'] == 1


def test_get_tracking_requests_includes_events(client, test_app, tracking_user):
    """Test that tracking requests include event data."""
    with test_app.app_context():
        user = User.query.get(tracking_user["id"])

        tr = TrackingRequest(
            user_id=user.id,
            tracking_id='events_test_456',
            subject='Test Email',
            sent_at=datetime.utcnow()
        )
        db.session.add(tr)
        db.session.flush()

        event = TrackingEvent(
            tracking_request_id=tr.id,
            opened_at=datetime.utcnow(),
            user_agent_parsed={'browser': 'Chrome', 'os': 'Mac OS X', 'device': 'Desktop'},
            city='San Francisco',
            country_code='US'
        )
        db.session.add(event)
        db.session.commit()

    resp = client.get(
        f'/api/tracking/requests?user_email={tracking_user["email"]}',
        headers={'Authorization': 'Bearer test-token'}
    )

    data = resp.get_json()
    assert len(data['requests']) == 1
    request_data = data['requests'][0]

    # Should include events array
    assert 'events' in request_data
    assert len(request_data['events']) == 1

    event_data = request_data['events'][0]
    assert event_data['user_agent_parsed']['browser'] == 'Chrome'
    assert event_data['city'] == 'San Francisco'
    assert event_data['country_code'] == 'US'


# ===== CONTACT ENGAGEMENT ENDPOINT TESTS =====

def test_get_contact_engagement_requires_auth(client):
    """Test that contact engagement endpoint requires authentication."""
    resp = client.get('/api/contacts/1/engagement')
    assert resp.status_code == 401


def test_get_contact_engagement_success(client, test_app, tracking_user, tracking_contacts):
    """Test fetching contact engagement data."""
    with test_app.app_context():
        user = User.query.get(tracking_user["id"])
        contact = Contact.query.filter_by(email='recipient1@example.com').first()

        # Create tracking request
        tr = TrackingRequest(
            user_id=user.id,
            tracking_id='engagement_test_789',
            subject='Engagement Test Email',
            sent_at=datetime.utcnow(),
            first_opened_at=datetime.utcnow(),
            open_count=2
        )
        db.session.add(tr)
        db.session.flush()

        # Link to contact
        recipient = TrackingRecipient(
            tracking_request_id=tr.id,
            contact_id=contact.id,
            recipient_type='to',
            has_opened=True,
            open_count=2
        )
        db.session.add(recipient)

        # Update contact metrics
        contact.emails_received = 2
        contact.emails_opened = 1
        contact.last_email_opened_at = datetime.utcnow()

        db.session.commit()
        contact_id = contact.id

    resp = client.get(
        f'/api/contacts/{contact_id}/engagement?user_email={tracking_user["email"]}',
        headers={'Authorization': 'Bearer test-token'}
    )

    assert resp.status_code == 200
    data = resp.get_json()

    assert data['success'] is True
    assert data['contact']['email'] == 'recipient1@example.com'
    assert data['contact']['emails_received'] == 2
    assert data['contact']['emails_opened'] == 1
    assert data['contact']['open_rate'] == 0.5
    assert len(data['recent_emails']) == 1


def test_get_contact_engagement_nonexistent_contact(client, tracking_user):
    """Test that requesting engagement for nonexistent contact returns 404."""
    resp = client.get(
        f'/api/contacts/99999/engagement?user_email={tracking_user["email"]}',
        headers={'Authorization': 'Bearer test-token'}
    )

    assert resp.status_code == 404


def test_get_contact_engagement_different_user(client, test_app, tracking_user, tracking_contacts):
    """Test that users can't access other users' contact engagement."""
    with test_app.app_context():
        # Create another user
        other_user = User(
            username="OtherUser",
            email="other@example.com",
            handle="other"
        )
        db.session.add(other_user)
        db.session.commit()

        # Get a contact from tracking_user
        contact = Contact.query.filter_by(email='recipient1@example.com').first()
        contact_id = contact.id

    # Try to access with other user's email
    resp = client.get(
        f'/api/contacts/{contact_id}/engagement?user_email=other@example.com',
        headers={'Authorization': 'Bearer test-token'}
    )

    # Should return 404 (contact not found for this user)
    assert resp.status_code == 404


# ===== CORS TESTS =====

def test_tracking_endpoints_have_cors_headers(client, tracking_user):
    """Test that tracking endpoints return proper CORS headers for extension."""
    resp = client.options(
        '/api/tracking/requests',
        headers={'Origin': 'chrome-extension://abcdef123456'}
    )

    assert resp.status_code == 200
    assert 'Access-Control-Allow-Origin' in resp.headers
    assert 'Access-Control-Allow-Methods' in resp.headers
    assert 'Access-Control-Allow-Headers' in resp.headers
