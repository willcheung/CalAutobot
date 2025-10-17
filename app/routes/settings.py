import pytz
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
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
