# Email Tracking Integration Plan for CalAutobot Chrome Extension

## Executive Summary

This plan adds email tracking to the **chrome-extension-scheduler** (NOT upgrading the legacy Needle extension). We're enhancing the existing CalAutobot extension with simple pixel-based tracking, real-time notifications, and a basic dashboard. Focus on **MVP simplicity** - reuse existing code patterns, minimal new infrastructure, no over-engineering.

---

## Changelog

**v3 - Contact Integration & Accuracy Features (2025-11-24)**
- ✅ **ADDED**: Link TrackingRequest to Contact model for CRM engagement tracking
- ✅ **ADDED**: Contact engagement metrics (emails_received, emails_opened, open_rate)
- ✅ **ADDED**: TrackingRecipient junction table for per-contact tracking
- ✅ **RESTORED**: declarativeNetRequest for self-tracking prevention (needed for accuracy)
- ✅ **RESTORED**: Geolocation fields (country_code, city, timezone) using free IP API
- ✅ **RESTORED**: user_agent_parsed as JSON (better than simple string)
- ✅ **NEW**: Contact engagement API endpoint
- 📊 Updated dependencies: `requests` for IP geolocation (likely already have)

**v2 - Simplified Based on Feedback (2025-11-24)**
- ✂️ Reduced from 6 API endpoints to 3 core + 1 engagement endpoint
- ✂️ Removed fancy stats dashboard with 4 cards (single list view)
- ✂️ Removed tabs UI (Opened/Unopened - single unified view)
- ✂️ Removed pagination and filtering for MVP
- ✂️ Simplified CSS significantly

---

## 1. Architecture Design

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Gmail Page                              │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  Content Script (content.js) - Enhanced                │     │
│  │  ┌──────────────────────────────────────────────┐      │     │
│  │  │  InboxSDK Integration                        │      │     │
│  │  │  - Compose handlers (existing)               │      │     │
│  │  │  - NEW: Tracking toggle UI                   │      │     │
│  │  │  - NEW: Tracking pixel injection             │      │     │
│  │  │  - Toolbar notification badge                │      │     │
│  │  │  - Analytics panel                           │      │     │
│  │  └──────────────────────────────────────────────┘      │     │
│  └────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
                         ↕ (chrome.runtime messaging)
┌─────────────────────────────────────────────────────────────────┐
│  Service Worker (background.js) - Enhanced                      │
│  - Alarm-based polling for tracking events (MV3)                │
│  - Badge counter management                                     │
│  - webRequest filtering for self-tracking prevention            │
│  - Message relay between content scripts and backend            │
│  - Notification management                                      │
└─────────────────────────────────────────────────────────────────┘
                         ↕ (fetch API)
┌─────────────────────────────────────────────────────────────────┐
│  CalAutobot Backend (Flask)                                     │
│  - NEW: /api/tracking/* endpoints                               │
│  - Tracking pixel endpoint (image serve + event recording)      │
│  - Analytics aggregation endpoints                              │
│  - TrackingRequest & TrackingEvent models                       │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Design Decisions

**✅ Use Manifest V3 Service Workers** (not persistent background pages)
- Leverage `chrome.alarms` for periodic polling instead of setInterval
- Store state in chrome.storage.local (not in-memory variables)

**✅ Pure Vanilla JavaScript** (no Vue.js/React)
- Use Web Components for UI encapsulation
- Native DOM manipulation for lightweight performance
- Template literals for HTML rendering

**✅ Modern Tracking Pixel Approach**
- 1x1 transparent GIF with unique tracking ID
- Server-side event recording with IP, user-agent, timestamp
- Support for both inline and linked image tracking

**✅ Integration with Existing CalAutobot Backend**
- Reuse authentication (Bearer token via Chrome Identity API)
- Leverage existing User model and contact sync
- Add tracking-specific models and endpoints

---

## 2. Database Schema

### 2.1 New Models (Add to `app/models.py`)

```python
class TrackingRequest(db.Model):
    """Represents a tracked email send"""
    __tablename__ = 'tracking_request'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    tracking_id = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # Email metadata
    subject = db.Column(db.String(500), nullable=True)
    # NOTE: Recipients now linked via TrackingRecipient junction table (not JSON)

    # Tracking configuration
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    tracking_enabled_at_send = db.Column(db.Boolean, default=True, nullable=False)

    # Metadata
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    first_opened_at = db.Column(db.DateTime, nullable=True)
    last_opened_at = db.Column(db.DateTime, nullable=True)
    open_count = db.Column(db.Integer, default=0, nullable=False)
    unique_open_count = db.Column(db.Integer, default=0, nullable=False)  # Distinct IPs

    # Gmail context
    gmail_message_id = db.Column(db.String(255), nullable=True)
    gmail_thread_id = db.Column(db.String(255), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    events = db.relationship('TrackingEvent', backref='tracking_request',
                            lazy='dynamic', cascade='all, delete-orphan',
                            order_by='TrackingEvent.opened_at.desc()')
    recipients = db.relationship('TrackingRecipient', backref='tracking_request',
                                lazy='dynamic', cascade='all, delete-orphan')
    user = db.relationship('User', backref=db.backref('tracking_requests', lazy='dynamic'))

    def to_dict(self, include_events=False):
        data = {
            'id': self.id,
            'tracking_id': self.tracking_id,
            'subject': self.subject,
            'recipients': [
                {
                    'email': tr.contact.email,
                    'name': tr.contact.display_name,
                    'type': tr.recipient_type,
                    'opened': tr.has_opened
                }
                for tr in self.recipients.all()
            ],
            'is_active': self.is_active,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'first_opened_at': self.first_opened_at.isoformat() if self.first_opened_at else None,
            'last_opened_at': self.last_opened_at.isoformat() if self.last_opened_at else None,
            'open_count': self.open_count,
            'unique_open_count': self.unique_open_count,
            'gmail_thread_id': self.gmail_thread_id,
        }
        if include_events:
            data['events'] = [event.to_dict() for event in self.events.limit(50).all()]
        return data


class TrackingRecipient(db.Model):
    """Junction table linking tracking requests to contacts"""
    __tablename__ = 'tracking_recipient'

    id = db.Column(db.Integer, primary_key=True)
    tracking_request_id = db.Column(db.Integer, db.ForeignKey('tracking_request.id'),
                                   nullable=False, index=True)
    contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=False, index=True)
    recipient_type = db.Column(db.String(10), nullable=False)  # 'to', 'cc', 'bcc'

    # Per-recipient engagement for this email
    has_opened = db.Column(db.Boolean, default=False, nullable=False)
    first_opened_at = db.Column(db.DateTime, nullable=True)
    open_count = db.Column(db.Integer, default=0, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    contact = db.relationship('Contact', backref='tracking_recipients')

    def to_dict(self):
        return {
            'contact_id': self.contact_id,
            'email': self.contact.email,
            'name': self.contact.display_name,
            'type': self.recipient_type,
            'has_opened': self.has_opened,
            'first_opened_at': self.first_opened_at.isoformat() if self.first_opened_at else None,
            'open_count': self.open_count
        }


class TrackingEvent(db.Model):
    """Represents a single email open event"""
    __tablename__ = 'tracking_event'

    id = db.Column(db.Integer, primary_key=True)
    tracking_request_id = db.Column(db.Integer, db.ForeignKey('tracking_request.id'),
                                   nullable=False, index=True)

    # Event data
    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    ip_hash = db.Column(db.String(64), nullable=True, index=True)  # SHA256 for privacy

    # Client information - parsed from user agent
    user_agent_parsed = db.Column(db.JSON, nullable=True)
    # Stores: {"browser": "Chrome 120", "os": "Mac OS X", "device": "Desktop"}

    # Geolocation - from IP lookup (ip-api.com free tier)
    country_code = db.Column(db.String(2), nullable=True)  # "US", "GB", etc.
    city = db.Column(db.String(100), nullable=True)
    timezone = db.Column(db.String(50), nullable=True)  # "America/Los_Angeles"

    # Metadata
    is_first_open = db.Column(db.Boolean, default=False, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'user_agent_parsed': self.user_agent_parsed,
            'location': f"{self.city}, {self.country_code}" if self.city and self.country_code else self.country_code,
            'timezone': self.timezone,
            'is_first_open': self.is_first_open,
        }


# Add to User model relationships (line 50 in models.py):
# tracking_requests = db.relationship('TrackingRequest', backref='user', lazy='dynamic')

# Update existing Contact model with tracking engagement fields:
# Add these fields to the Contact model (around line 290-320):
"""
# Email tracking engagement metrics
emails_received = db.Column(db.Integer, default=0, nullable=False)
emails_opened = db.Column(db.Integer, default=0, nullable=False)
last_email_opened_at = db.Column(db.DateTime, nullable=True)

@property
def email_open_rate(self):
    '''Calculate engagement rate'''
    if self.emails_received == 0:
        return 0.0
    return round(self.emails_opened / self.emails_received, 3)
"""
```

### 2.2 Migration Script

```python
# migrations/versions/add_email_tracking_tables.py
"""Add email tracking tables

Revision ID: xxx
Revises: yyy
Create Date: 2025-11-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    # Create tracking_request table
    op.create_table('tracking_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('tracking_id', sa.String(64), nullable=False),
        sa.Column('subject', sa.String(500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('tracking_enabled_at_send', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
        sa.Column('first_opened_at', sa.DateTime(), nullable=True),
        sa.Column('last_opened_at', sa.DateTime(), nullable=True),
        sa.Column('open_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unique_open_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('gmail_message_id', sa.String(255), nullable=True),
        sa.Column('gmail_thread_id', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE')
    )

    op.create_index('ix_tracking_request_user_id', 'tracking_request', ['user_id'])
    op.create_index('ix_tracking_request_tracking_id', 'tracking_request', ['tracking_id'], unique=True)
    op.create_index('ix_tracking_request_sent_at', 'tracking_request', ['sent_at'])
    op.create_index('ix_tracking_request_gmail_thread_id', 'tracking_request', ['gmail_thread_id'])

    # Create tracking_recipient junction table
    op.create_table('tracking_recipient',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tracking_request_id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('recipient_type', sa.String(10), nullable=False),
        sa.Column('has_opened', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('first_opened_at', sa.DateTime(), nullable=True),
        sa.Column('open_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tracking_request_id'], ['tracking_request.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contact_id'], ['contact.id'], ondelete='CASCADE')
    )

    op.create_index('ix_tracking_recipient_tracking_request_id', 'tracking_recipient', ['tracking_request_id'])
    op.create_index('ix_tracking_recipient_contact_id', 'tracking_recipient', ['contact_id'])

    # Create tracking_event table
    op.create_table('tracking_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tracking_request_id', sa.Integer(), nullable=False),
        sa.Column('opened_at', sa.DateTime(), nullable=False),
        sa.Column('ip_hash', sa.String(64), nullable=True),
        sa.Column('user_agent_parsed', sa.JSON(), nullable=True),
        sa.Column('country_code', sa.String(2), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('timezone', sa.String(50), nullable=True),
        sa.Column('is_first_open', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tracking_request_id'], ['tracking_request.id'], ondelete='CASCADE')
    )

    op.create_index('ix_tracking_event_tracking_request_id', 'tracking_event', ['tracking_request_id'])
    op.create_index('ix_tracking_event_opened_at', 'tracking_event', ['opened_at'])
    op.create_index('ix_tracking_event_ip_hash', 'tracking_event', ['ip_hash'])

    # Add engagement fields to existing contact table
    op.add_column('contact', sa.Column('emails_received', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('contact', sa.Column('emails_opened', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('contact', sa.Column('last_email_opened_at', sa.DateTime(), nullable=True))

def downgrade():
    # Remove fields from contact table
    op.drop_column('contact', 'last_email_opened_at')
    op.drop_column('contact', 'emails_opened')
    op.drop_column('contact', 'emails_received')

    # Drop tracking tables
    op.drop_table('tracking_event')
    op.drop_table('tracking_recipient')
    op.drop_table('tracking_request')
```

---

## 3. Backend API Endpoints

### 3.1 New Routes (Add to `app/routes/extension_support.py`)

**SIMPLIFIED: Only 3 endpoints for MVP**

```python
# ==============================================================================
# Email Tracking Endpoints
# ==============================================================================

@api_routes.route('/api/tracking/pixel/<tracking_id>', methods=['GET'])
def tracking_pixel(tracking_id):
    """
    Serves tracking pixel and records open event
    Public endpoint - no authentication required
    """
    from app.services.tracking_service import record_tracking_event
    from flask import send_file
    import io

    # Record event asynchronously (don't block pixel response)
    try:
        record_tracking_event(
            tracking_id=tracking_id,
            ip_address=request.headers.get('X-Forwarded-For', request.remote_addr),
            user_agent=request.headers.get('User-Agent'),
            referer=request.headers.get('Referer')
        )
    except Exception as e:
        app.logger.error(f"Error recording tracking event: {e}")

    # Return 1x1 transparent GIF
    gif_bytes = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')
    return send_file(io.BytesIO(gif_bytes), mimetype='image/gif', max_age=0)


@api_routes.route('/api/tracking/requests', methods=['POST'])
@require_extension_auth
def create_tracking_request():
    """
    Creates a new tracking request
    Request body: {
        "tracking_id": "abc123...",
        "subject": "Meeting follow-up",
        "recipients": [{"email": "...", "name": "..."}],
        "cc_recipients": [...],
        "gmail_message_id": "...",
        "gmail_thread_id": "..."
    }
    """
    from app.services.tracking_service import create_tracking_request

    user = g.extension_user
    data = request.get_json()

    tracking_request = create_tracking_request(
        user_id=user.id,
        tracking_id=data['tracking_id'],
        subject=data.get('subject'),
        recipients=data['recipients'],
        cc_recipients=data.get('cc_recipients'),
        bcc_recipients=data.get('bcc_recipients'),
        gmail_message_id=data.get('gmail_message_id'),
        gmail_thread_id=data.get('gmail_thread_id')
    )

    return jsonify({
        'success': True,
        'tracking_request': tracking_request.to_dict()
    })


@api_routes.route('/api/tracking/requests', methods=['GET'])
@require_extension_auth
def get_tracking_requests():
    """
    SIMPLIFIED: Get last 50 tracking requests (no pagination, no filtering)
    Returns basic list with new_opens_count for badge notification
    """
    user = g.extension_user
    since = request.args.get('since')  # For polling - get events since last check

    # Get recent tracking requests
    requests = TrackingRequest.query.filter_by(
        user_id=user.id,
        is_active=True
    ).order_by(TrackingRequest.sent_at.desc()).limit(50).all()

    # Count new opens since last poll (for badge)
    new_opens_count = 0
    if since:
        since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
        new_opens_count = db.session.query(db.func.count(TrackingEvent.id)).join(
            TrackingRequest
        ).filter(
            TrackingRequest.user_id == user.id,
            TrackingEvent.opened_at >= since_dt
        ).scalar() or 0

    return jsonify({
        'success': True,
        'requests': [req.to_dict() for req in requests],
        'new_opens_count': new_opens_count  # For badge notification
    })


@api_routes.route('/api/contacts/<int:contact_id>/engagement', methods=['GET'])
@require_extension_auth
def get_contact_engagement(contact_id):
    """Get email tracking engagement for a specific contact"""
    user = g.extension_user
    contact = Contact.query.filter_by(id=contact_id, user_id=user.id).first_or_404()

    # Get all tracked emails sent to this contact
    tracked_emails = db.session.query(TrackingRequest).join(
        TrackingRecipient
    ).filter(
        TrackingRecipient.contact_id == contact.id
    ).order_by(TrackingRequest.sent_at.desc()).limit(20).all()

    return jsonify({
        'success': True,
        'contact': {
            'id': contact.id,
            'email': contact.email,
            'display_name': contact.display_name,
            'emails_received': contact.emails_received,
            'emails_opened': contact.emails_opened,
            'open_rate': contact.email_open_rate,
            'last_email_opened_at': contact.last_email_opened_at.isoformat() if contact.last_email_opened_at else None
        },
        'recent_emails': [
            {
                'subject': req.subject,
                'sent_at': req.sent_at.isoformat(),
                'opened': req.first_opened_at is not None,
                'open_count': req.open_count
            }
            for req in tracked_emails
        ]
    })
```

### 3.2 New Service (Create `app/services/tracking_service.py`)

```python
from app.models import db, TrackingRequest, TrackingEvent, TrackingRecipient
from datetime import datetime
import hashlib
import requests
import re

def create_tracking_request(user_id, tracking_id, subject, recipients,
                            cc_recipients=None, bcc_recipients=None,
                            gmail_message_id=None, gmail_thread_id=None):
    """Create tracking request and link to contacts"""
    from app.services.contacts import ensure_contact

    tracking_request = TrackingRequest(
        user_id=user_id,
        tracking_id=tracking_id,
        subject=subject,
        gmail_message_id=gmail_message_id,
        gmail_thread_id=gmail_thread_id,
        sent_at=datetime.utcnow()
    )
    db.session.add(tracking_request)
    db.session.flush()  # Get tracking_request.id

    # Link recipients to contacts
    for recipient in recipients:
        contact = ensure_contact(user_id, recipient['email'], recipient.get('name'))

        tracking_recipient = TrackingRecipient(
            tracking_request_id=tracking_request.id,
            contact_id=contact.id,
            recipient_type='to'
        )
        db.session.add(tracking_recipient)

        # Update contact metrics
        contact.emails_received += 1
        contact.last_outgoing_email_at = datetime.utcnow()

    # Handle CC recipients
    for recipient in (cc_recipients or []):
        contact = ensure_contact(user_id, recipient['email'], recipient.get('name'))
        tracking_recipient = TrackingRecipient(
            tracking_request_id=tracking_request.id,
            contact_id=contact.id,
            recipient_type='cc'
        )
        db.session.add(tracking_recipient)
        contact.emails_received += 1

    # Handle BCC recipients
    for recipient in (bcc_recipients or []):
        contact = ensure_contact(user_id, recipient['email'], recipient.get('name'))
        tracking_recipient = TrackingRecipient(
            tracking_request_id=tracking_request.id,
            contact_id=contact.id,
            recipient_type='bcc'
        )
        db.session.add(tracking_recipient)
        contact.emails_received += 1

    db.session.commit()
    return tracking_request


def record_tracking_event(tracking_id, ip_address, user_agent):
    """Record tracking event with geolocation and update contact engagement"""
    tracking_request = TrackingRequest.query.filter_by(
        tracking_id=tracking_id,
        is_active=True
    ).first()

    if not tracking_request:
        return None

    # Hash IP for privacy (no raw IP storage)
    ip_hash = hashlib.sha256(ip_address.encode()).hexdigest() if ip_address else None

    # Parse user agent to structured JSON
    user_agent_parsed = parse_user_agent(user_agent) if user_agent else None

    # Get geolocation from IP (using free ip-api.com)
    location = get_location_from_ip(ip_address) if ip_address else {}

    # Check if this is first open
    is_first_open = tracking_request.first_opened_at is None

    # Create event
    event = TrackingEvent(
        tracking_request_id=tracking_request.id,
        opened_at=datetime.utcnow(),
        ip_hash=ip_hash,
        user_agent_parsed=user_agent_parsed,
        country_code=location.get('country_code'),
        city=location.get('city'),
        timezone=location.get('timezone'),
        is_first_open=is_first_open
    )
    db.session.add(event)

    # Update tracking request stats
    tracking_request.open_count += 1
    tracking_request.last_opened_at = datetime.utcnow()

    if is_first_open:
        tracking_request.first_opened_at = datetime.utcnow()

    # Update unique open count (distinct IPs)
    unique_ips = db.session.query(
        db.func.count(db.distinct(TrackingEvent.ip_hash))
    ).filter(
        TrackingEvent.tracking_request_id == tracking_request.id
    ).scalar()
    tracking_request.unique_open_count = unique_ips

    # Update contact engagement metrics
    for tracking_recipient in tracking_request.recipients:
        if not tracking_recipient.has_opened:
            tracking_recipient.has_opened = True
            tracking_recipient.first_opened_at = datetime.utcnow()

            # Update contact aggregate metrics
            tracking_recipient.contact.emails_opened += 1
            tracking_recipient.contact.last_email_opened_at = datetime.utcnow()

        tracking_recipient.open_count += 1

    db.session.commit()
    return event


def get_location_from_ip(ip_address):
    """Get geolocation using free ip-api.com (45 req/min limit)"""
    try:
        response = requests.get(
            f'http://ip-api.com/json/{ip_address}',
            params={'fields': 'status,countryCode,city,timezone'},
            timeout=2
        )
        data = response.json()
        if data.get('status') == 'success':
            return {
                'country_code': data.get('countryCode'),
                'city': data.get('city'),
                'timezone': data.get('timezone')
            }
    except:
        pass
    return {'country_code': None, 'city': None, 'timezone': None}


def parse_user_agent(user_agent):
    """Parse user agent without external library"""
    ua_lower = user_agent.lower()

    # Browser + version
    browser = "Unknown"
    if 'chrome' in ua_lower and 'edg' not in ua_lower:
        version = re.search(r'chrome/([\d.]+)', ua_lower)
        browser = f"Chrome {version.group(1).split('.')[0]}" if version else "Chrome"
    elif 'firefox' in ua_lower:
        version = re.search(r'firefox/([\d.]+)', ua_lower)
        browser = f"Firefox {version.group(1).split('.')[0]}" if version else "Firefox"
    elif 'safari' in ua_lower and 'chrome' not in ua_lower:
        version = re.search(r'version/([\d.]+)', ua_lower)
        browser = f"Safari {version.group(1).split('.')[0]}" if version else "Safari"
    elif 'edg' in ua_lower:
        version = re.search(r'edg/([\d.]+)', ua_lower)
        browser = f"Edge {version.group(1).split('.')[0]}" if version else "Edge"

    # OS
    os = "Unknown"
    if 'windows nt 10' in ua_lower:
        os = "Windows 10"
    elif 'windows nt 11' in ua_lower:
        os = "Windows 11"
    elif 'windows' in ua_lower:
        os = "Windows"
    elif 'mac os x' in ua_lower:
        version = re.search(r'mac os x ([\d_]+)', ua_lower)
        if version:
            os = f"Mac OS X {version.group(1).replace('_', '.')}"
        else:
            os = "Mac OS X"
    elif 'linux' in ua_lower:
        os = "Linux"
    elif 'iphone' in ua_lower:
        os = "iOS"
    elif 'ipad' in ua_lower:
        os = "iPad"
    elif 'android' in ua_lower:
        version = re.search(r'android ([\d.]+)', ua_lower)
        os = f"Android {version.group(1)}" if version else "Android"

    # Device type
    device = "Desktop"
    if 'mobile' in ua_lower or 'android' in ua_lower or 'iphone' in ua_lower:
        device = "Mobile"
    elif 'tablet' in ua_lower or 'ipad' in ua_lower:
        device = "Tablet"

    return {
        "browser": browser,
        "os": os,
        "device": device
    }
```

---

## 4. Chrome Extension Frontend (Vanilla JS)

### 4.1 Enhanced `background.js`

```javascript
// ==============================================================================
// Email Tracking - Service Worker Enhancements
// ==============================================================================

const TRACKING_ALARM_NAME = 'tracking-poll';
const TRACKING_POLL_INTERVAL = 30; // seconds
const API_BASE = 'https://2df5bf01-2bac-4ced-b741-7ba31655935b-00-1qhgrsiodr7l4.kirk.replit.dev';

// Initialize alarms on install
chrome.runtime.onInstalled.addListener(() => {
  // Set up periodic polling alarm (Manifest V3 pattern)
  chrome.alarms.create(TRACKING_ALARM_NAME, {
    periodInMinutes: TRACKING_POLL_INTERVAL / 60
  });

  // Initialize badge
  chrome.action.setBadgeBackgroundColor({ color: '#4285F4' });
});

// Alarm listener for polling
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === TRACKING_ALARM_NAME) {
    await pollTrackingEvents();
  }
});

// Poll for new tracking events - SIMPLIFIED
async function pollTrackingEvents() {
  try {
    const token = await getAuthToken();
    if (!token) return;

    // Get last poll time from storage
    const { lastPollTime } = await chrome.storage.local.get('lastPollTime');
    const since = lastPollTime || new Date(Date.now() - 3600000).toISOString();

    // Fetch tracking requests with new_opens_count
    const response = await fetch(`${API_BASE}/api/tracking/requests?since=${since}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });

    if (!response.ok) return;

    const data = await response.json();
    const newOpensCount = data.new_opens_count || 0;

    if (newOpensCount > 0) {
      // Update badge
      chrome.action.setBadgeText({ text: newOpensCount.toString() });

      // Show notification
      chrome.notifications.create({
        type: 'basic',
        iconUrl: 'icons/icon128.png',
        title: 'Email Opened',
        message: `${newOpensCount} email${newOpensCount > 1 ? 's' : ''} opened recently`,
        priority: 1
      });

      // Notify content scripts
      chrome.tabs.query({ url: 'https://mail.google.com/*' }, (tabs) => {
        tabs.forEach(tab => {
          chrome.tabs.sendMessage(tab.id, {
            type: 'TRACKING_EVENTS_UPDATE',
            count: newOpensCount
          });
        });
      });
    }

    // Update last poll time
    await chrome.storage.local.set({ lastPollTime: new Date().toISOString() });

  } catch (error) {
    console.error('Error polling tracking events:', error);
  }
}

// Handle messages from content script - SIMPLIFIED
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'CREATE_TRACKING_REQUEST') {
    handleCreateTrackingRequest(message.data)
      .then(sendResponse)
      .catch(error => sendResponse({ error: error.message }));
    return true; // Async response
  }

  if (message.type === 'GET_TRACKING_REQUESTS') {
    handleGetTrackingRequests()
      .then(sendResponse)
      .catch(error => sendResponse({ error: error.message }));
    return true;
  }

  if (message.type === 'CLEAR_BADGE') {
    chrome.action.setBadgeText({ text: '' });
    sendResponse({ success: true });
  }
});

async function handleCreateTrackingRequest(data) {
  const token = await getAuthToken();
  const response = await fetch(`${API_BASE}/api/tracking/requests`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });

  if (!response.ok) throw new Error('Failed to create tracking request');
  return await response.json();
}

async function handleGetTrackingRequests() {
  const token = await getAuthToken();
  const response = await fetch(`${API_BASE}/api/tracking/requests`, {
    headers: { 'Authorization': `Bearer ${token}` }
  });

  if (!response.ok) throw new Error('Failed to fetch tracking requests');
  return await response.json();
}

// OPTIONAL: Self-tracking prevention (defer to Phase 4 or backend)
// For MVP, we can skip this or do simple backend IP check
// Uncomment if implementing via declarativeNetRequest:
/*
chrome.declarativeNetRequest.updateDynamicRules({
  removeRuleIds: [1],
  addRules: [{
    id: 1,
    priority: 1,
    action: { type: 'block' },
    condition: {
      urlFilter: '*/api/tracking/pixel/*',
      resourceTypes: ['image'],
      initiatorDomains: ['mail.google.com']
    }
  }]
});
*/
```

### 4.2 Enhanced `content.js`

```javascript
// ==============================================================================
// Email Tracking - Content Script Enhancements
// ==============================================================================

let trackingEnabled = true; // Default to enabled
let trackingPanel = null;

// Load InboxSDK and initialize tracking
InboxSDK.load(2, 'sdk_scheduler_142f817c3e').then(async function(sdk) {
  console.log('InboxSDK loaded with tracking support!');

  // Load tracking preferences
  const prefs = await chrome.storage.local.get('trackingEnabled');
  trackingEnabled = prefs.trackingEnabled !== false;

  // Register compose handlers
  sdk.Compose.registerComposeViewHandler(function(composeView) {
    setupComposeTracking(composeView);
  });

  // Add tracking panel to toolbar
  addTrackingPanel(sdk);

  // Listen for tracking updates from background
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'TRACKING_EVENTS_UPDATE') {
      refreshTrackingPanel();
    }
  });
});

function setupComposeTracking(composeView) {
  // Add tracking toggle to existing dropdown
  const existingButton = composeView.addButton({
    title: 'CalAutobot',
    iconUrl: 'https://2df5bf01-2bac-4ced-b741-7ba31655935b-00-1qhgrsiodr7l4.kirk.replit.dev/static/logo-cal-autobot-40.png',
    onClick: function(event) {
      event.dropdown.el.innerHTML = `
        <div class="cal-dropdown">
          ${createTrackingToggleHTML()}
          <div class="cal-dropdown-item" data-action="insert-availability">
            <span class="icon">📅</span>
            <span>Insert Availability</span>
          </div>
          <div class="cal-dropdown-item" data-action="insert-link">
            <span class="icon">🔗</span>
            <span>Insert Booking Link</span>
          </div>
          <div class="cal-dropdown-item" data-action="cc-bot">
            <span class="icon">🤖</span>
            <span>CC Cal Bot</span>
          </div>
        </div>
      `;

      attachDropdownHandlers(event.dropdown.el, composeView);
    }
  });

  // Intercept send event to inject tracking pixel
  composeView.on('presending', async (event) => {
    await handlePresending(event, composeView);
  });

  // Capture sent event to save tracking metadata
  composeView.on('sent', async () => {
    await handleSent(composeView);
  });
}

function createTrackingToggleHTML() {
  return `
    <div class="cal-dropdown-item tracking-toggle" data-action="toggle-tracking">
      <span class="icon">${trackingEnabled ? '✅' : '⬜'}</span>
      <span>Track Email Opens</span>
      <span class="toggle-badge">${trackingEnabled ? 'ON' : 'OFF'}</span>
    </div>
  `;
}

function attachDropdownHandlers(dropdownEl, composeView) {
  // Tracking toggle handler
  const trackingToggle = dropdownEl.querySelector('[data-action="toggle-tracking"]');
  if (trackingToggle) {
    trackingToggle.addEventListener('click', async () => {
      trackingEnabled = !trackingEnabled;
      await chrome.storage.local.set({ trackingEnabled });

      // Update UI
      const icon = trackingToggle.querySelector('.icon');
      const badge = trackingToggle.querySelector('.toggle-badge');
      icon.textContent = trackingEnabled ? '✅' : '⬜';
      badge.textContent = trackingEnabled ? 'ON' : 'OFF';
    });
  }

  // Existing handlers...
  dropdownEl.querySelector('[data-action="insert-availability"]')?.addEventListener('click', () => {
    insertAvailability(composeView);
  });

  // ... other handlers
}

async function handlePresending(event, composeView) {
  // Don't inject pixel if tracking is disabled
  if (!trackingEnabled) return;

  try {
    // Generate unique tracking ID
    const trackingId = await generateTrackingId();

    // Get email body HTML
    const bodyHTML = composeView.getHTMLContent();

    // Inject tracking pixel at end of body
    const trackingPixelHTML = `<img src="${API_BASE}/api/tracking/pixel/${trackingId}" width="1" height="1" style="display:none" alt="" />`;
    const modifiedHTML = bodyHTML + trackingPixelHTML;

    // Update compose body
    composeView.setBodyHTML(modifiedHTML);

    // Store tracking ID for sent event
    composeView._calautobotTrackingId = trackingId;

  } catch (error) {
    console.error('Error injecting tracking pixel:', error);
  }
}

async function handleSent(composeView) {
  if (!trackingEnabled || !composeView._calautobotTrackingId) return;

  try {
    // Extract recipients
    const toRecipients = composeView.getToRecipients().map(r => ({
      email: r.emailAddress,
      name: r.name
    }));

    const ccRecipients = composeView.getCcRecipients().map(r => ({
      email: r.emailAddress,
      name: r.name
    }));

    // Get subject
    const subject = composeView.getSubject();

    // Send to backend
    const response = await chrome.runtime.sendMessage({
      type: 'CREATE_TRACKING_REQUEST',
      data: {
        tracking_id: composeView._calautobotTrackingId,
        subject: subject,
        recipients: toRecipients,
        cc_recipients: ccRecipients.length > 0 ? ccRecipients : null
      }
    });

    if (response.success) {
      console.log('Tracking request created:', response.tracking_request);
    }

  } catch (error) {
    console.error('Error creating tracking request:', error);
  }
}

async function generateTrackingId() {
  // Generate cryptographically random tracking ID
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return Array.from(array, byte => byte.toString(16).padStart(2, '0')).join('');
}

// ==============================================================================
// Tracking Panel UI
// ==============================================================================

function addTrackingPanel(sdk) {
  // Add button to Gmail toolbar with badge support
  sdk.NavMenu.addNavItem({
    name: 'CalAutobot Tracking',
    iconUrl: 'https://2df5bf01-2bac-4ced-b741-7ba31655935b-00-1qhgrsiodr7l4.kirk.replit.dev/static/logo-cal-autobot-40.png',
    onClick: () => {
      openTrackingPanel(sdk);
    }
  });
}

async function openTrackingPanel(sdk) {
  if (trackingPanel && !trackingPanel.destroyed) {
    trackingPanel.close();
  }

  // Create modal panel
  trackingPanel = sdk.Widgets.showModalView({
    title: 'Email Tracking',
    el: await createTrackingPanelHTML()
  });

  // Clear badge when opened
  chrome.runtime.sendMessage({ type: 'CLEAR_BADGE' });
}

async function createTrackingPanelHTML() {
  const container = document.createElement('div');
  container.className = 'cal-tracking-panel';
  container.style.cssText = 'width: 600px; height: 500px; overflow: auto; padding: 16px; background: #f8f9fa;';

  // Fetch tracking data
  const response = await chrome.runtime.sendMessage({ type: 'GET_TRACKING_REQUESTS' });

  if (response.error) {
    container.innerHTML = `<div class="error">Failed to load tracking data</div>`;
    return container;
  }

  const requests = response.requests || [];

  // Group by tracking request (email sent), show opens per recipient
  container.innerHTML = `
    <h3 style="margin: 0 0 16px 0; font-size: 16px; color: #202124;">Email Tracking</h3>
    <div class="tracking-list" id="trackingList">
      ${requests.length === 0 ? '<div class="empty">No tracked emails yet</div>' :
        requests.map(req => createTrackingCard(req)).join('')
      }
    </div>
  `;

  // Attach event listeners for expand/collapse
  container.querySelectorAll('.tracking-expand-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const details = e.target.closest('.tracking-card').querySelector('.tracking-details');
      const isExpanded = details.style.display !== 'none';
      details.style.display = isExpanded ? 'none' : 'block';
      e.target.textContent = isExpanded ? '▼' : '▲';
    });
  });

  return container;
}

function createTrackingCard(req) {
  const hasOpened = req.first_opened_at !== null;
  const openedRecipients = req.recipients.filter(r => r.opened);

  // For unopened, show "Sent to X recipients"
  // For opened, show who opened it
  const headerText = hasOpened
    ? `${openedRecipients.map(r => r.name || r.email).join(', ')} opened your message ${formatRelativeTime(req.first_opened_at)}`
    : `Sent to ${req.recipients.length} recipient${req.recipients.length > 1 ? 's' : ''}`;

  return `
    <div class="tracking-card ${hasOpened ? 'opened' : 'unopened'}">
      <div class="tracking-card-header">
        <div class="tracking-card-main">
          <div class="tracking-header-line">
            ${hasOpened ? '✓' : '⏱'} ${headerText}
          </div>
          <div class="tracking-subject-line">
            <strong>${escapeHTML(req.subject || 'No subject')}</strong>
            <span class="tracking-sent-time">that you sent ${formatRelativeTime(req.sent_at)}</span>
          </div>
        </div>
        <div class="tracking-card-actions">
          ${hasOpened ? `<button class="tracking-action-btn">Pause Tracking</button>` : ''}
        </div>
      </div>

      <div class="tracking-card-body">
        <div class="tracking-platform">
          <span class="platform-icon">📧</span> Gmail
          <span class="tracking-network">on google.com network</span>
        </div>
        <div class="tracking-open-count">
          Opened ${req.open_count} time${req.open_count > 1 ? 's' : ''}
          ${req.open_count > 1 ? `<button class="tracking-expand-btn">▼</button>` : ''}
        </div>

        ${req.open_count > 1 ? `
          <div class="tracking-details" style="display: none;">
            <div class="tracking-detail-item">
              <span class="detail-time">${formatFullTime(req.first_opened_at)}</span>
              <span class="detail-label">First open</span>
            </div>
            <div class="tracking-detail-item">
              <span class="detail-time">${formatFullTime(req.last_opened_at)}</span>
              <span class="detail-label">Most recent</span>
            </div>
            <div class="tracking-detail-item">
              <span class="detail-count">${req.unique_open_count} unique IP${req.unique_open_count > 1 ? 's' : ''}</span>
            </div>
          </div>
        ` : ''}
      </div>
    </div>
  `;
}

function formatFullTime(isoString) {
  const date = new Date(isoString);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true
  }); // e.g., "Oct 17, 9:01 PM"
}

async function refreshTrackingPanel() {
  // SIMPLIFIED: Just reload the entire panel when there are new events
  if (trackingPanel && !trackingPanel.destroyed) {
    trackingPanel.close();
    // Panel will be reopened when user clicks tracking button again
  }
}

// Utility functions
function escapeHTML(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatRelativeTime(isoString) {
  const date = new Date(isoString);
  const seconds = Math.floor((new Date() - date) / 1000);

  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
```

### 4.3 Enhanced `styles.css`

**Card-based layout matching screenshot**

```css
/* Email Tracking Styles */

.cal-dropdown .tracking-toggle {
  border-bottom: 1px solid #e0e0e0;
  margin-bottom: 8px;
  padding-bottom: 8px;
}

.toggle-badge {
  margin-left: auto;
  font-size: 11px;
  font-weight: 600;
  color: #4285F4;
}

.cal-tracking-panel {
  font-family: 'Google Sans', Roboto, Arial, sans-serif;
}

.tracking-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* Card Layout */
.tracking-card {
  background: white;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  transition: box-shadow 0.2s;
}

.tracking-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}

.tracking-card.opened {
  border-left: 4px solid #34a853;
}

.tracking-card.unopened {
  border-left: 4px solid #fbbc04;
}

/* Card Header */
.tracking-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.tracking-card-main {
  flex: 1;
}

.tracking-header-line {
  font-size: 14px;
  color: #202124;
  margin-bottom: 4px;
  line-height: 1.4;
}

.tracking-subject-line {
  font-size: 13px;
  color: #5f6368;
  line-height: 1.4;
}

.tracking-subject-line strong {
  color: #202124;
  font-weight: 500;
}

.tracking-sent-time {
  color: #80868b;
}

.tracking-card-actions {
  display: flex;
  gap: 8px;
  margin-left: 12px;
}

.tracking-action-btn {
  background: white;
  border: 1px solid #dadce0;
  border-radius: 4px;
  padding: 6px 12px;
  font-size: 13px;
  color: #5f6368;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}

.tracking-action-btn:hover {
  background: #f8f9fa;
  border-color: #5f6368;
}

/* Card Body */
.tracking-card-body {
  padding-left: 24px;
  font-size: 12px;
  color: #5f6368;
}

.tracking-platform {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.platform-icon {
  font-size: 14px;
}

.tracking-network {
  color: #80868b;
  margin-left: 4px;
}

.tracking-open-count {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #202124;
  font-weight: 500;
}

.tracking-expand-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 6px;
  font-size: 10px;
  color: #5f6368;
  transition: color 0.2s;
}

.tracking-expand-btn:hover {
  color: #202124;
}

/* Expandable Details */
.tracking-details {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e0e0e0;
}

.tracking-detail-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 12px;
}

.detail-time {
  color: #202124;
  font-weight: 500;
}

.detail-label {
  color: #80868b;
}

.detail-count {
  color: #5f6368;
}

/* Empty/Error States */
.loading, .empty, .error {
  text-align: center;
  padding: 32px;
  color: #5f6368;
}

.error {
  color: #d93025;
}
```

### 4.4 Enhanced `manifest.json`

**SIMPLIFIED - Only essential permissions**

```json
{
  "manifest_version": 3,
  "name": "CalAutobot Scheduler with Email Tracking",
  "version": "2.0.0",
  "description": "Schedule meetings and track email opens directly from Gmail",

  "permissions": [
    "identity",
    "scripting",
    "storage",
    "alarms",
    "notifications",
    "declarativeNetRequest"
  ],

  "declarative_net_request": {
    "rule_resources": []
  },

  "host_permissions": [
    "https://mail.google.com/*",
    "https://*.replit.dev/*"
  ],

  "background": {
    "service_worker": "background.js",
    "type": "module"
  },

  "content_scripts": [
    {
      "matches": ["https://mail.google.com/*"],
      "js": ["content.js"],
      "css": ["styles.css"],
      "run_at": "document_end"
    }
  ],

  "action": {
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },

  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  },

  "oauth2": {
    "client_id": "609660480116-gn5g0smq5nih4n0km73kac8l6b7vlpii.apps.googleusercontent.com",
    "scopes": [
      "https://www.googleapis.com/auth/userinfo.email",
      "https://www.googleapis.com/auth/userinfo.profile"
    ]
  }
}
```

---

## 5. Polling vs Event-Driven Architecture

### The Question: Why polling? Is there an event-driven alternative?

**Short Answer:** For Manifest V3 Chrome extensions, `chrome.alarms` polling is the **recommended pattern**. Event-driven alternatives exist but add significant complexity.

### Options Comparison:

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **chrome.alarms (Current)** | ✅ Simple<br>✅ Reliable<br>✅ Works with sleeping service workers<br>✅ No infrastructure changes | ⚠️ 30s delay (acceptable) | ✅ **RECOMMENDED** |
| **WebSockets** | ✅ Real-time (instant)<br>✅ Bidirectional | ❌ Service workers can't hold persistent connections<br>❌ Needs reconnection logic<br>❌ Backend WebSocket server required | ❌ Complex for MV3 |
| **Server-Sent Events (SSE)** | ✅ Real-time push | ❌ Same issues as WebSockets<br>❌ Service workers sleep | ❌ Not suitable |
| **Web Push API** | ✅ True push notifications | ❌ Requires push service registration<br>❌ User must grant permission<br>❌ More complex backend | 🤔 Overkill for this use case |
| **Long Polling** | ✅ Near real-time | ❌ Backend must hold connections<br>❌ Service worker sleep issues | ⚠️ Possible but not better |

### Why chrome.alarms wins:

1. **MV3 Service Workers Sleep**: Chrome can kill your service worker at any time to save resources. `chrome.alarms` will wake it back up reliably.

2. **No Persistent Connections Needed**: Polling is stateless - each check is independent.

3. **30 seconds is fast enough**: For email tracking, users don't need millisecond precision. Knowing someone opened your email within 30 seconds is sufficient.

4. **Simple Backend**: No need for WebSocket infrastructure, just regular HTTP endpoints.

5. **Battery Friendly**: Less aggressive than maintaining persistent connections.

### If you still want real-time:

You could implement **hybrid approach**:
- Use `chrome.alarms` for baseline polling (every 60s)
- Add WebSocket connection when extension is actively used
- Fall back to alarms when WebSocket disconnects

```python
# Backend WebSocket endpoint (optional future enhancement)
@socketio.on('connect')
def handle_connect():
    user_id = get_current_user_id()
    join_room(f'user_{user_id}')

# When email opened, push to user
def record_tracking_event(...):
    # ... existing code ...
    socketio.emit('email_opened', {
        'tracking_request_id': tracking_request.id,
        'subject': tracking_request.subject
    }, room=f'user_{user_id}')
```

**Recommendation for MVP:** Stick with `chrome.alarms` polling every 30s. It's simple, reliable, and sufficient.

---

## 6. Implementation Plan

### Phase 1: Database & Backend Foundation (Week 1)
**Goal**: Set up tracking infrastructure on backend

**Tasks**:
1. Create simplified TrackingRequest and TrackingEvent models (no geolocation, minimal fields)
2. Write and run database migration
3. Implement `tracking_service.py` with 2 core functions (create, record)
4. Add 3 tracking endpoints to `extension_support.py` (pixel, create, list)
5. Test tracking pixel endpoint manually
6. Test create and list endpoints with Postman/curl

**Deliverables**:
- Working pixel endpoint that serves GIF and records events
- POST endpoint to create tracking requests
- GET endpoint to list tracking requests
- Database tables created and indexed
- NO external dependencies (no user-agents library needed)

---

### Phase 2: Chrome Extension - Tracking Core (Week 2)
**Goal**: Implement pixel injection and tracking request creation

**Tasks**:
1. Update manifest.json with new permissions
2. Enhance background.js with tracking message handlers
3. Implement `generateTrackingId()` in content.js
4. Add tracking toggle to compose dropdown
5. Implement `handlePresending()` to inject pixel
6. Implement `handleSent()` to create tracking request
7. Test end-to-end: send email → pixel injected → request created
8. Verify tracking pixel is served and event recorded

**Deliverables**:
- Emails sent from extension contain tracking pixels
- Tracking requests saved to database on send
- Basic logging for debugging

---

### Phase 3: Real-Time Notifications (Week 3)
**Goal**: Implement polling and badge notifications

**Tasks**:
1. Implement alarm-based polling in background.js
2. Add `pollTrackingEvents()` function
3. Implement badge counter update logic
4. Add Chrome notifications for new opens
5. Implement message passing to content script
6. Store last poll time in chrome.storage.local
7. Test polling interval and badge updates

**Deliverables**:
- Badge shows number of recent email opens
- Notifications appear when emails are opened
- Polling runs every 30 seconds

---

### Phase 4: Self-Tracking Prevention (OPTIONAL - Can defer)
**Goal**: Prevent users from tracking themselves

**SIMPLIFIED APPROACH** - Choose one:

**Option A: Backend IP Check (Simpler)**
- Store user's recent IPs when they send emails
- In tracking pixel endpoint, ignore if IP matches sender's recent activity
- No extension changes needed

**Option B: Skip for MVP**
- Document as known limitation
- Add in future iteration if users request it

**Deliverables**:
- (Optional) Basic self-tracking prevention
- Or: Skip entirely for MVP

---

### Phase 5: Simple Dashboard UI (Week 4)
**Goal**: Build basic tracking panel in Gmail

**SIMPLIFIED TASKS**:
1. Implement `addTrackingPanel()` with InboxSDK NavMenu
2. Create `createTrackingPanelHTML()` with simple list (no stats, no tabs)
3. Add minimal CSS styling for list items
4. Show open status, open count, timestamps

**Deliverables**:
- Simple tracking panel accessible from Gmail sidebar
- Shows list of recent tracked emails (last 50)
- Indicates which emails have been opened
- Clean, minimal UI

---

### Phase 6: Testing & Polish (Week 5)
**Goal**: Ensure production-readiness

**Tasks**:
1. End-to-end testing: send → open → notification → view
2. Test with multiple recipients
3. Test with CC/BCC
4. Test tracking toggle (enabled/disabled)
5. Test error handling (network failures, token expiry)
6. Add loading states and error messages
7. Performance testing (large tracking lists)
8. Cross-browser testing (Chrome, Edge)
9. Privacy audit (IP hashing, GDPR considerations)
10. Documentation and user guide

**Deliverables**:
- Stable, production-ready extension
- Comprehensive test coverage
- User documentation

---

## 6. Tech Stack Modernization

### Compared to Legacy Needle Extension

| Component | Needle (2017) | CalAutobot (2025) |
|-----------|---------------|-------------------|
| **Manifest** | V2 (deprecated) | V3 (current standard) |
| **Background** | Persistent page | Service worker |
| **Frontend** | Vue.js 2.5 | Vanilla JS + Web Components |
| **Build** | Webpack 3 | None (static files) |
| **Polling** | setInterval (in-memory) | chrome.alarms (persistent) |
| **Storage** | In-memory variables | chrome.storage API |
| **Request Blocking** | webRequest API | declarativeNetRequest API |
| **Auth** | Custom flow | Chrome Identity API |
| **Dependencies** | 20+ npm packages | Zero dependencies |

### Benefits of Modern Approach

1. **Manifest V3 Compliance**: Future-proof (Google will disable MV2 in 2024-2025)
2. **No Build Step**: Faster development iteration
3. **Better Performance**: Service workers are lighter than persistent background pages
4. **Persistent State**: chrome.storage survives browser restarts
5. **Security**: Stricter CSP, declarative permissions
6. **Maintainability**: No npm dependency hell

---

## 7. Privacy & Security Considerations

### 7.1 Data Privacy

**IP Address Handling**:
- Store SHA256 hash of IP, not raw IP
- Only show partial IP in UI (`192.168...`)
- Comply with GDPR/CCPA right to deletion

**User Agent Parsing**:
- Parse to structured data (browser, OS, device)
- Don't store raw user agent string long-term

**Opt-Out Mechanism**:
- Allow users to disable tracking per-email
- Provide account-level setting to disable all tracking

### 7.2 Security Measures

**Tracking ID Generation**:
- Use `crypto.getRandomValues()` for unpredictable IDs
- 64-character hex (256-bit entropy)

**Self-Tracking Prevention**:
- Block tracking pixels initiated from Gmail
- Prevents accidental self-opens from skewing stats

**Authentication**:
- Reuse existing Bearer token auth
- No new attack surface

**Rate Limiting** (Backend):
```python
from flask_limiter import Limiter

limiter = Limiter(app, key_func=lambda: request.headers.get('Authorization'))

@api_routes.route('/api/tracking/pixel/<tracking_id>')
@limiter.limit("100 per minute")  # Prevent abuse
def tracking_pixel(tracking_id):
    # ...
```

---

## 8. Testing Strategy

### 8.1 Backend Tests

```python
# tests/test_tracking_service.py
def test_create_tracking_request(client, auth_user):
    tracking_id = "test123"
    request = create_tracking_request(
        user_id=auth_user.id,
        tracking_id=tracking_id,
        subject="Test Email",
        recipients=[{"email": "test@example.com"}]
    )
    assert request.tracking_id == tracking_id
    assert request.open_count == 0

def test_record_tracking_event(client, auth_user):
    # Create request
    request = create_tracking_request(...)

    # Record event
    event = record_tracking_event(
        tracking_id=request.tracking_id,
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0..."
    )

    assert event.is_first_open == True
    assert request.open_count == 1
    assert request.first_opened_at is not None
```

### 8.2 Extension E2E Tests

Use Selenium WebDriver with Chrome extension:

```javascript
// test/e2e/tracking.test.js
describe('Email Tracking', () => {
  it('should inject tracking pixel on send', async () => {
    await gmail.compose({
      to: 'test@example.com',
      subject: 'Test',
      body: 'Hello'
    });

    await gmail.enableTracking();
    await gmail.send();

    // Verify pixel injected
    const sentEmail = await gmail.getSentEmail();
    expect(sentEmail.html).toContain('/api/tracking/pixel/');
  });

  it('should show notification when email opened', async () => {
    // Simulate email open
    await triggerTrackingPixel(trackingId);

    // Wait for poll
    await sleep(31000);

    // Check badge
    const badge = await chrome.action.getBadgeText();
    expect(badge).toBe('1');
  });
});
```

---

## 9. Deployment Checklist

### Backend Deployment
- [ ] Run database migration: `flask db upgrade`
- [ ] Install new dependency: `pip install user-agents`
- [ ] Update requirements.txt
- [ ] Test tracking pixel endpoint in production
- [ ] Set up monitoring for tracking API endpoints
- [ ] Configure rate limiting

### Extension Deployment
- [ ] Update manifest version to 2.0.0
- [ ] Test in development mode (chrome://extensions)
- [ ] Package extension: `zip -r extension.zip . -x "*.git*"`
- [ ] Submit to Chrome Web Store for review
- [ ] Update extension listing with new features
- [ ] Prepare user announcement/changelog

### Documentation
- [ ] Update README with tracking features
- [ ] Create user guide for email tracking
- [ ] Document privacy policy updates
- [ ] Add API documentation for tracking endpoints

---

## 10. Future Enhancements (Post-MVP)

1. **Link Click Tracking**: Track clicks on links within emails
2. **Geolocation**: Add IP geolocation service (MaxMind GeoIP2)
3. **Email Engagement Score**: ML-based scoring of recipient engagement
4. **Templates**: Save tracked email templates
5. **Team Analytics**: Aggregate stats for organization
6. **Export**: CSV/JSON export of tracking data
7. **Integrations**: Zapier, Salesforce, HubSpot webhooks
8. **A/B Testing**: Track multiple versions of email

---

## Summary

This plan adds **email tracking with CRM integration** to CalAutobot's chrome-extension-scheduler:

### Key Features:
- ✅ **Contact Integration** - Link tracking to existing Contact model for engagement metrics
- ✅ **TrackingRecipient Junction Table** - Per-contact, per-email tracking
- ✅ **Contact Engagement Metrics** - emails_received, emails_opened, open_rate
- ✅ **Geolocation** - Country, city, timezone via free ip-api.com
- ✅ **User Agent Parsing** - Structured JSON (browser, OS, device) without external libraries
- ✅ **Self-Tracking Prevention** - declarativeNetRequest blocks own email opens
- ✅ **4 API Endpoints** - Pixel, create, list, contact engagement
- ✅ **Simple UI** - Single list view (no complex dashboard)
- ✅ **chrome.alarms Polling** - 30s intervals (recommended MV3 pattern)

### Tech Stack:
- ✅ **Pure Vanilla JS** (no Vue.js, no React, no build tools)
- ✅ **Manifest V3** (future-proof)
- ✅ **Zero build step** (rapid iteration)
- ✅ **Reuse existing code** (Chrome Identity auth, InboxSDK, Contact sync pattern)
- ✅ **Privacy-first** (IP hashing only, no raw IP storage)

### Database:
**3 New Tables:**
1. `tracking_request` - Email sends
2. `tracking_recipient` - Junction table (request ↔ contact)
3. `tracking_event` - Email opens with location/device data

**Updates to Existing:**
- `contact` - Add 3 engagement fields

### API Summary:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/tracking/pixel/<id>` | GET | Serve tracking GIF + record event |
| `/api/tracking/requests` | POST | Create tracking request with contacts |
| `/api/tracking/requests` | GET | List recent 50 with new_opens_count |
| `/api/contacts/<id>/engagement` | GET | Contact engagement metrics |

### Chrome Extension Permissions:
All 6 permissions are needed:
- `identity` - OAuth authentication ✅
- `scripting` - Inject InboxSDK ✅
- `storage` - Store lastPollTime, preferences ✅
- `alarms` - 30s polling (MV3 pattern) ✅
- `notifications` - Desktop alerts on opens ✅
- `declarativeNetRequest` - Block self-tracking ✅

### Metrics:
**Estimated Timeline**: 4-5 weeks
**Total LOC Added**: ~1,000 lines (backend + extension + styles)
**New Dependencies**: `requests` (likely already have it)

### Core Value Props:
1. **CRM Engagement Tracking** - See which contacts engage with your emails
2. **Real-time Notifications** - Know when prospects open emails (within 30s)
3. **Location Insights** - See where emails are opened
4. **Device Detection** - Understand how recipients view emails
5. **Open Rate Metrics** - Contact-level engagement scoring

Ready to start implementation with **Phase 1 (Database & Backend Foundation)**!
