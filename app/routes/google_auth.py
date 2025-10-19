# Use this Flask blueprint for Google authentication. Do not use flask-dance.

import json
import os

import requests
from app import db
from flask import Blueprint, redirect, request, url_for, session
from flask_login import login_required, login_user, logout_user
from app.models import User, Event
from app.services.users import assign_unique_handle
from oauthlib.oauth2 import WebApplicationClient

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID",
                                  "your-google-client-id")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET",
                                      "your-google-client-secret")
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

# Use relative redirect URL - Flask will handle the domain automatically
REDIRECT_URL = "/google_login/callback"

client = WebApplicationClient(GOOGLE_CLIENT_ID)

google_auth = Blueprint("google_auth", __name__)


@google_auth.route("/google_login")
def login():
    google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    # Store timezone in session for later use during user creation
    timezone = request.args.get('timezone', 'UTC')
    session['user_timezone'] = timezone

    # Store email parameter for new user signup flow
    email = request.args.get('email')
    if email:
        session['signup_email'] = email

    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=request.url_root.rstrip('/') + REDIRECT_URL,
        scope=[
            "email",
            "https://www.googleapis.com/auth/calendar"
        ],
        access_type="offline",  # Request offline access to get refresh token
        prompt="consent"  # Only prompt for account selection, not consent for returning users
    )
    return redirect(request_uri)


@google_auth.route("/google_login/callback")
def callback():
    code = request.args.get("code")
    google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
    token_endpoint = google_provider_cfg["token_endpoint"]

    token_url, headers, body = client.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=request.url_root.rstrip('/') + REDIRECT_URL,
        code=code,
    )
    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET),
    )

    # Store the token for Google Calendar API access
    token_data = token_response.json()

    client.parse_request_body_response(json.dumps(token_data))

    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = client.add_token(userinfo_endpoint)
    userinfo_response = requests.get(uri, headers=headers, data=body)

    userinfo = userinfo_response.json()
    if userinfo.get("email_verified"):
        users_email = userinfo["email"]
        users_name = userinfo["email"]  # Use email as username instead of given_name
        google_id = userinfo["sub"]
    else:
        return "User email not available or not verified by Google.", 400

    # Get timezone from session
    user_timezone = session.get('user_timezone', 'UTC')

    # Initialize logging for this function
    import logging
    logger = logging.getLogger(__name__)

    user = User.query.filter_by(email=users_email).first()
    is_provisional_user_signup = False  # Track if this is a provisional user upgrading
    old_timezone = None  # Track old timezone for event conversion
    
    if not user:
        user = User()
        user.username = users_name
        user.email = users_email
        user.google_id = google_id
        user.timezone = user_timezone
        user.email_count = 0  # Real users have no email limit
        db.session.add(user)
        logger.info(f"Created new user {users_email} with timezone {user_timezone}")
    else:
        # Check if this is a provisional user (no google_id) converting to real user
        is_provisional_user_signup = (user.google_id is None)
        
        # Capture old timezone before updating (needed for event conversion)
        old_timezone = user.timezone
        
        # Only update timezone if it's different (optimization)
        if user.timezone != user_timezone:
            user.timezone = user_timezone
            logger.info(f"Updated timezone for user {users_email}: {old_timezone} -> {user_timezone}")
        
        if is_provisional_user_signup:
            # Upgrade provisional user to real authenticated user
            user.google_id = google_id
            user.username = users_name
            user.email_count = 0  # Reset email count - real users have no limit
            logger.info(f"✅ Upgraded provisional user {users_email} to authenticated user")

    if not user.handle:
        assign_unique_handle(user, users_name)

    # Update the Google token for Calendar API access
    user.google_token = json.dumps(token_data)

    # Save refresh token separately for better management
    if token_data.get('refresh_token'):
        user.google_refresh_token = token_data.get('refresh_token')
        logger.info(f"Stored refresh token for user {users_email}")

    db.session.commit()

    login_user(user)

    # Check if this is a new signup from email invitation
    signup_email = session.get('signup_email')
    if signup_email and signup_email == users_email:
        # Clear the signup email from session
        session.pop('signup_email', None)

        # Check for any pending events that were extracted from their email
        # This could be implemented by storing temporary events in a separate table
        # or by re-processing their recent emails
        logger.info(f"New user {users_email} signed up after email invitation")

    # Auto-sync events for provisional users who just signed up
    if is_provisional_user_signup:
        try:
            from app.services.google_calendar import create_calendar_event
            from app.helpers.event_utils import prepare_event_data_for_calendar
            from datetime import datetime
            import pytz
            import logging
            logger = logging.getLogger(__name__)
            
            logger.info(f"✅ Provisional user {users_email} signed up, auto-syncing existing events")
            
            # Get user's unsynced events
            unsynced_events = Event.query.filter_by(user_id=user.id, is_synced=False).all()
            
            # Convert event times from UTC to user's timezone
            if old_timezone == 'UTC' and user_timezone != 'UTC' and unsynced_events:
                logger.info(f"Converting {len(unsynced_events)} events from UTC to {user_timezone}")
                user_tz = pytz.timezone(user_timezone)
                
                for event in unsynced_events:
                    # Convert start_datetime
                    if event.start_datetime:
                        try:
                            # Parse ISO format datetime string
                            utc_dt = datetime.fromisoformat(event.start_datetime.replace('Z', '+00:00'))
                            # Convert to user's timezone
                            local_dt = utc_dt.astimezone(user_tz)
                            event.start_datetime = local_dt.isoformat()
                        except Exception as e:
                            logger.warning(f"Failed to convert start_datetime for event {event.id}: {str(e)}")
                    
                    # Convert end_datetime
                    if event.end_datetime:
                        try:
                            utc_dt = datetime.fromisoformat(event.end_datetime.replace('Z', '+00:00'))
                            local_dt = utc_dt.astimezone(user_tz)
                            event.end_datetime = local_dt.isoformat()
                        except Exception as e:
                            logger.warning(f"Failed to convert end_datetime for event {event.id}: {str(e)}")
                
                # Commit timezone conversions
                db.session.commit()
                logger.info(f"✅ Converted event times from UTC to {user_timezone}")
            
            if unsynced_events:
                synced_count = 0
                for event in unsynced_events:
                    try:
                        event_data = prepare_event_data_for_calendar(event)
                        google_event_id = create_calendar_event(user, event_data, use_extraction_calendar=True)
                        
                        if google_event_id:
                            event.google_event_id = google_event_id
                            event.is_synced = True
                            synced_count += 1
                            logger.info(f"✅ Auto-synced event '{event.event_name}' for provisional user")
                    
                    except Exception as sync_error:
                        logger.warning(f"Failed to sync event '{event.event_name}': {str(sync_error)}")
                
                # Commit the sync updates
                db.session.commit()
                logger.info(f"✅ Auto-synced {synced_count}/{len(unsynced_events)} events for provisional user {users_email}")
            else:
                logger.info(f"No unsynced events found for provisional user {users_email}")
        
        except Exception as e:
            logger.error(f"Error auto-syncing events for provisional user {users_email}: {str(e)}")
            # Don't fail the signup process if sync fails

    return redirect(url_for("main_routes.dashboard"))




@google_auth.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main_routes.index"))
