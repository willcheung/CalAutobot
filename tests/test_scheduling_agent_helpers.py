from datetime import datetime, timedelta
from types import SimpleNamespace

import pytz
import pytest

from app.services import scheduling_agent
from app.services.availability import AvailabilityError


class DummySlot:
    def __init__(self, start: datetime, end: datetime):
        self.start = start
        self.end = end


def _tz_aware(dt: datetime):
    return pytz.UTC.localize(dt)


def test_slot_matches_target_detects_match():
    target = _tz_aware(datetime(2025, 1, 1, 10, 0))
    candidates = [DummySlot(target, target + timedelta(minutes=30))]

    assert scheduling_agent._slot_matches_target(target, candidates)


def test_slot_matches_target_handles_miss():
    target = _tz_aware(datetime(2025, 1, 1, 11, 0))
    candidates = [DummySlot(_tz_aware(datetime(2025, 1, 1, 10, 0)), _tz_aware(datetime(2025, 1, 1, 10, 30)))]

    assert not scheduling_agent._slot_matches_target(target, candidates)


def test_system_issue_agent_result_shape():
    result = scheduling_agent._system_issue_agent_result("Owner Name", "availability_verify_error")

    assert result["action"] == "request_clarification"
    assert "Owner Name" in result["reply"]
    assert result["notes"] == "availability_verify_error"
    assert result["proposed_slots"] == []
    assert result["confirmed_slot"] is None


def test_validate_confirmed_slot_handles_availability_error(monkeypatch):
    monkeypatch.setattr(
        scheduling_agent.availability_service,
        "get_slots_for_date",
        lambda *_, **__: (_ for _ in ()).throw(AvailabilityError("boom")),  # raises AvailabilityError
    )

    owner_name = "Owner"
    slot_start = _tz_aware(datetime(2025, 1, 5, 14, 0))

    result = scheduling_agent._validate_confirmed_slot(
        user=SimpleNamespace(),
        event_type=SimpleNamespace(),
        slot_start=slot_start,
        owner_name=owner_name,
    )

    assert result is not None
    assert result["action"] == "request_clarification"
    assert "Owner" in result["reply"]
    assert result["notes"] == "availability_verify_error"


def test_validate_confirmed_slot_returns_none_when_slot_available(monkeypatch):
    slot_start = _tz_aware(datetime(2025, 1, 5, 14, 0))
    monkeypatch.setattr(
        scheduling_agent.availability_service,
        "get_slots_for_date",
        lambda *_, **__: [DummySlot(slot_start, slot_start + timedelta(minutes=30))],
    )

    result = scheduling_agent._validate_confirmed_slot(
        user=SimpleNamespace(),
        event_type=SimpleNamespace(),
        slot_start=slot_start,
        owner_name="Owner",
    )

    assert result is None


def test_validate_confirmed_slot_returns_fallback_when_slot_taken(monkeypatch):
    slot_start = _tz_aware(datetime(2025, 1, 5, 14, 0))
    fallback_slot = DummySlot(
        _tz_aware(datetime(2025, 1, 6, 9, 0)),
        _tz_aware(datetime(2025, 1, 6, 9, 30)),
    )

    monkeypatch.setattr(
        scheduling_agent.availability_service,
        "get_slots_for_date",
        lambda *_, **__: [DummySlot(_tz_aware(datetime(2025, 1, 5, 10, 0)), _tz_aware(datetime(2025, 1, 5, 10, 30)))],
    )
    monkeypatch.setattr(
        scheduling_agent,
        "_find_fallback_slots",
        lambda *_, **__: [fallback_slot],
    )
    monkeypatch.setattr(
        scheduling_agent.availability_service,
        "get_timezone",
        lambda *_: pytz.UTC,
    )

    result = scheduling_agent._validate_confirmed_slot(
        user=SimpleNamespace(),
        event_type=SimpleNamespace(),
        slot_start=slot_start,
        owner_name="Owner",
    )

    assert result is not None
    assert result["action"] == "propose_slots"
    assert len(result["proposed_slots"]) == 1
    assert result["proposed_slots"][0]["start"].startswith("2025-01-06T09:00")
    assert "Here are a few other openings" in result["reply"]


def test_find_fallback_slots_respects_limit_and_skips_matching_slot(monkeypatch):
    slot_start = _tz_aware(datetime(2025, 1, 5, 14, 0))

    def fake_get_availability_for_range(user, event_type, start_date, end_date):
        return SimpleNamespace(
            slots_by_date={
                start_date: [
                    DummySlot(slot_start, slot_start + timedelta(minutes=30)),
                    DummySlot(slot_start + timedelta(hours=1), slot_start + timedelta(hours=1, minutes=30)),
                ],
                start_date + timedelta(days=1): [
                    DummySlot(slot_start + timedelta(days=1), slot_start + timedelta(days=1, minutes=30)),
                ],
            }
        )

    monkeypatch.setattr(
        scheduling_agent.availability_service,
        "get_timezone",
        lambda *_: pytz.UTC,
    )
    monkeypatch.setattr(
        scheduling_agent.availability_service,
        "get_availability_for_range",
        fake_get_availability_for_range,
    )

    slots = scheduling_agent._find_fallback_slots(
        user=SimpleNamespace(),
        event_type=SimpleNamespace(),
        slot_start=slot_start,
        limit=2,
    )

    # Should skip the matching slot and honor the limit
    assert len(slots) == 2
    assert all(abs((slot.start - slot_start).total_seconds()) >= 60 for slot in slots)


def test_notify_owner_calendar_issue_sends_email(monkeypatch):
    captured = {}

    def fake_send_email(to_addr, subject, text_body, **kwargs):
        captured["to"] = to_addr
        captured["subject"] = subject
        captured["body"] = text_body

    monkeypatch.setattr(scheduling_agent.gmail_service, "send_email", fake_send_email)

    user = SimpleNamespace(email="owner@example.com", username="Owner")
    scheduling_agent._notify_owner_calendar_issue(user, "availability_fetch_error")

    assert captured["to"] == "owner@example.com"
    assert "Restore Google Calendar access" in captured["subject"]
    assert "Settings → Calendars" in captured["body"]
    assert "https://calautobot.com/settings/calendars" in captured["body"]


def test_notify_owner_calendar_issue_ignores_unknown_note(monkeypatch):
    monkeypatch.setattr(
        scheduling_agent.gmail_service,
        "send_email",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    user = SimpleNamespace(email="owner@example.com", username="Owner")
    scheduling_agent._notify_owner_calendar_issue(user, "unrelated_note")


def test_notify_owner_calendar_issue_requires_email(monkeypatch):
    monkeypatch.setattr(
        scheduling_agent.gmail_service,
        "send_email",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    user = SimpleNamespace(email=None, username="Owner")
    scheduling_agent._notify_owner_calendar_issue(user, "availability_fetch_error")


def test_coalesce_availability_windows_merges_contiguous_slots():
    day = datetime(2025, 1, 5, 9, 0, tzinfo=pytz.UTC)
    slots_by_date = {
        day.date(): [
            DummySlot(day, day + timedelta(minutes=30)),
            DummySlot(day + timedelta(minutes=30), day + timedelta(minutes=60)),
            DummySlot(day + timedelta(minutes=60), day + timedelta(minutes=90)),
        ]
    }
    batch = SimpleNamespace(slots_by_date=slots_by_date)

    blocks = scheduling_agent._coalesce_availability_windows(batch, day.date(), max_blocks=5)

    assert len(blocks) == 1
    assert blocks[0]["start"].startswith("2025-01-05T09:00")
    assert blocks[0]["end"].startswith("2025-01-05T10:30")


def test_coalesce_availability_windows_splits_on_gap():
    day = datetime(2025, 1, 5, 9, 0, tzinfo=pytz.UTC)
    slots_by_date = {
        day.date(): [
            DummySlot(day, day + timedelta(minutes=30)),
            DummySlot(day + timedelta(minutes=30), day + timedelta(minutes=60)),
            DummySlot(day + timedelta(minutes=120), day + timedelta(minutes=150)),
        ]
    }
    batch = SimpleNamespace(slots_by_date=slots_by_date)

    blocks = scheduling_agent._coalesce_availability_windows(batch, day.date(), max_blocks=5)

    assert len(blocks) == 2
    assert blocks[0]["start"].startswith("2025-01-05T09:00")
    assert blocks[0]["end"].startswith("2025-01-05T10:00")
    assert blocks[1]["start"].startswith("2025-01-05T11:00")
    assert blocks[1]["end"].startswith("2025-01-05T11:30")


def test_coalesce_availability_windows_respects_limit():
    day = datetime(2025, 1, 5, 9, 0, tzinfo=pytz.UTC)
    slots_by_date = {
        day.date(): [
            DummySlot(day + timedelta(minutes=offset), day + timedelta(minutes=offset + 30))
            for offset in range(0, 240, 30)
        ]
    }
    batch = SimpleNamespace(slots_by_date=slots_by_date)

    blocks = scheduling_agent._coalesce_availability_windows(batch, day.date(), max_blocks=1)

    assert len(blocks) == 1
    assert blocks[0]["start"].startswith("2025-01-05T09:00")
