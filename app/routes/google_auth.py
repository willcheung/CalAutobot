# Use this Flask blueprint for Google authentication. Do not use flask-dance.

import json
import os

import requests
from app import db
from flask import Blueprint, redirect, render_template, request, url_for, session
from flask_login import current_user, login_required, login_user, logout_user
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


BASIC_SCOPES = ["openid", "email", "profile"]
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


@google_auth.route("/google_login")
def login():
    google_provider_cfg = requests.get(GOOGLE_DISCOVERY_URL).json()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    # Store timezone in session for later use during user creation
    timezone = request.args.get('timezone', 'UTC')
    session['user_timezone'] = timezone

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
    if not user or not user.google_id:
        logger.info("Rejected closed signup attempt for %s", users_email)
        session.pop('signup_email', None)
        session.pop('in_onboarding', None)
        return render_template("signup_closed.html"), 403

    old_timezone = user.timezone or 'UTC'

    # Never update timezone for existing users - they can change it in settings.
    if profile_picture:
        user.profile_picture_url = profile_picture

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

    login_user(user)

    gained_calendar_access = bool(user.google_token) and not had_calendar_access

    # Auto-sync events when an existing customer grants calendar access.
    if gained_calendar_access:
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
            # Don't fail the calendar connection process if sync fails

    # Check if user is in onboarding flow (via session flag)
    in_onboarding = session.get('in_onboarding', False)
    
    if in_onboarding:
        logger.info("Redirecting existing customer %s back to onboarding", users_email)
        return redirect(url_for("onboarding_routes.onboarding"))
    
    return redirect(url_for("main_routes.bookings"))




@google_auth.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main_routes.index"))
