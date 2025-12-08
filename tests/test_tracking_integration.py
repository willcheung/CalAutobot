"""
Integration tests for email tracking feature.

Tests end-to-end flows:
- Send email → Track opens → View dashboard
- Multiple recipients with different engagement
- Contact engagement tracking over time
"""

from datetime import datetime, timedelta
import pytest

from app import db
from app.models import User, Contact, TrackingRequest, TrackingEvent
from app.services import tracking_service


@pytest.fixture
def integration_user(test_app):
    """Create a test user for integration tests."""
    with test_app.app_context():
        user = User(
            username="IntegrationUser",
            email="integration@example.com",
            handle="integration"
        )
        db.session.add(user)
        db.session.commit()
        return {
            "id": user.id,
            "email": user.email
        }


# ===== END-TO-END TRACKING FLOW TESTS =====

def test_complete_tracking_flow(client, test_app, integration_user):
    """Test complete tracking flow from send to dashboard view."""

    # Step 1: Send tracked email (create tracking request)
    with test_app.app_context():
        resp = client.post(
            '/api/tracking/requests',
            json={
                'user_email': integration_user['email'],
                'tracking_id': 'integration_flow_123',
                'subject': 'Integration Test Email',
                'recipients': [
                    {'email': 'alice@example.com', 'name': 'Alice'},
                    {'email': 'bob@example.com', 'name': 'Bob'}
                ]
            },
            headers={'Authorization': 'Bearer test-token'}
        )
        assert resp.status_code == 200

    # Step 2: Alice opens the email
    resp = client.get('/api/tracking/pixel/integration_flow_123')
    assert resp.status_code == 200

    # Step 3: Check tracking dashboard
    with test_app.app_context():
        resp = client.get(
            f'/api/tracking/requests?user_email={integration_user["email"]}',
            headers={'Authorization': 'Bearer test-token'}
        )
        data = resp.get_json()

        assert data['success'] is True
        assert len(data['requests']) == 1

        request = data['requests'][0]
        assert request['subject'] == 'Integration Test Email'
        assert request['open_count'] == 1
        assert request['first_opened_at'] is not None

        # Check recipients
        opened_recipients = [r for r in request['recipients'] if r['opened']]
        unopened_recipients = [r for r in request['recipients'] if not r['opened']]

        assert len(opened_recipients) == 2  # Both marked as opened (simplified for test)
        assert len(unopened_recipients) == 0


def test_multiple_emails_tracking(client, test_app, integration_user):
    """Test tracking multiple emails to the same recipient."""

    with test_app.app_context():
        user = User.query.get(integration_user["id"])

        # Send 3 emails to same recipient
        for i in range(3):
            tr = tracking_service.create_tracking_request(
                user=user,
                tracking_id=f'multi_email_{i}',
                subject=f'Email {i+1}',
                recipients=[{'email': 'charlie@example.com', 'name': 'Charlie'}]
            )

        # Charlie opens 2 out of 3 emails
        tracking_service.record_tracking_event('multi_email_0', '8.8.8.8', 'Test')
        tracking_service.record_tracking_event('multi_email_1', '8.8.8.8', 'Test')

        # Check contact engagement
        contact = Contact.query.filter_by(email='charlie@example.com').first()
        assert contact.emails_received == 3
        assert contact.emails_opened == 2
        assert contact.email_open_rate == round(2/3, 3)


def test_tracking_with_cc_bcc_recipients(client, test_app, integration_user):
    """Test tracking with TO, CC, and BCC recipients."""

    with test_app.app_context():
        resp = client.post(
            '/api/tracking/requests',
            json={
                'user_email': integration_user['email'],
                'tracking_id': 'cc_bcc_integration',
                'subject': 'Email with CC and BCC',
                'recipients': [
                    {'email': 'to@example.com', 'name': 'To Person'}
                ],
                'cc_recipients': [
                    {'email': 'cc@example.com', 'name': 'CC Person'}
                ],
                'bcc_recipients': [
                    {'email': 'bcc@example.com', 'name': 'BCC Person'}
                ]
            },
            headers={'Authorization': 'Bearer test-token'}
        )
        assert resp.status_code == 200

        # All recipients should be created as contacts
        to_contact = Contact.query.filter_by(email='to@example.com').first()
        cc_contact = Contact.query.filter_by(email='cc@example.com').first()
        bcc_contact = Contact.query.filter_by(email='bcc@example.com').first()

        assert to_contact is not None
        assert cc_contact is not None
        assert bcc_contact is not None

        # All should have emails_received = 1
        assert to_contact.emails_received == 1
        assert cc_contact.emails_received == 1
        assert bcc_contact.emails_received == 1


def test_contact_engagement_over_time(client, test_app, integration_user):
    """Test tracking contact engagement over multiple emails and opens."""

    with test_app.app_context():
        user = User.query.get(integration_user["id"])

        # Email 1: Sent and opened
        tr1 = tracking_service.create_tracking_request(
            user=user,
            tracking_id='engagement_email_1',
            subject='First Email',
            recipients=[{'email': 'diana@example.com', 'name': 'Diana'}]
        )
        tracking_service.record_tracking_event('engagement_email_1', '1.1.1.1', 'Test')

        # Email 2: Sent but not opened
        tr2 = tracking_service.create_tracking_request(
            user=user,
            tracking_id='engagement_email_2',
            subject='Second Email',
            recipients=[{'email': 'diana@example.com', 'name': 'Diana'}]
        )

        # Email 3: Sent and opened twice
        tr3 = tracking_service.create_tracking_request(
            user=user,
            tracking_id='engagement_email_3',
            subject='Third Email',
            recipients=[{'email': 'diana@example.com', 'name': 'Diana'}]
        )
        tracking_service.record_tracking_event('engagement_email_3', '2.2.2.2', 'Test')
        tracking_service.record_tracking_event('engagement_email_3', '2.2.2.2', 'Test')

        # Check final contact engagement
        contact = Contact.query.filter_by(email='diana@example.com').first()
        assert contact.emails_received == 3
        assert contact.emails_opened == 2  # Emails 1 and 3
        assert contact.email_open_rate == round(2/3, 3)

        # Check via engagement endpoint
        contact_id = contact.id

    resp = client.get(
        f'/api/contacts/{contact_id}/engagement?user_email={integration_user["email"]}',
        headers={'Authorization': 'Bearer test-token'}
    )

    data = resp.get_json()
    assert data['success'] is True
    assert data['contact']['emails_received'] == 3
    assert data['contact']['emails_opened'] == 2
    assert data['contact']['open_rate'] == round(2/3, 3)
    assert len(data['recent_emails']) == 3


def test_polling_for_new_opens(client, test_app, integration_user):
    """Test polling mechanism for detecting new opens."""

    with test_app.app_context():
        user = User.query.get(integration_user["id"])

        # Create tracking request
        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='polling_test_123',
            subject='Polling Test',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )

    # First poll - no opens yet
    resp1 = client.get(
        f'/api/tracking/requests?user_email={integration_user["email"]}',
        headers={'Authorization': 'Bearer test-token'}
    )
    data1 = resp1.get_json()
    assert data1['new_opens_count'] == 0

    # Record timestamp for 'since' parameter
    since_time = datetime.utcnow().isoformat()

    # Simulate email open after first poll
    with test_app.app_context():
        tracking_service.record_tracking_event('polling_test_123', '8.8.8.8', 'Test')

    # Second poll with 'since' parameter
    resp2 = client.get(
        f'/api/tracking/requests?user_email={integration_user["email"]}&since={since_time}',
        headers={'Authorization': 'Bearer test-token'}
    )
    data2 = resp2.get_json()

    # Should detect the new open
    assert data2['new_opens_count'] == 1


def test_unique_ip_tracking(client, test_app, integration_user):
    """Test that unique IP tracking works correctly."""

    with test_app.app_context():
        user = User.query.get(integration_user["id"])

        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='unique_ip_test',
            subject='Unique IP Test',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )

        # Same IP opens 3 times
        tracking_service.record_tracking_event('unique_ip_test', '1.1.1.1', 'Agent1')
        tracking_service.record_tracking_event('unique_ip_test', '1.1.1.1', 'Agent2')
        tracking_service.record_tracking_event('unique_ip_test', '1.1.1.1', 'Agent3')

        # Different IP opens once
        tracking_service.record_tracking_event('unique_ip_test', '2.2.2.2', 'Agent4')

        # Check stats
        tr = TrackingRequest.query.filter_by(tracking_id='unique_ip_test').first()
        assert tr.open_count == 4  # Total opens
        assert tr.unique_open_count == 2  # Only 2 unique IPs


def test_first_open_flag(client, test_app, integration_user):
    """Test that only first open is marked as is_first_open."""

    with test_app.app_context():
        user = User.query.get(integration_user["id"])

        tr = tracking_service.create_tracking_request(
            user=user,
            tracking_id='first_open_test',
            subject='First Open Test',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )

        # Record 3 opens
        tracking_service.record_tracking_event('first_open_test', '1.1.1.1', 'Agent')
        tracking_service.record_tracking_event('first_open_test', '2.2.2.2', 'Agent')
        tracking_service.record_tracking_event('first_open_test', '3.3.3.3', 'Agent')

        # Check events
        events = TrackingEvent.query.filter_by(tracking_request_id=tr.id).order_by(TrackingEvent.opened_at.asc()).all()
        assert len(events) == 3

        # Only first should be marked as first open
        assert events[0].is_first_open is True
        assert events[1].is_first_open is False
        assert events[2].is_first_open is False


def test_contact_created_with_first_seen_source(client, test_app, integration_user):
    """Test that contacts created via tracking have correct first_seen_source."""

    with test_app.app_context():
        resp = client.post(
            '/api/tracking/requests',
            json={
                'user_email': integration_user['email'],
                'tracking_id': 'source_test_123',
                'subject': 'Source Test',
                'recipients': [
                    {'email': 'newsource@example.com', 'name': 'New Source'}
                ]
            },
            headers={'Authorization': 'Bearer test-token'}
        )
        assert resp.status_code == 200

        # Check contact source
        contact = Contact.query.filter_by(email='newsource@example.com').first()
        assert contact.first_seen_source == 'email_tracking'


def test_dashboard_shows_correct_order(client, test_app, integration_user):
    """Test that dashboard returns emails in correct order (most recent first)."""

    with test_app.app_context():
        user = User.query.get(integration_user["id"])

        # Create emails with different timestamps
        tr1 = tracking_service.create_tracking_request(
            user=user,
            tracking_id='order_test_1',
            subject='Oldest Email',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )
        tr1.sent_at = datetime.utcnow() - timedelta(hours=3)

        tr2 = tracking_service.create_tracking_request(
            user=user,
            tracking_id='order_test_2',
            subject='Middle Email',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )
        tr2.sent_at = datetime.utcnow() - timedelta(hours=2)

        tr3 = tracking_service.create_tracking_request(
            user=user,
            tracking_id='order_test_3',
            subject='Newest Email',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )
        tr3.sent_at = datetime.utcnow() - timedelta(hours=1)

        db.session.commit()

    # Fetch dashboard
    resp = client.get(
        f'/api/tracking/requests?user_email={integration_user["email"]}',
        headers={'Authorization': 'Bearer test-token'}
    )
    data = resp.get_json()

    assert len(data['requests']) == 3

    # Should be ordered by sent_at descending (newest first)
    assert data['requests'][0]['subject'] == 'Newest Email'
    assert data['requests'][1]['subject'] == 'Middle Email'
    assert data['requests'][2]['subject'] == 'Oldest Email'


def test_inactive_tracking_request_not_counted(client, test_app, integration_user):
    """Test that inactive tracking requests are not included in dashboard."""

    with test_app.app_context():
        user = User.query.get(integration_user["id"])

        # Create active request
        tr_active = tracking_service.create_tracking_request(
            user=user,
            tracking_id='active_test',
            subject='Active Email',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )

        # Create inactive request
        tr_inactive = tracking_service.create_tracking_request(
            user=user,
            tracking_id='inactive_test',
            subject='Inactive Email',
            recipients=[{'email': 'test@example.com', 'name': 'Test'}]
        )
        tr_inactive.is_active = False
        db.session.commit()

    # Fetch dashboard
    resp = client.get(
        f'/api/tracking/requests?user_email={integration_user["email"]}',
        headers={'Authorization': 'Bearer test-token'}
    )
    data = resp.get_json()

    # Should only return active request
    assert len(data['requests']) == 1
    assert data['requests'][0]['subject'] == 'Active Email'
