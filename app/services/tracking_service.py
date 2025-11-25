"""
Email tracking service for managing tracking requests and events.
"""

from datetime import datetime
from typing import Optional, Dict, List
import hashlib
import re

from app import db
from app.models import TrackingRequest, TrackingEvent, TrackingRecipient, User
from app.services.contacts import ensure_contact


def create_tracking_request(
    user: User,
    tracking_id: str,
    subject: Optional[str],
    recipients: List[Dict],
    cc_recipients: Optional[List[Dict]] = None,
    bcc_recipients: Optional[List[Dict]] = None,
    gmail_message_id: Optional[str] = None,
    gmail_thread_id: Optional[str] = None,
) -> TrackingRequest:
    """
    Create tracking request and link to contacts.

    Args:
        user: User object
        tracking_id: Unique tracking identifier (64-char hex)
        subject: Email subject
        recipients: List of {"email": "...", "name": "..."}
        cc_recipients: List of CC recipients
        bcc_recipients: List of BCC recipients
        gmail_message_id: Gmail message ID
        gmail_thread_id: Gmail thread ID

    Returns:
        TrackingRequest instance
    """
    tracking_request = TrackingRequest(
        user_id=user.id,
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
        contact = ensure_contact(
            user,
            recipient['email'],
            display_name=recipient.get('name'),
            first_seen_source='email_tracking'
        )

        if contact:
            tracking_recipient = TrackingRecipient(
                tracking_request_id=tracking_request.id,
                contact_id=contact.id,
                recipient_type='to',
                created_at=datetime.utcnow()
            )
            db.session.add(tracking_recipient)

            # Update contact metrics
            contact.emails_received += 1
            contact.last_outgoing_email_at = datetime.utcnow()

    # Handle CC recipients
    for recipient in (cc_recipients or []):
        contact = ensure_contact(
            user,
            recipient['email'],
            display_name=recipient.get('name'),
            first_seen_source='email_tracking'
        )

        if contact:
            tracking_recipient = TrackingRecipient(
                tracking_request_id=tracking_request.id,
                contact_id=contact.id,
                recipient_type='cc',
                created_at=datetime.utcnow()
            )
            db.session.add(tracking_recipient)
            contact.emails_received += 1

    # Handle BCC recipients
    for recipient in (bcc_recipients or []):
        contact = ensure_contact(
            user,
            recipient['email'],
            display_name=recipient.get('name'),
            first_seen_source='email_tracking'
        )

        if contact:
            tracking_recipient = TrackingRecipient(
                tracking_request_id=tracking_request.id,
                contact_id=contact.id,
                recipient_type='bcc',
                created_at=datetime.utcnow()
            )
            db.session.add(tracking_recipient)
            contact.emails_received += 1

    db.session.commit()
    return tracking_request


def record_tracking_event(
    tracking_id: str,
    ip_address: Optional[str],
    user_agent: Optional[str]
) -> Optional[TrackingEvent]:
    """
    Record tracking event with geolocation and update contact engagement.

    Args:
        tracking_id: Tracking identifier
        ip_address: IP address of opener
        user_agent: User agent string

    Returns:
        TrackingEvent instance or None if tracking request not found
    """
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
        db.func.count(db.func.distinct(TrackingEvent.ip_hash))
    ).filter(
        TrackingEvent.tracking_request_id == tracking_request.id
    ).scalar()
    tracking_request.unique_open_count = unique_ips or 0

    # Update contact engagement metrics
    for tracking_recipient in tracking_request.recipients:
        if not tracking_recipient.has_opened:
            tracking_recipient.has_opened = True
            tracking_recipient.first_opened_at = datetime.utcnow()

            # Update contact aggregate metrics
            if tracking_recipient.contact:
                tracking_recipient.contact.emails_opened += 1
                tracking_recipient.contact.last_email_opened_at = datetime.utcnow()

        tracking_recipient.open_count += 1

    db.session.commit()
    return event


def get_location_from_ip(ip_address: str) -> Dict[str, Optional[str]]:
    """
    Get geolocation using free ip-api.com (45 req/min limit).

    Args:
        ip_address: IP address to lookup

    Returns:
        Dict with country_code, city, timezone
    """
    try:
        import requests
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
    except Exception:
        pass

    return {'country_code': None, 'city': None, 'timezone': None}


def parse_user_agent(user_agent: str) -> Dict[str, str]:
    """
    Parse user agent without external library.

    Args:
        user_agent: User agent string

    Returns:
        Dict with browser, os, device
    """
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
