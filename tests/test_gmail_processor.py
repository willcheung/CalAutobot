from datetime import datetime

from app import db
from app.models import MeetingMessage, MeetingRequest, User
from app.services import gmail_processor
from app.agents.task_classifier import ASSISTANT_EMAILS


def _base_payload(**overrides):
    payload = {
        "id": "abc",
        "sender": "external@example.com",
        "sender_name": "External",
        "subject": "Hello",
        "stripped-text": "Body",
        "body_html": "<p>Body</p>",
        "to": ["go@calautobot.com"],
        "cc": [],
        "thread_id": "thread-1",
        "message_id": "message-1",
        "received_at": datetime.utcnow(),
        "raw_headers": {},
        "attachments": [],
    }
    payload.update(overrides)
    return payload


def test_process_single_email_skips_assistant_sender(app_context):
    assistant_email = next(iter(ASSISTANT_EMAILS))
    payload = _base_payload(sender=assistant_email)

    assert gmail_processor.process_single_email(payload) is True


def test_process_single_email_skips_duplicate_message(app_context):
    user = User(username="Owner", email="owner@example.com", timezone="UTC")
    db.session.add(user)
    db.session.commit()

    meeting_request = MeetingRequest(user_id=user.id, subject="Test")
    db.session.add(meeting_request)
    db.session.flush()

    db.session.add(
        MeetingMessage(
            meeting_request_id=meeting_request.id,
            sender_email="external@example.com",
            message_id="message-1",
            thread_id="thread-1",
            body_text="Existing",
            received_at=datetime.utcnow(),
        )
    )
    db.session.commit()

    payload = _base_payload()

    # process_single_email should detect the existing message and skip further work
    assert gmail_processor.process_single_email(payload) is True
