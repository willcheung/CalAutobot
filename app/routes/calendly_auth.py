"""
Calendly OAuth integration for CalAutobot.

Handles OAuth flow for connecting user's Calendly account.
"""

import logging
import os
import requests
from datetime import datetime

from flask import Blueprint, redirect, request, url_for, flash, session
from flask_login import current_user, login_required

from app import db
from app.models import User

logger = logging.getLogger(__name__)

# Calendly OAuth configuration
CALENDLY_CLIENT_ID = os.environ.get("CALENDLY_CLIENT_ID", "")
CALENDLY_CLIENT_SECRET = os.environ.get("CALENDLY_CLIENT_SECRET", "")

# Calendly OAuth endpoints
CALENDLY_AUTHORIZE_URL = "https://auth.calendly.com/oauth/authorize"
CALENDLY_TOKEN_URL = "https://auth.calendly.com/oauth/token"
CALENDLY_API_BASE = "https://api.calendly.com"

calendly_auth = Blueprint("calendly_auth", __name__)


@calendly_auth.route("/auth/calendly")
@login_required
def connect():
    """Initiate Calendly OAuth flow."""
    if not CALENDLY_CLIENT_ID or not CALENDLY_CLIENT_SECRET:
        flash("Calendly integration is not configured. Please contact support.", "error")
        return redirect(url_for("onboarding_routes.onboarding"))

    # Build authorization URL
    redirect_uri = request.url_root.rstrip('/') + "/auth/calendly/callback"

    params = {
        "client_id": CALENDLY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
    }

    auth_url = f"{CALENDLY_AUTHORIZE_URL}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    return redirect(auth_url)


@calendly_auth.route("/auth/calendly/callback")
@login_required
def callback():
    """Handle Calendly OAuth callback."""
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        flash(f"Calendly authorization failed: {error}", "error")
        return redirect(url_for("onboarding_routes.onboarding"))

    if not code:
        flash("No authorization code received from Calendly.", "error")
        return redirect(url_for("onboarding_routes.onboarding"))

    # Exchange code for access token
    redirect_uri = request.url_root.rstrip('/') + "/auth/calendly/callback"

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": CALENDLY_CLIENT_ID,
        "client_secret": CALENDLY_CLIENT_SECRET,
    }

    try:
        token_response = requests.post(CALENDLY_TOKEN_URL, data=token_data, timeout=10)
        token_response.raise_for_status()
        token_json = token_response.json()
    except requests.RequestException as e:
        flash(f"Failed to exchange authorization code: {str(e)}", "error")
        return redirect(url_for("onboarding_routes.onboarding"))

    access_token = token_json.get("access_token")
    refresh_token = token_json.get("refresh_token")

    if not access_token:
        flash("Failed to obtain access token from Calendly.", "error")
        return redirect(url_for("onboarding_routes.onboarding"))

    # Get user info from Calendly
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        user_response = requests.get(f"{CALENDLY_API_BASE}/users/me", headers=headers, timeout=10)
        user_response.raise_for_status()
        user_data = user_response.json()
    except requests.RequestException as e:
        flash(f"Failed to fetch user info from Calendly: {str(e)}", "error")
        return redirect(url_for("onboarding_routes.onboarding"))

    # Extract user information
    resource = user_data.get("resource", {})
    user_uri = resource.get("uri")
    organization_uri = resource.get("current_organization")
    scheduling_url = resource.get("scheduling_url")
    calendly_timezone = resource.get("timezone")  # e.g., "America/Los_Angeles"

    # Fetch organization details to get plan information
    calendly_plan = None
    if organization_uri:
        try:
            from app.services.calendly_api import CalendlyAPIClient
            # Ensure access token is set before instantiating client
            current_user.calendly_access_token = access_token
            client = CalendlyAPIClient(current_user)
            org_data = client.get_organization(organization_uri)

            # Log the full organization response for debugging
            logger.info(f"Calendly organization API response for user {current_user.id}: {org_data}")

            # Calendly plan might be in different fields depending on API version
            # Common field names: plan, tier, subscription_tier, plan_tier
            calendly_plan = (
                org_data.get("plan") or
                org_data.get("tier") or
                org_data.get("subscription_tier") or
                org_data.get("plan_tier") or
                "unknown"
            )
            logger.info(f"Extracted Calendly plan for user {current_user.id}: plan={calendly_plan}")
        except Exception as e:
            logger.warning(f"Failed to fetch Calendly organization details: {e}", exc_info=True)
            calendly_plan = "unknown"

    # Save to database
    current_user.calendly_access_token = access_token
    current_user.calendly_refresh_token = refresh_token
    current_user.calendly_user_uri = user_uri
    current_user.calendly_organization_uri = organization_uri
    current_user.calendly_scheduling_url = scheduling_url
    current_user.calendly_timezone = calendly_timezone
    current_user.calendly_plan = calendly_plan
    current_user.calendly_connected_at = datetime.utcnow()

    try:
        db.session.commit()
        flash("Successfully connected to Calendly!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to save Calendly connection: {str(e)}", "error")
        return redirect(url_for("onboarding_routes.onboarding"))

    # Sync event types from Calendly
    try:
        from app.services.sync_calendly import sync_calendly_event_types
        num_synced = sync_calendly_event_types(current_user)
        logger.info(f"Synced {num_synced} event types from Calendly for user {current_user.id}")
    except Exception as e:
        logger.warning(f"Failed to sync event types from Calendly: {e}")
        # Don't fail the connection if sync fails - user can manually sync later

    # Check if we're in onboarding flow
    if session.get('in_onboarding'):
        return redirect(url_for("onboarding_routes.onboarding"))
    else:
        return redirect(url_for("settings_routes.calendar_settings"))


@calendly_auth.route("/auth/calendly/sync", methods=["POST"])
@login_required
def sync_event_types():
    """Manually sync event types, plan, and timezone from Calendly."""
    if not current_user.calendly_access_token:
        flash("Calendly is not connected.", "error")
        return redirect(url_for("settings_routes.calendar_settings"))

    try:
        from app.services.sync_calendly import sync_calendly_event_types
        from app.services.calendly_api import CalendlyAPIClient

        client = CalendlyAPIClient(current_user)

        # Sync user info (timezone)
        try:
            user_data = client.get_current_user()
            resource = user_data.get("resource", {})
            calendly_timezone = resource.get("timezone")
            if calendly_timezone:
                current_user.calendly_timezone = calendly_timezone
                logger.info(f"Updated Calendly timezone for user {current_user.id}: {calendly_timezone}")
        except Exception as tz_err:
            logger.warning(f"Failed to update Calendly timezone for user {current_user.id}: {tz_err}", exc_info=True)

        # Sync plan information
        if current_user.calendly_organization_uri:
            try:
                org_data = client.get_organization(current_user.calendly_organization_uri)

                # Log the full organization response for debugging
                logger.info(f"Calendly organization API response for user {current_user.id}: {org_data}")

                calendly_plan = (
                    org_data.get("plan") or
                    org_data.get("tier") or
                    org_data.get("subscription_tier") or
                    org_data.get("plan_tier") or
                    "unknown"
                )
                current_user.calendly_plan = calendly_plan
                logger.info(f"Updated Calendly plan for user {current_user.id}: {calendly_plan}")
            except Exception as plan_err:
                logger.warning(f"Failed to update Calendly plan for user {current_user.id}: {plan_err}", exc_info=True)

        # Sync event types
        num_synced = sync_calendly_event_types(current_user)

        if num_synced == 0:
            flash("No event types found to sync from Calendly.", "warning")
        elif num_synced == 1:
            flash("Successfully synced 1 event type from Calendly.", "success")
        else:
            flash(f"Successfully synced {num_synced} event types from Calendly.", "success")

        logger.info(f"User {current_user.id} manually synced {num_synced} event types from Calendly")
    except Exception as e:
        logger.error(f"Failed to sync event types for user {current_user.id}: {e}", exc_info=True)
        flash(f"Failed to sync event types from Calendly: {str(e)}", "error")

    return redirect(url_for("settings_routes.calendar_settings"))


@calendly_auth.route("/auth/calendly/disconnect", methods=["POST"])
@login_required
def disconnect():
    """Disconnect Calendly account and clear all related data."""
    current_user.calendly_access_token = None
    current_user.calendly_refresh_token = None
    current_user.calendly_user_uri = None
    current_user.calendly_organization_uri = None
    current_user.calendly_scheduling_url = None
    current_user.calendly_timezone = None
    current_user.calendly_plan = None
    current_user.calendly_webhook_subscription_uri = None
    current_user.calendly_connected_at = None

    try:
        db.session.commit()
        flash("Successfully disconnected from Calendly.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to disconnect Calendly: {str(e)}", "error")

    return redirect(url_for("settings_routes.calendar_settings"))


def refresh_calendly_token(user: User) -> str | None:
    """
    Refresh Calendly access token for a user.

    Args:
        user: User object with calendly_refresh_token

    Returns:
        New access token if successful, otherwise None
    """
    if not user.calendly_refresh_token:
        return None

    token_data = {
        "grant_type": "refresh_token",
        "refresh_token": user.calendly_refresh_token,
        "client_id": CALENDLY_CLIENT_ID,
        "client_secret": CALENDLY_CLIENT_SECRET,
    }

    try:
        token_response = requests.post(CALENDLY_TOKEN_URL, data=token_data, timeout=10)
        token_response.raise_for_status()
        token_json = token_response.json()

        access_token = token_json.get("access_token")
        refresh_token = token_json.get("refresh_token")

        if access_token:
            user.calendly_access_token = access_token
            if refresh_token:
                user.calendly_refresh_token = refresh_token
            db.session.commit()
            logger.info(f"Successfully refreshed Calendly token for user {user.id}")
            return access_token
    except Exception as e:
        logger.error(f"Failed to refresh Calendly token for user {user.id}: {e}")
        return None

    return None
