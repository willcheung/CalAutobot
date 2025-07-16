import os
import logging
import requests
import mimetypes
from typing import List, Dict, Optional, Tuple
from object_store import object_store
from models import EmailAttachment, TextInput, Event
from app import db
from event_extractor import extract_events_from_text
import json
import tempfile
import base64

logger = logging.getLogger(__name__)

class AttachmentProcessor:
    """
    Process email attachments from Mailgun for event extraction.
    Uses Replit Object Store for temporary file storage.
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
        attachment_url = attachment_data.get('url')
        
        logger.info(f"Processing attachment: {filename} ({content_type}, {file_size} bytes)")
        
        # Validate file
        if not self._validate_attachment(filename, file_size, content_type):
            logger.warning(f"Attachment validation failed: {filename}")
            return None
        
        # Create database record
        attachment_record = EmailAttachment(
            text_input_id=text_input.id,
            filename=filename,
            file_type=content_type,
            file_size=file_size,
            processing_status='pending'
        )
        
        try:
            db.session.add(attachment_record)
            db.session.flush()  # Get the ID without committing
            
            # Download and process the attachment
            success = self._download_and_process_attachment(
                attachment_record, attachment_url, text_input
            )
            
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
    
    def _download_and_process_attachment(self, attachment_record: EmailAttachment, 
                                       attachment_url: str, text_input: TextInput) -> bool:
        """
        Download attachment from Mailgun and process for event extraction.
        
        Args:
            attachment_record (EmailAttachment): Database record
            attachment_url (str): Mailgun attachment URL
            text_input (TextInput): Parent text input
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Download attachment from Mailgun
            file_content = self._download_from_mailgun(attachment_url)
            if not file_content:
                return False
            
            # Store in Object Store temporarily
            object_key = object_store.upload_file(
                file_content, 
                attachment_record.filename, 
                attachment_record.file_type
            )
            
            if not object_key:
                logger.error("Failed to upload file to Object Store")
                return False
            
            try:
                # Process attachment for event extraction
                extracted_events = self._extract_events_from_attachment(
                    file_content, attachment_record, text_input
                )
                
                if extracted_events:
                    # Save extracted events to database
                    self._save_extracted_events(extracted_events, attachment_record, text_input)
                    attachment_record.extracted_events_count = len(extracted_events)
                    logger.info(f"Extracted {len(extracted_events)} events from {attachment_record.filename}")
                
                return True
                
            finally:
                # Clean up from Object Store
                object_store.delete_file(object_key)
                
        except Exception as e:
            logger.error(f"Error downloading and processing attachment: {str(e)}")
            return False
    
    def _download_from_mailgun(self, attachment_url: str) -> Optional[bytes]:
        """
        Download attachment from Mailgun API.
        
        Args:
            attachment_url (str): Mailgun attachment URL
        
        Returns:
            bytes: File content or None if failed
        """
        try:
            response = requests.get(
                attachment_url,
                auth=('api', self.mailgun_api_key),
                timeout=30
            )
            
            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"Failed to download attachment: HTTP {response.status_code}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error downloading attachment from Mailgun: {str(e)}")
            return None
    
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
        Extract events from image using OpenAI Vision API.
        
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
            # This will need to be enhanced in event_extractor.py
            events = extract_events_from_text(
                text=f"Please extract calendar events from this image attachment.",
                current_date=text_input.created_at.strftime('%Y-%m-%d'),
                user_timezone=text_input.user.timezone if text_input.user else "UTC",
                image_data=encoded_image  # New parameter to be added
            )
            
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
            events = extract_events_from_text(
                text=document_text,
                current_date=text_input.created_at.strftime('%Y-%m-%d'),
                user_timezone=text_input.user.timezone if text_input.user else "UTC"
            )
            
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
                event = Event(
                    user_id=text_input.user_id,
                    text_input_id=text_input.id,
                    event_name=event_data.get('event_name', 'Unknown Event'),
                    event_description=event_data.get('event_description', ''),
                    start_date=event_data.get('start_date'),
                    start_time=event_data.get('start_time'),
                    start_datetime=event_data.get('start_datetime'),
                    end_date=event_data.get('end_date'),
                    end_time=event_data.get('end_time'),
                    end_datetime=event_data.get('end_datetime'),
                    location=event_data.get('location', ''),
                    is_synced=False
                )
                
                db.session.add(event)
            
            db.session.commit()
            logger.info(f"Saved {len(extracted_events)} events from attachment")
            
        except Exception as e:
            logger.error(f"Error saving extracted events: {str(e)}")
            db.session.rollback()

# Global instance
attachment_processor = AttachmentProcessor()