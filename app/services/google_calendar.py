import json
import os
import logging
import uuid
from datetime import datetime, timedelta
import requests
from flask import current_app
import sentry_sdk

logger = logging.getLogger(__name__)

from app.services.calendar_notifications import notify_owner_calendar_issue


def _resolve_calendar_id(user, access_token, *, use_extraction_calendar=False, calendar_id=None):
    """Determine which calendar ID to use for Google Calendar operations."""
    if calendar_id:
        return calendar_id

    if use_extraction_calendar:
        return get_or_create_extraction_calendar(user, access_token)

    booking_calendar_id = getattr(user, "default_booking_calendar_id", None)
    if booking_calendar_id:
        return booking_calendar_id

    raise Exception(
        "No booking calendar configured. Please choose a calendar under Settings › Calendars."  # noqa: EM101
    )

# Database-stored calendar IDs replace caching for better reliability

def check_user_has_calendar_scope(user):
    """
    Check if user has granted the required Google Calendar scope.
    Since our OAuth flow requests calendar scope, if the user has a token,
    they have granted calendar permissions.

    Args:
        user: User object with google_token

    Returns:
        bool: True if user has calendar scope, False otherwise
    """
    if not user.google_token:
        return False

    try:
        token_data = json.loads(user.google_token)
        # If user has a stored token, they previously granted calendar access
        # since our OAuth flow in google_auth.py requests calendar scope
        return bool(token_data.get('access_token'))

    except json.JSONDecodeError:
        logger.error("Invalid Google token data stored")
        return False
    except Exception as e:
        logger.error(f"Error checking calendar scope: {str(e)}")
        return False

def fetch_user_calendar_list(user, min_access_role="reader"):
    """
    Fetch the list of calendars the user has granted access to.

    Args:
        user: User object with Google token
        min_access_role: Minimum access level to include in results

    Returns:
        list: List of calendar dicts from Google Calendar API
    """
    access_token = refresh_google_token(user)

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json',
    }

    calendars = []
    page_token = None

    try:
        while True:
            params = {
                'minAccessRole': min_access_role,
                'showDeleted': 'false',
                'maxResults': 250,
            }
            if page_token:
                params['pageToken'] = page_token

            response = requests.get(
                'https://www.googleapis.com/calendar/v3/users/me/calendarList',
                headers=headers,
                params=params,
                timeout=15,
            )

            if response.status_code == 200:
                data = response.json()
                calendars.extend(data.get('items', []))
                page_token = data.get('nextPageToken')
                if not page_token:
                    break
            elif response.status_code == 401:
                logger.error("Google Calendar authentication failed when listing calendars")
                raise Exception("Google Calendar authentication failed. Please sign in again.")
            elif response.status_code == 403:
                logger.error("Permission denied when fetching calendar list")
                raise Exception("Permission denied. Please re-connect Google Calendar access.")
            else:
                logger.error(f"Failed to fetch calendar list: {response.status_code} - {response.text}")
                raise Exception("Unable to fetch calendars from Google. Please try again.")
    except requests.exceptions.Timeout:
        logger.error("Timeout while fetching user calendar list")
        raise Exception("Google Calendar request timed out. Please try again.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching calendar list: {str(e)}")
        raise Exception("Network error fetching calendars. Please check your connection.")

    return calendars


def fetch_freebusy(user, calendar_ids, time_min: datetime, time_max: datetime):
    """
    Fetch busy periods for the given calendars between time_min and time_max.

    Returns a mapping of calendar_id -> {'busy': [{'start': iso, 'end': iso}, ...]}
    """
    if not calendar_ids:
        return {}

    access_token = refresh_google_token(user)

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }
    body = {
        'timeMin': time_min.isoformat(),
        'timeMax': time_max.isoformat(),
        'items': [{'id': calendar_id} for calendar_id in calendar_ids],
    }

    try:
        response = requests.post(
            'https://www.googleapis.com/calendar/v3/freeBusy',
            headers=headers,
            data=json.dumps(body),
            timeout=15,
        )
    except requests.exceptions.Timeout:
        logger.error("Timeout while fetching Google free/busy data")
        raise Exception("Google Calendar request timed out. Please try again.")
    except requests.exceptions.RequestException as exc:
        logger.error("Error fetching Google free/busy data: %s", exc)
        raise Exception("Unable to fetch busy calendar data. Please try again.")

    if response.status_code == 200:
        data = response.json()
        return data.get('calendars', {})
    elif response.status_code in {400, 401, 403}:
        logger.error(
            "Google free/busy request failed (%s): %s",
            response.status_code,
            response.text,
        )
        raise Exception("Google Calendar access failed. Please refresh your connection.")
    else:
        logger.error(
            "Unexpected Google free/busy error (%s): %s",
            response.status_code,
            response.text,
        )
        raise Exception("Unable to fetch calendar availability from Google.")

def refresh_google_token(user):
    """
    Refresh Google OAuth token if needed.

    Args:
        user: User object with google_token

    Returns:
        str: Valid access token
    """
    if not user.google_token:
        raise Exception("Please sign in with Google to sync events to your calendar")

    try:
        from app import db
        token_data = json.loads(user.google_token)
        access_token = token_data.get('access_token')
        # Check both the JSON and the separate column for refresh token
        refresh_token = token_data.get('refresh_token') or user.google_refresh_token

        logger.info(f"Token data keys: {list(token_data.keys())}")
        logger.info(f"Has refresh token in JSON: {bool(token_data.get('refresh_token'))}")
        logger.info(f"Has refresh token in column: {bool(user.google_refresh_token)}")
        logger.info(f"Using refresh token: {bool(refresh_token)}")

        if not access_token:
            raise Exception("Invalid Google authentication. Please sign in again")

        # Test the current token by checking if we can access the calendar service
        # Using the tokeninfo endpoint to validate the token without requiring calendar permissions
        test_response = requests.get(
            f'https://www.googleapis.com/oauth2/v1/tokeninfo?access_token={access_token}',
            timeout=10
        )

        if test_response.status_code == 200:
            # Token is still valid, check if it has the right scope
            token_info = test_response.json()
            if 'scope' in token_info and 'calendar' in token_info['scope']:
                return access_token
            else:
                logger.warning("Token doesn't have required calendar scope, attempting refresh")

        # If token is invalid or doesn't have proper scope, attempt refresh
        if refresh_token:
            # Token expired, try to refresh it
            logger.info("Access token expired, attempting to refresh")
            logger.info(f"Using refresh token: {refresh_token[:10]}...")

            refresh_data = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': os.environ.get('GOOGLE_OAUTH_CLIENT_ID'),
                'client_secret': os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET'),
            }

            refresh_response = requests.post(
                'https://oauth2.googleapis.com/token',
                data=refresh_data,
                timeout=10
            )

            logger.info(f"Refresh response status: {refresh_response.status_code}")
            if refresh_response.status_code != 200:
                logger.error(f"Refresh response error: {refresh_response.text}")

            if refresh_response.status_code == 200:
                new_token_data = refresh_response.json()

                # Update token data while preserving refresh token
                token_data['access_token'] = new_token_data['access_token']
                if 'refresh_token' in new_token_data:
                    token_data['refresh_token'] = new_token_data['refresh_token']

                # Save updated token to database
                user.google_token = json.dumps(token_data)
                db.session.commit()

                logger.info("Successfully refreshed Google access token")
                return new_token_data['access_token']
            else:
                logger.error(f"Failed to refresh token: {refresh_response.status_code}")
                raise Exception("Google authentication has expired. Please sign in again")
        else:
            # No refresh token or other error
            if test_response.status_code == 401 or test_response.status_code == 400:
                if not refresh_token:
                    logger.warning("No refresh token available, user needs to re-authenticate")
                    logger.warning("This usually happens when user granted permissions without offline access")
                    raise Exception("Google Calendar access expired. Please use 'Refresh Google Access' to restore calendar sync")
                else:
                    logger.error("Token refresh failed or other auth issue")
                    logger.error(f"Refresh token present but failed: {refresh_token[:10] if refresh_token else 'None'}...")
                    raise Exception("Google authentication has expired. Please use 'Refresh Google Access' to sign in again")
            else:
                logger.error(f"Calendar API error: {test_response.status_code} - {test_response.text}")
                raise Exception("Unable to access Google Calendar. Please check your permissions")

    except json.JSONDecodeError:
        raise Exception("Invalid Google authentication data. Please sign in again")
    except requests.exceptions.Timeout:
        raise Exception("Connection timeout. Please try again")
    except Exception as e:
        if "sign in" in str(e).lower() or "expired" in str(e).lower():
            raise e
        else:
            logger.error(f"Unexpected error in token refresh: {str(e)}")
            raise Exception("Google authentication issue. Please sign in again")

def get_or_create_extraction_calendar(user, access_token):
    """
    Get stored extraction calendar ID or create a new one if needed.
    Validates existing calendar ID and creates a new one if invalid.

    Args:
        user: User object with extraction_calendar_id
        access_token: Valid Google access token

    Returns:
        str: Calendar ID for the Cal Event Extraction calendar
    """
    from app import db

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    # Check if user already has a stored calendar ID and validate it
    if user.extraction_calendar_id:
        logger.info(
            "Validating stored Cal Event Extraction calendar ID: %s",
            user.extraction_calendar_id,
        )

        try:
            # Test if the stored calendar ID is still valid
            test_response = requests.get(
                f'https://www.googleapis.com/calendar/v3/calendars/{user.extraction_calendar_id}',
                headers=headers,
                timeout=10
            )

            if test_response.status_code == 200:
                logger.info("Stored calendar ID is valid, using it")
                return user.extraction_calendar_id
            else:
                logger.warning(f"Stored calendar ID is invalid (status {test_response.status_code}), will create new calendar")
                user.extraction_calendar_id = None  # Clear invalid ID

        except Exception as e:
            logger.warning(f"Error validating stored calendar ID: {str(e)}, will create new calendar")
            user.extraction_calendar_id = None  # Clear invalid ID

    try:
        # Create new Cal Event Extraction calendar since user doesn't have one stored or it's invalid
        logger.info("Creating new Cal Event Extraction calendar for user")
        calendar_data = {
            'summary': 'Cal Event Extraction',
            'description': 'AI-generated calendar events from email extraction',
            'timeZone': user.timezone
        }

        response = requests.post(
            'https://www.googleapis.com/calendar/v3/calendars',
            headers=headers,
            data=json.dumps(calendar_data),
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            calendar_id = result.get('id')

            # Store the calendar ID in the user's record
            user.extraction_calendar_id = calendar_id
            db.session.commit()

            logger.info(f"Successfully created and stored Cal Event Extraction calendar with ID: {calendar_id}")
            
            # Set up webhook for this calendar
            try:
                setup_calendar_webhook_for_user(user, access_token, calendar_id)
            except Exception as webhook_error:
                logger.warning(f"Failed to set up webhook for calendar {calendar_id}: {str(webhook_error)}")
                # Don't fail calendar creation if webhook setup fails
            
            return calendar_id
        else:
            logger.error(f"Failed to create Cal Event Extraction calendar: {response.status_code} - {response.text}")
            raise Exception("Failed to create Cal Event Extraction calendar")

    except requests.exceptions.Timeout:
        logger.error("Timeout while creating Cal Event Extraction calendar")
        raise Exception("Calendar operation timed out. Please try again.")
    except Exception as e:
        logger.error(f"Error creating Cal Event Extraction calendar: {str(e)}")
        raise Exception("Failed to create calendar. Please try again.")

def _extract_conference_url(event_payload: dict) -> str | None:
    """Attempt to pull a primary video conferencing URL from a Google event response."""
    conference_url = event_payload.get("hangoutLink")
    if conference_url:
        return conference_url

    conference_data = event_payload.get("conferenceData") or {}
    entry_points = conference_data.get("entryPoints") or []
    for entry in entry_points:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    return None


def create_calendar_event(
    user,
    event_data,
    use_extraction_calendar=False,
    calendar_id=None,
    add_google_meet: bool = False,
    return_conference_link: bool = False,
):
    """
    Create an event in Google Calendar.

    Args:
        user: User object with Google token
        event_data: Dictionary with event details
        use_extraction_calendar: Whether to use the extraction calendar
        calendar_id: Optional explicit calendar id override
        add_google_meet: Whether to request Google Meet conference data
        return_conference_link: When True, return a tuple of (event_id, conference_url)

    Returns:
        str | tuple[str, str | None]: Google event ID (and optional conference URL)
    """
    try:
        logger.info(f"Creating calendar event: {event_data.get('event_name', 'Unnamed Event')}")
        access_token = refresh_google_token(user)

        target_calendar_id = _resolve_calendar_id(
            user,
            access_token,
            use_extraction_calendar=use_extraction_calendar,
            calendar_id=calendar_id,
        )



        # Use combined datetime fields if available, otherwise fall back to separate date/time
        if event_data.get('start_datetime') and event_data.get('end_datetime'):
            start_datetime = event_data['start_datetime']
            end_datetime = event_data['end_datetime']
            logger.info(f"Using combined datetime fields: start={start_datetime}, end={end_datetime}")
        else:
            # Fallback to separate date/time fields for backward compatibility
            start_datetime = event_data['start_date']
            end_datetime = event_data.get('end_date', event_data['start_date'])

            # Add time if specified
            if event_data.get('start_time'):
                start_datetime += f"T{event_data['start_time']}:00"
            else:
                start_datetime += "T09:00:00"  # Default to 9 AM

            if event_data.get('end_time'):
                end_datetime += f"T{event_data['end_time']}:00"
            else:
                # Default to 1 hour duration if no end time specified
                if event_data.get('start_time'):
                    start_time = datetime.strptime(event_data['start_time'], '%H:%M')
                    end_time = start_time + timedelta(hours=1)
                    end_datetime += f"T{end_time.strftime('%H:%M')}:00"
                else:
                    end_datetime += "T10:00:00"  # Default to 10 AM
            logger.info(f"Using separate date/time fields: start={start_datetime}, end={end_datetime}")

        # Create the calendar event
        calendar_event = {
            "summary": event_data['event_name'],
            "description": event_data.get('event_description', ''),
            "start": {
                "dateTime": start_datetime,
                "timeZone": user.timezone
            },
            "end": {
                "dateTime": end_datetime,
                "timeZone": user.timezone
            }
        }

        # Add location if specified
        if event_data.get('location'):
            calendar_event["location"] = event_data['location']

        # Add attendees if provided
        attendees = event_data.get('attendees') or []
        if attendees:
            calendar_event["attendees"] = []
            for attendee_email in attendees:
                attendee_entry = {"email": attendee_email}
                if attendee_email.lower() == (user.email or "").lower():
                    attendee_entry["responseStatus"] = "accepted"
                calendar_event["attendees"].append(attendee_entry)

        # Make API request to Google Calendar
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        params = {"sendUpdates": "all"}
        if add_google_meet:
            calendar_event["conferenceData"] = {
                "createRequest": {
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    "requestId": uuid.uuid4().hex,
                }
            }
            params["conferenceDataVersion"] = 1

        logger.info("Making request to Google Calendar API")
        response = requests.post(
            f'https://www.googleapis.com/calendar/v3/calendars/{target_calendar_id}/events',
            headers=headers,
            params=params,
            data=json.dumps(calendar_event),
            timeout=30
        )

        if response.status_code in {400, 403} and add_google_meet:
            logger.warning(
                "Google Meet creation failed (%s); retrying without conference data",
                response.status_code,
            )
            calendar_event.pop("conferenceData", None)
            params = {"sendUpdates": "all"}
            response = requests.post(
                f'https://www.googleapis.com/calendar/v3/calendars/{target_calendar_id}/events',
                headers=headers,
                params=params,
                data=json.dumps(calendar_event),
                timeout=30
            )

        if response.status_code == 200:
            result = response.json()
            event_id = result.get('id')
            logger.info(f"Successfully created calendar event with ID: {event_id}")
            if return_conference_link:
                conference_url = _extract_conference_url(result)
                return event_id, conference_url
            return event_id
        elif response.status_code == 401:
            logger.error("Google Calendar authentication failed")
            sentry_sdk.capture_message("Google Calendar authentication failed", level="error")
            raise Exception("Google Calendar authentication failed. Please sign in again.")
        elif response.status_code == 403:
            logger.error("Google Calendar permission denied")
            sentry_sdk.capture_message("Google Calendar permission denied", level="error")
            raise Exception("Permission denied. Please ensure Google Calendar access is granted.")
        elif response.status_code == 429:
            logger.warning("Google Calendar rate limit exceeded")
            sentry_sdk.capture_message("Google Calendar rate limit exceeded", level="warning")
            raise Exception("Google Calendar is temporarily busy. Please try again in a moment.")
        else:
            logger.error(f"Google Calendar API error {response.status_code}: {response.text}")
            sentry_sdk.capture_message(f"Google Calendar API error: {response.status_code}", level="error")
            raise Exception(f"Failed to create calendar event. Please try again.")

    except requests.exceptions.Timeout:
        logger.error("Google Calendar API timeout")
        sentry_sdk.capture_message("Google Calendar API timeout", level="error")
        raise Exception("Google Calendar request timed out. Please try again.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error with Google Calendar API: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise Exception("Network error connecting to Google Calendar. Please check your connection.")
    except Exception as e:
        error_text = str(e)
        logger.error("Unexpected error creating calendar event: %s", error_text)
        sentry_sdk.capture_exception(e)
        if "Please sign in with Google" in error_text or "Invalid Google authentication" in error_text:
            notify_owner_calendar_issue(user, "calendar_access_error")
        raise Exception(f"Failed to create calendar event: {error_text}")


def _delete_calendar_event_impl(user, google_event_id, use_extraction_calendar=False, calendar_id=None):
    """Delete an event from the user's calendar if we have the ID."""
    if not google_event_id:
        return

    access_token = refresh_google_token(user)
    target_calendar_id = _resolve_calendar_id(
        user,
        access_token,
        use_extraction_calendar=use_extraction_calendar,
        calendar_id=calendar_id,
    )

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.delete(
            f'https://www.googleapis.com/calendar/v3/calendars/{target_calendar_id}/events/{google_event_id}',
            headers=headers,
            timeout=15,
        )
        if response.status_code in (200, 204, 410):
            logger.info("Deleted Google Calendar event %s", google_event_id)
            return
        elif response.status_code == 404:
            logger.info("Google Calendar event %s already removed", google_event_id)
            return
        elif response.status_code == 401:
            logger.warning("Google Calendar auth failed when deleting %s", google_event_id)
        else:
            logger.warning("Failed to delete Google Calendar event %s: %s - %s", google_event_id, response.status_code, response.text)
    except requests.exceptions.RequestException as exc:
        logger.warning("Network error deleting Google Calendar event %s: %s", google_event_id, exc)

def update_calendar_event(user, google_event_id, event_data, use_extraction_calendar=False, calendar_id=None):
    """Update an existing event in Google Calendar."""
    if not google_event_id:
        return False

    try:
        access_token = refresh_google_token(user)
        target_calendar_id = _resolve_calendar_id(
            user,
            access_token,
            use_extraction_calendar=use_extraction_calendar,
            calendar_id=calendar_id,
        )

        if event_data.get('start_datetime') and event_data.get('end_datetime'):
            start_datetime = event_data['start_datetime']
            end_datetime = event_data['end_datetime']
        else:
            start_datetime = event_data['start_date']
            end_datetime = event_data.get('end_date', event_data['start_date'])

            if event_data.get('start_time'):
                start_datetime += f"T{event_data['start_time']}:00"
            else:
                start_datetime += "T09:00:00"

            if event_data.get('end_time'):
                end_datetime += f"T{event_data['end_time']}:00"
            else:
                if event_data.get('start_time'):
                    start_time = datetime.strptime(event_data['start_time'], '%H:%M')
                    end_time = start_time + timedelta(hours=1)
                    end_datetime += f"T{end_time.strftime('%H:%M')}:00"
                else:
                    end_datetime += "T10:00:00"

        calendar_event = {
            "summary": event_data['event_name'],
            "description": event_data.get('event_description', ''),
            "start": {
                "dateTime": start_datetime,
                "timeZone": user.timezone,
            },
            "end": {
                "dateTime": end_datetime,
                "timeZone": user.timezone,
            },
        }

        if event_data.get('location'):
            calendar_event["location"] = event_data['location']

        attendees = event_data.get('attendees') or []
        if attendees:
            calendar_event["attendees"] = [{"email": email} for email in attendees]

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

        response = requests.put(
            f'https://www.googleapis.com/calendar/v3/calendars/{target_calendar_id}/events/{google_event_id}',
            headers=headers,
            data=json.dumps(calendar_event),
            timeout=30,
        )

        if response.status_code in (200, 204):
            logger.info(f"Successfully updated calendar event {google_event_id}")
            return True
        if response.status_code == 404:
            logger.warning(f"Calendar event {google_event_id} not found during update")
            return False

        logger.error(
            "Failed to update calendar event %s: %s - %s",
            google_event_id,
            response.status_code,
            response.text,
        )
        return False

    except requests.exceptions.RequestException as exc:
        logger.error("Network error updating calendar event %s: %s", google_event_id, exc)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error updating calendar event: {str(exc)}")
        return False


def delete_calendar_event(user, google_event_id, use_extraction_calendar=False, calendar_id=None):
    try:
        _delete_calendar_event_impl(
            user,
            google_event_id,
            use_extraction_calendar=use_extraction_calendar,
            calendar_id=calendar_id,
        )
        return True
    except Exception as exc:
        error_text = str(exc)
        logger.error(f"Error deleting calendar event: {error_text}")
        if "Please sign in with Google" in error_text or "Invalid Google authentication" in error_text:
            notify_owner_calendar_issue(user, "calendar_access_error")
        return False


def setup_calendar_webhook_for_user(user, access_token, calendar_id):
    """
    Set up a Google Calendar webhook for event change notifications.
    
    Args:
        user: User object to set up webhook for
        access_token: Valid Google access token
        calendar_id: Calendar ID to watch for changes
    
    Returns:
        dict: Webhook response data if successful
    """
    try:
        from app import db
        
        # Check if user already has an active webhook
        if user.webhook_channel_id and user.webhook_expiration:
            # Check if webhook is still valid (not expired)
            if user.webhook_expiration > datetime.utcnow():
                logger.info(f"User {user.email} already has active webhook, skipping setup")
                return None
        
        # Generate unique channel ID
        channel_id = f"cal-autobot-{user.id}-{uuid.uuid4().hex[:8]}"
        
        # Get the webhook URL from environment or current app context
        webhook_url = os.environ.get('WEBHOOK_BASE_URL')
        if not webhook_url:
            from flask import request
            webhook_url = request.url_root.rstrip('/') if request else "https://your-domain.replit.app"
        
        webhook_endpoint = f"{webhook_url}/webhook/google-calendar"
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Set expiration to 7 days (max allowed by Google)
        expiration_time = datetime.utcnow() + timedelta(days=7)
        expiration_timestamp = int(expiration_time.timestamp() * 1000)
        
        watch_request = {
            "id": channel_id,
            "type": "web_hook",
            "address": webhook_endpoint,
            "token": f"cal-autobot-{user.id}",
            "expiration": expiration_timestamp
        }
        
        url = f'https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/watch'
        response = requests.post(url, headers=headers, json=watch_request, timeout=30)
        
        if response.status_code == 200:
            webhook_data = response.json()
            
            # Store webhook info in user record
            user.webhook_channel_id = webhook_data.get('id')
            user.webhook_resource_id = webhook_data.get('resourceId')
            user.webhook_expiration = expiration_time
            
            db.session.commit()
            
            logger.info(f"Successfully set up webhook for user {user.email}: channel_id={channel_id}")
            return webhook_data
        else:
            logger.error(f"Failed to set up webhook for user {user.email}: {response.status_code} - {response.text}")
            raise Exception(f"Failed to create webhook subscription: {response.status_code}")
        
    except Exception as e:
        logger.error(f"Error setting up calendar webhook for user {user.email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise e

def stop_calendar_webhook_for_user(user):
    """
    Stop an existing Google Calendar webhook for a user.
    
    Args:
        user: User object with webhook details
    
    Returns:
        bool: True if successful or no webhook to stop
    """
    try:
        if not user.webhook_channel_id or not user.webhook_resource_id:
            logger.info(f"No webhook to stop for user {user.email}")
            return True
        
        access_token = refresh_google_token(user)
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        stop_request = {
            "id": user.webhook_channel_id,
            "resourceId": user.webhook_resource_id
        }
        
        url = 'https://www.googleapis.com/calendar/v3/channels/stop'
        response = requests.post(url, headers=headers, json=stop_request, timeout=30)
        
        if response.status_code == 200 or response.status_code == 404:
            # Clear webhook info from user record
            user.webhook_channel_id = None
            user.webhook_resource_id = None
            user.webhook_expiration = None
            
            from app import db
            db.session.commit()
            
            logger.info(f"Successfully stopped webhook for user {user.email}")
            return True
        else:
            logger.warning(f"Failed to stop webhook for user {user.email}: {response.status_code} - {response.text}")
            return False
        
    except Exception as e:
        logger.error(f"Error stopping calendar webhook for user {user.email}: {str(e)}")
        return False
