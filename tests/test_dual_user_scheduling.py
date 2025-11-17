"""
Tests for dual authenticated user scheduling scenarios.

When two authenticated Cal users email each other with Cal cc'd,
the system should deterministically select the sender as the owner.
"""

from datetime import datetime

import pytest

from app import db
from app.models import User
from app.services.gmail_processor import process_single_email


def test_dual_authenticated_users_sender_priority(monkeypatch, app_context):
    """
    Test that when both sender and recipient are authenticated users,
    the sender is selected as the owner (deterministic behavior).

    Scenario:
    - Alice (authenticated) emails Bob (authenticated) with Cal cc'd
    - System should use Alice's calendar as the owner
    """
    # Create two authenticated users
    alice = User(
        username="Alice",
        email="alice@example.com",
        timezone="America/Los_Angeles",
        google_id="alice-google-id",
        google_token='{"access_token": "alice-token", "refresh_token": "alice-refresh"}'
    )
    db.session.add(alice)

    bob = User(
        username="Bob",
        email="bob@example.com",
        timezone="America/New_York",
        google_id="bob-google-id",
        google_token='{"access_token": "bob-token", "refresh_token": "bob-refresh"}'
    )
    db.session.add(bob)
    db.session.commit()

    # Track which user was selected as owner
    selected_owner = []

    def fake_handle_scheduling_email(email_data, owner_user):
        selected_owner.append(owner_user.email)
        return {"action": "propose_slots"}

    monkeypatch.setattr(
        "app.services.gmail_processor.handle_scheduling_email",
        fake_handle_scheduling_email
    )

    # Mock classification to return schedule_meeting
    def fake_classify(*args, **kwargs):
        return "schedule_meeting"

    monkeypatch.setattr("app.agents.task_classifier.classify_email_task", fake_classify)

    # Alice emails Bob with Cal cc'd
    email_data = {
        "sender": "alice@example.com",
        "sender_name": "Alice",
        "subject": "Let's meet next week",
        "body_text": "Hi Bob, can we schedule a meeting next week?",
        "body_html": "<p>Hi Bob, can we schedule a meeting next week?</p>",
        "to": ["bob@example.com"],
        "cc": ["cal@calautobot.com"],
        "thread_id": "thread-dual-user-123",
        "message_id": "msg-dual-user-123",
        "received_at": datetime.utcnow(),
        "raw_headers": {},
        "attachments": [],
    }

    # Process the email
    result = process_single_email(email_data)

    # Verify sender (Alice) was selected as owner
    assert len(selected_owner) == 1
    assert selected_owner[0] == "alice@example.com", (
        "Sender should be selected as owner when both users are authenticated"
    )

    print("✅ Test passed: Sender (Alice) was selected as owner over recipient (Bob)")


def test_dual_authenticated_users_recipient_fallback(monkeypatch, app_context):
    """
    Test that when sender is NOT authenticated but recipient is,
    the recipient is selected as the owner.

    Scenario:
    - Charlie (not authenticated) emails Alice (authenticated) with Cal cc'd
    - System should use Alice's calendar as the owner
    """
    # Create authenticated user
    alice = User(
        username="Alice",
        email="alice@example.com",
        timezone="America/Los_Angeles",
        google_id="alice-google-id",
        google_token='{"access_token": "alice-token", "refresh_token": "alice-refresh"}'
    )
    db.session.add(alice)
    db.session.commit()

    # Track which user was selected as owner
    selected_owner = []

    def fake_handle_scheduling_email(email_data, owner_user):
        selected_owner.append(owner_user.email)
        return {"action": "propose_slots"}

    monkeypatch.setattr(
        "app.services.gmail_processor.handle_scheduling_email",
        fake_handle_scheduling_email
    )

    # Mock classification to return schedule_meeting
    def fake_classify(*args, **kwargs):
        return "schedule_meeting"

    monkeypatch.setattr("app.agents.task_classifier.classify_email_task", fake_classify)

    # Charlie (not a Cal user) emails Alice with Cal cc'd
    email_data = {
        "sender": "charlie@external.com",
        "sender_name": "Charlie",
        "subject": "Meeting request",
        "body_text": "Hi Alice, can we meet?",
        "body_html": "<p>Hi Alice, can we meet?</p>",
        "to": ["alice@example.com"],
        "cc": ["cal@calautobot.com"],
        "thread_id": "thread-fallback-123",
        "message_id": "msg-fallback-123",
        "received_at": datetime.utcnow(),
        "raw_headers": {},
        "attachments": [],
    }

    # Process the email
    result = process_single_email(email_data)

    # Verify recipient (Alice) was selected as owner
    assert len(selected_owner) == 1
    assert selected_owner[0] == "alice@example.com", (
        "Recipient should be selected as owner when sender is not authenticated"
    )

    print("✅ Test passed: Recipient (Alice) was selected as owner when sender not authenticated")


def test_dual_authenticated_users_multiple_recipients(monkeypatch, app_context):
    """
    Test that sender is selected even when there are multiple authenticated recipients.

    Scenario:
    - Alice (authenticated) emails Bob (authenticated) and Carol (authenticated) with Cal cc'd
    - System should still use Alice's calendar (sender priority)
    """
    # Create three authenticated users
    alice = User(
        username="Alice",
        email="alice@example.com",
        timezone="America/Los_Angeles",
        google_id="alice-google-id",
        google_token='{"access_token": "alice-token", "refresh_token": "alice-refresh"}'
    )
    db.session.add(alice)

    bob = User(
        username="Bob",
        email="bob@example.com",
        timezone="America/New_York",
        google_id="bob-google-id",
        google_token='{"access_token": "bob-token", "refresh_token": "bob-refresh"}'
    )
    db.session.add(bob)

    carol = User(
        username="Carol",
        email="carol@example.com",
        timezone="America/Chicago",
        google_id="carol-google-id",
        google_token='{"access_token": "carol-token", "refresh_token": "carol-refresh"}'
    )
    db.session.add(carol)
    db.session.commit()

    # Track which user was selected as owner
    selected_owner = []

    def fake_handle_scheduling_email(email_data, owner_user):
        selected_owner.append(owner_user.email)
        return {"action": "propose_slots"}

    monkeypatch.setattr(
        "app.services.gmail_processor.handle_scheduling_email",
        fake_handle_scheduling_email
    )

    # Mock classification to return schedule_meeting
    def fake_classify(*args, **kwargs):
        return "schedule_meeting"

    monkeypatch.setattr("app.agents.task_classifier.classify_email_task", fake_classify)

    # Alice emails Bob and Carol with Cal cc'd
    email_data = {
        "sender": "alice@example.com",
        "sender_name": "Alice",
        "subject": "Team meeting",
        "body_text": "Hi Bob and Carol, let's schedule a team meeting",
        "body_html": "<p>Hi Bob and Carol, let's schedule a team meeting</p>",
        "to": ["bob@example.com", "carol@example.com"],
        "cc": ["cal@calautobot.com"],
        "thread_id": "thread-multi-123",
        "message_id": "msg-multi-123",
        "received_at": datetime.utcnow(),
        "raw_headers": {},
        "attachments": [],
    }

    # Process the email
    result = process_single_email(email_data)

    # Verify sender (Alice) was selected as owner
    assert len(selected_owner) == 1
    assert selected_owner[0] == "alice@example.com", (
        "Sender should be selected as owner even with multiple authenticated recipients"
    )

    print("✅ Test passed: Sender (Alice) selected over multiple authenticated recipients")


def test_provisional_user_with_authenticated_recipient_still_works(monkeypatch, app_context):
    """
    Test that the existing fix for provisional users cc'ing authenticated users still works.

    This ensures we didn't break the previous bug fix where provisional users
    at their limit could bypass it by cc'ing an authenticated user.
    """
    # Create authenticated user
    alice = User(
        username="Alice",
        email="alice@example.com",
        timezone="America/Los_Angeles",
        google_id="alice-google-id",
        google_token='{"access_token": "alice-token", "refresh_token": "alice-refresh"}'
    )
    db.session.add(alice)
    db.session.commit()

    # Track which user was selected as owner
    selected_owner = []

    def fake_handle_scheduling_email(email_data, owner_user):
        selected_owner.append(owner_user.email)
        return {"action": "propose_slots"}

    monkeypatch.setattr(
        "app.services.gmail_processor.handle_scheduling_email",
        fake_handle_scheduling_email
    )

    # Mock classification to return schedule_meeting
    def fake_classify(*args, **kwargs):
        return "schedule_meeting"

    monkeypatch.setattr("app.agents.task_classifier.classify_email_task", fake_classify)

    # Provisional user emails with Alice cc'd
    email_data = {
        "sender": "provisional@external.com",
        "sender_name": "Provisional User",
        "subject": "Meeting with Alice",
        "body_text": "Hi Alice, can we schedule a meeting?",
        "body_html": "<p>Hi Alice, can we schedule a meeting?</p>",
        "to": ["alice@example.com"],
        "cc": ["cal@calautobot.com"],
        "thread_id": "thread-provisional-123",
        "message_id": "msg-provisional-123",
        "received_at": datetime.utcnow(),
        "raw_headers": {},
        "attachments": [],
    }

    # Process the email
    result = process_single_email(email_data)

    # Verify recipient (Alice) was selected as owner (bypassing provisional user limits)
    assert len(selected_owner) == 1
    assert selected_owner[0] == "alice@example.com", (
        "Authenticated recipient should be selected as owner for provisional sender"
    )

    print("✅ Test passed: Provisional user with authenticated recipient still bypasses limits")
