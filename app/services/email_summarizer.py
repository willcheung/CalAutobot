"""
Email Summarization and Sender Categorization Service

This service provides AI-powered email summarization and sender pattern tracking.
"""

import json
import logging
import re
from datetime import datetime
from typing import Optional, Tuple

from openai import OpenAI
import sentry_sdk

from app import db
from app.models import EmailSummary, SenderPattern

logger = logging.getLogger(__name__)

# OpenAI client setup
import os
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY environment variable must be set")
openai = OpenAI(api_key=OPENAI_API_KEY)

# Email summarization prompt
EMAIL_SUMMARY_SYS_PROMPT = """You are an expert at analyzing emails and providing concise, actionable summaries. Always respond with a valid JSON object. No extra commentary.

Analyze the email and provide:
1. A 1-2 sentence summary of what this email is about
2. A category classification
3. A priority score (1-10)
4. Whether action is required
5. If action is required, what specifically needs to be done"""

EMAIL_SUMMARY_PROMPT = """Analyze this email and respond with JSON only:

{
  "summary": "1-2 sentence summary of the email content",
  "category": "one of: newsletter, promotion, personal, business, urgent, scheduling, other",
  "priority": 1-10 (10 = urgent action needed today, 1 = can ignore),
  "action_required": true/false,
  "action_description": "specific action needed if action_required is true, otherwise null",
  "sender_name": "name of sender if mentioned in email, otherwise null"
}

Category definitions:
- newsletter: subscriptions, digests, regular updates
- promotion: marketing, sales, discounts, offers
- personal: friends, family, personal matters
- business: work, professional, colleagues, clients
- urgent: needs immediate attention (today)
- scheduling: meeting requests, calendar-related, appointments
- other: doesn't fit above categories

Priority guidelines:
- 9-10: Urgent, needs response/action today
- 7-8: Important, should address within 1-2 days
- 5-6: Moderate, address within a week
- 3-4: Low priority, can address eventually
- 1-2: Can likely ignore or auto-archive

Email content:
'''{email_text}'''"""


def extract_sender_info(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract sender email, domain, and name from email text.

    Args:
        text: Email text content

    Returns:
        Tuple of (sender_email, sender_domain, sender_name)
    """
    sender_email = None
    sender_domain = None
    sender_name = None

    # Try to find From: header
    from_match = re.search(r'From:\s*(.+?)(?:\n|$)', text, re.IGNORECASE | re.MULTILINE)
    if from_match:
        from_line = from_match.group(1).strip()

        # Extract email from "Name <email>" format
        email_match = re.search(r'<([^>]+)>', from_line)
        if email_match:
            sender_email = email_match.group(1).lower()
            # Extract name before email
            name_match = re.match(r'^([^<]+)', from_line)
            if name_match:
                sender_name = name_match.group(1).strip().strip('"\'')
        else:
            # Plain email
            email_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', from_line)
            if email_match:
                sender_email = email_match.group(1).lower()
            else:
                # Might just be a name
                sender_name = from_line.strip().strip('"\'').strip('<>')

    if sender_email and '@' in sender_email:
        sender_domain = sender_email.split('@')[1]

    return sender_email, sender_domain, sender_name


def summarize_email(text: str, from_email: str = None) -> dict:
    """
    Summarize email and categorize sender using OpenAI.

    Args:
        text: The email text content
        from_email: Optional pre-extracted sender email

    Returns:
        Dictionary with summary, category, priority, action info, and sender details
    """
    try:
        # Extract sender info
        extracted_email, extracted_domain, extracted_name = extract_sender_info(text)
        sender_email = from_email or extracted_email
        sender_domain = extracted_domain or (sender_email.split('@')[1] if sender_email and '@' in sender_email else None)

        # Truncate text if too long (OpenAI token limit)
        max_chars = 8000
        truncated_text = text[:max_chars] if len(text) > max_chars else text

        # Call OpenAI
        response = openai.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": EMAIL_SUMMARY_SYS_PROMPT},
                {"role": "user", "content": EMAIL_SUMMARY_PROMPT.format(email_text=truncated_text)}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            timeout=30.0
        )

        content = response.choices[0].message.content
        if not content:
            raise Exception("Empty response from AI service")

        result = json.loads(content)

        # Build response with sender info
        return {
            'summary': result.get('summary'),
            'category': result.get('category', 'other'),
            'priority_score': result.get('priority', 5),
            'action_required': result.get('action_required', False),
            'action_description': result.get('action_description'),
            'sender_email': sender_email,
            'sender_domain': sender_domain,
            'sender_name': result.get('sender_name') or extracted_name,
        }

    except Exception as e:
        logger.error(f"Email summarization error: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise Exception(f"Failed to summarize email: {str(e)}")


def save_email_summary(user_id: int, text_input_id: int, text: str, from_email: str = None,
                       subject: str = None) -> Optional[EmailSummary]:
    """
    Summarize an email and save to database.

    Args:
        user_id: User ID
        text_input_id: TextInput ID
        text: Email text content
        from_email: Optional pre-extracted sender email
        subject: Optional email subject

    Returns:
        EmailSummary object or None on failure
    """
    try:
        # Get summary
        summary_data = summarize_email(text, from_email)

        # Create EmailSummary record
        email_summary = EmailSummary(
            user_id=user_id,
            text_input_id=text_input_id,
            sender_email=summary_data.get('sender_email'),
            sender_domain=summary_data.get('sender_domain'),
            sender_name=summary_data.get('sender_name'),
            summary=summary_data.get('summary'),
            category=summary_data.get('category'),
            priority_score=summary_data.get('priority_score'),
            action_required=summary_data.get('action_required', False),
            action_description=summary_data.get('action_description'),
            email_subject=subject,
        )

        db.session.add(email_summary)

        # Update sender pattern
        update_sender_pattern(
            user_id=user_id,
            sender_email=summary_data.get('sender_email'),
            sender_name=summary_data.get('sender_name'),
            sender_domain=summary_data.get('sender_domain'),
            category=summary_data.get('category'),
            priority_score=summary_data.get('priority_score'),
            action_required=summary_data.get('action_required', False)
        )

        db.session.commit()
        logger.info(f"Saved email summary for text_input_id={text_input_id}, category={summary_data.get('category')}")

        return email_summary

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to save email summary: {str(e)}")
        sentry_sdk.capture_exception(e)
        return None


def update_sender_pattern(user_id: int, sender_email: str, sender_name: str = None,
                          sender_domain: str = None, category: str = None,
                          priority_score: int = None, action_required: bool = False) -> Optional[SenderPattern]:
    """
    Update or create sender pattern for tracking.

    Args:
        user_id: User ID
        sender_email: Sender email address
        sender_name: Sender name
        sender_domain: Sender domain
        category: Email category
        priority_score: Priority score (1-10)
        action_required: Whether action was required

    Returns:
        SenderPattern object or None on failure
    """
    if not sender_email:
        return None

    try:
        # Find existing pattern or create new
        pattern = SenderPattern.query.filter_by(
            user_id=user_id,
            sender_email=sender_email
        ).first()

        now = datetime.utcnow()

        if pattern:
            # Update existing pattern
            pattern.email_count += 1
            pattern.last_email_date = now

            # Update category if provided (use most recent)
            if category:
                pattern.category = category

            # Update sender name if provided and not set
            if sender_name and not pattern.sender_name:
                pattern.sender_name = sender_name

            # Update average priority
            if priority_score is not None:
                if pattern.avg_priority_score:
                    pattern.avg_priority_score = (
                        (pattern.avg_priority_score * (pattern.email_count - 1) + priority_score)
                        / pattern.email_count
                    )
                else:
                    pattern.avg_priority_score = float(priority_score)

            # Track actions required
            if action_required:
                pattern.total_actions_required += 1

            pattern.updated_at = now

        else:
            # Create new pattern
            pattern = SenderPattern(
                user_id=user_id,
                sender_email=sender_email,
                sender_name=sender_name,
                sender_domain=sender_domain or (sender_email.split('@')[1] if '@' in sender_email else None),
                category=category,
                email_count=1,
                first_email_date=now,
                last_email_date=now,
                avg_priority_score=float(priority_score) if priority_score else None,
                total_actions_required=1 if action_required else 0,
            )
            db.session.add(pattern)

        logger.info(f"Updated sender pattern for {sender_email}, count={pattern.email_count}")
        return pattern

    except Exception as e:
        logger.error(f"Failed to update sender pattern: {str(e)}")
        sentry_sdk.capture_exception(e)
        return None


def get_sender_patterns_by_category(user_id: int, category: str = None) -> list:
    """
    Get sender patterns for a user, optionally filtered by category.

    Args:
        user_id: User ID
        category: Optional category filter

    Returns:
        List of SenderPattern dictionaries
    """
    query = SenderPattern.query.filter_by(user_id=user_id)

    if category:
        query = query.filter_by(category=category)

    patterns = query.order_by(SenderPattern.email_count.desc()).all()
    return [p.to_dict() for p in patterns]


def get_high_priority_senders(user_id: int, min_avg_priority: float = 7.0) -> list:
    """
    Get senders with high average priority scores.

    Args:
        user_id: User ID
        min_avg_priority: Minimum average priority score

    Returns:
        List of SenderPattern dictionaries
    """
    patterns = SenderPattern.query.filter(
        SenderPattern.user_id == user_id,
        SenderPattern.avg_priority_score >= min_avg_priority
    ).order_by(SenderPattern.avg_priority_score.desc()).all()

    return [p.to_dict() for p in patterns]
