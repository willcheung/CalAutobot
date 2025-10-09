import hashlib
import json
from datetime import datetime
from typing import List, Dict, Set
from app.models import Event
from app import db
import logging

logger = logging.getLogger(__name__)

def generate_event_fingerprint(event_data: Dict) -> str:
    """
    Generate a unique fingerprint for an event to detect duplicates.
    Uses normalized event name, datetime, and location.
    """
    # Normalize the data for fingerprinting
    normalized_data = {
        'name': str(event_data.get('event_name', '')).lower().strip(),
        'start': str(event_data.get('start_datetime', '')).strip(),
        'end': str(event_data.get('end_datetime', '')).strip(),
        'location': str(event_data.get('location', '')).lower().strip()
    }
    
    # Create a consistent string representation
    fingerprint_string = json.dumps(normalized_data, sort_keys=True)
    
    # Generate SHA256 hash
    return hashlib.sha256(fingerprint_string.encode('utf-8')).hexdigest()

def deduplicate_events(all_events: List[Event], user_id: int, text_input_id: int) -> List[Event]:
    """
    Remove duplicate events based on fingerprinting.
    Returns only unique events and removes duplicates from database.
    """
    seen_fingerprints: Set[str] = set()
    unique_events: List[Event] = []
    
    for event in all_events:
        # Generate fingerprint for this event
        event_data = {
            'event_name': event.event_name,
            'start_datetime': event.start_datetime,
            'end_datetime': event.end_datetime,
            'location': event.location
        }
        
        fingerprint = generate_event_fingerprint(event_data)
        
        if fingerprint not in seen_fingerprints:
            seen_fingerprints.add(fingerprint)
            unique_events.append(event)
            logger.info(f"✅ Keeping unique event: {event.event_name}")
        else:
            # This is a duplicate - remove from database
            logger.info(f"🔄 Removing duplicate event: {event.event_name}")
            db.session.delete(event)
    
    # Commit the deletions
    try:
        db.session.commit()
        logger.info(f"📊 Deduplication complete: {len(unique_events)} unique events from {len(all_events)} total")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error during deduplication commit: {str(e)}")
        raise
    
    return unique_events

def should_skip_attachment(filename: str, content_type: str, size: int) -> bool:
    """
    Determine if an attachment should be skipped (likely signature/logo images).
    """
    filename_lower = filename.lower()
    
    # Skip common signature/logo patterns
    signature_patterns = [
        'image00', 'logo', 'signature', 'sig_', 'header', 'footer',
        'banner', 'brand', 'company_logo', 'email_signature'
    ]
    
    # Skip very small images (likely logos/signatures)
    if content_type.startswith('image/') and size < 10000:  # Less than 10KB
        logger.info(f"🚫 Skipping small image (likely signature): {filename} ({size} bytes)")
        return True
    
    # Skip by filename pattern
    for pattern in signature_patterns:
        if pattern in filename_lower:
            logger.info(f"🚫 Skipping signature-like attachment: {filename}")
            return True
    
    return False
