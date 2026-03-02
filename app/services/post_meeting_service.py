"""
Post-Meeting Follow-up Service

Automatically sends follow-up emails after meetings end.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app import db
from app.models import Event, User
from app.services.gmail_service import GmailService

logger = logging.getLogger(__name__)


# Default follow-up templates
DEFAULT_THANK_YOU_TEMPLATE = """Hi {invitee_name},

Thank you for meeting with me today! I appreciated our conversation about {event_name}.

If you have any follow-up questions or would like to schedule another meeting, feel free to reply to this email or visit my scheduling link.

Best regards,
{owner_name}
"""

DEFAULT_FEEDBACK_TEMPLATE = """Hi {invitee_name},

Thank you for taking the time to meet with me today about {event_name}.

I'd love to hear your feedback on our conversation. Was there anything you'd like to explore further?

Feel free to reply directly to this email.

Best,
{owner_name}
"""


def detect_completed_meetings(user_id: int, lookback_hours: int = 24) -> List[Event]:
    """
    Find events that have ended but haven't received a post-meeting follow-up.
    
    Args:
        user_id: User ID to check events for
        lookback_hours: How far back to look for completed meetings
        
    Returns:
        List of Event objects that need follow-up
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=lookback_hours)
    
    events = Event.query.filter(
        Event.user_id == user_id,
        Event.status == 'scheduled',
        Event.start_datetime.isnot(None),
        Event.post_meeting_sent_at.is_(None),
        Event.invitee_email.isnot(None),
    ).all()
    
    # Filter to events that have ended
    completed = []
    for event in events:
        try:
            # Parse RFC3339 datetime
            start_dt_str = event.start_datetime
            duration = event.duration_minutes or 30
            
            # Simple parsing for RFC3339 format
            if 'T' in start_dt_str:
                start_dt = datetime.fromisoformat(start_dt_str.replace('Z', '+00:00').replace('+00:00', ''))
            else:
                continue
                
            end_dt = start_dt + timedelta(minutes=duration)
            
            # Event has ended and is within lookback window
            if end_dt <= now and end_dt >= cutoff:
                completed.append(event)
        except Exception as e:
            logger.warning(f"Error parsing datetime for event {event.id}: {e}")
            continue
    
    return completed


def generate_followup_content(event: Event, user: User, template_type: str = 'thank_you') -> Dict[str, str]:
    """
    Generate follow-up email content for an event.
    
    Args:
        event: Event to generate follow-up for
        user: Owner of the event
        template_type: Type of template ('thank_you' or 'feedback')
        
    Returns:
        Dict with 'subject' and 'body' keys
    """
    invitee_name = event.invitee_name or event.invitee_email.split('@')[0]
    owner_name = user.display_name or user.email.split('@')[0]
    event_name = event.event_name or "our meeting"
    
    if template_type == 'feedback':
        body = DEFAULT_FEEDBACK_TEMPLATE.format(
            invitee_name=invitee_name,
            event_name=event_name,
            owner_name=owner_name
        )
    else:
        body = DEFAULT_THANK_YOU_TEMPLATE.format(
            invitee_name=invitee_name,
            event_name=event_name,
            owner_name=owner_name
        )
    
    subject = f"Thank you for our meeting - {event_name}"
    
    return {
        'subject': subject,
        'body': body
    }


def send_post_meeting_followup(event: Event, template_type: str = 'thank_you') -> bool:
    """
    Send a post-meeting follow-up email.
    
    Args:
        event: Event to send follow-up for
        template_type: Type of follow-up ('thank_you' or 'feedback')
        
    Returns:
        True if email sent successfully
    """
    user = event.user
    if not user:
        logger.warning(f"Event {event.id} has no user")
        return False
    
    if not event.invitee_email:
        logger.info(f"Event {event.id} has no invitee email, skipping follow-up")
        return False
    
    # Check if already sent
    if event.post_meeting_sent_at:
        logger.info(f"Event {event.id} already has post-meeting follow-up sent")
        return False
    
    # Generate content
    content = generate_followup_content(event, user, template_type)
    
    # Send email
    try:
        gmail = GmailService()
        success = gmail.send_email(
            to=event.invitee_email,
            subject=content['subject'],
            text_body=content['body']
        )
        
        if success:
            event.post_meeting_sent_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"Sent post-meeting follow-up for event {event.id} to {event.invitee_email}")
            return True
        else:
            logger.error(f"Failed to send post-meeting follow-up for event {event.id}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending post-meeting follow-up for event {event.id}: {e}")
        return False


def process_post_meetings(user_id: Optional[int] = None, lookback_hours: int = 24) -> Dict[str, int]:
    """
    Process all completed meetings and send follow-ups.
    
    Args:
        user_id: Specific user to process (None for all users)
        lookback_hours: How far back to look for completed meetings
        
    Returns:
        Dict with 'processed' and 'sent' counts
    """
    processed = 0
    sent = 0
    
    if user_id:
        user_ids = [user_id]
    else:
        # Get all users with post-meeting follow-up enabled
        users = User.query.filter(
            User.post_meeting_followup_enabled == True  # noqa: E712
        ).all()
        user_ids = [u.id for u in users]
    
    for uid in user_ids:
        events = detect_completed_meetings(uid, lookback_hours)
        
        for event in events:
            processed += 1
            try:
                success = send_post_meeting_followup(event)
                if success:
                    sent += 1
            except Exception as e:
                logger.error(f"Error processing post-meeting for event {event.id}: {e}")
    
    return {
        'processed': processed,
        'sent': sent
    }
