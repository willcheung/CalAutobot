import calendar
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request
from sqlalchemy import func

from app import db
from app.models import EventType, User
from app.services import availability as availability_service
from app.services.event_types import get_event_type_by_slug
from app.services.public_booking import create_booking_event
from app.services.users import assign_unique_handle

public_booking = Blueprint("public_booking", __name__)


def _get_user_or_404(user_id: int) -> User:
    return User.query.filter_by(id=user_id).first_or_404()


def _render_profile_page(user: User):
    event_types = (
        EventType.query.filter_by(user_id=user.id, is_active=True, is_public=True)
        .order_by(EventType.duration_minutes.asc())
        .all()
    )

    return render_template(
        "public/profile.html",
        user=user,
        event_types=event_types,
        display_sidebar=False,
    )


@public_booking.route("/u/<handle>")
def profile_page(handle: str):
    user = User.query.filter(func.lower(User.handle) == handle.lower()).first()
    if not user and handle.isdigit():
        user = _get_user_or_404(int(handle))
        if not user.handle:
            assign_unique_handle(user)
            db.session.commit()
    if not user:
        abort(404)
    return _render_profile_page(user)


def _render_event_type_page(user: User, slug: str):
    event_type = get_event_type_by_slug(user.id, slug)
    if not event_type or not event_type.is_active or not event_type.is_public:
        abort(404)

    tz = availability_service.get_timezone(user)
    if request.method == "POST":
        slot_iso = request.form.get("slot")
        invitee_name = request.form.get("invitee_name", "").strip()
        invitee_email = request.form.get("invitee_email", "").strip()
        notes = request.form.get("notes", "")

        if not slot_iso or not invitee_name or not invitee_email:
            flash("Please select a time and provide your details", "danger")
            return redirect(request.url)

        try:
            slot_start = datetime.fromisoformat(slot_iso)
            slot_start = slot_start.astimezone(tz)
        except Exception:
            flash("Invalid time selection", "danger")
            return redirect(request.url)

        slots = availability_service.get_slots_for_date(user, event_type, slot_start.date())
        if not any(abs((s.start - slot_start).total_seconds()) < 60 for s in slots):
            flash("That time is no longer available", "danger")
            return redirect(request.url)

        create_booking_event(user, event_type, slot_start, invitee_name, invitee_email, notes)
        return render_template(
            "public/confirmation.html",
            user=user,
            event_type=event_type,
            slot_start=slot_start,
            invitee_name=invitee_name,
            display_sidebar=False,
        )

    date_str = request.args.get("date")
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = datetime.now(tz).date()
    else:
        target_date = datetime.now(tz).date()

    availability_service.ensure_default_windows(user)
    slots = availability_service.get_slots_for_date(user, event_type, target_date)
    slots_for_template = availability_service.format_slots_for_template(slots)

    month_start = target_date.replace(day=1)
    today = datetime.now(tz).date()
    month_calendar = calendar.Calendar(firstweekday=6).monthdatescalendar(
        month_start.year, month_start.month
    )

    availability_cache = {target_date: len(slots) > 0}
    calendar_weeks = []

    for week in month_calendar:
        week_cells = []
        for day in week:
            if day not in availability_cache and day >= today:
                day_slots = availability_service.get_slots_for_date(user, event_type, day)
                availability_cache[day] = len(day_slots) > 0

            week_cells.append(
                {
                    "iso": day.isoformat(),
                    "day": day.day,
                    "in_month": day.month == month_start.month,
                    "is_today": day == today,
                    "is_selected": day == target_date,
                    "is_available": availability_cache.get(day, False),
                }
            )
        calendar_weeks.append(week_cells)

    prev_month = (month_start - timedelta(days=1)).replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)

    return render_template(
        "public/event_type.html",
        user=user,
        event_type=event_type,
        target_date=target_date,
        slots=slots_for_template,
        calendar_weeks=calendar_weeks,
        month_label=target_date.strftime("%B %Y"),
        weekday_labels=["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        prev_month_date=prev_month.isoformat(),
        next_month_date=next_month.isoformat(),
        timezone_label=tz.zone,
        display_sidebar=False,
    )


@public_booking.route("/u/<handle>/<slug>", methods=["GET", "POST"])
def event_type_page(handle: str, slug: str):
    user = User.query.filter(func.lower(User.handle) == handle.lower()).first()
    if not user and handle.isdigit():
        user = _get_user_or_404(int(handle))
        if not user.handle:
            assign_unique_handle(user)
            db.session.commit()
    if not user:
        abort(404)
    return _render_event_type_page(user, slug)
