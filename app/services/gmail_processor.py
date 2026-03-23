import logging
import json
import base64
from datetime import datetime
from typing import List, Dict, Optional
from app.models import User, Event, UserEmail, TextInput, MeetingRequest, MeetingMessage
from app.services.event_processing import process_text_to_events
from app.helpers.event_utils import format_event_for_api
from app.helpers.domain_utils import get_base_url
from app.helpers.event_deduplication import deduplicate_events, should_skip_attachment
from app import db
from app.services.gmail_service import gmail_service, GmailOAuthError
from app.services.users import assign_unique_handle
from app.agents.task_classifier import classify_email_task, ASSISTANT_EMAILS
from app.services.scheduling_agent import handle_scheduling_email
import sentry_sdk

logger = logging.getLogger(__name__)

def check_new_emails():
    """
    Main function to check for new emails from Gmail.
    Optimized for 5-minute polling intervals.

    Not used anymore - replaced by pub/sub webhook processing.
    """
    start_time = datetime.utcnow()
    try:
        logger.info("=" * 80)
        logger.info("GMAIL EMAIL CHECK - Starting email polling")
        logger.info("=" * 80)
        
        # Limit to 10 emails max for 5-minute intervals (prevents timeouts)
        emails = gmail_service.get_unread_emails(max_results=5)
        
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
        
    except GmailOAuthError as e:
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        logger.error(f"Gmail OAuth error in email check after {duration:.2f}s: {str(e)}")
        sentry_sdk.capture_exception(e)
        # Re-raise OAuth errors so webhook endpoint can return error status
        raise
    except Exception as e:
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        logger.error(f"Error in Gmail email check after {duration:.2f}s: {str(e)}")
        sentry_sdk.capture_exception(e)

def find_meeting_owner_by_thread(thread_id: Optional[str]) -> Optional[User]:
    if not thread_id:
        return None

    meeting_request = (
        MeetingRequest.query.join(MeetingMessage)
        .filter(MeetingMessage.thread_id == thread_id)
        .order_by(MeetingRequest.created_at.desc())
        .first()
    )
    if meeting_request:
        return meeting_request.user
    return None


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

        message_id = email_data.get("message_id")
        if sender_email in ASSISTANT_EMAILS:
            logger.info("Skipping assistant-sent message %s", message_id)
            return True

        if message_id:
            existing_message = MeetingMessage.query.filter_by(message_id=message_id).first()
            if existing_message:
                logger.info("Skipping already processed message %s", message_id)
                return True
        
        # Allow processing even without body text if there are attachments or subject
        if not body_text.strip() and not attachments_info and not subject.strip():
            logger.warning(f"Email has no content (no body, subject, or attachments): sender={sender_email}")
            return False
        
        logger.info(f"Processing email from {sender_email}, subject: {subject}")

        # Determine desired workflow (event extraction vs scheduling)
        classification_payload = {
            "subject": subject,
            "body_text": body_text,
            "from": sender_email,
            "to": email_data.get("to") or [],
            "cc": email_data.get("cc") or [],
            "has_attachments": bool(attachments_info),
        }
        task_type = classify_email_task(classification_payload)
        logger.info(f"Classifier routed email {email_data.get('id')} to {task_type}")

        thread_id = email_data.get("thread_id")
        existing_owner = find_meeting_owner_by_thread(thread_id)

        user = db.session.query(User).filter_by(email=sender_email).first()

        if existing_owner:
            scheduling_payload = {
                "sender": email_data.get("sender"),
                "sender_name": email_data.get("sender_name"),
                "subject": subject,
                "body_text": body_text,
                "body_html": email_data.get("body_html"),
                "to": email_data.get("to") or [],
                "cc": email_data.get("cc") or [],
                "thread_id": thread_id,
                "message_id": email_data.get("message_id"),
                "received_at": email_data.get("received_at"),
                "raw_headers": email_data.get("raw_headers"),
                "attachments": attachments_info,
            }
            result = handle_scheduling_email(scheduling_payload, owner_user=existing_owner)
            return result is not None

        # Check if there's an authenticated user in TO or CC (even without existing thread)
        # This handles cases where a provisional user cc's an authenticated user
        # Priority: sender first (they're initiating), then recipients
        authenticated_owner = None

        # First check if sender is authenticated
        if sender_email and sender_email not in ASSISTANT_EMAILS:
            potential_sender = db.session.query(User).filter_by(email=sender_email).first()
            if potential_sender and potential_sender.google_id:
                authenticated_owner = potential_sender
                logger.info(
                    f"Sender {sender_email} is authenticated. Using sender as owner for scheduling."
                )

        # If sender not authenticated, check recipients
        if not authenticated_owner:
            for recipient in (email_data.get("to") or []) + (email_data.get("cc") or []):
                recipient_email = recipient.strip().lower() if isinstance(recipient, str) else recipient
                if recipient_email and recipient_email not in ASSISTANT_EMAILS:
                    potential_owner = db.session.query(User).filter_by(email=recipient_email).first()
                    if potential_owner and potential_owner.google_id:
                        authenticated_owner = potential_owner
                        break

        if authenticated_owner:
            # Only route to scheduling if it's NOT an event extraction task
            if task_type == "extract_event":
                logger.info(
                    f"Authenticated user {authenticated_owner.email} found, but task is 'extract_event'. "
                    "Skipping scheduling flow to proceed with event extraction."
                )
            else:
                # Route to scheduling flow with authenticated owner, skip provisional user limits
                logger.info(
                    f"Found authenticated user {authenticated_owner.email} in recipients. "
                    f"Routing to scheduling flow for owner, bypassing provisional user limits for sender {sender_email}"
                )
                scheduling_payload = {
                    "sender": email_data.get("sender"),
                    "sender_name": email_data.get("sender_name"),
                    "subject": subject,
                    "body_text": body_text,
                    "body_html": email_data.get("body_html"),
                    "to": email_data.get("to") or [],
                    "cc": email_data.get("cc") or [],
                    "thread_id": thread_id,
                    "message_id": email_data.get("message_id"),
                    "received_at": email_data.get("received_at"),
                    "raw_headers": email_data.get("raw_headers"),
                    "attachments": attachments_info,
                }
                result = handle_scheduling_email(scheduling_payload, owner_user=authenticated_owner)
                return result is not None

        if task_type == "schedule_meeting" or (task_type == "no_action" and (not user or user.google_id is None)):
            if not user:
                user = ensure_provisional_user(sender_email)

            if user.google_id is None:
                handle_provisional_scheduler_user(user)
                return True

            scheduling_payload = {
                "sender": email_data.get("sender"),
                "sender_name": email_data.get("sender_name"),
                "subject": subject,
                "body_text": body_text,
                "body_html": email_data.get("body_html"),
                "to": email_data.get("to") or [],
                "cc": email_data.get("cc") or [],
                "thread_id": email_data.get("thread_id"),
                "message_id": email_data.get("message_id"),
                "received_at": email_data.get("received_at"),
                "raw_headers": email_data.get("raw_headers"),
                "attachments": attachments_info,
            }
            result = handle_scheduling_email(scheduling_payload, owner_user=user)
            return result is not None
        elif task_type == "no_action":
            logger.info("No action taken for email %s; sending courtesy reply.", email_data.get("id"))
            auto_reply = (
                "Hi there,\n\n"
                "I've only been trained to schedule meetings and create calendar events. "
                "No action has been taken on this email.\n\n"
                "Thanks!\nCal"
            )
            if sender_email:
                subject_prefix = subject or ""
                if subject_prefix.lower().startswith("re:"):
                    reply_subject = subject_prefix
                else:
                    reply_subject = f"Re: {subject_prefix}".strip() or "Re: Message from Cal Autobot"
                try:
                    gmail_service.send_email(
                        sender_email,
                        reply_subject,
                        text_body=auto_reply,
                        thread_id=email_data.get("thread_id"),
                        reply_to_message_id=email_data.get("message_id"),
                    )
                except Exception as send_err:
                    logger.warning("Failed to send no-action reply to %s: %s", sender_email, send_err)
            else:
                logger.info("No sender email found; skipping courtesy reply.")
            return True
        
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
                        
                        # Use inline data if available, otherwise download from Gmail
                        if attachment_info.get('data'):
                            attachment_content = base64.urlsafe_b64decode(attachment_info['data'].encode('UTF-8'))
                            logger.info(f"📎 Used inline attachment data for: {filename}")
                        else:
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
            # Check if this is a real user (has google_id) or provisional user (no google_id)
            if user.google_id:
                # Real authenticated user - process normally
                existing_result = process_existing_user_email(
                    formatted_text, attachments_data, user, sender_email, subject
                )
                if existing_result["success"] and existing_result["events_count"] == 0:
                    send_no_events_response(email_data, sender_email)
                return existing_result["success"]
            else:
                # Provisional user - check email limit
                if user.email_count >= 2:
                    # Hit limit - send limit reached email
                    logger.info(f"📧 Provisional user {sender_email} hit 2-email limit")
                    send_limit_reached_email(sender_email)
                    return True
                else:
                    # Under limit - process and increment count
                    user.email_count += 1
                    db.session.commit()
                    logger.info(f"📧 Processing email {user.email_count}/2 for provisional user {sender_email}")
                    provisional_result = process_provisional_user_email(
                        formatted_text, attachments_data, user, sender_email, subject
                    )
                    if provisional_result["success"] and provisional_result["events_count"] == 0:
                        send_no_events_response(email_data, sender_email)
                    return provisional_result["success"]
        else:
            # New user - create provisional user
            logger.info(f"📧 Creating new provisional user for {sender_email}")
            provisional_result = process_new_provisional_user_email(
                formatted_text, attachments_data, sender_email, subject
            )
            if provisional_result["success"] and provisional_result["events_count"] == 0:
                send_no_events_response(email_data, sender_email)
            return provisional_result["success"]
            
    except Exception as e:
        logger.error(f"Error processing single email: {str(e)}")
        sentry_sdk.capture_exception(e)
        return False

def process_existing_user_email(formatted_text: str, attachments_data: List[Dict], 
                               user: User, sender_email: str, subject: str) -> Dict[str, object]:
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
            from app.services.attachment_processor import attachment_processor
            
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
            from app.services.google_calendar import create_calendar_event
            from app.helpers.event_utils import prepare_event_data_for_calendar
            
            logger.info(f"🔄 Starting centralized sync for {len(unique_events)} unique events")
            
            for event in unique_events:
                try:
                    if event.is_synced and event.google_event_id:
                        synced_count += 1
                        continue
                    
                    # Prepare and sync event
                    event_data = prepare_event_data_for_calendar(event)
                    google_event_id = create_calendar_event(user, event_data, use_extraction_calendar=True)
                    
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
        
        return {"success": True, "events_count": total_events_count}
        
    except Exception as e:
        logger.error(f"Error processing email for existing user {sender_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        return {"success": False, "events_count": 0}

def process_provisional_user_email(formatted_text: str, attachments_data: List[Dict], 
                                  user: User, sender_email: str, subject: str) -> Dict[str, object]:
    """Process email for provisional user (no Google authentication yet)"""
    try:
        if not user.handle:
            assign_unique_handle(user, sender_email or user.username or user.email or "user")
            db.session.commit()

        result = process_text_to_events(
            formatted_text, 
            user, 
            source_type="email", 
            auto_sync=False  # Don't auto-sync for provisional users
        )
        
        email_events = result.get('events', [])
        text_input = result.get('text_input')
        
        # Collect all events from email body and attachments
        all_events = list(email_events)  # Start with email events
        
        # Process attachments if present
        if attachments_data and text_input:
            from app.services.attachment_processor import attachment_processor
            
            logger.info(f"🔄 PROCESSING {len(attachments_data)} attachments for provisional user {user.id}")
            processed_attachments = attachment_processor.process_email_attachments(
                text_input, attachments_data, auto_sync=False
            )
            logger.info(f"✅ COMPLETED processing {len(processed_attachments)} attachments for provisional user {user.id}")
            
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
        
        events_count = len(all_events)

        # Send provisional summary email only when we actually found events to share
        if events_count > 0:
            send_provisional_summary_email(sender_email, all_events)
        
        return {"success": True, "events_count": events_count}
        
    except Exception as e:
        logger.error(f"Error processing email for provisional user {sender_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        return {"success": False, "events_count": 0}

def process_new_provisional_user_email(formatted_text: str, attachments_data: List[Dict], 
                                       sender_email: str, subject: str) -> Dict[str, object]:
    """Process email for new provisional user (create provisional user)"""
    try:
        # Create provisional user
        new_user = User()
        new_user.email = sender_email
        new_user.username = sender_email
        new_user.google_id = None  # No Google auth yet
        new_user.email_count = 1  # First email
        new_user.timezone = 'UTC'
        
        db.session.add(new_user)
        assign_unique_handle(new_user, sender_email)
        db.session.commit()
        
        logger.info(f"✅ Created provisional user for {sender_email}")
        
        # Process the email for this new provisional user
        return process_provisional_user_email(formatted_text, attachments_data, new_user, sender_email, subject)
        
    except Exception as e:
        logger.error(f"Error creating provisional user for {sender_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        db.session.rollback()
        return {"success": False, "events_count": 0}

def send_provisional_summary_email(recipient_email: str, events_data: List):
    """Send email to provisional user with extracted events and signup link"""
    try:
        from flask import render_template
        
        base_url = get_base_url()
        signup_url = f"{base_url}/signup"
        
        # Render email template
        html_body = render_template(
            'emails/provisional_summary.html',
            events=events_data,
            signup_url=signup_url
        )
        
        subject = f"✅ We found {len(events_data)} event{'s' if len(events_data) != 1 else ''} in your email!"
        
        # Send email using Gmail service
        success = gmail_service.send_email(
            to=recipient_email,
            subject=subject,
            html_body=html_body
        )
        
        if success:
            logger.info(f"📧 Sent provisional summary email to {recipient_email} with {len(events_data)} events")
        else:
            logger.error(f"❌ Failed to send provisional summary email to {recipient_email}")
        
        return success
        
    except Exception as e:
        logger.error(f"Error sending provisional summary email to {recipient_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        return False

def send_provisional_scheduler_email(recipient_email: str):
    """Send onboarding email to provisional user requesting meeting scheduling."""
    try:
        from flask import render_template

        signup_url = f"{get_base_url()}/signup"
        html_body = render_template(
            'emails/provisional_scheduler.html',
            signup_url=signup_url,
        )

        subject = "✨ Unlock Cal's meeting coordination assistant"
        success = gmail_service.send_email(
            to=recipient_email,
            subject=subject,
            html_body=html_body,
        )
        if success:
            logger.info("📧 Sent scheduler onboarding email to %s", recipient_email)
        else:
            logger.error("❌ Failed to send scheduler onboarding email to %s", recipient_email)
        return success
    except Exception as exc:
        logger.error("Error sending scheduler onboarding email to %s: %s", recipient_email, exc)
        sentry_sdk.capture_exception(exc)
        return False

def send_limit_reached_email(recipient_email: str):
    """Send email to provisional user who hit the 2-email limit"""
    try:
        from flask import render_template
        
        base_url = get_base_url()
        signup_url = f"{base_url}/signup"
        
        # Render email template
        html_body = render_template('emails/limit_reached.html', signup_url=signup_url)
        
        subject = "⚠️ Email limit reached - Sign up to continue"
        
        # Send email using Gmail service
        success = gmail_service.send_email(
            to=recipient_email,
            subject=subject,
            html_body=html_body
        )
        
        if success:
            logger.info(f"📧 Sent limit reached email to {recipient_email}")
        else:
            logger.error(f"❌ Failed to send limit reached email to {recipient_email}")
        
        return success
        
    except Exception as e:
        logger.error(f"Error sending limit reached email to {recipient_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        return False

def send_confirmation_email(recipient_email: str, events_count: int, synced_count: int):
    """Send confirmation email to existing user after processing"""
    try:
        logger.info(f"📧 Confirmation: {recipient_email} - {events_count} events processed, {synced_count} synced")
        
        base_url = get_base_url()
        bookings_url = f"{base_url}/bookings"
        logger.info(f"📧 Bookings URL for {recipient_email}: {bookings_url}")
        
        # For now, just log - can add actual email template later if needed
        return True
        
    except Exception as e:
        logger.error(f"Error preparing confirmation email for {recipient_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        return False

def ensure_provisional_user(sender_email: str) -> User:
    """Create or retrieve a provisional user record for the sender."""
    user = db.session.query(User).filter_by(email=sender_email).first()
    if user:
        return user

    user = User()
    user.email = sender_email
    user.username = sender_email
    user.google_id = None
    user.email_count = 0
    user.timezone = 'UTC'

    db.session.add(user)
    db.session.commit()
    logger.info("✅ Created provisional user for scheduling: %s", sender_email)
    return user


def handle_provisional_scheduler_user(user: User) -> None:
    """Handle scheduling requests for provisional users (invite or limit notice)."""
    if user.email_count is None:
        user.email_count = 0

    if user.email_count >= 2:
        send_limit_reached_email(user.email)
        return

    user.email_count += 1
    db.session.commit()
    send_provisional_scheduler_email(user.email)


def send_no_events_response(email_data: Dict, recipient_email: str) -> None:
    """Reply to the email thread indicating no events were found."""
    if not recipient_email:
        return

    body = (
        "Hi there,\n\n"
        "I looked over your email but couldn't find any calendar events to create. "
        "If you want me to schedule a meeting for you, or you'd like me to capture a specific date/time, feel free to reply with more details.\n\n"
        "Thanks!\nCal"
    )

    subject = email_data.get("subject") or "Message from Cal Autobot"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}".strip()

    try:
        gmail_service.send_email(
            recipient_email,
            subject,
            text_body=body,
            thread_id=email_data.get("thread_id"),
            reply_to_message_id=email_data.get("message_id"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to send 'no events found' reply to %s: %s",
            recipient_email,
            exc,
        )
