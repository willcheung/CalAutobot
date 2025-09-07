import os
import logging
import base64
from typing import List, Dict, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json

logger = logging.getLogger(__name__)

class GmailService:
    """
    Backend Gmail service for checking emails from a single inbox.
    Replaces Mailgun webhook with Gmail API polling.
    """
    
    def __init__(self):
        """Initialize Gmail service with backend credentials"""
        self.credentials = None
        self._initialize_credentials()
    
    def _initialize_credentials(self):
        """Initialize Gmail credentials from environment variables"""
        try:
            # Get credentials from environment variables
            client_id = os.environ.get("GMAIL_CLIENT_ID")
            client_secret = os.environ.get("GMAIL_CLIENT_SECRET") 
            refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN")
            access_token = os.environ.get("GMAIL_ACCESS_TOKEN")
            
            if not all([client_id, client_secret, refresh_token]):
                logger.error("Missing required Gmail credentials in environment variables")
                return
            
            # Create credentials object
            token_data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "token": access_token
            }
            
            self.credentials = Credentials.from_authorized_user_info(
                token_data,
                scopes=['https://www.googleapis.com/auth/gmail.readonly']
            )
            
            logger.info("Gmail credentials initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing Gmail credentials: {str(e)}")
            self.credentials = None
    
    def get_service(self):
        """Get Gmail API service with fresh token"""
        try:
            if not self.credentials:
                logger.error("Gmail credentials not initialized")
                return None
            
            # Refresh token if needed
            if self.credentials.expired:
                logger.info("Refreshing expired Gmail access token")
                self.credentials.refresh(Request())
            
            service = build('gmail', 'v1', credentials=self.credentials)
            return service
            
        except Exception as e:
            logger.error(f"Error getting Gmail service: {str(e)}")
            return None
    
    def get_unread_emails(self, max_results: int = 50) -> List[Dict]:
        """
        Get unread emails from Gmail inbox.
        
        Args:
            max_results (int): Maximum number of emails to fetch
        
        Returns:
            List[Dict]: List of email data
        """
        try:
            service = self.get_service()
            if not service:
                logger.error("Failed to get Gmail service")
                return []
            
            # Search for unread emails
            results = service.users().messages().list(
                userId='me',
                q='is:unread',
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            
            if not messages:
                logger.info("No unread emails found")
                return []
            
            logger.info(f"Found {len(messages)} unread emails")
            
            # Get full message details for each email
            emails = []
            for message in messages:
                try:
                    email_data = self.get_email_details(service, message['id'])
                    if email_data:
                        emails.append(email_data)
                except Exception as e:
                    logger.error(f"Error processing email {message['id']}: {str(e)}")
                    continue
            
            logger.info(f"Successfully processed {len(emails)} emails")
            return emails
            
        except Exception as e:
            logger.error(f"Error getting unread emails: {str(e)}")
            return []
    
    def get_email_details(self, service, message_id: str) -> Optional[Dict]:
        """
        Get detailed email data including attachments.
        
        Args:
            service: Gmail API service
            message_id (str): Gmail message ID
        
        Returns:
            Dict: Email data with same structure as Mailgun webhook
        """
        try:
            # Get full message details
            message = service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            # Parse email data
            email_data = self._parse_gmail_message(service, message)
            
            return email_data
            
        except Exception as e:
            logger.error(f"Error getting email details for {message_id}: {str(e)}")
            return None
    
    def _parse_gmail_message(self, service, message: Dict) -> Dict:
        """
        Parse Gmail message into the same format as Mailgun webhook data.
        
        Args:
            service: Gmail API service
            message (Dict): Gmail message data
        
        Returns:
            Dict: Parsed email data
        """
        try:
            payload = message['payload']
            headers = payload.get('headers', [])
            
            # Extract headers
            subject = self._get_header_value(headers, 'Subject')
            from_email = self._get_header_value(headers, 'From')
            to_email = self._get_header_value(headers, 'To')
            date = self._get_header_value(headers, 'Date')
            
            # Extract email address from "Name <email>" format
            if from_email and '<' in from_email and '>' in from_email:
                from_email = from_email.split('<')[1].split('>')[0].strip()
            
            # Extract email body
            body_text = self._extract_body_text(payload)
            
            # Extract attachments
            attachments_data = self._extract_attachments(service, message['id'], payload)
            
            # Return data in same format as Mailgun webhook
            email_data = {
                'id': message['id'],
                'sender': from_email.lower().strip() if from_email else '',
                'recipient': to_email,
                'subject': subject or '',
                'stripped-text': body_text,
                'stripped-html': '',  # We'll use plain text for simplicity
                'date': date,
                'attachments': attachments_data
            }
            
            logger.info(f"Parsed email from {email_data['sender']}: {email_data['subject']}")
            
            return email_data
            
        except Exception as e:
            logger.error(f"Error parsing Gmail message: {str(e)}")
            return None
    
    def _get_header_value(self, headers: List[Dict], header_name: str) -> str:
        """Get header value by name"""
        for header in headers:
            if header.get('name', '').lower() == header_name.lower():
                return header.get('value', '')
        return ''
    
    def _extract_body_text(self, payload: Dict) -> str:
        """
        Extract plain text body from Gmail message payload.
        
        Args:
            payload (Dict): Gmail message payload
        
        Returns:
            str: Email body text
        """
        try:
            # Handle different payload structures
            if 'parts' in payload:
                # Multipart message
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        body_data = part.get('body', {}).get('data')
                        if body_data:
                            return base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
                
                # Fallback to HTML if plain text not found
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/html':
                        body_data = part.get('body', {}).get('data')
                        if body_data:
                            return base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
            
            elif payload.get('mimeType') == 'text/plain':
                # Simple text message
                body_data = payload.get('body', {}).get('data')
                if body_data:
                    return base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
            
            return ''
            
        except Exception as e:
            logger.error(f"Error extracting body text: {str(e)}")
            return ''
    
    def _extract_attachments(self, service, message_id: str, payload: Dict) -> List[Dict]:
        """
        Extract attachment information from Gmail message.
        
        Args:
            service: Gmail API service
            message_id (str): Gmail message ID
            payload (Dict): Gmail message payload
        
        Returns:
            List[Dict]: Attachment data in Mailgun-compatible format
        """
        try:
            attachments = []
            
            # Check for attachments in parts
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('filename') and part.get('body', {}).get('attachmentId'):
                        attachment_info = {
                            'name': part['filename'],
                            'content-type': part.get('mimeType', 'application/octet-stream'),
                            'size': part.get('body', {}).get('size', 0),
                            'attachment_id': part['body']['attachmentId'],
                            'message_id': message_id
                        }
                        attachments.append(attachment_info)
            
            if attachments:
                logger.info(f"Found {len(attachments)} attachments in email {message_id}")
            
            return attachments
            
        except Exception as e:
            logger.error(f"Error extracting attachments: {str(e)}")
            return []
    
    def download_attachment(self, message_id: str, attachment_id: str) -> Optional[bytes]:
        """
        Download attachment content from Gmail.
        
        Args:
            message_id (str): Gmail message ID
            attachment_id (str): Gmail attachment ID
        
        Returns:
            bytes: Attachment content
        """
        try:
            service = self.get_service()
            if not service:
                return None
            
            # Get attachment data
            attachment = service.users().messages().attachments().get(
                userId='me',
                messageId=message_id,
                id=attachment_id
            ).execute()
            
            # Decode base64 content
            file_data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
            
            logger.info(f"Downloaded attachment {attachment_id} from message {message_id} ({len(file_data)} bytes)")
            
            return file_data
            
        except Exception as e:
            logger.error(f"Error downloading attachment {attachment_id}: {str(e)}")
            return None
    
    def mark_as_read(self, message_id: str) -> bool:
        """
        Mark email as read after processing.
        
        Args:
            message_id (str): Gmail message ID
        
        Returns:
            bool: True if successful
        """
        try:
            service = self.get_service()
            if not service:
                return False
            
            # Remove UNREAD label
            service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
            
            logger.info(f"Marked email {message_id} as read")
            return True
            
        except Exception as e:
            logger.error(f"Error marking email as read {message_id}: {str(e)}")
            return False

# Global instance
gmail_service = GmailService()