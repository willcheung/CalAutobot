import calendar
from datetime import datetime, timedelta, time

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from app import db
from app.models import Event, EventType, User
from app.services import availability as availability_service
from app.services.availability import AvailabilityError
from app.services.event_types import get_event_type_by_slug
from app.services.public_booking import (
    BookingCreationError,
    cancel_booking_event,
    create_booking_event,
)
from app.services.users import assign_unique_handle
import pytz

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
    owner_timezone = tz.zone
    owner_timezone_label = f"{owner_timezone.replace('_', ' ')} ({datetime.now(tz).strftime('%Z')})"

    timezone_options = []
    for zone in [owner_timezone] + list(pytz.common_timezones):
        if zone not in timezone_options:
            timezone_options.append(zone)

    date_str = request.args.get("date")
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = datetime.now(tz).date()
    else:
        target_date = datetime.now(tz).date()

    month_start = target_date.replace(day=1)
    today = datetime.now(tz).date()
    month_calendar = calendar.Calendar(firstweekday=6).monthdatescalendar(
        month_start.year, month_start.month
    )

    calendar_range_start = month_calendar[0][0]
    calendar_range_end = month_calendar[-1][-1]

    former_slot_iso = request.args.get("former_slot")
    reschedule_token = request.args.get("reschedule_token")
    legacy_cancel_event_id = request.args.get("cancel_event_id", type=int)
    former_slot_start = None
    former_slot_end = None

    if not reschedule_token and legacy_cancel_event_id:
        legacy_event = Event.query.filter_by(id=legacy_cancel_event_id, user_id=user.id).first()
        if legacy_event and legacy_event.public_token:
            reschedule_token = legacy_event.public_token

    if reschedule_token:
        event_to_reschedule = Event.query.filter_by(public_token=reschedule_token, user_id=user.id).first()
        if event_to_reschedule:
            if not former_slot_iso:
                former_dt = None
                if event_to_reschedule.start_datetime:
                    try:
                        former_dt = datetime.fromisoformat(event_to_reschedule.start_datetime)
                    except ValueError:
                        former_dt = None
                if former_dt is None and event_to_reschedule.start_date:
                    base_time = event_to_reschedule.start_time or time(0, 0)
                    former_dt = tz.localize(datetime.combine(event_to_reschedule.start_date, base_time))
                if former_dt is not None:
                    former_slot_iso = former_dt.isoformat()
                    former_slot_start = former_dt.astimezone(tz)
                    former_slot_end = former_slot_start + timedelta(minutes=event_type.duration_minutes)
        else:
            flash("We couldn't find the booking you want to reschedule.", "warning")

    availability_error = None
    availability_map = {}
    slots_for_template = []

    try:
        availability_batch = availability_service.get_availability_for_range(
            user, event_type, calendar_range_start, calendar_range_end
        )
        availability_map = availability_batch.availability_map

        if target_date < today or not availability_map.get(target_date, False):
            next_available = next(
                (
                    day
                    for day in sorted(availability_map.keys())
                    if day >= today and availability_map.get(day, False)
                ),
                None,
            )
            if next_available and next_available != target_date:
                return redirect(
                    url_for(
                        "public_booking.event_type_page",
                        handle=user.handle,
                        slug=event_type.slug,
                        date=next_available.isoformat(),
                    )
                )

        slots = availability_batch.slots_by_date.get(target_date, [])
        slots_for_template = availability_service.format_slots_for_template(slots)
    except AvailabilityError as exc:
        availability_error = str(exc) or "We can't load availability right now. Please try again later."

    if former_slot_iso and former_slot_start is None:
        try:
            former_dt = datetime.fromisoformat(former_slot_iso)
            former_dt = former_dt.astimezone(tz)
            former_slot_start = former_dt
            former_slot_end = former_dt + timedelta(minutes=event_type.duration_minutes)
        except (ValueError, TypeError):
            former_slot_start = None
            former_slot_end = None
    calendar_weeks = []

    for week in month_calendar:
        week_cells = []
        for day in week:
            is_selectable = day >= today and availability_map.get(day, False)
            week_cells.append(
                {
                    "iso": day.isoformat(),
                    "day": day.day,
                    "in_month": day.month == month_start.month,
                    "is_today": day == today,
                    "is_selected": day == target_date,
                    "is_available": is_selectable,
                    "is_selectable": is_selectable,
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
        timezone_label=owner_timezone_label,
        owner_timezone=owner_timezone,
        timezone_options=timezone_options,
        availability_error=availability_error,
        former_slot_start=former_slot_start,
        former_slot_end=former_slot_end,
        former_slot_iso=former_slot_iso,
        reschedule_token=reschedule_token,
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


@public_booking.route("/u/<handle>/<slug>/confirm", methods=["GET", "POST"])
def confirm_booking_page(handle: str, slug: str):
    user = User.query.filter(func.lower(User.handle) == handle.lower()).first()
    if not user and handle.isdigit():
        user = _get_user_or_404(int(handle))
        if not user.handle:
            assign_unique_handle(user)
            db.session.commit()
    if not user:
        abort(404)

    event_type = get_event_type_by_slug(user.id, slug)
    if not event_type or not event_type.is_active or not event_type.is_public:
        abort(404)

    tz = availability_service.get_timezone(user)
    slot_iso = request.values.get("slot")
    reschedule_token = request.values.get("reschedule_token")
    visitor_timezone = request.values.get("visitor_timezone")
    if visitor_timezone and visitor_timezone not in pytz.all_timezones:
        visitor_timezone = None
    legacy_reschedule_event_id = request.values.get("reschedule_event_id", type=int)
    if not reschedule_token and legacy_reschedule_event_id:
        legacy_event = Event.query.filter_by(id=legacy_reschedule_event_id, user_id=user.id).first()
        if legacy_event and legacy_event.public_token:
            reschedule_token = legacy_event.public_token

    if not slot_iso:
        flash("Please pick a time before continuing.", "danger")
        redirect_args = {"handle": handle, "slug": slug}
        if reschedule_token:
            redirect_args["reschedule_token"] = reschedule_token
        return redirect(url_for("public_booking.event_type_page", **redirect_args))

    try:
        slot_start = datetime.fromisoformat(slot_iso)
    except ValueError:
        flash("Invalid time selection.", "danger")
        redirect_args = {"handle": handle, "slug": slug}
        if reschedule_token:
            redirect_args["reschedule_token"] = reschedule_token
        return redirect(url_for("public_booking.event_type_page", **redirect_args))

    slot_start = slot_start.astimezone(tz)
    slot_date = slot_start.date()

    try:
        day_slots = availability_service.get_slots_for_date(user, event_type, slot_date)
    except AvailabilityError:
        flash("We couldn't verify availability right now. Please try again shortly.", "danger")
        redirect_args = {
            "handle": handle,
            "slug": slug,
            "date": slot_date.isoformat(),
        }
        if reschedule_token:
            redirect_args["reschedule_token"] = reschedule_token
        return redirect(url_for("public_booking.event_type_page", **redirect_args))

    selected_slot = next(
        (s for s in day_slots if abs((s.start - slot_start).total_seconds()) < 60),
        None,
    )

    if not selected_slot:
        flash("That time is no longer available. Please choose another slot.", "danger")
        redirect_args = {
            "handle": handle,
            "slug": slug,
            "date": slot_date.isoformat(),
        }
        if reschedule_token:
            redirect_args["reschedule_token"] = reschedule_token
        return redirect(url_for("public_booking.event_type_page", **redirect_args))

    host_slot_start = selected_slot.start.astimezone(tz)
    host_slot_end = selected_slot.end.astimezone(tz)
    host_timezone_label = f"{tz.zone.replace('_', ' ')} ({host_slot_start.strftime('%Z')})"
    host_date_display = host_slot_start.strftime("%A, %B %d, %Y")
    host_time_range = f"{host_slot_start.strftime('%I:%M %p').lstrip('0')} – {host_slot_end.strftime('%I:%M %p').lstrip('0')}"

    def compute_visitor_details(zone: str):
        if not zone or zone not in pytz.all_timezones:
            return None, None, None, None
        try:
            tz_obj = pytz.timezone(zone)
        except Exception:
            return None, None, None, None
        visitor_slot_start = selected_slot.start.astimezone(tz_obj)
        visitor_slot_end = selected_slot.end.astimezone(tz_obj)
        label = f"{zone.replace('_', ' ')} ({visitor_slot_start.strftime('%Z')})"
        date_display = visitor_slot_start.strftime("%A, %B %d, %Y")
        time_range = (
            f"{visitor_slot_start.strftime('%I:%M %p').lstrip('0')} – "
            f"{visitor_slot_end.strftime('%I:%M %p').lstrip('0')}"
        )
        return zone, label, date_display, time_range

    visitor_timezone, visitor_timezone_label, visitor_date_display, visitor_time_range = compute_visitor_details(
        visitor_timezone
    )

    if request.method == "POST":
        invitee_name = request.form.get("invitee_name", "").strip()
        invitee_email = request.form.get("invitee_email", "").strip()
        notes = request.form.get("notes", "")
        visitor_timezone, visitor_timezone_label, visitor_date_display, visitor_time_range = compute_visitor_details(
            request.form.get("visitor_timezone") or visitor_timezone
        )

        if not invitee_name or not invitee_email:
            flash("Please provide your name and email to continue.", "danger")
        else:
            try:
                event_record = create_booking_event(
                    user,
                    event_type,
                    selected_slot.start,
                    invitee_name,
                    invitee_email,
                    notes,
                )
            except BookingCreationError as exc:
                flash(str(exc) or "We couldn't schedule that meeting. Please try again.", "danger")
            except Exception as exc:  # noqa: BLE001
                current_app.logger.exception(
                    "Unexpected error while creating booking for user %s and event type %s",
                    user.id,
                    event_type.id,
                )
                flash("We couldn't schedule that meeting. Please try again.", "danger")
            else:
                if reschedule_token:
                    original_event = Event.query.filter_by(public_token=reschedule_token, user_id=user.id).first()
                    if original_event:
                        cancel_booking_event(user, original_event)
                slot_end = selected_slot.end
                return render_template(
                    "public/confirmation.html",
                    user=user,
                    event_type=event_type,
                    host_date_display=host_date_display,
                    host_time_range=host_time_range,
                    host_timezone_label=host_timezone_label,
                    visitor_timezone_label=visitor_timezone_label,
                    visitor_date_display=visitor_date_display,
                    visitor_time_range=visitor_time_range,
                    invitee_name=invitee_name,
                    invitee_email=invitee_email,
                    visitor_timezone=visitor_timezone,
                    reschedule_url=url_for(
                        "public_booking.event_type_page",
                        handle=user.handle,
                        slug=event_type.slug,
                        former_slot=selected_slot.start.isoformat(),
                        date=selected_slot.start.date().isoformat(),
                        reschedule_token=event_record.public_token,
                    ),
                    cancel_url=url_for(
                        "public_booking.cancel_booking",
                        handle=user.handle,
                        slug=event_type.slug,
                        token=event_record.public_token,
                    ),
                    display_sidebar=False,
                )

    if current_user.is_authenticated:
        display_name = (
            getattr(current_user, "display_name", None)
            or getattr(current_user, "username", None)
            or current_user.email
        )
        display_email = current_user.email or ""
    else:
        display_name = ""
        display_email = ""

    slot_end = selected_slot.end
    notes_value = request.form.get("notes", "") if request.method == "POST" else ""
    return render_template(
        "public/confirm_booking.html",
        user=user,
        event_type=event_type,
        slot_iso=slot_iso,
        slot_start=selected_slot.start,
        slot_end=slot_end,
        timezone_label=tz.zone,
        host_date_display=host_date_display,
        host_time_range=host_time_range,
        host_timezone_label=host_timezone_label,
        visitor_timezone=visitor_timezone,
        visitor_timezone_label=visitor_timezone_label,
        visitor_date_display=visitor_date_display,
        visitor_time_range=visitor_time_range,
        default_name=display_name,
        default_email=display_email,
        notes=notes_value,
        reschedule_token=reschedule_token,
        display_sidebar=False,
    )


@public_booking.route("/u/<handle>/<slug>/cancel")
def cancel_booking(handle: str, slug: str):
    user = User.query.filter(func.lower(User.handle) == handle.lower()).first()
    if not user and handle.isdigit():
        user = _get_user_or_404(int(handle))
        if not user.handle:
            assign_unique_handle(user)
            db.session.commit()
    if not user:
        abort(404)

    event_type = get_event_type_by_slug(user.id, slug)
    if not event_type or not event_type.is_active or not event_type.is_public:
        abort(404)

    token = request.args.get("token")
    event_record = None

    if token:
        event_record = Event.query.filter_by(public_token=token, user_id=user.id).first()
    else:
        legacy_event_id = request.args.get("event_id", type=int)
        if legacy_event_id:
            event_record = Event.query.filter_by(id=legacy_event_id, user_id=user.id).first()

    if not event_record:
        flash("We couldn't find that booking to cancel.", "warning")
        return redirect(url_for("public_booking.profile_page", handle=user.handle))

    cancel_booking_event(user, event_record)
    flash("Your booking has been cancelled.", "info")

    return redirect(url_for("public_booking.profile_page", handle=user.handle))
