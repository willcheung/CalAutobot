"""Tests for the Gmail push processor (synchronous processing, locking, dedup)."""

import base64
import json
import ssl
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models import GmailPushState
from app.services import gmail_push_processor
from app.services.gmail_push_processor import (
    LOCK_TIMEOUT_SECONDS,
    _acquire_lock,
    _acquire_state,
    _extract_message_ids,
    _get_allowed_recipients,
    _recipient_is_allowed,
    _release_lock,
    handle_history,
    handle_history_message,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pubsub_envelope(history_id="12345", email_address="test@example.com"):
    """Build a minimal Pub/Sub push envelope."""
    data = base64.b64encode(
        json.dumps({"historyId": history_id, "emailAddress": email_address}).encode()
    ).decode()
    return {
        "message": {
            "data": data,
            "attributes": {
                "emailAddress": email_address,
                "resourceState": "exists",
                "resourceId": "res-1",
            },
        }
    }


def _make_email_data(message_id="msg-1", to="go@calautobot.com", sender="user@example.com"):
    """Build minimal email data matching GmailService.get_email_details output."""
    return {
        "id": message_id,
        "thread_id": "thread-1",
        "message_id": f"<{message_id}@mail.gmail.com>",
        "sender": sender,
        "sender_name": "Test User",
        "recipient": to,
        "to": [to],
        "cc": [],
        "subject": "Test Email",
        "stripped-text": "Test body",
        "body_text": "Test body",
        "attachments": [],
        "raw_headers": {"to": to, "cc": ""},
        "received_at": datetime.utcnow(),
    }


# ---------------------------------------------------------------------------
# Lock mechanism tests
# ---------------------------------------------------------------------------


class TestAcquireLock:
    def test_first_acquisition_creates_state(self, app_context):
        state = _acquire_lock("new@example.com")
        assert state is not None
        assert state.email_address == "new@example.com"
        assert state.processing_locked_at is not None

    def test_second_acquisition_blocked_within_timeout(self, app_context):
        state = _acquire_lock("test@example.com")
        assert state is not None

        # Second attempt within the lock window should fail
        state2 = _acquire_lock("test@example.com")
        assert state2 is None

    def test_acquisition_succeeds_after_timeout(self, app_context):
        state = _acquire_lock("test@example.com")
        assert state is not None

        # Manually expire the lock
        state.processing_locked_at = datetime.utcnow() - timedelta(
            seconds=LOCK_TIMEOUT_SECONDS + 1
        )
        db.session.commit()

        # Now acquisition should succeed
        state2 = _acquire_lock("test@example.com")
        assert state2 is not None

    def test_release_lock_clears_timestamp(self, app_context):
        state = _acquire_lock("test@example.com")
        assert state.processing_locked_at is not None

        _release_lock(state)
        assert state.processing_locked_at is None

        # After release, re-acquisition should succeed
        state2 = _acquire_lock("test@example.com")
        assert state2 is not None

    def test_different_emails_do_not_block_each_other(self, app_context):
        state_a = _acquire_lock("a@example.com")
        state_b = _acquire_lock("b@example.com")
        assert state_a is not None
        assert state_b is not None


class TestAcquireState:
    def test_creates_new_state(self, app_context):
        state = _acquire_state("fresh@example.com")
        assert state.email_address == "fresh@example.com"
        assert state.id is not None

    def test_returns_existing_state(self, app_context):
        state1 = _acquire_state("same@example.com")
        state2 = _acquire_state("same@example.com")
        assert state1.id == state2.id


# ---------------------------------------------------------------------------
# Recipient filtering tests
# ---------------------------------------------------------------------------


class TestRecipientFiltering:
    def test_allowed_recipients_from_env(self, monkeypatch):
        monkeypatch.setenv("GMAIL_ALLOWED_RECIPIENTS", "a@test.com, b@test.com")
        result = _get_allowed_recipients()
        assert result == {"a@test.com", "b@test.com"}

    def test_allowed_recipients_default(self, monkeypatch):
        monkeypatch.delenv("GMAIL_ALLOWED_RECIPIENTS", raising=False)
        result = _get_allowed_recipients()
        assert result == {"go@calautobot.com", "cal@calautobot.com"}

    def test_recipient_is_allowed_matches(self):
        allowed = {"go@calautobot.com"}
        assert _recipient_is_allowed("go@calautobot.com", allowed) is True
        assert _recipient_is_allowed("User <go@calautobot.com>", allowed) is True

    def test_recipient_is_allowed_no_match(self):
        allowed = {"go@calautobot.com"}
        assert _recipient_is_allowed("other@example.com", allowed) is False

    def test_recipient_allowed_via_cc(self):
        allowed = {"go@calautobot.com"}
        assert _recipient_is_allowed("other@example.com", allowed, cc_header="go@calautobot.com") is True

    def test_empty_allowed_permits_all(self):
        assert _recipient_is_allowed("anyone@example.com", set()) is True


# ---------------------------------------------------------------------------
# Message ID extraction tests
# ---------------------------------------------------------------------------


class TestExtractMessageIds:
    def test_extracts_from_messages_added(self):
        records = [
            {"messagesAdded": [{"message": {"id": "msg-1"}}, {"message": {"id": "msg-2"}}]},
            {"messagesAdded": [{"message": {"id": "msg-3"}}]},
        ]
        assert _extract_message_ids(records) == {"msg-1", "msg-2", "msg-3"}

    def test_empty_history(self):
        assert _extract_message_ids([]) == set()

    def test_no_messages_added_key(self):
        records = [{"labelsAdded": [{"message": {"id": "msg-1"}}]}]
        assert _extract_message_ids(records) == set()


# ---------------------------------------------------------------------------
# handle_history_message tests
# ---------------------------------------------------------------------------


class TestHandleHistoryMessage:
    def test_skips_message_without_data(self, app_context):
        envelope = {"message": {"attributes": {}}}
        # Should not raise — just logs and returns
        handle_history_message(envelope)

    def test_skips_invalid_base64(self, app_context):
        envelope = {"message": {"data": "!!!not-base64!!!", "attributes": {}}}
        handle_history_message(envelope)

    def test_skips_missing_history_id(self, app_context):
        data = base64.b64encode(json.dumps({"emailAddress": "x@test.com"}).encode()).decode()
        envelope = {"message": {"data": data, "attributes": {}}}
        handle_history_message(envelope)

    @patch("app.services.gmail_push_processor.handle_history")
    def test_calls_handle_history_with_decoded_payload(self, mock_handle, app_context):
        envelope = _make_pubsub_envelope(history_id="99999", email_address="user@test.com")
        handle_history_message(envelope)

        mock_handle.assert_called_once_with(
            email_address="user@test.com",
            history_id="99999",
            resource_state="exists",
            resource_id="res-1",
        )


# ---------------------------------------------------------------------------
# handle_history integration tests
# ---------------------------------------------------------------------------


class TestHandleHistory:
    @patch("app.services.gmail_push_processor.gmail_service")
    def test_updates_history_id_when_no_new_messages(self, mock_gmail, app_context):
        mock_gmail.list_history.return_value = []

        handle_history(email_address="me", history_id="500")

        state = GmailPushState.query.filter_by(email_address="me").first()
        assert state.last_history_id == "500"
        assert state.processing_locked_at is None  # lock released

    @patch("app.services.gmail_push_processor.gmail_service")
    def test_processes_new_messages(self, mock_gmail, app_context):
        mock_gmail.list_history.return_value = [
            {"id": "600", "messagesAdded": [{"message": {"id": "msg-A"}}]},
        ]
        mock_service = MagicMock()
        mock_gmail.get_service.return_value = mock_service
        mock_gmail.get_email_details.return_value = _make_email_data("msg-A")

        with patch("app.services.gmail_processor.process_single_email", return_value=True):
            handle_history(email_address="me", history_id="600")

        mock_gmail.mark_as_read.assert_called_once_with("msg-A")
        state = GmailPushState.query.filter_by(email_address="me").first()
        assert state.last_history_id == "600"
        assert state.processing_locked_at is None

    @patch("app.services.gmail_push_processor.gmail_service")
    def test_skips_disallowed_recipients(self, mock_gmail, app_context, monkeypatch):
        monkeypatch.setenv("GMAIL_ALLOWED_RECIPIENTS", "go@calautobot.com")

        mock_gmail.list_history.return_value = [
            {"id": "700", "messagesAdded": [{"message": {"id": "msg-B"}}]},
        ]
        mock_service = MagicMock()
        mock_gmail.get_service.return_value = mock_service
        mock_gmail.get_email_details.return_value = _make_email_data(
            "msg-B", to="other@domain.com"
        )

        with patch("app.services.gmail_processor.process_single_email") as mock_process:
            handle_history(email_address="me", history_id="700")
            mock_process.assert_not_called()

    @patch("app.services.gmail_push_processor.gmail_service")
    def test_lock_prevents_concurrent_processing(self, mock_gmail, app_context):
        mock_gmail.list_history.return_value = []

        # First call acquires the lock and processes
        handle_history(email_address="me", history_id="100")

        # Simulate a lock that hasn't been released (mimic concurrent scenario)
        state = GmailPushState.query.filter_by(email_address="me").first()
        state.processing_locked_at = datetime.utcnow()
        db.session.commit()

        # Reset the mock to check the second call doesn't process
        mock_gmail.list_history.reset_mock()

        handle_history(email_address="me", history_id="200")

        # list_history should NOT have been called — lock blocked it
        mock_gmail.list_history.assert_not_called()

    @patch("app.services.gmail_push_processor.gmail_service")
    def test_tracks_highest_history_id(self, mock_gmail, app_context):
        mock_gmail.list_history.return_value = [
            {"id": "800", "messagesAdded": [{"message": {"id": "msg-C"}}]},
            {"id": "850", "messagesAdded": [{"message": {"id": "msg-D"}}]},
        ]
        mock_service = MagicMock()
        mock_gmail.get_service.return_value = mock_service
        mock_gmail.get_email_details.return_value = _make_email_data("msg-C")

        with patch("app.services.gmail_processor.process_single_email", return_value=True):
            handle_history(email_address="me", history_id="800")

        state = GmailPushState.query.filter_by(email_address="me").first()
        assert state.last_history_id == "850"

    @patch("app.services.gmail_push_processor.gmail_service")
    def test_releases_lock_on_exception(self, mock_gmail, app_context):
        mock_gmail.list_history.return_value = [
            {"id": "900", "messagesAdded": [{"message": {"id": "msg-E"}}]},
        ]
        mock_gmail.get_service.return_value = MagicMock()
        # Simulate a failure when fetching email details
        mock_gmail.get_email_details.side_effect = RuntimeError("boom")

        handle_history(email_address="me", history_id="900")

        state = GmailPushState.query.filter_by(email_address="me").first()
        assert state.processing_locked_at is None  # lock released despite error


# ---------------------------------------------------------------------------
# Webhook route tests
# ---------------------------------------------------------------------------


class TestGmailPushWebhook:
    def test_get_returns_challenge(self, client):
        resp = client.get("/webhook/gmail/push?challenge=test123")
        assert resp.status_code == 200
        assert resp.data == b"test123"

    def test_post_without_message_returns_204(self, client):
        resp = client.post(
            "/webhook/gmail/push",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 204

    @patch("app.services.gmail_push_processor.handle_history")
    def test_post_processes_synchronously(self, mock_handle, client):
        envelope = _make_pubsub_envelope()
        resp = client.post(
            "/webhook/gmail/push",
            json=envelope,
            content_type="application/json",
        )
        assert resp.status_code == 204
        mock_handle.assert_called_once()


# ---------------------------------------------------------------------------
# SSL retry tests (gmail_service.list_history)
# ---------------------------------------------------------------------------


class TestListHistorySSLRetry:
    @patch("app.services.gmail_service.GmailService.get_service")
    def test_retries_on_ssl_error(self, mock_get_service):
        from app.services.gmail_service import gmail_service as gs

        mock_service = MagicMock()
        # First call raises SSL error, second succeeds
        first_history_call = MagicMock()
        first_history_call.list.return_value.execute.side_effect = ssl.SSLError(
            "EOF occurred in violation of protocol"
        )
        second_history_call = MagicMock()
        second_history_call.list.return_value.execute.return_value = {
            "history": [{"id": "100", "messagesAdded": []}]
        }

        mock_service.users.return_value.history.side_effect = [
            first_history_call,
            second_history_call,
        ]
        mock_get_service.return_value = mock_service

        result = gs.list_history("50")
        assert len(result) == 1
        assert mock_get_service.call_count == 2  # called twice (original + retry)

    @patch("app.services.gmail_service.GmailService.get_service")
    def test_does_not_retry_non_ssl_errors(self, mock_get_service):
        from app.services.gmail_service import gmail_service as gs

        mock_service = MagicMock()
        mock_service.users.return_value.history.return_value.list.return_value.execute.side_effect = (
            ValueError("unrelated error")
        )
        mock_get_service.return_value = mock_service

        result = gs.list_history("50")
        assert result == []
        assert mock_get_service.call_count == 1  # no retry

    @patch("app.services.gmail_service.GmailService.get_service")
    def test_does_not_retry_more_than_once(self, mock_get_service):
        from app.services.gmail_service import gmail_service as gs

        mock_service = MagicMock()
        mock_service.users.return_value.history.return_value.list.return_value.execute.side_effect = (
            ssl.SSLError("EOF occurred in violation of protocol")
        )
        mock_get_service.return_value = mock_service

        result = gs.list_history("50")
        assert result == []
        assert mock_get_service.call_count == 2  # original + one retry, no more


# ---------------------------------------------------------------------------
# SSL retry tests (gmail_service.mark_as_read)
# ---------------------------------------------------------------------------


class TestMarkAsReadSSLRetry:
    @patch("app.services.gmail_service.GmailService.get_service")
    def test_retries_on_ssl_error(self, mock_get_service):
        from app.services.gmail_service import gmail_service as gs

        # First service: modify raises SSL error
        first_service = MagicMock()
        first_service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = (
            ssl.SSLError("EOF occurred in violation of protocol")
        )
        # Second service: modify succeeds
        second_service = MagicMock()
        second_service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}

        mock_get_service.side_effect = [first_service, second_service]

        result = gs.mark_as_read("msg-123")
        assert result is True
        assert mock_get_service.call_count == 2  # original + retry

    @patch("app.services.gmail_service.GmailService.get_service")
    def test_does_not_retry_non_ssl_errors(self, mock_get_service):
        from app.services.gmail_service import gmail_service as gs

        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = (
            ValueError("unrelated error")
        )
        mock_get_service.return_value = mock_service

        result = gs.mark_as_read("msg-123")
        assert result is False
        assert mock_get_service.call_count == 1  # no retry

    @patch("app.services.gmail_service.GmailService.get_service")
    def test_does_not_retry_more_than_once(self, mock_get_service):
        from app.services.gmail_service import gmail_service as gs

        mock_service = MagicMock()
        mock_service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = (
            ssl.SSLError("EOF occurred in violation of protocol")
        )
        mock_get_service.return_value = mock_service

        result = gs.mark_as_read("msg-123")
        assert result is False
        assert mock_get_service.call_count == 2  # original + one retry, no more
