from datetime import datetime, time, timedelta

import pytz

from app import db
from app.models import Event, EventType, User
from app.services import availability as availability_service


def test_get_slots_respects_existing_events(app_context):
    user = User(username="Scheduler", email="scheduler@example.com", timezone="UTC")
    db.session.add(user)
    db.session.commit()

    today = datetime.utcnow().date() + timedelta(days=1)
    availability_service.set_weekly_windows(
        user,
        [
            {"weekday": today.weekday(), "start": "09:00", "end": "17:00", "is_active": True}
        ],
    )

    event_type = EventType(
        user_id=user.id,
        title="30 Min Meeting",
        slug="30-min",
        duration_minutes=30,
        is_active=True,
        is_public=True,
    )
    db.session.add(event_type)
    db.session.commit()

    tz = pytz.timezone(user.timezone)
    busy_start = tz.localize(datetime.combine(today, time(10, 0)))
    busy_end = busy_start + timedelta(minutes=30)

    busy_event = Event(
        user_id=user.id,
        event_name="Busy",
        event_description="Busy slot",
        start_datetime=busy_start.isoformat(),
        end_datetime=busy_end.isoformat(),
        duration_minutes=30,
    )
    busy_event.start_date = busy_start.date()
    busy_event.start_time = busy_start.time()
    busy_event.end_date = busy_end.date()
    busy_event.end_time = busy_end.time()
    db.session.add(busy_event)
    db.session.commit()

    slots = availability_service.get_slots_for_date(user, event_type, today)
    assert slots, "Expected at least one available slot"
    assert all(abs((slot.start - busy_start).total_seconds()) >= 60 for slot in slots)
