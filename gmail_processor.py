import logging
import json
from datetime import datetime
from typing import List, Dict, Optional
from models import User, Event, UserEmail, TextInput
from helpers.event_processing import process_text_to_events
from helpers.event_utils import format_event_for_api
from helpers.domain_utils import get_base_url
from app import db
from gmail_service import gmail_service
import sentry_sdk

logger = logging.getLogger(__name__)

def check_new_emails():
    """
    Main function to check for new emails from Gmail.
    Replaces the Mailgun webhook functionality.
    """
    try:
        logger.info("=" * 80)
        logger.info("GMAIL EMAIL CHECK - Starting email polling")
        logger.info("=" * 80)
        
        # Get unread emails from Gmail
        emails = gmail_service.get_unread_emails(max_results=50)
        
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
        
    except Exception as e:
        logger.error(f"Error in Gmail email check: {str(e)}")
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
        
        if not sender_email or not body_text.strip():
            logger.warning(f"Missing sender or email content: sender={sender_email}")
            return False
        
        logger.info(f"Processing email from {sender_email}, subject: {subject}")
        
        # Download attachment content (similar to Mailgun webhook logic)
        attachments_data = []
        
        if attachments_info:
            logger.info(f"🔍 DETECTED {len(attachments_info)} attachments from Gmail from {sender_email}")
            
            # Download each attachment from Gmail
            for attachment_info in attachments_info:
                try:
                    attachment_id = attachment_info.get('attachment_id')
                    message_id = attachment_info.get('message_id')
                    filename = attachment_info.get('name', 'unknown')
                    
                    if attachment_id and message_id:
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
        formatted_text = f"From: {sender_email}\nSubject: {subject}\n\n{body_text}"
        
        # Check if sender is an existing user (reuse existing logic)
        user = User.query.filter_by(email=sender_email).first()
        
        # If not found, check additional emails
        if not user:
            user_email = UserEmail.query.filter_by(email=sender_email).first()
            if user_email:
                user = user_email.user
        
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
        # Auto-sync only if user has google_id
        auto_sync = user.google_id is not None
        
        result = process_text_to_events(
            formatted_text, 
            user, 
            source_type="email", 
            auto_sync=auto_sync
        )
        
        # Process attachments if present and include events in totals
        total_attachment_events = 0
        total_attachment_synced = 0
        
        if attachments_data:
            # Import here to avoid circular dependency
            from attachment_processor import attachment_processor
            
            text_input = result.get('text_input')
            if text_input:
                logger.info(f"🔄 PROCESSING {len(attachments_data)} attachments for existing user {user.id}")
                processed_attachments = attachment_processor.process_email_attachments(
                    text_input, attachments_data
                )
                logger.info(f"✅ COMPLETED processing {len(processed_attachments)} attachments for user {user.id}")
                
                # Count events from attachments
                for attachment in processed_attachments:
                    if attachment and hasattr(attachment, 'extracted_events_count'):
                        attachment_events = attachment.extracted_events_count or 0
                        total_attachment_events += attachment_events
                        
                        # Count synced events from this attachment
                        attachment_synced_events = Event.query.filter_by(
                            user_id=user.id,
                            text_input_id=text_input.id,
                            is_synced=True
                        ).filter(
                            Event.extracted_at >= attachment.created_at
                        ).count()
                        total_attachment_synced += attachment_synced_events
                
                if total_attachment_events > 0:
                    logger.info(f"📅 EXTRACTED {total_attachment_events} events from attachments, {total_attachment_synced} synced")
            else:
                logger.error("❌ No text_input found for attachment processing")
        
        # Calculate total events and synced counts
        email_events_count = len(result['events'])
        email_synced_count = result['synced_count']
        
        total_events_count = email_events_count + total_attachment_events
        total_synced_count = email_synced_count + total_attachment_synced
        
        logger.info(f"📊 TOTAL PROCESSING SUMMARY for user {user.id}: {email_events_count} email events + {total_attachment_events} attachment events = {total_events_count} total events, {total_synced_count} synced")
        
        # Send confirmation email with total counts (reuse existing function)
        send_confirmation_email(sender_email, total_events_count, total_synced_count)
        
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