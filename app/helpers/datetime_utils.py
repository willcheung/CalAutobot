from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytz


def ensure_timezone(timezone_name: Optional[str]) -> pytz.BaseTzInfo:
    """Return a pytz timezone for the provided name, defaulting to UTC."""
    tz_name = timezone_name or "UTC"
    try:
        return pytz.timezone(tz_name)
    except Exception:
        return pytz.UTC


def convert_to_timezone(dt: Optional[datetime], tz: Optional[pytz.BaseTzInfo]) -> Optional[datetime]:
    """Convert a datetime to the provided timezone, assuming naive values are UTC."""
    if not dt or not tz:
        return None
    if dt.tzinfo is None:
        try:
            dt = pytz.UTC.localize(dt)
        except ValueError:
            dt = dt.replace(tzinfo=pytz.UTC)
    else:
        dt = dt.astimezone(pytz.UTC)
    return dt.astimezone(tz)


def format_datetime(dt: Optional[datetime], tz: Optional[pytz.BaseTzInfo], fmt: str = "%b %d, %Y") -> Optional[str]:
    """Format a datetime in the provided timezone."""
    localized = convert_to_timezone(dt, tz)
    if not localized:
        return None
    return localized.strftime(fmt)
