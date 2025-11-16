from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Tuple
import os
import time as time_module

import logging

import pytz
from dateutil import parser
from sqlalchemy import or_

from app import db
from app.models import AvailabilityWindow, Event, EventType, User
from app.services import google_calendar

logger = logging.getLogger(__name__)

_AVAILABILITY_CACHE: Dict[Tuple[int, int, int, int], Tuple["AvailabilityBatch", float]] = {}
_AVAILABILITY_CACHE_MAXSIZE = int(os.environ.get("AVAILABILITY_CACHE_MAXSIZE", "256"))
_AVAILABILITY_CACHE_TTL_SECONDS = int(os.environ.get("AVAILABILITY_CACHE_TTL", "60"))


def _cache_enabled() -> bool:
    return _AVAILABILITY_CACHE_TTL_SECONDS > 0 and _AVAILABILITY_CACHE_MAXSIZE > 0


def _build_cache_key(user_id: int, event_type_id: int, start_date: date, end_date: date) -> Tuple[int, int, int, int]:
    return (user_id, event_type_id, start_date.toordinal(), end_date.toordinal())


def _prune_cache(now_ts: float) -> None:
    expired = [key for key, (_, expires) in _AVAILABILITY_CACHE.items() if expires <= now_ts]
    for key in expired:
        _AVAILABILITY_CACHE.pop(key, None)

    while _AVAILABILITY_CACHE_MAXSIZE > 0 and len(_AVAILABILITY_CACHE) >= _AVAILABILITY_CACHE_MAXSIZE:
        try:
            _AVAILABILITY_CACHE.pop(next(iter(_AVAILABILITY_CACHE)))
        except StopIteration:
            break


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


@dataclass
class AvailabilityBatch:
    slots_by_date: Dict[date, List[Slot]]
    availability_map: Dict[date, bool]


class AvailabilityError(Exception):
    def __init__(self, message: str, code: str = "availability_error"):
        super().__init__(message)
        self.code = code


def get_timezone(user: User, event_type: Optional[EventType] = None) -> pytz.BaseTzInfo:
    """
    Get the appropriate timezone for the user.

    If event_type is provided and is Calendly-managed, use Calendly's timezone.
    Otherwise, use the user's CalAutobot timezone.
    """
    # For Calendly-managed event types, use Calendly's timezone
    if event_type and event_type.is_calendly_managed and user.calendly_timezone:
        tz_name = user.calendly_timezone
    else:
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


def _collect_local_busy_slots(
    user: User, range_start: datetime, range_end: datetime, tz
) -> List[Slot]:
    busy_slots: List[Slot] = []

    events_query = Event.query.filter(Event.user_id == user.id)
    # Narrow down by SQL date columns when available
    events_query = events_query.filter(
        or_(Event.start_date == None, Event.start_date <= range_end.date())
    ).filter(or_(Event.end_date == None, Event.end_date >= range_start.date()))

    events = events_query.all()

    for event in events:
        slot = _parse_event_datetime(event, tz)
        if not slot:
            continue
        if slot.end <= range_start or slot.start >= range_end:
            continue
        busy_slots.append(slot)

    return busy_slots


def _collect_google_busy_slots(
    user: User, range_start: datetime, range_end: datetime, tz
) -> List[Slot]:
    conflict_calendar_ids = [
        calendar.calendar_id
        for calendar in user.calendars
        if calendar.is_selected_for_conflicts
    ]
    if not conflict_calendar_ids:
        return []

    try:
        calendars_busy = google_calendar.fetch_freebusy(
            user, conflict_calendar_ids, range_start, range_end
        )
    except Exception as exc:
        logger.warning("Failed to fetch Google free/busy data: %s", exc)
        raise AvailabilityError(
            "Unable to check calendar conflicts right now. Please try again shortly.",
            code="google_unavailable",
        ) from exc

    busy_slots: List[Slot] = []
    for calendar_id in conflict_calendar_ids:
        periods = calendars_busy.get(calendar_id, {}).get("busy", [])
        for period in periods:
            try:
                start_dt = parser.isoparse(period["start"]).astimezone(tz)
                end_dt = parser.isoparse(period["end"]).astimezone(tz)
            except Exception:
                continue
            busy_slots.append(Slot(start=start_dt, end=end_dt))
    return busy_slots


def _group_busy_slots_by_date(
    busy_slots: Iterable[Slot], tz
) -> Dict[date, List[Slot]]:
    busy_by_date: Dict[date, List[Slot]] = defaultdict(list)
    for slot in busy_slots:
        start_day = slot.start.astimezone(tz).date()
        end_day = slot.end.astimezone(tz).date()
        current_day = start_day
        while current_day <= end_day:
            busy_by_date[current_day].append(slot)
            current_day += timedelta(days=1)
    return busy_by_date


def _slot_overlaps(slot: Slot, busy_slots: Iterable[Slot]) -> bool:
    for busy in busy_slots:
        if max(slot.start, busy.start) < min(slot.end, busy.end):
            return True
    return False


def _get_calendly_availability(
    user: User,
    event_type: EventType,
    start_date: date,
    end_date: date,
    tz: pytz.BaseTzInfo,
) -> Optional[AvailabilityBatch]:
    """
    Get availability from Calendly API.

    Returns None if Calendly is not configured or fails.
    """
    # Check if user has Calendly and event type has URI
    if not user.calendly_access_token:
        return None

    if not event_type.calendly_event_type_uri:
        return None

    try:
        from app.services.calendly_api import CalendlyAPIClient, CalendlyAPIError

        client = CalendlyAPIClient(user)

        slots_by_date: Dict[date, List[Slot]] = {}
        availability_map: Dict[date, bool] = {}

        # Calendly API limits to 7-day ranges, so chunk the request
        current_start = start_date
        while current_start <= end_date:
            current_end = min(current_start + timedelta(days=6), end_date)

            # Convert dates to datetime for API call
            # Use time(23, 59, 59) instead of time.max to avoid microseconds that Calendly API rejects
            range_start_dt = tz.localize(datetime.combine(current_start, time.min))
            range_end_dt = tz.localize(datetime.combine(current_end, time(23, 59, 59)))

            # Calendly requires start_time to be in the future
            # If start time is in the past, use current time instead
            now = datetime.now(tz)
            if range_start_dt < now:
                range_start_dt = now

            # Call Calendly API
            calendly_slots = client.get_event_type_available_times(
                event_type_uri=event_type.calendly_event_type_uri,
                start_time=range_start_dt,
                end_time=range_end_dt,
            )

            # Convert Calendly response to Slot objects grouped by date
            for calendly_slot in calendly_slots:
                if calendly_slot.get("status") != "available":
                    continue

                start_time_str = calendly_slot.get("start_time")
                if not start_time_str:
                    continue

                # Parse ISO datetime and convert to user timezone
                slot_start_utc = parser.isoparse(start_time_str)
                slot_start = slot_start_utc.astimezone(tz)
                slot_end = slot_start + timedelta(minutes=event_type.duration_minutes)

                slot = Slot(start=slot_start, end=slot_end)
                slot_date = slot_start.date()

                if slot_date not in slots_by_date:
                    slots_by_date[slot_date] = []

                slots_by_date[slot_date].append(slot)

            # Move to next chunk
            current_start = current_end + timedelta(days=1)

        # Fill in empty dates
        current_date = start_date
        while current_date <= end_date:
            if current_date not in slots_by_date:
                slots_by_date[current_date] = []
            availability_map[current_date] = bool(slots_by_date[current_date])
            current_date += timedelta(days=1)

        return AvailabilityBatch(
            slots_by_date=slots_by_date,
            availability_map=availability_map,
        )

    except Exception as exc:
        logger.warning(f"Failed to fetch availability from Calendly: {exc}")
        return None


def get_availability_for_range(
    user: User,
    event_type: EventType,
    start_date: date,
    end_date: date,
) -> AvailabilityBatch:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")

    # Use Calendly's timezone for Calendly-managed event types
    tz = get_timezone(user, event_type)

    # Try Calendly first if configured
    calendly_result = _get_calendly_availability(user, event_type, start_date, end_date, tz)
    if calendly_result is not None:
        logger.info(f"Using Calendly availability for user {user.id}, event type {event_type.id}")
        return calendly_result

    # Fall back to local availability windows
    logger.info(f"Using local availability for user {user.id}, event type {event_type.id}")
    ensure_default_windows(user)

    weekly_windows = [
        window for window in get_weekly_windows(user) if window.is_active
    ]
    if not weekly_windows:
        return AvailabilityBatch(slots_by_date={}, availability_map={})

    windows_by_weekday: Dict[int, List[AvailabilityWindow]] = defaultdict(list)
    for window in weekly_windows:
        windows_by_weekday[window.weekday].append(window)

    duration = timedelta(minutes=event_type.duration_minutes)
    now = datetime.now(tz)

    range_start_dt = tz.localize(datetime.combine(start_date, time.min))
    range_end_dt = tz.localize(datetime.combine(end_date, time.max))

    local_busy = _collect_local_busy_slots(user, range_start_dt, range_end_dt, tz)
    google_busy = _collect_google_busy_slots(user, range_start_dt, range_end_dt, tz)
    all_busy = local_busy + google_busy
    busy_by_date = _group_busy_slots_by_date(all_busy, tz)

    slots_by_date: Dict[date, List[Slot]] = {}
    availability_map: Dict[date, bool] = {}

    current_date = start_date
    while current_date <= end_date:
        day_windows = windows_by_weekday.get(current_date.weekday(), [])
        day_slots: List[Slot] = []

        if day_windows:
            day_busy = busy_by_date.get(current_date, [])
            for window in day_windows:
                raw_start = datetime.combine(current_date, window.start_time)
                raw_end = datetime.combine(current_date, window.end_time)
                window_start = tz.localize(raw_start)
                window_end = tz.localize(raw_end)

                if window_end - window_start < duration:
                    continue

                cursor = window_start
                # align to top of hour or half hour
                minute_offset = cursor.minute % 30
                if minute_offset != 0:
                    cursor += timedelta(minutes=30 - minute_offset)

                while cursor + duration <= window_end:
                    slot = Slot(start=cursor, end=cursor + duration)
                    if slot.start < now:
                        cursor += timedelta(minutes=30)
                        continue
                    if not _slot_overlaps(slot, day_busy):
                        day_slots.append(slot)
                    cursor += timedelta(minutes=30)

        slots_by_date[current_date] = day_slots
        availability_map[current_date] = bool(day_slots)
        current_date += timedelta(days=1)

    return AvailabilityBatch(
        slots_by_date=slots_by_date,
        availability_map=availability_map,
    )


def clear_availability_cache() -> None:
    _AVAILABILITY_CACHE.clear()


def get_cached_availability_for_range(
    user: User,
    event_type: EventType,
    start_date: date,
    end_date: date,
) -> AvailabilityBatch:
    if not _cache_enabled():
        return get_availability_for_range(user, event_type, start_date, end_date)

    key = _build_cache_key(user.id, event_type.id, start_date, end_date)
    now_ts = time_module.time()
    cached = _AVAILABILITY_CACHE.get(key)
    if cached and cached[1] > now_ts:
        return cached[0]

    batch = get_availability_for_range(user, event_type, start_date, end_date)
    _prune_cache(now_ts)
    _AVAILABILITY_CACHE[key] = (batch, now_ts + _AVAILABILITY_CACHE_TTL_SECONDS)
    return batch


def get_slots_for_date(user: User, event_type: EventType, target_date: date) -> List[Slot]:
    batch = get_cached_availability_for_range(user, event_type, target_date, target_date)
    return batch.slots_by_date.get(target_date, [])


def format_slots_for_template(slots: Iterable[Slot]) -> List[dict]:
    return [slot.to_dict() for slot in slots]
