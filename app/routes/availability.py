from datetime import time

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.services import availability as availability_service

availability_routes = Blueprint("availability_routes", __name__)


@availability_routes.route("/settings/availability", methods=["GET", "POST"])
@login_required
def edit_availability():
    user = current_user

    if request.method == "POST":
        windows = []
        for weekday in range(7):
            enabled = request.form.get(f"day-{weekday}-enabled")
            start = request.form.get(f"day-{weekday}-start")
            end = request.form.get(f"day-{weekday}-end")
            if enabled and start and end:
                windows.append(
                    {
                        "weekday": weekday,
                        "start": start,
                        "end": end,
                        "is_active": True,
                    }
                )
        try:
            availability_service.set_weekly_windows(user, windows)
            flash("Availability updated", "success")
        except ValueError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("availability_routes.edit_availability"))

    availability_service.ensure_default_windows(user)
    weekly_windows = availability_service.get_weekly_windows(user)

    windows_by_day = {i: None for i in range(7)}
    for window in weekly_windows:
        if window.is_active:
            windows_by_day[window.weekday] = window

    day_names = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    return render_template(
        "availability/index.html",
        windows_by_day=windows_by_day,
        day_names=day_names,
    )
