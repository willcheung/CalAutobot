import os
import logging
import requests
import mimetypes
from typing import List, Dict, Optional, Tuple
from models import EmailAttachment, TextInput, User, Event
from app import db
from event_extractor import extract_events_from_text
import json
import base64

logger = logging.getLogger(__name__)

class AttachmentProcessor:
    """
    Process email attachments from Mailgun for event extraction.
    Uses Mailgun Email API to fetch stored emails and attachments.
    """
    
    SUPPORTED_FORMATS = {
        'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/bmp',
        'application/pdf', 'application/msword', 
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain', 'text/html'
    }
    
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit
    
    def __init__(self):
        self.mailgun_api_key = os.environ.get('MAILGUN_API_KEY')
        self.mailgun_domain = os.environ.get('MAILGUN_DOMAIN')
        self.mailgun_base_url = f"https://api.mailgun.net/v3/{self.mailgun_domain}"
    
    def process_email_attachments(self, text_input: TextInput, attachments_data: List[Dict]) -> List[EmailAttachment]:
        """
        Process all attachments from an email.
        
        Args:
            text_input (TextInput): The parent text input record
            attachments_data (List[Dict]): List of attachment metadata from Mailgun
        
        Returns:
            List[EmailAttachment]: List of processed attachment records
        """
        if not attachments_data:
            logger.info("No attachments to process")
            return []
        
        processed_attachments = []
        
        for attachment_data in attachments_data:
            try:
                attachment_record = self._process_single_attachment(text_input, attachment_data)
                if attachment_record:
                    processed_attachments.append(attachment_record)
            except Exception as e:
                logger.error(f"Error processing attachment {attachment_data.get('name', 'unknown')}: {str(e)}")
                continue
        
        return processed_attachments
    
    def _process_single_attachment(self, text_input: TextInput, attachment_data: Dict) -> Optional[EmailAttachment]:
        """
        Process a single attachment.
        
        Args:
            text_input (TextInput): Parent text input record
            attachment_data (Dict): Attachment metadata from Mailgun
        
        Returns:
            EmailAttachment: Processed attachment record or None if failed
        """
        filename = attachment_data.get('name', 'unknown')
        file_size = attachment_data.get('size', 0)
        content_type = attachment_data.get('content-type', 'application/octet-stream')
        file_content = attachment_data.get('content')
        
        logger.info(f"Processing attachment: {filename} ({content_type}, {file_size} bytes)")
        
        # Validate file
        if not self._validate_attachment(filename, file_size, content_type):
            logger.warning(f"Attachment validation failed: {filename}")
            return None
        
        if not file_content:
            logger.error(f"No file content provided for attachment: {filename}")
            return None
        
        # Create database record
        attachment_record = EmailAttachment()
        attachment_record.text_input_id = text_input.id
        attachment_record.filename = filename
        attachment_record.file_type = content_type
        attachment_record.file_size = file_size
        attachment_record.processing_status = 'pending'
        
        try:
            db.session.add(attachment_record)
            db.session.flush()  # Get the ID without committing
            
            # Process the attachment directly with content (base64 decode if needed)
            try:
                if isinstance(file_content, str):
                    # Base64 decode the content
                    file_content_bytes = base64.b64decode(file_content)
                else:
                    file_content_bytes = file_content
                    
                success = self._process_attachment_content(
                    attachment_record, file_content_bytes, text_input
                )
            except Exception as decode_error:
                logger.error(f"Failed to decode attachment content: {str(decode_error)}")
                success = False
            
            if success:
                attachment_record.processing_status = 'processed'
                logger.info(f"Successfully processed attachment: {filename}")
            else:
                attachment_record.processing_status = 'failed'
                logger.error(f"Failed to process attachment: {filename}")
            
            db.session.commit()
            return attachment_record
            
        except Exception as e:
            logger.error(f"Error processing attachment {filename}: {str(e)}")
            db.session.rollback()
            return None
    
    def _validate_attachment(self, filename: str, file_size: int, content_type: str) -> bool:
        """
        Validate attachment before processing.
        
        Args:
            filename (str): Original filename
            file_size (int): File size in bytes
            content_type (str): MIME type
        
        Returns:
            bool: True if valid, False otherwise
        """
        # Check file size
        if file_size > self.MAX_FILE_SIZE:
            logger.warning(f"File too large: {filename} ({file_size} bytes)")
            return False
        
        # Check content type
        if content_type not in self.SUPPORTED_FORMATS:
            logger.warning(f"Unsupported file type: {filename} ({content_type})")
            return False
        
        return True
    
    def _process_attachment_content(self, attachment_record: EmailAttachment, 
                                   file_content: bytes, text_input: TextInput) -> bool:
        """
        Process attachment content using the same workflow as email text processing.
        
        Args:
            attachment_record (EmailAttachment): Database record
            file_content (bytes): Actual file content
            text_input (TextInput): Parent text input
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            from helpers.event_processing import process_text_to_events
            
            logger.info(f"📥 PROCESSING attachment content: {attachment_record.filename} ({len(file_content)} bytes)")
            
            # Extract events using the same method as email text processing
            extracted_events = self._extract_events_from_attachment(
                file_content, attachment_record, text_input
            )
            
            if extracted_events:
                # Use the standard event processing workflow for extracted events
                # Create a temporary text representation for the attachment
                attachment_text = f"Events extracted from attachment: {attachment_record.filename}\n"
                attachment_text += f"File type: {attachment_record.file_type}\n"
                attachment_text += f"Size: {attachment_record.file_size} bytes\n"
                attachment_text += f"From email: {text_input.from_email or 'Unknown'}"
                
                # Check if user has Google authentication for auto-sync
                user = User.query.get(text_input.user_id)
                auto_sync = user.google_id is not None if user else False
                
                # Process events using the standard workflow - this handles:
                # - Event validation and cleaning
                # - Database storage 
                # - Auto-sync to Google Calendar (if enabled)
                # - All the same error handling and logging
                result = self._process_attachment_events(
                    extracted_events, attachment_record, text_input, auto_sync
                )
                
                attachment_record.extracted_events_count = len(result.get('events', []))
                logger.info(f"✅ PROCESSED {attachment_record.extracted_events_count} events from {attachment_record.filename} using standard workflow")
                
                return True
            else:
                logger.info(f"⚠️  No events extracted from {attachment_record.filename}")
                attachment_record.extracted_events_count = 0
                return True
                
        except Exception as e:
            logger.error(f"❌ Error processing attachment content: {str(e)}")
            return False
    
    def _process_attachment_events(self, extracted_events: List[Dict], 
                                 attachment_record: EmailAttachment, 
                                 text_input: TextInput, auto_sync: bool) -> Dict:
        """
        Process extracted events using the standard event processing workflow.
        
        Args:
            extracted_events (List[Dict]): Events extracted from attachment
            attachment_record (EmailAttachment): Attachment record
            text_input (TextInput): Parent text input
            auto_sync (bool): Whether to auto-sync to Google Calendar
        
        Returns:
            Dict: Processing results
        """
        from helpers.event_processing import process_text_to_events
        from event_extractor import validate_and_clean_event
        from datetime import datetime
        from app import db
        from models import Event
        from helpers.text_processing import sanitize_text_for_db
        from google_calendar import create_calendar_event
        
        user = User.query.get(text_input.user_id)
        created_events = []
        synced_count = 0
        
        logger.info(f"🔄 PROCESSING {len(extracted_events)} extracted events from attachment using standard workflow")
        
        try:
            # Process each extracted event using the same validation as email text
            for i, event_data in enumerate(extracted_events, 1):
                try:
                    logger.info(f"📝 Processing attachment event {i}/{len(extracted_events)}: {event_data.get('event_name', 'Unnamed')}")
                    cleaned_event = validate_and_clean_event(event_data)
                    logger.info(f"✅ Attachment event {i} validation successful")

                    event = Event()
                    event.user_id = user.id
                    event.text_input_id = text_input.id
                    
                    # Sanitize event data before saving to database
                    event.event_name = sanitize_text_for_db(cleaned_event['event_name'])
                    event.event_description = sanitize_text_for_db(cleaned_event['event_description'])
                    event.extracted_at = datetime.utcnow()

                    # Parse dates safely - start_date is required by database schema
                    if cleaned_event['start_date']:
                        event.start_date = datetime.strptime(cleaned_event['start_date'], '%Y-%m-%d').date()
                    else:
                        # If no start date provided, use today as default (required by DB schema)
                        event.start_date = datetime.now().date()

                    if cleaned_event['start_time']:
                        event.start_time = datetime.strptime(cleaned_event['start_time'], '%H:%M').time()
                    if cleaned_event['end_date']:
                        event.end_date = datetime.strptime(cleaned_event['end_date'], '%Y-%m-%d').date()
                    else:
                        # If no end date, use start date
                        event.end_date = event.start_date

                    if cleaned_event['end_time']:
                        event.end_time = datetime.strptime(cleaned_event['end_time'], '%H:%M').time()

                    # Store RFC3339 datetime strings for Google Calendar
                    event.start_datetime = cleaned_event.get('start_datetime')
                    event.end_datetime = cleaned_event.get('end_datetime')
                    event.location = sanitize_text_for_db(cleaned_event['location'])
                    
                    # Calculate and store duration in minutes
                    from helpers.event_utils import calculate_event_duration_minutes
                    event.duration_minutes = calculate_event_duration_minutes(event)

                    created_events.append(event)
                    logger.info(f"✅ Attachment event {i} successfully prepared for database: '{event.event_name}'")

                except Exception as e:
                    logger.error(f"❌ VALIDATION FAILED for attachment event {i}/{len(extracted_events)}: {str(e)}")
                    logger.error(f"❌ Failed attachment event data: {event_data}")
                    continue

            # Save events to database
            for event in created_events:
                db.session.add(event)
            
            db.session.commit()
            logger.info(f"📊 ATTACHMENT PROCESSING SUMMARY: Extracted {len(extracted_events)} events, Successfully processed {len(created_events)} events")
            
            # Auto-sync to Google Calendar if enabled
            if auto_sync and created_events:
                for event in created_events:
                    try:
                        # Skip if already synced
                        if event.is_synced and event.google_event_id:
                            synced_count += 1
                            continue

                        # Prepare event data for Google Calendar
                        event_data = {
                            'event_name': event.event_name,
                            'event_description': event.event_description,
                            'location': event.location
                        }

                        # Use datetime fields if available, otherwise fall back to separate date/time
                        if event.start_datetime and event.end_datetime:
                            event_data['start_datetime'] = event.start_datetime
                            event_data['end_datetime'] = event.end_datetime
                        else:
                            # Fallback to separate date/time fields
                            if event.start_date:
                                event_data['start_date'] = event.start_date.strftime('%Y-%m-%d')
                            if event.start_time:
                                event_data['start_time'] = event.start_time.strftime('%H:%M')
                            if event.end_date:
                                event_data['end_date'] = event.end_date.strftime('%Y-%m-%d')
                            if event.end_time:
                                event_data['end_time'] = event.end_time.strftime('%H:%M')

                        # Create event in Google Calendar
                        google_event_id = create_calendar_event(user, event_data)

                        if google_event_id:
                            event.google_event_id = google_event_id
                            event.is_synced = True
                            synced_count += 1
                            logger.info(f"✅ Synced attachment event '{event.event_name}' to Google Calendar")
                        else:
                            logger.warning(f"❌ Failed to sync attachment event '{event.event_name}' to Google Calendar")

                    except Exception as sync_error:
                        logger.error(f"❌ Error syncing attachment event '{event.event_name}': {str(sync_error)}")
                        continue

                # Commit sync updates
                db.session.commit()
                logger.info(f"🔄 Auto-sync completed for attachment events: {synced_count}/{len(created_events)} synced")

            return {
                'events': created_events,
                'synced_count': synced_count,
                'text_input': text_input
            }
            
        except Exception as e:
            logger.error(f"❌ Error in attachment event processing: {str(e)}")
            db.session.rollback()
            return {
                'events': [],
                'synced_count': 0,
                'text_input': text_input
            }
    
    
    
    def _extract_events_from_attachment(self, file_content: bytes, 
                                      attachment_record: EmailAttachment, 
                                      text_input: TextInput) -> List[Dict]:
        """
        Extract events from attachment using OpenAI multimodal API.
        
        Args:
            file_content (bytes): File content
            attachment_record (EmailAttachment): Attachment record
            text_input (TextInput): Parent text input
        
        Returns:
            List[Dict]: Extracted events
        """
        try:
            # Prepare content for OpenAI
            if attachment_record.file_type.startswith('image/'):
                # For images, use multimodal processing
                return self._extract_from_image(file_content, text_input)
            else:
                # For documents, extract text first then process
                return self._extract_from_document(file_content, attachment_record, text_input)
                
        except Exception as e:
            logger.error(f"Error extracting events from attachment: {str(e)}")
            return []
    
    def _extract_from_image(self, image_content: bytes, text_input: TextInput) -> List[Dict]:
        """
        Extract events from image using OpenAI API.
        
        Args:
            image_content (bytes): Image file content
            text_input (TextInput): Parent text input
        
        Returns:
            List[Dict]: Extracted events
        """
        try:
            # Encode image to base64
            import base64
            encoded_image = base64.b64encode(image_content).decode('utf-8')
            
            # Use existing event extraction with image support
            # extract_events_from_text returns a tuple: (events, from_email, is_offline, openai_status, openai_error)
            result = extract_events_from_text(
                text=text_input.original_text,  # Use the actual email text
                current_date=text_input.created_at.strftime('%Y-%m-%d'),
                user_timezone=text_input.user.timezone if text_input.user else "UTC",
                image_data=encoded_image
            )
            
            # Extract only the events list from the tuple
            events = result[0] if isinstance(result, tuple) else result
            return events
            
        except Exception as e:
            logger.error(f"Error extracting events from image: {str(e)}")
            return []
    
    def _extract_from_document(self, file_content: bytes, 
                             attachment_record: EmailAttachment, 
                             text_input: TextInput) -> List[Dict]:
        """
        Extract events from document (PDF, Word, etc.).
        
        Args:
            file_content (bytes): Document content
            attachment_record (EmailAttachment): Attachment record
            text_input (TextInput): Parent text input
        
        Returns:
            List[Dict]: Extracted events
        """
        try:
            # Extract text from document
            document_text = self._extract_text_from_document(file_content, attachment_record.file_type)
            
            if not document_text:
                logger.warning(f"No text extracted from document: {attachment_record.filename}")
                return []
            
            # Use existing text extraction
            # extract_events_from_text returns a tuple: (events, from_email, is_offline, openai_status, openai_error)
            result = extract_events_from_text(
                text=document_text,
                current_date=text_input.created_at.strftime('%Y-%m-%d'),
                user_timezone=text_input.user.timezone if text_input.user else "UTC"
            )
            
            # Extract only the events list from the tuple
            events = result[0] if isinstance(result, tuple) else result
            return events
            
        except Exception as e:
            logger.error(f"Error extracting events from document: {str(e)}")
            return []
    
    def _extract_text_from_document(self, file_content: bytes, content_type: str) -> str:
        """
        Extract text from various document formats.
        
        Args:
            file_content (bytes): Document content
            content_type (str): MIME type
        
        Returns:
            str: Extracted text
        """
        try:
            if content_type == 'application/pdf':
                return self._extract_from_pdf(file_content)
            elif content_type in ['application/msword', 
                                'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
                return self._extract_from_word(file_content)
            elif content_type in ['text/plain', 'text/html']:
                return file_content.decode('utf-8', errors='ignore')
            else:
                logger.warning(f"Unsupported document type for text extraction: {content_type}")
                return ""
                
        except Exception as e:
            logger.error(f"Error extracting text from document: {str(e)}")
            return ""
    
    def _extract_from_pdf(self, file_content: bytes) -> str:
        """Extract text from PDF file."""
        try:
            import PyPDF2
            import io
            
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
            text = ""
            
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            
            return text.strip()
            
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {str(e)}")
            return ""
    
    def _extract_from_word(self, file_content: bytes) -> str:
        """Extract text from Word document."""
        try:
            import docx
            import io
            
            doc = docx.Document(io.BytesIO(file_content))
            text = ""
            
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            
            return text.strip()
            
        except Exception as e:
            logger.error(f"Error extracting text from Word document: {str(e)}")
            return ""
    
    def _save_extracted_events(self, extracted_events: List[Dict], 
                             attachment_record: EmailAttachment, 
                             text_input: TextInput):
        """
        Save extracted events to database.
        
        Args:
            extracted_events (List[Dict]): Events extracted from attachment
            attachment_record (EmailAttachment): Attachment record
            text_input (TextInput): Parent text input
        """
        try:
            from models import Event
            
            for event_data in extracted_events:
                # Create event record
                event = Event()
                event.user_id = text_input.user_id
                event.text_input_id = text_input.id
                event.event_name = event_data.get('event_name', 'Unknown Event')
                event.event_description = event_data.get('event_description', '')
                event.start_date = event_data.get('start_date')
                event.start_time = event_data.get('start_time')
                event.start_datetime = event_data.get('start_datetime')
                event.end_date = event_data.get('end_date')
                event.end_time = event_data.get('end_time')
                event.end_datetime = event_data.get('end_datetime')
                event.location = event_data.get('location', '')
                event.is_synced = False
                
                db.session.add(event)
            
            db.session.commit()
            logger.info(f"Saved {len(extracted_events)} events from attachment")
            
        except Exception as e:
            logger.error(f"Error saving extracted events: {str(e)}")
            db.session.rollback()

# Global instance
attachment_processor = AttachmentProcessor()