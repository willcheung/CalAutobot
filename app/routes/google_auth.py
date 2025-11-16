# Use this Flask blueprint for Google authentication. Do not use flask-dance.

import json
import os

import requests
from app import db
from flask import Blueprint, redirect, request, url_for, session
from flask_login import current_user, login_required, login_user, logout_user
from app.models import User, Event
from app.services.event_types import create_event_type
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


BASIC_SCOPES = ["openid", "email", "profile"]
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


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

    full_access = request.args.get('full') == '1'
    if full_access:
        session['oauth_flow'] = 'calendar'
        request_uri = client.prepare_request_uri(
            authorization_endpoint,
            redirect_uri=request.url_root.rstrip('/') + REDIRECT_URL,
            scope=BASIC_SCOPES + [CALENDAR_SCOPE],
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
    else:
        session['oauth_flow'] = 'basic'
        request_uri = client.prepare_request_uri(
            authorization_endpoint,
            redirect_uri=request.url_root.rstrip('/') + REDIRECT_URL,
            scope=BASIC_SCOPES,
            include_granted_scopes="true",
            prompt="select_account",
        )
    return redirect(request_uri)


@google_auth.route("/google_login/calendar")
@login_required
def connect_calendar():
    google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    timezone = request.args.get('timezone') or current_user.timezone or 'UTC'
    session['user_timezone'] = timezone
    session['oauth_flow'] = 'calendar'

    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=request.url_root.rstrip('/') + REDIRECT_URL,
        scope=BASIC_SCOPES + [CALENDAR_SCOPE],
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
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
        users_name = userinfo.get("name") or userinfo.get("given_name") or userinfo["email"]
        google_id = userinfo["sub"]
        profile_picture = userinfo.get("picture")
    else:
        return "User email not available or not verified by Google.", 400

    oauth_flow = session.pop('oauth_flow', 'basic')

    # Get timezone from session
    user_timezone = session.get('user_timezone', 'UTC')

    # Initialize logging for this function
    import logging
    logger = logging.getLogger(__name__)

    user = User.query.filter_by(email=users_email).first()
    is_provisional_user_signup = False  # Track if this is a provisional user upgrading
    old_timezone = (user.timezone if user else None) or 'UTC'
    
    if not user:
        user = User()
        user.username = users_name
        user.email = users_email
        user.google_id = google_id
        user.timezone = user_timezone
        if profile_picture:
            user.profile_picture_url = profile_picture
        user.email_count = 0  # Real users have no email limit
        db.session.add(user)
        logger.info(f"Created new user {users_email} with timezone {user_timezone}")
        is_new_user = True
    else:
        # Check if this is a provisional user (no google_id) converting to real user
        is_provisional_user_signup = (user.google_id is None)
        is_new_user = False
        
        # Never update timezone for existing users - they can change it in settings
        
        if is_provisional_user_signup:
            # Upgrade provisional user to real authenticated user
            user.google_id = google_id
            user.username = users_name
            user.email_count = 0  # Reset email count - real users have no limit
            logger.info(f"✅ Upgraded provisional user {users_email} to authenticated user")
    if profile_picture:
        user.profile_picture_url = profile_picture

    has_existing_event_types = bool(user.event_types)

    if not user.handle:
        assign_unique_handle(user, users_name)

    had_calendar_access = bool(user.google_token)
    received_calendar_scope = CALENDAR_SCOPE in (token_data.get('scope') or '')

    if oauth_flow == 'calendar' or received_calendar_scope:
        user.google_token = json.dumps(token_data)
        if token_data.get('refresh_token'):
            user.google_refresh_token = token_data.get('refresh_token')
            logger.info(f"Stored refresh token for user {users_email}")
    elif not had_calendar_access:
        # Ensure we don't leave a stale token if the user revoked access
        user.google_token = None
        user.google_refresh_token = None

    db.session.commit()

    # Create a default event type for new users
    should_create_default_event_type = is_new_user or (is_provisional_user_signup and not has_existing_event_types)

    if should_create_default_event_type:
        try:
            create_event_type(
                user_id=user.id,
                title="30 min chat",
                duration_minutes=30,
                description="",
                slug=None,
                is_public=True,
            )
            logger.info(
                "Created default event type for user %s (reason: %s)",
                users_email,
                "new_signup" if is_new_user else "provisional_upgrade",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to create default event type for user %s: %s",
                users_email,
                exc,
            )

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

    gained_calendar_access = bool(user.google_token) and not had_calendar_access

    # Auto-sync events for provisional users who just signed up or anyone who just granted calendar access
    if is_provisional_user_signup or gained_calendar_access:
        try:
            from app.services.google_calendar import create_calendar_event
            from app.helpers.event_utils import prepare_event_data_for_calendar
            from datetime import datetime
            import pytz
            import logging
            logger = logging.getLogger(__name__)
            
            logger.info(
                "✅ User %s gained calendar access, auto-syncing existing events",
                users_email,
            )
            
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

    # Check if user is in onboarding flow (via session flag)
    in_onboarding = session.get('in_onboarding', False)
    
    # Redirect to onboarding for:
    # 1. New users or provisional upgrades
    # 2. Users who are currently in the onboarding flow (e.g., connecting calendar from onboarding page)
    if is_new_user or is_provisional_user_signup or in_onboarding:
        logger.info(f"Redirecting {users_email} to onboarding (is_new_user={is_new_user}, is_provisional={is_provisional_user_signup}, in_onboarding={in_onboarding})")
        return redirect(url_for("onboarding_routes.onboarding"))
    
    return redirect(url_for("main_routes.bookings"))




@google_auth.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main_routes.index"))
