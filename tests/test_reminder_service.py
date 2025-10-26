from datetime import datetime, timedelta
from types import SimpleNamespace

import pytz

from app.services import reminder_service


def test_should_send_reminder_window():
    start_dt = datetime(2025, 1, 1, 15, 0, tzinfo=pytz.UTC)
    now = start_dt - timedelta(hours=2)
    assert reminder_service._should_send_reminder(now, start_dt, lead_hours=2)
    before_window = start_dt - timedelta(hours=2, minutes=1)
    assert not reminder_service._should_send_reminder(before_window, start_dt, lead_hours=2)
    assert not reminder_service._should_send_reminder(start_dt + timedelta(minutes=5), start_dt, lead_hours=1)


def test_collect_recipients_excludes_owner_and_assistants():
    event = SimpleNamespace(invitee_email="invitee@example.com")
    meeting_request = SimpleNamespace(
        participants=[
            SimpleNamespace(email="owner@example.com"),
            SimpleNamespace(email="cal@calautobot.com"),
            SimpleNamespace(email="partner@example.com"),
        ]
    )
    recipients = reminder_service._collect_recipient_emails(event, meeting_request, "owner@example.com")
    assert recipients == ["invitee@example.com", "partner@example.com"]


def test_send_reminder_email_moves_owner_to_cc(monkeypatch):
    sent_payload = {}

    def fake_send_email(to, subject, **kwargs):
        sent_payload["to"] = to
        sent_payload["subject"] = subject
        sent_payload["cc"] = kwargs.get("cc_recipients")
        sent_payload["body"] = kwargs.get("text_body")
        return True

    monkeypatch.setattr(reminder_service.gmail_service, "send_email", fake_send_email)

    result = reminder_service._send_reminder_email(
        owner_email="owner@example.com",
        participant_emails=["guest@example.com", "ally@example.com"],
        subject="Reminder",
        body="Body",
    )

    assert result is True
    assert sent_payload["to"] == "guest@example.com, ally@example.com"
    assert sent_payload["cc"] == ["owner@example.com"]
