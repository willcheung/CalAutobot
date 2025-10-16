from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional

import pytz
from dateutil import parser

from app import db
from app.models import AvailabilityWindow, Event, EventType, User


@dataclass
class Slot:
    start: datetime
    end: datetime

    def to_dict(self):
        return {
            "start_iso": self.start.isoformat(),
            "end_iso": self.end.isoformat(),
            "start_display": self.start.strftime("%I:%M %p").lstrip("0"),
        }


def get_timezone(user: User) -> pytz.BaseTzInfo:
    tz_name = user.timezone or "UTC"
    try:
        return pytz.timezone(tz_name)
    except Exception:
        return pytz.UTC


def get_weekly_windows(user: User) -> List[AvailabilityWindow]:
    return (
        AvailabilityWindow.query.filter_by(user_id=user.id)
        .order_by(AvailabilityWindow.weekday.asc(), AvailabilityWindow.start_time.asc())
        .all()
    )


def ensure_default_windows(user: User):
    if AvailabilityWindow.query.filter_by(user_id=user.id).count() > 0:
        return

    for weekday in range(5):  # Monday-Friday 09:00-17:00
        window = AvailabilityWindow(
            user_id=user.id,
            weekday=weekday,
            start_time=time(9, 0),
            end_time=time(17, 0),
            is_active=True,
        )
        db.session.add(window)
    db.session.commit()


def set_weekly_windows(user: User, windows: Iterable[dict]):
    existing = AvailabilityWindow.query.filter_by(user_id=user.id).all()
    by_id = {win.id: win for win in existing}

    seen_ids = set()
    for window_data in windows:
        window_id = window_data.get("id")
        weekday = int(window_data["weekday"])
        start = window_data["start"]
        end = window_data["end"]
        is_active = bool(window_data.get("is_active", True))

        start_time_obj = datetime.strptime(start, "%H:%M").time()
        end_time_obj = datetime.strptime(end, "%H:%M").time()

        if end_time_obj <= start_time_obj:
            raise ValueError("End time must be after start time")

        if window_id and window_id in by_id:
            window = by_id[window_id]
            window.weekday = weekday
            window.start_time = start_time_obj
            window.end_time = end_time_obj
            window.is_active = is_active
            seen_ids.add(window_id)
        else:
            window = AvailabilityWindow(
                user_id=user.id,
                weekday=weekday,
                start_time=start_time_obj,
                end_time=end_time_obj,
                is_active=is_active,
            )
            db.session.add(window)

    # Remove windows not submitted
    for window in existing:
        if window.id not in seen_ids and window.id is not None:
            db.session.delete(window)

    db.session.commit()


def _parse_event_datetime(event: Event, tz) -> Optional[Slot]:
    if event.start_datetime and event.end_datetime:
        try:
            start_dt = parser.isoparse(event.start_datetime)
            end_dt = parser.isoparse(event.end_datetime)
        except ValueError:
            start_dt = None
            end_dt = None
    else:
        start_dt = None
        end_dt = None

    if start_dt is None and event.start_date:
        start_dt = datetime.combine(event.start_date, event.start_time or time(0, 0))
        start_dt = tz.localize(start_dt)
    if end_dt is None and event.end_date:
        end_dt = datetime.combine(event.end_date, event.end_time or time(0, 0))
        end_dt = tz.localize(end_dt)

    if start_dt is None:
        return None

    if end_dt is None:
        duration_minutes = event.duration_minutes or 30
        end_dt = start_dt + timedelta(minutes=duration_minutes)

    if start_dt.tzinfo is None:
        start_dt = tz.localize(start_dt)
    else:
        start_dt = start_dt.astimezone(tz)

    if end_dt.tzinfo is None:
        end_dt = tz.localize(end_dt)
    else:
        end_dt = end_dt.astimezone(tz)

    return Slot(start=start_dt, end=end_dt)


def _collect_busy_slots(user: User, day_start: datetime, day_end: datetime) -> List[Slot]:
    tz = get_timezone(user)
    busy_slots: List[Slot] = []

    events = Event.query.filter(Event.user_id == user.id).all()

    for event in events:
        slot = _parse_event_datetime(event, tz)
        if not slot:
            continue
        if slot.end <= day_start or slot.start >= day_end:
            continue
        busy_slots.append(slot)

    return busy_slots


def _slot_overlaps(slot: Slot, busy_slots: Iterable[Slot]) -> bool:
    for busy in busy_slots:
        if max(slot.start, busy.start) < min(slot.end, busy.end):
            return True
    return False


def get_slots_for_date(user: User, event_type: EventType, target_date: date) -> List[Slot]:
    ensure_default_windows(user)
    tz = get_timezone(user)

    weekday = target_date.weekday()
    windows = (
        AvailabilityWindow.query.filter_by(user_id=user.id, weekday=weekday, is_active=True)
        .order_by(AvailabilityWindow.start_time.asc())
        .all()
    )

    if not windows:
        return []

    day_start = tz.localize(datetime.combine(target_date, time.min))
    day_end = tz.localize(datetime.combine(target_date, time.max))
    busy_slots = _collect_busy_slots(user, day_start, day_end)

    duration = timedelta(minutes=event_type.duration_minutes)
    now = datetime.now(tz)

    available: List[Slot] = []
    for window in windows:
        window_start = tz.localize(datetime.combine(target_date, window.start_time))
        window_end = tz.localize(datetime.combine(target_date, window.end_time))

        cursor = window_start
        while cursor + duration <= window_end:
            slot = Slot(start=cursor, end=cursor + duration)
            if slot.start < now:
                cursor += duration
                continue
            if not _slot_overlaps(slot, busy_slots):
                available.append(slot)
            cursor += duration

    return available


def format_slots_for_template(slots: Iterable[Slot]) -> List[dict]:
    return [slot.to_dict() for slot in slots]
