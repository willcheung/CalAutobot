import os
import logging
import base64
from typing import List, Dict, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json

logger = logging.getLogger(__name__)

class GmailOAuthError(Exception):
    """Custom exception for Gmail OAuth authentication errors"""
    pass

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
                scopes=['https://www.googleapis.com/auth/gmail.modify']
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
                return None  # Don't raise OAuth error for missing credentials
            
            # Refresh token if needed
            if self.credentials.expired:
                logger.info("Refreshing expired Gmail access token")
                self.credentials.refresh(Request())
            
            service = build('gmail', 'v1', credentials=self.credentials)
            return service
            
        except Exception as e:
            error_msg = str(e).lower()
            logger.error(f"Error getting Gmail service: {str(e)}")
            
            # More specific OAuth authentication error detection
            oauth_errors = [
                'invalid_grant',
                'token has been expired or revoked',
                'token_expired',
                'invalid_token'
            ]
            
            if any(phrase in error_msg for phrase in oauth_errors):
                raise GmailOAuthError(f"Gmail OAuth authentication failed: {str(e)}")
            
            # For other errors, re-raise as generic exception
            raise
    
    def get_unread_emails(self, max_results: int = 50) -> List[Dict]:
        """
        Get unread emails sent to go@calautobot.com only.
        
        Args:
            max_results (int): Maximum number of emails to fetch
        
        Returns:
            List[Dict]: List of email data
        """
        try:
            service = self.get_service()
            
            # Search for unread emails sent to go@calautobot.com only
            results = service.users().messages().list(
                userId='me',
                q='is:unread to:go@calautobot.com',
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            
            if not messages:
                logger.info("No unread emails found for go@calautobot.com")
                return []
            
            logger.info(f"Found {len(messages)} unread emails for go@calautobot.com")
            
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
            
        except GmailOAuthError:
            # Re-raise OAuth errors so they can be handled by caller
            raise
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
        Handles complex nested structures and HTML-only emails.
        
        Args:
            payload (Dict): Gmail message payload
        
        Returns:
            str: Email body text
        """
        try:
            # Recursive function to find body text in nested parts
            def extract_from_parts(parts):
                text_content = ""
                html_content = ""
                
                for part in parts:
                    mime_type = part.get('mimeType', '')
                    
                    # Handle nested multipart (recursive)
                    if 'parts' in part:
                        nested_text, nested_html = extract_from_parts(part['parts'])
                        if nested_text:
                            text_content += nested_text + "\n"
                        if nested_html:
                            html_content += nested_html + "\n"
                    
                    # Extract plain text
                    elif mime_type == 'text/plain':
                        body_data = part.get('body', {}).get('data')
                        if body_data:
                            text_content += base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore') + "\n"
                    
                    # Extract HTML (as fallback)
                    elif mime_type == 'text/html':
                        body_data = part.get('body', {}).get('data')
                        if body_data:
                            html_content += base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore') + "\n"
                
                return text_content.strip(), html_content.strip()
            
            # Handle different payload structures
            if 'parts' in payload:
                # Multipart message (most common for forwarded emails)
                text_content, html_content = extract_from_parts(payload['parts'])
                
                # Return plain text if available, otherwise HTML
                if text_content:
                    return text_content
                elif html_content:
                    # Simple HTML tag removal for basic text extraction
                    import re
                    # Remove HTML tags and decode entities
                    clean_text = re.sub(r'<[^>]+>', '', html_content)
                    clean_text = clean_text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                    return clean_text.strip()
            
            elif payload.get('mimeType') == 'text/plain':
                # Simple text message
                body_data = payload.get('body', {}).get('data')
                if body_data:
                    return base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
            
            elif payload.get('mimeType') == 'text/html':
                # HTML-only message
                body_data = payload.get('body', {}).get('data')
                if body_data:
                    html_content = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
                    # Simple HTML tag removal
                    import re
                    clean_text = re.sub(r'<[^>]+>', '', html_content)
                    clean_text = clean_text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                    return clean_text.strip()
            
            # If no content found, return the subject as fallback
            logger.warning("No body content found in email, this might be an empty or attachment-only email")
            return ""
            
        except Exception as e:
            logger.error(f"Error extracting body text: {str(e)}")
            return ""
    
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