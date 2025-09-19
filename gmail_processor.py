import logging
import json
from datetime import datetime
from typing import List, Dict, Optional
from models import User, Event, UserEmail, TextInput
from helpers.event_processing import process_text_to_events
from helpers.event_utils import format_event_for_api
from helpers.domain_utils import get_base_url
from helpers.event_deduplication import deduplicate_events, should_skip_attachment
from app import db
from gmail_service import gmail_service
import sentry_sdk

logger = logging.getLogger(__name__)

def check_new_emails():
    """
    Main function to check for new emails from Gmail.
    Optimized for 5-minute polling intervals.
    """
    start_time = datetime.utcnow()
    try:
        logger.info("=" * 80)
        logger.info("GMAIL EMAIL CHECK - Starting email polling")
        logger.info("=" * 80)
        
        # Limit to 10 emails max for 5-minute intervals (prevents timeouts)
        emails = gmail_service.get_unread_emails(max_results=10)
        
        if not emails:
            logger.info("No new emails to process")
            return
        
        logger.info(f"Processing {len(emails)} new emails")
        
        # Process each email
        processed_count = 0
        for email_data in emails:
            try:
                success = process_single_email(email_data)
                if success:
                    processed_count += 1
                    # Mark as read after successful processing
                    gmail_service.mark_as_read(email_data['id'])
                else:
                    logger.warning(f"Failed to process email {email_data['id']}")
            except Exception as e:
                logger.error(f"Error processing email {email_data['id']}: {str(e)}")
                sentry_sdk.capture_exception(e)
                continue
        
        logger.info(f"Successfully processed {processed_count}/{len(emails)} emails")
        
        # Performance monitoring for 5-minute intervals
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        logger.info(f"⏱️ Email check completed in {duration:.2f} seconds")
        
        # Warn if taking too long for 5-minute intervals
        if duration > 120:  # 2 minutes
            logger.warning(f"⚠️ Email check took {duration:.2f}s - consider optimization for 5-min intervals")
        
    except Exception as e:
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        logger.error(f"Error in Gmail email check after {duration:.2f}s: {str(e)}")
        sentry_sdk.capture_exception(e)

def process_single_email(email_data: Dict) -> bool:
    """
    Process a single email from Gmail.
    Reuses most of the logic from mailgun_webhook.py
    
    Args:
        email_data (Dict): Email data from Gmail API
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Extract email data (already parsed by Gmail service)
        sender_email = email_data.get('sender', '').lower().strip()
        recipient = email_data.get('recipient', '')
        subject = email_data.get('subject', '')
        body_text = email_data.get('stripped-text', '')
        attachments_info = email_data.get('attachments', [])
        
        if not sender_email:
            logger.warning(f"Missing sender email")
            return False
        
        # Allow processing even without body text if there are attachments or subject
        if not body_text.strip() and not attachments_info and not subject.strip():
            logger.warning(f"Email has no content (no body, subject, or attachments): sender={sender_email}")
            return False
        
        logger.info(f"Processing email from {sender_email}, subject: {subject}")
        
        # Download attachment content with filtering for signature images
        attachments_data = []
        
        if attachments_info:
            logger.info(f"🔍 DETECTED {len(attachments_info)} attachments from Gmail from {sender_email}")
            
            # Download each attachment from Gmail (with filtering)
            for attachment_info in attachments_info:
                try:
                    attachment_id = attachment_info.get('attachment_id')
                    message_id = attachment_info.get('message_id')
                    filename = attachment_info.get('name', 'unknown')
                    
                    if attachment_id and message_id:
                        # Check if we should skip this attachment (signature/logo images)
                        content_type = attachment_info.get('content-type', 'application/octet-stream')
                        estimated_size = attachment_info.get('size', 0)
                        
                        if should_skip_attachment(filename, content_type, estimated_size):
                            continue
                        
                        logger.info(f"🔗 Attempting to download attachment: {filename}")
                        
                        # Download attachment content from Gmail
                        attachment_content = gmail_service.download_attachment(message_id, attachment_id)
                        
                        if attachment_content:
                            attachment_data = {
                                'name': filename,
                                'content-type': attachment_info.get('content-type', 'application/octet-stream'),
                                'size': len(attachment_content),
                                'content': attachment_content
                            }
                            attachments_data.append(attachment_data)
                            logger.info(f"📎 Downloaded attachment: {attachment_data['name']} ({attachment_data['content-type']}, {attachment_data['size']} bytes)")
                        else:
                            logger.error(f"❌ Failed to download attachment: {filename}")
                    else:
                        logger.error(f"❌ Missing attachment or message ID for: {filename}")
                        
                except Exception as e:
                    logger.error(f"❌ Error downloading attachment {attachment_info.get('name', 'unknown')}: {str(e)}")
                    continue
        else:
            logger.info(f"📧 No attachments found in Gmail email from {sender_email}")
        
        # Process text to events using existing helper function
        # Use subject as content if no body text available
        email_content = body_text if body_text.strip() else f"Email subject: {subject}"
        formatted_text = f"From: {sender_email}\nSubject: {subject}\n\n{email_content}"
        
        # Optimized user lookup with join (single query instead of two)
        user = db.session.query(User).filter_by(email=sender_email).first()
        if not user:
            # Check additional emails with join to avoid multiple queries
            user = db.session.query(User).join(UserEmail).filter(UserEmail.email == sender_email).first()
        
        if user:
            # Check if email was found via UserEmail lookup
            user_email = UserEmail.query.filter_by(email=sender_email).first()
            is_additional_email = user_email is not None
            
            # If found via UserEmail or has google_id, treat as existing user
            if is_additional_email or user.google_id is not None:
                # This is an existing user - process and send confirmation
                return process_existing_user_email(
                    formatted_text, attachments_data, user, sender_email, subject
                )
            else:
                # This is a temp user - send signup email
                return process_temp_user_email(
                    formatted_text, attachments_data, user, sender_email, subject
                )
        else:
            # SECURITY: Ignore emails from non-users to prevent unauthorized usage
            logger.info(f"🚫 Ignoring email from non-user: {sender_email} (not in user database)")
            return True  # Mark as "processed" but don't actually process
            
    except Exception as e:
        logger.error(f"Error processing single email: {str(e)}")
        sentry_sdk.capture_exception(e)
        return False

def process_existing_user_email(formatted_text: str, attachments_data: List[Dict], 
                               user: User, sender_email: str, subject: str) -> bool:
    """Process email for existing user with Google authentication"""
    try:
        # Disable auto-sync for now - we'll sync all events together after deduplication
        auto_sync = False
        
        # Process email body text (no auto-sync)
        result = process_text_to_events(
            formatted_text, 
            user, 
            source_type="email", 
            auto_sync=auto_sync
        )
        
        email_events = result.get('events', [])
        text_input = result.get('text_input')
        
        # Collect all events from email body and attachments
        all_events = list(email_events)  # Start with email events
        
        # Process attachments if present (no auto-sync)
        if attachments_data and text_input:
            # Import here to avoid circular dependency
            from attachment_processor import attachment_processor
            
            logger.info(f"🔄 PROCESSING {len(attachments_data)} attachments for existing user {user.id} (no auto-sync)")
            processed_attachments = attachment_processor.process_email_attachments(
                text_input, attachments_data, auto_sync=False
            )
            logger.info(f"✅ COMPLETED processing {len(processed_attachments)} attachments for user {user.id}")
            
            # Collect events from all attachments
            for attachment in processed_attachments:
                if attachment and hasattr(attachment, 'id'):
                    # Get events created from this attachment
                    attachment_events = Event.query.filter_by(
                        user_id=user.id,
                        text_input_id=text_input.id
                    ).filter(
                        Event.extracted_at >= attachment.created_at
                    ).all()
                    all_events.extend(attachment_events)
        
        # Now deduplicate all events (email + attachments)
        logger.info(f"🔄 Starting deduplication: {len(all_events)} total events found")
        unique_events = deduplicate_events(all_events, user.id, text_input.id if text_input else 0)
        
        # Now sync all unique events if user has Google authentication
        synced_count = 0
        if user.google_id and unique_events:
            from google_calendar import create_calendar_event
            from helpers.event_utils import prepare_event_data_for_calendar
            
            logger.info(f"🔄 Starting centralized sync for {len(unique_events)} unique events")
            
            for event in unique_events:
                try:
                    if event.is_synced and event.google_event_id:
                        synced_count += 1
                        continue
                    
                    # Prepare and sync event
                    event_data = prepare_event_data_for_calendar(event)
                    google_event_id = create_calendar_event(user, event_data)
                    
                    if google_event_id:
                        event.google_event_id = google_event_id
                        event.is_synced = True
                        synced_count += 1
                        logger.info(f"✅ Synced unique event: {event.event_name}")
                        
                except Exception as sync_error:
                    logger.error(f"❌ Error syncing event '{event.event_name}': {str(sync_error)}")
                    continue
            
            # Commit sync updates
            db.session.commit()
        
        # Calculate final counts
        total_events_count = len(unique_events)
        
        logger.info(f"📊 FINAL PROCESSING SUMMARY for user {user.id}: {total_events_count} unique events extracted, {synced_count} synced")
        
        # Send confirmation email with total counts (reuse existing function)
        send_confirmation_email(sender_email, total_events_count, synced_count)
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing email for existing user {sender_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        return False

def process_temp_user_email(formatted_text: str, attachments_data: List[Dict], 
                           user: User, sender_email: str, subject: str) -> bool:
    """Process email for temp user (no Google authentication)"""
    try:
        result = process_text_to_events(
            formatted_text, 
            user, 
            source_type="email", 
            auto_sync=False  # Don't auto-sync for temp users
        )
        
        # Process attachments if present
        if attachments_data:
            from attachment_processor import attachment_processor
            
            text_input = result.get('text_input')
            if text_input:
                logger.info(f"🔄 PROCESSING {len(attachments_data)} attachments for temp user {user.id}")
                processed_attachments = attachment_processor.process_email_attachments(
                    text_input, attachments_data
                )
                logger.info(f"✅ COMPLETED processing {len(processed_attachments)} attachments for temp user {user.id}")
        
        # Send signup email with extracted events (reuse existing function)
        send_signup_email_with_events(sender_email, result['events'], subject)
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing email for temp user {sender_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        return False

def process_new_user_email(formatted_text: str, attachments_data: List[Dict], 
                          sender_email: str, subject: str) -> bool:
    """Process email for new user (create temp user)"""
    try:
        # Create temporary user
        temp_user = User()
        temp_user.email = sender_email
        temp_user.username = sender_email.split('@')[0]
        temp_user.is_temporary = True
        temp_user.timezone = 'UTC'
        
        db.session.add(temp_user)
        db.session.commit()
        
        logger.info(f"Created temporary user for {sender_email}")
        
        # Process the email for this new temp user
        return process_temp_user_email(formatted_text, attachments_data, temp_user, sender_email, subject)
        
    except Exception as e:
        logger.error(f"Error creating new user for {sender_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        db.session.rollback()
        return False

def send_signup_email_with_events(recipient_email: str, events_data: List, original_subject: str = ""):
    """
    Send email to new user with extracted events and signup link.
    Note: This now just logs instead of actually sending email since we're removing Mailgun send functionality.
    You may want to integrate with a different email service for sending.
    """
    try:
        logger.info(f"📧 Would send signup email to {recipient_email} with {len(events_data)} events")
        logger.info(f"📧 Events found: {[event.get('event_name', 'Unnamed') for event in events_data]}")
        
        # TODO: Integrate with your preferred email sending service here
        # For now, just log the signup invitation
        base_url = get_base_url()
        signup_url = f"{base_url}/google_login?email={recipient_email}"
        logger.info(f"📧 Signup URL for {recipient_email}: {signup_url}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error preparing signup email for {recipient_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        return False

def send_confirmation_email(recipient_email: str, events_count: int, synced_count: int):
    """
    Send confirmation email to existing user after processing.
    Note: This now just logs instead of actually sending email since we're removing Mailgun send functionality.
    You may want to integrate with a different email service for sending.
    """
    try:
        logger.info(f"📧 Would send confirmation email to {recipient_email}: {events_count} events processed, {synced_count} synced")
        
        # TODO: Integrate with your preferred email sending service here
        # For now, just log the confirmation
        base_url = get_base_url()
        dashboard_url = f"{base_url}/dashboard"
        logger.info(f"📧 Dashboard URL for {recipient_email}: {dashboard_url}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error preparing confirmation email for {recipient_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        return False