"""
Email tracking service for managing tracking requests and events.
"""

from datetime import datetime
from typing import Optional, Dict, List
import hashlib
import re
from user_agents import parse

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
    sender_ip: Optional[str] = None,
    sender_user_agent: Optional[str] = None,
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
        sender_ip: Sender's IP address (for fingerprinting)
        sender_user_agent: Sender's user agent (for fingerprinting)

    Returns:
        TrackingRequest instance
    """
    # Hash sender IP for privacy
    sender_ip_hash = hashlib.sha256(sender_ip.encode()).hexdigest() if sender_ip else None
    sender_ua_parsed = parse_user_agent(sender_user_agent) if sender_user_agent else None
    
    tracking_request = TrackingRequest(
        user_id=user.id,
        tracking_id=tracking_id,
        subject=subject,
        gmail_message_id=gmail_message_id,
        gmail_thread_id=gmail_thread_id,
        sender_ip_hash=sender_ip_hash,
        sender_user_agent_parsed=sender_ua_parsed,
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

    # Prevent self-tracking: check if current user is the sender
    from flask_login import current_user
    if current_user.is_authenticated and tracking_request.user:
        if current_user.email == tracking_request.user.email:
            # Silently ignore self-opens
            return None

    # Hash IP for privacy (no raw IP storage)
    ip_hash = hashlib.sha256(ip_address.encode()).hexdigest() if ip_address else None

    # Parse user agent to structured JSON
    user_agent_parsed = parse_user_agent(user_agent) if user_agent else None

    # ===== SELF-TRACKING PREVENTION (Multiple Layers) =====
    
    # Layer 1: Sender fingerprint check (catches first self-open if IP matches)
    if tracking_request.sender_ip_hash and ip_hash == tracking_request.sender_ip_hash:
        # Same IP - check user agent too for higher confidence
        if tracking_request.sender_user_agent_parsed and user_agent_parsed:
            sender_device = tracking_request.sender_user_agent_parsed.get('device')
            opener_device = user_agent_parsed.get('device')
            sender_browser = tracking_request.sender_user_agent_parsed.get('browser')
            opener_browser = user_agent_parsed.get('browser')
            
            # If either is Gmail proxy, ignore device comparison
            if sender_device == 'Gmail' or opener_device == 'Gmail':
                if sender_browser == opener_browser:
                    return None  # Sender opening their own email
            else:
                if sender_device == opener_device and sender_browser == opener_browser:
                    return None  # Sender opening their own email
    
    # Layer 2: Duplicate detection (catches repeated self-opens from same IP/UA)
    # This is critical for Gmail proxy opens, where sender IP differs from proxy IP
    if ip_hash and user_agent_parsed:
        previous_events = TrackingEvent.query.filter_by(
            tracking_request_id=tracking_request.id,
            ip_hash=ip_hash
        ).all()
        
        for event in previous_events:
            if event.user_agent_parsed:
                prev_device = event.user_agent_parsed.get('device')
                curr_device = user_agent_parsed.get('device')
                prev_browser = event.user_agent_parsed.get('browser')
                curr_browser = user_agent_parsed.get('browser')
                
                # If either is Gmail proxy, only match on browser
                if prev_device == 'Gmail' or curr_device == 'Gmail':
                    if prev_browser == curr_browser:
                        return None  # Duplicate open from same IP/browser
                else:
                    if prev_device == curr_device and prev_browser == curr_browser:
                        return None  # Duplicate open from same IP/device/browser


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
        region=location.get('region'),
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
        ip_address: IP address to lookup (may contain comma-separated list from X-Forwarded-For)

    Returns:
        Dict with country_code, region, city, timezone
    """
    # Extract first IP from X-Forwarded-For header (client's real IP)
    if ',' in ip_address:
        ip_address = ip_address.split(',')[0].strip()

    # Skip API call for private/internal IP addresses
    if is_private_ip(ip_address):
        return {'country_code': None, 'region': None, 'city': None, 'timezone': None}

    try:
        import requests
        response = requests.get(
            f'http://ip-api.com/json/{ip_address}',
            params={'fields': 'status,countryCode,region,city,timezone'},
            timeout=2
        )
        data = response.json()
        if data.get('status') == 'success':
            return {
                'country_code': data.get('countryCode'),
                'region': data.get('region'),  # State/province (e.g., "CA", "NY")
                'city': data.get('city'),
                'timezone': data.get('timezone')
            }
        # Log failures for debugging
        elif data.get('status') == 'fail':
            print(f"IP geolocation failed for {ip_address}: {data.get('message', 'unknown error')}")
    except Exception as e:
        print(f"IP geolocation exception for {ip_address}: {str(e)}")

    return {'country_code': None, 'city': None, 'timezone': None}


def is_private_ip(ip_address: str) -> bool:
    """
    Check if IP address is private/internal (RFC 1918, loopback, etc.).

    Args:
        ip_address: IP address string

    Returns:
        True if private/internal, False if public
    """
    try:
        import ipaddress
        ip = ipaddress.ip_address(ip_address)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except (ValueError, TypeError):
        # Invalid IP format
        return True  # Treat invalid IPs as private (skip API call)


def parse_user_agent(user_agent: str) -> Dict[str, str]:
    """
    Parse user agent using user_agents library.

    Args:
        user_agent: User agent string

    Returns:
        Dict with browser, os, device
    """
    # Detect Gmail image proxy first (before parsing)
    is_gmail_proxy = (
        'GoogleImageProxy' in user_agent or
        'ggpht.com' in user_agent or
        'Google Web Preview' in user_agent or
        # Gmail often uses this specific outdated Windows version
        ('Windows NT 5.1' in user_agent and 'Gecko' in user_agent)
    )
    
    ua = parse(user_agent)

    # Browser with major version
    browser = ua.browser.family
    if ua.browser.version_string:
        major_version = ua.browser.version_string.split('.')[0]
        browser = f"{ua.browser.family} {major_version}"

    # OS with version
    os = ua.os.family
    if ua.os.version_string:
        os = f"{ua.os.family} {ua.os.version_string}"

    # Device type
    if is_gmail_proxy:
        device = "Gmail"  # Gmail image proxy - actual device unknown
    elif ua.is_mobile:
        device = "Mobile"
    elif ua.is_tablet:
        device = "Tablet"
    else:
        device = "Desktop"

    return {
        "browser": browser,
        "os": os,
        "device": device
    }
