from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.models import EventType, User
from app.services import availability as availability_service
from app.services.event_types import get_event_type_by_slug
from app.services.public_booking import create_booking_event

public_booking = Blueprint("public_booking", __name__)


def _get_user_or_404(user_id: int) -> User:
    return User.query.filter_by(id=user_id).first_or_404()


@public_booking.route("/u/<int:user_id>")
def profile_page(user_id):
    user = _get_user_or_404(user_id)
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


@public_booking.route("/u/<int:user_id>/<slug>", methods=["GET", "POST"])
def event_type_page(user_id, slug):
    user = _get_user_or_404(user_id)
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

    return render_template(
        "public/event_type.html",
        user=user,
        event_type=event_type,
        target_date=target_date,
        slots=slots_for_template,
        display_sidebar=False,
    )
