import pytz
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db

settings_routes = Blueprint("settings_routes", __name__)


@settings_routes.route("/settings/profile", methods=["GET", "POST"])
@login_required
def profile_settings():
    if request.method == "POST":
        display_name = request.form.get("display_name", "").strip()
        timezone = request.form.get("timezone", "UTC")

        if display_name:
            current_user.username = display_name
        current_user.timezone = timezone
        db.session.commit()
        flash("Settings updated", "success")
        return redirect(url_for("settings_routes.profile_settings"))

    timezones = pytz.common_timezones
    return render_template(
        "settings/profile.html",
        timezones=timezones,
    )
