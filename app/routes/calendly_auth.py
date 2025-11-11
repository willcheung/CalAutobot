"""
Calendly OAuth integration for CalAutobot.

Handles OAuth flow for connecting user's Calendly account.
"""

import os
import requests
from datetime import datetime

from flask import Blueprint, redirect, request, url_for, flash, session
from flask_login import current_user, login_required

from app import db
from app.models import User

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

    # Save to database
    current_user.calendly_access_token = access_token
    current_user.calendly_refresh_token = refresh_token
    current_user.calendly_user_uri = user_uri
    current_user.calendly_organization_uri = organization_uri
    current_user.calendly_scheduling_url = scheduling_url
    current_user.calendly_connected_at = datetime.utcnow()

    try:
        db.session.commit()
        flash("Successfully connected to Calendly!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to save Calendly connection: {str(e)}", "error")
        return redirect(url_for("onboarding_routes.onboarding"))

    # Check if we're in onboarding flow
    if session.get('in_onboarding'):
        return redirect(url_for("onboarding_routes.onboarding"))
    else:
        return redirect(url_for("main_routes.settings"))


@calendly_auth.route("/auth/calendly/disconnect", methods=["POST"])
@login_required
def disconnect():
    """Disconnect Calendly account."""
    current_user.calendly_access_token = None
    current_user.calendly_refresh_token = None
    current_user.calendly_user_uri = None
    current_user.calendly_organization_uri = None
    current_user.calendly_scheduling_url = None
    current_user.calendly_webhook_subscription_uri = None
    current_user.calendly_connected_at = None

    try:
        db.session.commit()
        flash("Successfully disconnected from Calendly.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to disconnect Calendly: {str(e)}", "error")

    return redirect(url_for("main_routes.settings"))


def refresh_calendly_token(user: User) -> bool:
    """
    Refresh Calendly access token for a user.

    Args:
        user: User object with calendly_refresh_token

    Returns:
        True if successful, False otherwise
    """
    if not user.calendly_refresh_token:
        return False

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
            return True
    except Exception:
        return False

    return False
