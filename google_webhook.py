import os
import json
import logging
import hmac
import hashlib
from datetime import datetime
from flask import Blueprint, request, jsonify
from app import db
from models import User, Event
import sentry_sdk

# Configure logging
logger = logging.getLogger(__name__)

google_webhook = Blueprint("google_calendar_webhook", __name__)

def verify_google_webhook_signature(payload, signature):
    """
    Verify Google webhook signature.
    Google uses X-Goog-Channel-Token for verification, which we'll validate
    against our stored channel tokens.
    """
    try:
        # For now, we'll implement basic token validation
        # In a production system, you might want to use HMAC verification
        channel_token = request.headers.get('X-Goog-Channel-Token', '')
        
        # Basic validation - check if token starts with our app identifier
        if channel_token.startswith('cal-autobot-'):
            return True
        
        logger.warning(f"Invalid channel token received: {channel_token}")
        return False
    except Exception as e:
        logger.error(f"Error verifying Google webhook signature: {str(e)}")
        return False

@google_webhook.route("/webhook/google-calendar", methods=["POST"])
def handle_google_calendar_webhook():
    """
    Handle Google Calendar push notifications.
    
    This endpoint receives notifications when events in a user's Calendar Autobot
    calendar are created, updated, or deleted. We primarily focus on deletions
    to sync with our local database.
    """
    try:
        # Log all headers for debugging
        logger.info("Google Calendar webhook received")
        logger.info("Headers:")
        for header_name, header_value in request.headers.items():
            if header_name.startswith('X-Goog-'):
                logger.info(f"  {header_name}: {header_value}")
        
        # Extract Google-specific headers
        channel_id = request.headers.get('X-Goog-Channel-ID')
        resource_id = request.headers.get('X-Goog-Resource-ID')
        resource_uri = request.headers.get('X-Goog-Resource-URI')
        resource_state = request.headers.get('X-Goog-Resource-State')
        message_number = request.headers.get('X-Goog-Message-Number')
        
        logger.info(f"Channel ID: {channel_id}")
        logger.info(f"Resource ID: {resource_id}")
        logger.info(f"Resource State: {resource_state}")
        
        # Verify the webhook signature/token
        if not verify_google_webhook_signature(request.data, request.headers.get('X-Goog-Channel-Token')):
            logger.warning("Invalid Google webhook signature")
            return jsonify({"error": "Invalid signature"}), 401
        
        # Handle sync messages (initial setup confirmation)
        if resource_state == 'sync':
            logger.info("Received sync message - webhook setup confirmed")
            return jsonify({"status": "sync acknowledged"}), 200
        
        # Handle actual change notifications
        if resource_state == 'exists':
            logger.info("Received notification about calendar changes")
            
            # For exists notifications, we need to check what actually changed
            # Since Google doesn't tell us exactly what changed, we need to:
            # 1. Find the user who owns this calendar resource
            # 2. Sync their events to detect deletions
            
            user = find_user_by_calendar_resource(resource_id, resource_uri)
            if user:
                logger.info(f"Processing calendar changes for user: {user.email}")
                sync_calendar_events_for_deletion(user)
            else:
                logger.warning(f"Could not find user for calendar resource: {resource_id}")
        
        return jsonify({"status": "processed"}), 200
        
    except Exception as e:
        logger.error(f"Error processing Google Calendar webhook: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"error": "Internal server error"}), 500

def find_user_by_calendar_resource(resource_id, resource_uri):
    """
    Find the user who owns the calendar resource that triggered the webhook.
    
    Args:
        resource_id: The Google resource ID from the webhook
        resource_uri: The Google resource URI from the webhook
    
    Returns:
        User object or None if not found
    """
    try:
        # Extract calendar ID from the resource URI
        # Format: https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events
        if '/calendars/' in resource_uri and '/events' in resource_uri:
            calendar_id = resource_uri.split('/calendars/')[1].split('/events')[0]
            
            # Find user with this calendar ID
            user = User.query.filter_by(textbot_calendar_id=calendar_id).first()
            return user
        
        logger.warning(f"Could not extract calendar ID from resource URI: {resource_uri}")
        return None
        
    except Exception as e:
        logger.error(f"Error finding user by calendar resource: {str(e)}")
        return None

def sync_calendar_events_for_deletion(user):
    """
    Check for deleted events in the user's Google Calendar and remove them
    from our database.
    
    Args:
        user: User object whose calendar to sync
    """
    try:
        from google_calendar import refresh_google_token
        import requests
        
        # Get a fresh access token
        access_token = refresh_google_token(user)
        if not access_token:
            logger.error(f"Could not refresh token for user: {user.email}")
            return
        
        # Get all events from the user's Calendar Autobot calendar
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        calendar_id = user.textbot_calendar_id
        if not calendar_id:
            logger.warning(f"User {user.email} has no Calendar Autobot calendar ID")
            return
        
        # Fetch current events from Google Calendar
        url = f'https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events'
        params = {
            'showDeleted': 'false',  # Only get non-deleted events
            'singleEvents': 'true',
            'maxResults': 2500  # Max allowed by API
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch calendar events for user {user.email}: {response.status_code}")
            return
        
        calendar_data = response.json()
        google_event_ids = set()
        
        # Collect all current Google event IDs
        for item in calendar_data.get('items', []):
            google_event_ids.add(item['id'])
        
        logger.info(f"Found {len(google_event_ids)} current events in Google Calendar for user {user.email}")
        
        # Find events in our database that are synced but no longer exist in Google Calendar
        synced_events = Event.query.filter_by(
            user_id=user.id,
            is_synced=True
        ).filter(Event.google_event_id.isnot(None)).all()
        
        deleted_count = 0
        for event in synced_events:
            if event.google_event_id not in google_event_ids:
                logger.info(f"Event '{event.event_name}' (ID: {event.google_event_id}) was deleted from Google Calendar, removing from database")
                db.session.delete(event)
                deleted_count += 1
        
        if deleted_count > 0:
            db.session.commit()
            logger.info(f"Removed {deleted_count} deleted events for user {user.email}")
        else:
            logger.info(f"No deleted events found for user {user.email}")
        
    except Exception as e:
        logger.error(f"Error syncing calendar events for deletion for user {user.email}: {str(e)}")
        db.session.rollback()
        sentry_sdk.capture_exception(e)

@google_webhook.route("/webhook/google-calendar/setup", methods=["POST"])
def setup_calendar_webhook():
    """
    Set up a webhook subscription for a user's Calendar Autobot calendar.
    This should be called after creating the calendar for a user.
    """
    try:
        from flask_login import login_required, current_user
        from google_calendar import refresh_google_token
        import requests
        import uuid
        
        # This endpoint requires authentication
        if not hasattr(current_user, 'id') or not current_user.is_authenticated:
            return jsonify({"error": "Authentication required"}), 401
        
        # Get user's calendar ID
        calendar_id = current_user.textbot_calendar_id
        if not calendar_id:
            return jsonify({"error": "No Calendar Autobot calendar found for user"}), 400
        
        # Get a fresh access token
        access_token = refresh_google_token(current_user)
        if not access_token:
            return jsonify({"error": "Could not refresh Google token"}), 401
        
        # Create webhook subscription
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Generate unique channel ID
        channel_id = f"cal-autobot-{current_user.id}-{uuid.uuid4().hex[:8]}"
        
        # Get the webhook URL from environment or request
        webhook_url = os.environ.get('WEBHOOK_BASE_URL', request.url_root.rstrip('/'))
        webhook_endpoint = f"{webhook_url}/webhook/google-calendar"
        
        watch_request = {
            "id": channel_id,
            "type": "web_hook",
            "address": webhook_endpoint,
            "token": f"cal-autobot-{current_user.id}",
            # Set expiration to 7 days (max allowed)
            "expiration": int((datetime.utcnow().timestamp() + 7 * 24 * 3600) * 1000)
        }
        
        url = f'https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/watch'
        response = requests.post(url, headers=headers, json=watch_request, timeout=30)
        
        if response.status_code == 200:
            webhook_data = response.json()
            logger.info(f"Successfully set up webhook for user {current_user.email}: {webhook_data}")
            
            # Store webhook info in user record for future reference
            # You might want to add webhook fields to the User model
            
            return jsonify({
                "status": "success",
                "channel_id": webhook_data.get('id'),
                "resource_id": webhook_data.get('resourceId'),
                "expiration": webhook_data.get('expiration')
            }), 200
        else:
            logger.error(f"Failed to set up webhook for user {current_user.email}: {response.status_code} - {response.text}")
            return jsonify({"error": "Failed to create webhook subscription"}), 500
        
    except Exception as e:
        logger.error(f"Error setting up calendar webhook: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"error": "Internal server error"}), 500

@google_webhook.route("/webhook/google-calendar/test", methods=["GET", "POST"])
def test_google_calendar_webhook():
    """Test endpoint for Google Calendar webhook configuration"""
    
    if request.method == "GET":
        return jsonify({
            "status": "Google Calendar webhook endpoint is active",
            "endpoint": "/webhook/google-calendar",
            "methods": ["POST"],
            "timestamp": datetime.utcnow().isoformat()
        }), 200
    
    # Handle POST request as a test webhook
    logger.info("Test webhook received")
    logger.info(f"Headers: {dict(request.headers)}")
    logger.info(f"Body: {request.get_data(as_text=True)}")
    
    return jsonify({
        "status": "test webhook received",
        "headers": dict(request.headers),
        "timestamp": datetime.utcnow().isoformat()
    }), 200