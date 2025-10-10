import os
import logging
import base64
from typing import List, Dict, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json
from datetime import datetime

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
            
            if not all([client_id, client_secret, refresh_token]):
                logger.error("Missing required Gmail credentials in environment variables")
                return
            
            # Create credentials object (access token will be obtained automatically from refresh token)
            token_data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token
            }
            
            self.credentials = Credentials.from_authorized_user_info(
                token_data,
                scopes=['https://mail.google.com']
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
            if not service:
                logger.error("Gmail service not available")
                return []
            
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
    
    def _parse_gmail_message(self, service, message: Dict) -> Optional[Dict]:
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

    def start_watch(self, topic_name: str, label_ids: Optional[List[str]] = None,
                    label_filter_action: str = 'include') -> Optional[Dict]:
        """
        Start or renew a Gmail push watch on the configured mailbox.

        Args:
            topic_name (str): Full Pub/Sub topic name.
            label_ids (List[str], optional): Labels to scope the watch to.
            label_filter_action (str): Either 'include' or 'exclude'.

        Returns:
            Optional[Dict]: Gmail watch response with historyId/expiration.
        """
        try:
            service = self.get_service()
            if not service:
                logger.error("Cannot start Gmail watch: service unavailable")
                return None

            body = {
                'topicName': topic_name,
                'labelFilterAction': label_filter_action
            }
            if label_ids:
                body['labelIds'] = label_ids

            response = service.users().watch(
                userId='me',
                body=body
            ).execute()

            history_id = response.get('historyId')
            expiration_ms = response.get('expiration')
            expiration_dt = None
            if expiration_ms:
                try:
                    expiration_dt = datetime.utcfromtimestamp(int(expiration_ms) / 1000.0)
                except (TypeError, ValueError):
                    expiration_dt = None

            logger.info(
                "Started Gmail watch on topic %s (labels=%s, historyId=%s, expires=%s)",
                topic_name,
                label_ids,
                history_id,
                expiration_dt.isoformat() if expiration_dt else "unknown"
            )
            return response

        except Exception as e:
            logger.error(f"Error starting Gmail watch: {str(e)}")
            return None

    def list_history(self, start_history_id: str) -> List[Dict]:
        """
        Fetch Gmail history records starting from the provided history ID.

        Args:
            start_history_id (str): Starting history ID from which to fetch events.

        Returns:
            List[Dict]: History records containing messageAdded/labelAdded entries.
        """
        try:
            service = self.get_service()
            if not service:
                logger.error("Cannot list Gmail history: service unavailable")
                return []

            all_history = []
            page_token = None
            while True:
                params = {
                    'userId': 'me',
                    'startHistoryId': str(start_history_id),
                    'historyTypes': ['messageAdded', 'labelAdded']
                }
                if page_token:
                    params['pageToken'] = page_token

                response = service.users().history().list(**params).execute()
                all_history.extend(response.get('history', []))
                page_token = response.get('nextPageToken')

                if not page_token:
                    break

            logger.info(
                "Fetched %s Gmail history record(s) from start ID %s",
                len(all_history),
                start_history_id
            )
            return all_history

        except Exception as e:
            logger.error(f"Error listing Gmail history from {start_history_id}: {str(e)}")
            return []
    
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
    
    def send_email(self, to: str, subject: str, html_body: str) -> bool:
        """
        Send an email using Gmail API.
        
        Args:
            to (str): Recipient email address
            subject (str): Email subject
            html_body (str): HTML email body
        
        Returns:
            bool: True if successful
        """
        try:
            service = self.get_service()
            if not service:
                logger.error("Cannot send email: Gmail service not available")
                return False
            
            # Create email message
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            message = MIMEMultipart('alternative')
            message['To'] = to
            message['From'] = 'Cal AutoBot <cal@calautobot.com>'
            message['Subject'] = subject
            
            # Add HTML body
            html_part = MIMEText(html_body, 'html')
            message.attach(html_part)
            
            # Encode message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            # Send message
            service.users().messages().send(
                userId='me',
                body={'raw': raw_message}
            ).execute()
            
            logger.info(f"Successfully sent email to {to}: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending email to {to}: {str(e)}")
            return False

# Global instance
gmail_service = GmailService()
