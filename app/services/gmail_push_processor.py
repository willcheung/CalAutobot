import base64
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional, Set, List

import sentry_sdk
from flask import current_app

from app import db
from app.models import GmailPushState
from app.services.gmail_service import gmail_service

logger = logging.getLogger(__name__)

# Lock window keeps concurrent push deliveries from stepping on each other.
# Keep it short so we rarely skip pushes yet still avoid parallel processing.
LOCK_TIMEOUT_SECONDS = 5

_MAX_WORKERS = max(1, int(os.environ.get("GMAIL_PUSH_WORKERS", "2")))
_PUSH_EXECUTOR = ThreadPoolExecutor(
    max_workers=_MAX_WORKERS,
    thread_name_prefix="gmail-push",
)


def _queue_depth() -> Optional[int]:
    work_queue = getattr(_PUSH_EXECUTOR, "_work_queue", None)
    if not work_queue:
        return None
    try:
        return work_queue.qsize()
    except Exception:
        return None


def enqueue_history_message(envelope: dict) -> bool:
    """Submit a Gmail push payload for background processing."""
    if not envelope:
        return False

    app = current_app._get_current_object()
    message_attrs = (envelope.get("message") or {}).get("attributes") or {}
    history_id = None

    raw_data = (envelope.get("message") or {}).get("data")
    if raw_data:
        try:
            decoded = base64.b64decode(raw_data).decode("utf-8")
            payload = json.loads(decoded)
            history_id = payload.get("historyId")
        except Exception:
            history_id = None

    depth = _queue_depth()
    sentry_sdk.add_breadcrumb(
        category="gmail_push.enqueue",
        message="Queued Gmail push task",
        level="info",
        data={
            "queue_depth": depth,
            "history_id": history_id,
            "resource_id": message_attrs.get("resourceId"),
        },
    )

    logger.info(
        "Enqueuing Gmail push task history_id=%s resource_id=%s depth=%s",
        history_id,
        message_attrs.get("resourceId"),
        depth,
    )

    _PUSH_EXECUTOR.submit(_run_history_task, app, envelope, depth)
    return True


def _run_history_task(app, envelope: dict, enqueue_depth: Optional[int] = None) -> None:
    start = time.monotonic()
    with app.app_context():
        try:
            sentry_sdk.add_breadcrumb(
                category="gmail_push.worker",
                message="Processing Gmail push task",
                level="info",
                data={"enqueue_depth": enqueue_depth},
            )
            handle_history_message(envelope)
            duration = time.monotonic() - start
            logger.info(
                "Completed Gmail push task in %.2fs (queued_depth=%s)",
                duration,
                enqueue_depth,
            )
            sentry_sdk.add_breadcrumb(
                category="gmail_push.worker",
                message="Completed Gmail push task",
                level="info",
                data={"duration_sec": round(duration, 2)},
            )
        except Exception as exc:
            duration = time.monotonic() - start
            logger.exception(
                "Background Gmail push task failed after %.2fs: %s",
                duration,
                exc,
            )
            sentry_sdk.capture_exception(exc)


def _get_allowed_recipients() -> Set[str]:
    """
    Determines which recipient addresses should be processed.
    Falls back to the historical inboxes if env override is absent.
    """
    raw = os.environ.get("GMAIL_ALLOWED_RECIPIENTS")
    if raw:
        recipients = [part.strip().lower() for part in raw.split(",") if part.strip()]
    else:
        recipients = ["go@calautobot.com", "cal@calautobot.com"]
    return {addr for addr in recipients if addr}


def _parse_recipients(header_value: Optional[str]) -> Set[str]:
    if not header_value:
        return set()
    parts = [item.strip().lower() for item in header_value.replace(">", "").split(",")]
    cleaned = set()
    for part in parts:
        if "<" in part:
            cleaned.add(part.split("<")[-1].strip())
        else:
            cleaned.add(part.strip())
    return {addr for addr in cleaned if addr}


def _recipient_is_allowed(to_header: Optional[str], allowed: Set[str], cc_header: Optional[str] = None) -> bool:
    if not allowed:
        return True
    addresses = _parse_recipients(to_header) | _parse_recipients(cc_header)
    if not addresses:
        return False
    return any(addr in allowed for addr in addresses)


def _acquire_state(email_address: str) -> GmailPushState:
    state = GmailPushState.query.filter_by(email_address=email_address).first()
    if not state:
        state = GmailPushState(email_address=email_address)
        db.session.add(state)
        db.session.commit()
    return state


def _acquire_lock(state: GmailPushState) -> bool:
    now = datetime.utcnow()
    if (
        state.processing_locked_at
        and (now - state.processing_locked_at) < timedelta(seconds=LOCK_TIMEOUT_SECONDS)
    ):
        logger.warning(
            "Gmail push processor locked for %s (started at %s)",
            state.email_address,
            state.processing_locked_at.isoformat(),
        )
        return False

    state.processing_locked_at = now
    db.session.commit()
    return True


def _release_lock(state: GmailPushState):
    state.processing_locked_at = None
    state.updated_at = datetime.utcnow()
    db.session.commit()


def _process_snapshot(allowed_recipients: Set[str]) -> int:
    """
    Fallback for initial sync: pull unread messages and run them through
    the existing polling handler.
    """
    try:
        emails = gmail_service.get_unread_emails(max_results=20)
        if not emails:
            return 0

        from app.services.gmail_processor import process_single_email

        processed = 0
        for email_data in emails:
            if not _recipient_is_allowed(email_data.get("recipient"), allowed_recipients):
                continue
            if process_single_email(email_data):
                gmail_service.mark_as_read(email_data["id"])
                processed += 1
        return processed
    except Exception as exc:
        logger.error("Error processing snapshot of unread emails: %s", exc)
        return 0


def _extract_message_ids(history_records: List[dict]) -> Set[str]:
    message_ids: Set[str] = set()
    for record in history_records:
        for entry in record.get("messagesAdded", []):
            message = entry.get("message", {})
            message_id = message.get("id")
            if message_id:
                message_ids.add(message_id)
    return message_ids


def handle_history_message(pubsub_message: dict) -> None:
    """
    Entry point for Pub/Sub push payloads. The payload is already decoded
    from JSON when routed here.
    """
    message_data = pubsub_message.get("message", {})
    attributes = message_data.get("attributes", {})
    email_address = attributes.get("emailAddress", "me")

    # Pub/Sub payload contains base64 encoded data with historyId + email.
    data = message_data.get("data")
    if not data:
        logger.warning("Received Gmail push message without data")
        return

    try:
        decoded = base64.b64decode(data).decode("utf-8")
        payload = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("Failed to decode Gmail push payload: %s", exc)
        return

    history_id = payload.get("historyId")
    if not history_id:
        logger.warning("Gmail push payload missing historyId; skipping")
        return

    resource_state = message_data.get("attributes", {}).get("resourceState")
    resource_id = message_data.get("attributes", {}).get("resourceId")

    handle_history(
        email_address=email_address,
        history_id=str(history_id),
        resource_state=resource_state,
        resource_id=resource_id,
    )


def handle_history(
    email_address: str,
    history_id: str,
    resource_state: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> None:
    """
    Process Gmail history entries starting at the provided history ID.

    Args:
        email_address (str): Gmail account that generated the push.
        history_id (str): Starting history ID from the push message.
        resource_state (Optional[str]): Optional Gmail resource state header.
        resource_id (Optional[str]): Optional Gmail resource identifier.
    """
    allowed_recipients = _get_allowed_recipients()
    state = _acquire_state(email_address)

    if not _acquire_lock(state):
        return

    try:
        if resource_id:
            state.watch_resource_id = resource_id

        start_history_id = state.last_history_id or history_id

        # Gmail emits a "sync" state for the very first push. Run a snapshot to
        # make sure we do not miss existing unread mail.
        processed_count = 0
        if resource_state == "sync" and not state.last_history_id:
            processed_count += _process_snapshot(allowed_recipients)

        history_records = gmail_service.list_history(start_history_id)
        if not history_records:
            state.last_history_id = history_id
            db.session.commit()
            if processed_count:
                logger.info(
                    "Completed Gmail snapshot processing for %s (%s messages)",
                    email_address,
                    processed_count,
                )
            return

        message_ids = _extract_message_ids(history_records)
        if not message_ids:
            logger.info("No new Gmail message IDs found for %s", email_address)
            state.last_history_id = history_id
            db.session.commit()
            return

        service = gmail_service.get_service()
        if not service:
            logger.error("Gmail service unavailable; cannot process push messages")
            return

        from app.services.gmail_processor import process_single_email

        for message_id in message_ids:
            try:
                email_data = gmail_service.get_email_details(service, message_id)
                if not email_data:
                    continue

                to_header = email_data.get("recipient")
                cc_header = None
                raw_headers = email_data.get("raw_headers")
                if isinstance(raw_headers, dict):
                    cc_header = raw_headers.get("cc")

                if not _recipient_is_allowed(to_header, allowed_recipients, cc_header):
                    logger.debug(
                        "Skipping Gmail message %s; recipients %s/%s not allowed",
                        message_id,
                        to_header,
                        cc_header,
                    )
                    continue

                if process_single_email(email_data):
                    gmail_service.mark_as_read(email_data["id"])
            except Exception as exc:
                logger.exception("Error processing Gmail message %s: %s", message_id, exc)
                continue

        # Track the highest history ID we observed to avoid reprocessing.
        history_candidates: List[int] = []
        try:
            history_candidates.append(int(history_id))
        except (TypeError, ValueError):
            pass
        for record in history_records:
            rid = record.get("id")
            if rid is None:
                continue
            try:
                history_candidates.append(int(rid))
            except (TypeError, ValueError):
                continue
        if history_candidates:
            state.last_history_id = str(max(history_candidates))
        db.session.commit()

    finally:
        _release_lock(state)


def renew_watch_if_needed(
    topic_name: str,
    label_ids: Optional[List[str]] = None,
    email_address: str = "me",
    renew_margin: timedelta = timedelta(hours=12),
    label_filter_action: str = "include",
) -> Optional[dict]:
    """
    Ensure a Gmail watch is active. If the existing watch is missing or close to
    expiring, start (or renew) it and persist the new history/expiration.
    """
    state = _acquire_state(email_address)
    now = datetime.utcnow()

    should_start = False
    if not state.watch_expiration:
        should_start = True
    elif state.watch_expiration <= now + renew_margin:
        should_start = True

    if not should_start:
        logger.info(
            "Existing Gmail watch for %s valid until %s",
            email_address,
            state.watch_expiration.isoformat() if state.watch_expiration else "unknown",
        )
        return None

    response = gmail_service.start_watch(
        topic_name=topic_name,
        label_ids=label_ids,
        label_filter_action=label_filter_action,
    )
    if not response:
        return None

    history_id = response.get("historyId")
    expiration_ms = response.get("expiration")

    if label_ids is not None:
        state.label_ids = label_ids

    if history_id:
        state.last_history_id = str(history_id)

    if expiration_ms:
        try:
            state.watch_expiration = datetime.utcfromtimestamp(int(expiration_ms) / 1000.0)
        except (TypeError, ValueError):
            state.watch_expiration = None

    state.processing_locked_at = None
    db.session.commit()
    logger.info(
        "Renewed Gmail watch for %s (historyId=%s, expires=%s)",
        email_address,
        history_id,
        state.watch_expiration.isoformat() if state.watch_expiration else "unknown",
    )
    return response
