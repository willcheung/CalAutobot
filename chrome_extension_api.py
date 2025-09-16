"""
Chrome Extension API endpoint for Calendar AI
Provides a clean API interface for the Chrome extension while reusing existing backend logic.
"""

from flask import request, jsonify
from flask_login import login_required, current_user
import logging
from helpers.event_processing import process_text_to_events
from models import User
import json

logger = logging.getLogger(__name__)

def setup_chrome_extension_routes(app):
    """Setup Chrome extension API routes"""
    
    @app.route('/api/extension/process', methods=['POST', 'OPTIONS'])
    def extension_process_events():
        """
        Process text and/or attachments from Chrome extension.
        Reuses existing processing pipeline with cleaner API interface.
        """
        # Handle CORS preflight
        if request.method == 'OPTIONS':
            response = jsonify({'status': 'ok'})
            response.headers.add('Access-Control-Allow-Origin', 'chrome-extension://*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
            return response

        # Add CORS headers to all responses
        def add_cors_headers(response):
            response.headers.add('Access-Control-Allow-Origin', 'chrome-extension://*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            return response

        try:

            # Check authentication via Authorization header
            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                response = jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'})
                return add_cors_headers(response), 401

            # Extract token and validate user
            token = auth_header.split(' ')[1]
            
            # In a production environment, you would validate this token properly
            # For now, we'll look up the user by email from the request
            user_email = ''
            if request.form:
                user_email = request.form.get('From', '')
            elif request.json:
                user_email = request.json.get('user_email', '')
            
            if not user_email:
                response = jsonify({'error': 'User email required', 'code': 'EMAIL_REQUIRED'})
                return add_cors_headers(response), 400

            # Find user in database
            logger.info(f"🔍 Chrome extension looking for user with email: '{user_email}'")
            user = User.query.filter_by(email=user_email).first()
            if not user:
                logger.warning(f"❌ Chrome extension user not found: '{user_email}'")
                # List all users for debugging (first few characters only for privacy)
                all_users = User.query.all()
                user_emails = [u.email[:10] + "..." if len(u.email) > 10 else u.email for u in all_users[:5]]
                logger.info(f"📋 Available users in database (first 5): {user_emails}")
                response = jsonify({'error': 'User not found', 'code': 'USER_NOT_FOUND', 'requested_email': user_email})
                return add_cors_headers(response), 404

            # Extract text input
            text_input = ''
            if request.content_type and request.content_type.startswith('application/json'):
                data = request.get_json() or {}
                text_input = data.get('text', '')
                source_info = data.get('source', 'Chrome Extension')
            else:
                text_input = request.form.get('stripped-text', '')
                source_info = request.form.get('Subject', 'Chrome Extension Text Input')

            if not text_input.strip():
                response = jsonify({'error': 'No text provided to process', 'code': 'NO_TEXT'})
                return add_cors_headers(response), 400

            # Format text for processing (similar to email format)
            formatted_text = f"From: {user_email}\nSource: {source_info}\n\n{text_input}"

            # Process attachments if present (screenshots)
            attachments_data = []
            if request.files:
                for field_name, file_obj in request.files.items():
                    if file_obj and file_obj.filename:
                        file_content = file_obj.read()
                        attachment_info = {
                            'name': file_obj.filename,
                            'content-type': file_obj.content_type or 'image/png',
                            'size': len(file_content),
                            'content': file_content
                        }
                        attachments_data.append(attachment_info)
                        logger.info(f"📎 Chrome extension attachment: {attachment_info['name']} ({attachment_info['size']} bytes)")

            # Auto-sync if user has Google authentication
            auto_sync = user.google_id is not None

            # Process using existing pipeline
            result = process_text_to_events(
                formatted_text,
                user,
                source_type="chrome_extension",
                auto_sync=auto_sync
            )

            # Process attachments if present
            total_attachment_events = 0
            total_attachment_synced = 0
            
            if attachments_data:
                from attachment_processor import attachment_processor
                
                text_input_record = result.get('text_input')
                if text_input_record:
                    logger.info(f"🔄 Processing {len(attachments_data)} Chrome extension attachments")
                    processed_attachments = attachment_processor.process_email_attachments(
                        text_input_record, attachments_data
                    )
                    
                    # Count attachment events
                    for attachment in processed_attachments:
                        if attachment and hasattr(attachment, 'extracted_events_count'):
                            attachment_events = attachment.extracted_events_count or 0
                            total_attachment_events += attachment_events
                            
                            # Count synced events from this attachment
                            from models import Event
                            attachment_synced_events = Event.query.filter_by(
                                user_id=user.id,
                                text_input_id=text_input_record.id,
                                is_synced=True
                            ).filter(
                                Event.extracted_at >= attachment.created_at
                            ).count()
                            total_attachment_synced += attachment_synced_events

            # Calculate totals
            text_events = len(result.get('events', []))
            text_synced = result.get('synced_count', 0)
            
            total_events = text_events + total_attachment_events
            total_synced = text_synced + total_attachment_synced

            logger.info(f"📊 Chrome extension processing complete: {total_events} events extracted, {total_synced} synced")

            # Return structured response
            response_data = {
                'status': 'success',
                'text_events_extracted': text_events,
                'attachment_events_extracted': total_attachment_events,
                'total_events_extracted': total_events,
                'total_events_synced': total_synced,
                'auto_sync_enabled': auto_sync,
                'attachments_processed': len(attachments_data),
                'user_id': user.id,
                'message': f'Successfully extracted {total_events} events' + 
                          (f', {total_synced} synced to calendar' if auto_sync else '')
            }

            response = jsonify(response_data)
            return add_cors_headers(response), 200

        except Exception as e:
            logger.error(f"Chrome extension API error: {str(e)}", exc_info=True)
            response = jsonify({
                'error': 'Processing failed',
                'code': 'PROCESSING_ERROR',
                'message': str(e)
            })
            return add_cors_headers(response), 500

    @app.route('/api/extension/auth/verify', methods=['POST', 'OPTIONS'])
    def extension_verify_auth():
        """Verify Chrome extension authentication"""
        
        def add_cors_headers(response):
            response.headers.add('Access-Control-Allow-Origin', 'chrome-extension://*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            return response
            
        if request.method == 'OPTIONS':
            response = jsonify({'status': 'ok'})
            response.headers.add('Access-Control-Allow-Origin', 'chrome-extension://*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
            return response

        try:

            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                response = jsonify({'authenticated': False, 'error': 'No auth token'})
                return add_cors_headers(response), 401

            # Get user email from request
            data = request.get_json() or {}
            user_email = data.get('email', '')
            
            if not user_email:
                response = jsonify({'authenticated': False, 'error': 'Email required'})
                return add_cors_headers(response), 400

            # Find user
            user = User.query.filter_by(email=user_email).first()
            if not user:
                response = jsonify({'authenticated': False, 'error': 'User not found'})
                return add_cors_headers(response), 404

            response_data = {
                'authenticated': True,
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'username': user.username,
                    'has_google_auth': bool(user.google_id),
                    'timezone': user.timezone
                }
            }

            response = jsonify(response_data)
            return add_cors_headers(response), 200

        except Exception as e:
            logger.error(f"Chrome extension auth verify error: {str(e)}")
            response = jsonify({'authenticated': False, 'error': 'Verification failed'})
            response.headers.add('Access-Control-Allow-Origin', 'chrome-extension://*')
            return response, 500