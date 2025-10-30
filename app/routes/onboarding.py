import pytz
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db

onboarding_routes = Blueprint("onboarding_routes", __name__)


@onboarding_routes.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    """
    Onboarding page for first-time users.
    Shows 3 steps: connect calendar, select timezone, getting started.
    """
    from flask import session
    
    # Set session flag to track onboarding state
    session['in_onboarding'] = True
    
    # If calendar is already connected and they're hitting this page via POST,
    # they've completed onboarding
    if request.method == "POST":
        # Update timezone if provided
        timezone = request.form.get("timezone")
        if timezone and timezone in pytz.common_timezones:
            current_user.timezone = timezone
            db.session.commit()
        
        # Clear onboarding flag
        session.pop('in_onboarding', None)
        
        # Redirect to bookings page
        flash("Welcome to Cal! You're all set.", "success")
        return redirect(url_for("main_routes.bookings"))
    
    # Check if calendar is connected
    has_calendar = bool(current_user.google_token)
    
    # Get list of timezones
    timezones = pytz.common_timezones
    
    return render_template(
        "onboarding.html",
        has_calendar=has_calendar,
        timezones=timezones,
    )
