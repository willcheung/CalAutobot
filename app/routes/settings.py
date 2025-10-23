import pytz
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import UserCalendar
from app.services.google_calendar import fetch_user_calendar_list
from app.services.users import assign_unique_handle, is_handle_available, normalize_handle

settings_routes = Blueprint("settings_routes", __name__)


@settings_routes.route("/settings/profile", methods=["GET", "POST"])
@login_required
def profile_settings():
    if not current_user.handle:
        assign_unique_handle(current_user)
        db.session.commit()

    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        timezone = request.form.get("timezone", "UTC")
        handle_input = request.form.get("handle", "").strip()

        handle = normalize_handle(handle_input)
        if not handle:
            flash("Handle must include at least one letter or number.", "danger")
            return redirect(url_for("settings_routes.profile_settings"))

        if (
            handle != (current_user.handle or "")
            and not is_handle_available(handle, exclude_user_id=current_user.id)
        ):
            flash("That handle is already taken. Please choose another.", "danger")
            return redirect(url_for("settings_routes.profile_settings"))

        if display_name:
            current_user.username = display_name
        current_user.handle = handle
        current_user.timezone = timezone
        db.session.commit()
        flash("Settings updated", "success")
        return redirect(url_for("settings_routes.profile_settings"))

    timezones = pytz.common_timezones
    return render_template(
        "settings/profile.html",
        timezones=timezones,
    )


@settings_routes.route("/settings/calendars", methods=["GET", "POST"])
@login_required
def calendar_settings():
    calendar_error = None
    calendar_items = []

    calendars_by_id = {cal.calendar_id: cal for cal in current_user.calendars}
    seen_calendar_ids = set()
    pending_changes = False

    if request.method == "POST":
        booking_calendar_id = request.form.get("booking_calendar_id") or None
        extraction_calendar_id = request.form.get("extraction_calendar_id") or None
        conflict_calendar_ids = set(request.form.getlist("conflict_calendar_ids"))

        valid_calendar_ids = set(calendars_by_id.keys())
        conflict_calendar_ids &= valid_calendar_ids

        writable_calendar_ids = {
            cal_id
            for cal_id, calendar in calendars_by_id.items()
            if calendar.access_role in {"owner", "writer"}
        }

        is_valid = True
        if booking_calendar_id and booking_calendar_id not in writable_calendar_ids:
            flash("Selected booking calendar is not available.", "danger")
            is_valid = False
        if extraction_calendar_id and extraction_calendar_id not in writable_calendar_ids:
            flash("Selected extraction calendar is not available.", "danger")
            is_valid = False

        if is_valid:
            if booking_calendar_id:
                if current_user.default_booking_calendar_id != booking_calendar_id:
                    current_user.default_booking_calendar_id = booking_calendar_id
                    pending_changes = True
            elif (
                current_user.default_booking_calendar_id
                and current_user.default_booking_calendar_id not in valid_calendar_ids
            ):
                current_user.default_booking_calendar_id = None
                pending_changes = True

            if extraction_calendar_id:
                if current_user.extraction_calendar_id != extraction_calendar_id:
                    current_user.extraction_calendar_id = extraction_calendar_id
                    pending_changes = True
            elif (
                current_user.extraction_calendar_id
                and current_user.extraction_calendar_id not in valid_calendar_ids
            ):
                current_user.extraction_calendar_id = None
                pending_changes = True

            for calendar_id, calendar in calendars_by_id.items():
                selected = calendar_id in conflict_calendar_ids
                if calendar.is_selected_for_conflicts != selected:
                    calendar.is_selected_for_conflicts = selected
                    pending_changes = True

            if pending_changes:
                db.session.commit()
                flash("Calendar preferences updated.", "success")
            return redirect(url_for("settings_routes.calendar_settings"))

    if not calendar_error:
        try:
            calendar_items = fetch_user_calendar_list(current_user)
        except Exception as exc:
            calendar_error = str(exc)
            calendar_items = []

    if not calendar_error:
        for item in calendar_items:
            calendar_id = item.get("id")
            if not calendar_id:
                continue

            seen_calendar_ids.add(calendar_id)
            existing = calendars_by_id.get(calendar_id)
            is_primary = bool(item.get("primary"))
            calendar_name = item.get("summary") or calendar_id
            access_role = item.get("accessRole")
            calendar_email = item.get("id")

            if not existing:
                existing = UserCalendar(
                    user=current_user,
                    calendar_id=calendar_id,
                    calendar_name=calendar_name,
                    calendar_email=calendar_email,
                    access_role=access_role,
                    is_primary=is_primary,
                    is_selected_for_conflicts=is_primary,
                )
                db.session.add(existing)
                calendars_by_id[calendar_id] = existing
                pending_changes = True
            else:
                if existing.calendar_name != calendar_name:
                    existing.calendar_name = calendar_name
                    pending_changes = True
                if existing.calendar_email != calendar_email:
                    existing.calendar_email = calendar_email
                    pending_changes = True
                if existing.access_role != access_role:
                    existing.access_role = access_role
                    pending_changes = True
                if existing.is_primary != is_primary:
                    existing.is_primary = is_primary
                    if is_primary and not existing.is_selected_for_conflicts:
                        existing.is_selected_for_conflicts = True
                    pending_changes = True

        # Remove calendars the user no longer has access to
        for calendar in list(current_user.calendars):
            if calendar.calendar_id not in seen_calendar_ids:
                if current_user.default_booking_calendar_id == calendar.calendar_id:
                    current_user.default_booking_calendar_id = None
                    pending_changes = True
                if current_user.extraction_calendar_id == calendar.calendar_id:
                    current_user.extraction_calendar_id = None
                    pending_changes = True
                db.session.delete(calendar)
                calendars_by_id.pop(calendar.calendar_id, None)
                pending_changes = True

        service_calendar = next(
            (
                cal
                for cal in calendars_by_id.values()
                if cal.calendar_name == "Cal Event Extraction"
            ),
            None,
        )
        primary_calendar = next(
            (cal for cal in calendars_by_id.values() if cal.is_primary),
            None,
        )

        if not current_user.default_booking_calendar_id:
            default_booking = primary_calendar or service_calendar
            if default_booking:
                current_user.default_booking_calendar_id = default_booking.calendar_id
                pending_changes = True

        if not current_user.extraction_calendar_id:
            default_extraction_calendar = service_calendar or primary_calendar
            if default_extraction_calendar:
                current_user.extraction_calendar_id = default_extraction_calendar.calendar_id
                if not default_extraction_calendar.is_selected_for_conflicts:
                    default_extraction_calendar.is_selected_for_conflicts = True
                pending_changes = True

    if pending_changes:
        db.session.commit()
        # Refresh calendar cache to avoid expired attributes triggering N+1 queries
        calendars_by_id = {cal.calendar_id: cal for cal in current_user.calendars}

    calendar_preferences = []
    for calendar_id, calendar in calendars_by_id.items():
        calendar_preferences.append(
            {
                "id": calendar_id,
                "name": calendar.calendar_name,
                "email": calendar.calendar_email,
                "is_primary": calendar.is_primary,
                "access_role": calendar.access_role,
                "can_add_events": calendar.access_role in {"owner", "writer"},
                "selected_for_conflicts": calendar.is_selected_for_conflicts,
                "is_booking_destination": calendar_id
                == current_user.default_booking_calendar_id,
                "is_extraction_destination": calendar_id
                == current_user.extraction_calendar_id,
            }
        )

    calendar_preferences.sort(
        key=lambda cal: (not cal["is_primary"], cal["name"].lower())
    )

    writable_calendars = [
        cal for cal in calendar_preferences if cal["can_add_events"]
    ]
    booking_calendar_id = current_user.default_booking_calendar_id
    extraction_calendar_id = current_user.extraction_calendar_id
    booking_calendar_missing = bool(
        booking_calendar_id
        and not any(cal["id"] == booking_calendar_id for cal in writable_calendars)
    )
    extraction_calendar_missing = bool(
        extraction_calendar_id
        and not any(cal["id"] == extraction_calendar_id for cal in writable_calendars)
    )
    primary_calendar_id = next(
        (cal["id"] for cal in calendar_preferences if cal["is_primary"]),
        None,
    )

    return render_template(
        "settings/calendar.html",
        calendar_error=calendar_error,
        calendars=calendar_preferences,
        booking_calendar_id=booking_calendar_id,
        extraction_calendar_id=extraction_calendar_id,
        writable_calendars=writable_calendars,
        booking_calendar_missing=booking_calendar_missing,
        extraction_calendar_missing=extraction_calendar_missing,
        primary_calendar_id=primary_calendar_id,
    )
