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
    
    # Check if calendar is connected (use same logic as bookings/settings)
    from app.routes.main_routes import calendar_needs_connection
    has_calendar = not calendar_needs_connection()
    
    # If calendar is connected, sync calendars to ensure primary is selected for conflicts
    if has_calendar:
        try:
            from app.services.google_calendar import fetch_user_calendar_list
            from app.models import UserCalendar
            
            calendar_items = fetch_user_calendar_list(current_user)
            calendars_by_id = {cal.calendar_id: cal for cal in current_user.calendars}
            
            for item in calendar_items:
                calendar_id = item.get("id")
                if not calendar_id:
                    continue
                
                existing = calendars_by_id.get(calendar_id)
                is_primary = bool(item.get("primary"))
                
                if not existing:
                    # Create new calendar entry with primary selected for conflicts
                    existing = UserCalendar(
                        user=current_user,
                        calendar_id=calendar_id,
                        calendar_name=item.get("summary") or calendar_id,
                        calendar_email=item.get("id"),
                        access_role=item.get("accessRole"),
                        is_primary=is_primary,
                        is_selected_for_conflicts=is_primary,
                    )
                    db.session.add(existing)
            
            db.session.commit()
        except Exception as exc:
            # Don't fail onboarding if calendar sync fails
            print(f"Failed to sync calendars during onboarding: {exc}")
    
    # Get list of timezones
    timezones = pytz.common_timezones
    
    return render_template(
        "onboarding.html",
        has_calendar=has_calendar,
        timezones=timezones,
    )
