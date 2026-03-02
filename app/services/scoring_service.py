"""
Meeting and Lead Scoring Service

Provides intelligent scoring for meetings and leads based on various factors.
"""

import logging
from datetime import datetime, time
from typing import Optional

from app import db
from app.models import Event, Contact

logger = logging.getLogger(__name__)

# Enterprise domains that get bonus points
ENTERPRISE_DOMAINS = [
    # Tech companies
    'google.com', 'microsoft.com', 'apple.com', 'amazon.com', 'meta.com', 'facebook.com',
    'netflix.com', 'spotify.com', 'uber.com', 'lyft.com', 'airbnb.com', 'stripe.com',
    'square.com', 'shopify.com', 'salesforce.com', 'adobe.com', 'oracle.com', 'ibm.com',
    'cisco.com', 'intel.com', 'nvidia.com', 'amd.com', 'vmware.com', 'atlassian.com',
    'slack.com', 'zoom.us', 'dropbox.com', 'box.com', 'figma.com', 'notion.so',
    # Finance
    'goldmansachs.com', 'morganstanley.com', 'jpmorgan.com', 'bankofamerica.com',
    'wellsfargo.com', 'citibank.com', 'blackrock.com', 'bridgewater.com',
    # Consulting
    'mckinsey.com', 'bcg.com', 'bain.com', 'deloitte.com', 'pwc.com', 'kpmg.com',
    'ey.com', 'accenture.com', 'bcg.com',
]

PERSONAL_DOMAINS = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com', 'icloud.com']


def is_business_hours(start_time: Optional[time]) -> bool:
    """Check if time is during business hours (9 AM - 6 PM)."""
    if not start_time:
        return False
    return time(9, 0) <= start_time <= time(18, 0)


def is_weekend(start_date) -> bool:
    """Check if date is a weekend."""
    if not start_date:
        return False
    return start_date.weekday() >= 5  # Saturday = 5, Sunday = 6


def calculate_meeting_score(event: Event) -> int:
    """
    Calculate a priority score for a meeting (1-100).
    
    Factors:
    - Duration: Longer meetings score higher
    - Timing: Business hours score higher
    - Weekend: Weekend meetings score lower
    - Attendees: More attendees = higher score
    - Source: Calendly/CalAutobot meetings score higher
    
    Args:
        event: Event object to score
        
    Returns:
        Score from 1-100
    """
    score = 50  # Base score
    
    # Duration bonus
    duration = event.duration_minutes or 0
    if duration >= 60:
        score += 15
    elif duration >= 30:
        score += 10
    elif duration >= 15:
        score += 5
    elif duration > 0:
        score += 2  # Some bonus for having duration
    
    # Timing bonus (business hours)
    if event.start_time and is_business_hours(event.start_time):
        score += 10
    
    # Weekend penalty
    if event.start_date and is_weekend(event.start_date):
        score -= 15
    
    # Source bonus
    if event.source in ['calendly', 'calautobot']:
        score += 5
    
    # Invitee bonus (if we track attendees)
    # For now, just check if there's an invitee
    if event.invitee_email:
        score += 5
    
    # Conference URL bonus (means it's a real meeting)
    if event.conference_url:
        score += 5
    
    # Clamp score to 1-100
    return max(1, min(100, score))


def calculate_lead_score(email: str, total_meetings: int = 0, 
                         response_time_hours: float = None,
                         opened_followup: bool = False) -> int:
    """
    Calculate a lead score based on email domain and engagement.
    
    Args:
        email: Lead's email address
        total_meetings: Number of meetings with this lead
        response_time_hours: Hours until first response
        opened_followup: Whether they opened follow-up emails
        
    Returns:
        Score from 1-100
    """
    score = 50  # Base score
    
    if not email or '@' not in email:
        return score
    
    domain = email.split('@')[1].lower()
    
    # Domain bonus
    if domain in ENTERPRISE_DOMAINS:
        score += 15
    elif domain in PERSONAL_DOMAINS:
        score -= 5
    
    # Meeting history bonus
    if total_meetings >= 3:
        score += 15
    elif total_meetings >= 1:
        score += 5
    
    # Response time bonus
    if response_time_hours is not None:
        if response_time_hours <= 1:
            score += 20
        elif response_time_hours <= 4:
            score += 10
        elif response_time_hours <= 24:
            score += 5
    
    # Follow-up engagement
    if opened_followup:
        score += 10
    
    return max(1, min(100, score))


def score_event(event: Event, save: bool = True) -> int:
    """
    Score an event and optionally save to database.
    
    Args:
        event: Event to score
        save: Whether to save to database
        
    Returns:
        Calculated score
    """
    score = calculate_meeting_score(event)
    event.meeting_score = score
    event.last_scored_at = datetime.utcnow()
    
    if save:
        try:
            db.session.commit()
            logger.info(f"Scored event {event.id}: {score}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to save event score: {str(e)}")
    
    return score


def score_contact(contact: Contact, save: bool = True) -> int:
    """
    Score a contact and optionally save to database.
    
    Args:
        contact: Contact to score
        save: Whether to save to database
        
    Returns:
        Calculated score
    """
    # Calculate total meetings with this contact
    total_meetings = len(contact.participants) if contact.participants else 0
    
    # Check if they opened follow-up emails
    opened_followup = contact.emails_opened > 0 if contact.emails_received > 0 else False
    
    score = calculate_lead_score(
        email=contact.email,
        total_meetings=total_meetings,
        opened_followup=opened_followup
    )
    
    contact.lead_score = score
    contact.last_lead_scored_at = datetime.utcnow()
    
    if save:
        try:
            db.session.commit()
            logger.info(f"Scored contact {contact.id}: {score}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to save contact score: {str(e)}")
    
    return score


def score_all_user_events(user_id: int, limit: int = 100) -> dict:
    """
    Score all events for a user.
    
    Args:
        user_id: User ID
        limit: Maximum number of events to score
        
    Returns:
        Dictionary with scoring statistics
    """
    events = Event.query.filter_by(user_id=user_id).order_by(
        Event.created_at.desc()
    ).limit(limit).all()
    
    scored_count = 0
    scores = []
    
    for event in events:
        try:
            score = score_event(event, save=False)
            scores.append(score)
            scored_count += 1
        except Exception as e:
            logger.warning(f"Failed to score event {event.id}: {str(e)}")
    
    # Bulk commit
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to commit scores: {str(e)}")
    
    return {
        'scored_count': scored_count,
        'avg_score': sum(scores) / len(scores) if scores else 0,
        'min_score': min(scores) if scores else 0,
        'max_score': max(scores) if scores else 0,
    }


def get_high_priority_events(user_id: int, min_score: int = 70, limit: int = 10) -> list:
    """
    Get high-priority events for a user.
    
    Args:
        user_id: User ID
        min_score: Minimum score threshold
        limit: Maximum number of events to return
        
    Returns:
        List of high-priority events
    """
    events = Event.query.filter(
        Event.user_id == user_id,
        Event.meeting_score >= min_score,
        Event.status == 'scheduled'
    ).order_by(
        Event.meeting_score.desc(),
        Event.start_date.asc()
    ).limit(limit).all()
    
    return events


def get_score_distribution(user_id: int) -> dict:
    """
    Get score distribution for a user's events.
    
    Args:
        user_id: User ID
        
    Returns:
        Dictionary with score ranges and counts
    """
    events = Event.query.filter(
        Event.user_id == user_id,
        Event.meeting_score.isnot(None)
    ).all()
    
    distribution = {
        'critical': 0,    # 90-100
        'high': 0,        # 70-89
        'medium': 0,      # 50-69
        'low': 0,         # 30-49
        'minimal': 0,     # 1-29
    }
    
    for event in events:
        score = event.meeting_score
        if score >= 90:
            distribution['critical'] += 1
        elif score >= 70:
            distribution['high'] += 1
        elif score >= 50:
            distribution['medium'] += 1
        elif score >= 30:
            distribution['low'] += 1
        else:
            distribution['minimal'] += 1
    
    return distribution
