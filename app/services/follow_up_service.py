import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from app import db
from app.models import MeetingRequest
from app.services.calendar_notifications import notify_owner_calendar_issue
from app.services.scheduling_agent import (
    MAX_FOLLOW_UPS,
    get_follow_up_delays,
    prepare_agent_context_for_request,
    run_meeting_scheduler_agent,
    send_agent_reply_email,
)

logger = logging.getLogger(__name__)


def _latest_message_record(meeting_request: MeetingRequest):
    if not meeting_request.messages:
        return None
    return max(
        meeting_request.messages,
        key=lambda msg: (msg.received_at or msg.created_at or datetime.utcnow()),
    )


def _update_follow_up_schedule_after_send(
    meeting_request: MeetingRequest,
    user_first_delay: int,
    user_second_delay: int,
) -> None:
    follow_up_number = (meeting_request.follow_up_count or 0) + 1
    meeting_request.follow_up_count = follow_up_number

    if follow_up_number >= MAX_FOLLOW_UPS:
        meeting_request.next_follow_up_at = None
        return

    delta_days = max(1, user_second_delay - user_first_delay)
    meeting_request.next_follow_up_at = datetime.utcnow() + timedelta(days=delta_days)


def _should_track_follow_up(action: Optional[str]) -> bool:
    return action in {"propose_slots", "request_clarification", "reschedule"}


def _send_follow_up_for_request(meeting_request: MeetingRequest) -> bool:
    user = meeting_request.user
    if not user:
        logger.warning("Skipping follow-up for meeting_request %s without user", meeting_request.id)
        return False

    if user.follow_up_enabled is False:
        meeting_request.next_follow_up_at = None
        meeting_request.follow_up_count = 0
        return False

    latest_message_row = _latest_message_record(meeting_request)
    if not latest_message_row:
        logger.warning("Skipping follow-up for meeting_request %s with no message history", meeting_request.id)
        meeting_request.next_follow_up_at = None
        return False

    context = prepare_agent_context_for_request(user, meeting_request)
    availability_error = context["availability_error"]
    if availability_error:
        logger.warning(
            "Skipping follow-up for meeting_request %s due to availability error: %s",
            meeting_request.id,
            availability_error,
        )
        meeting_request.next_follow_up_at = None
        return False

    agent_input = dict(context["agent_input"])
    history = context["history"]
    latest_message = context["latest_message"]
    availability = context["availability"]

    follow_up_number = (meeting_request.follow_up_count or 0) + 1
    wait_origin = (
        meeting_request.last_agent_reply_at
        or meeting_request.updated_at
        or meeting_request.created_at
        or datetime.utcnow()
    )
    days_waiting = max(1, (datetime.utcnow() - wait_origin).days or 1)
    agent_input["follow_up_context"] = (
        f"This is automated follow-up #{follow_up_number}. "
        f"No replies have been received in {days_waiting} day(s). "
        "Send a short, polite reminder and include refreshed availability."
    )

    agent_result = run_meeting_scheduler_agent(
        agent_input,
        history,
        latest_message,
        availability=availability,
    )

    action = agent_result.get("action")
    reply_text = agent_result.get("reply")
    if not reply_text or not _should_track_follow_up(action):
        logger.info(
            "Follow-up agent returned no actionable reply for meeting_request %s (action=%s)",
            meeting_request.id,
            action,
        )
        meeting_request.next_follow_up_at = None
        return False

    meeting_request.proposed_slots = agent_result.get("proposed_slots")
    meeting_request.confirmed_slot = agent_result.get("confirmed_slot")
    meeting_request.current_step = action
    if action == "confirm_slot" and meeting_request.confirmed_slot:
        meeting_request.status = "confirmed"
    elif action == "request_clarification":
        meeting_request.status = "collecting"
    else:
        meeting_request.status = "proposed"
    meeting_request.updated_at = datetime.utcnow()

    notify_owner_calendar_issue(user, agent_result.get("notes"))

    thread_id = latest_message_row.thread_id
    reply_to_message_id = latest_message_row.message_id
    if not thread_id:
        logger.warning("Cannot send follow-up for meeting_request %s without thread_id", meeting_request.id)
        meeting_request.next_follow_up_at = None
        return False

    if action == "confirm_slot":
        confirmed_info = meeting_request.confirmed_slot or {}
        conference_url = None
        if isinstance(confirmed_info, dict):
            conference_url = confirmed_info.get("conference_url")
        if conference_url and conference_url not in reply_text:
            reply_text = reply_text.rstrip() + f"\n\nVideo conference: {conference_url}\n"

    send_success = send_agent_reply_email(
        user,
        meeting_request,
        reply_text,
        thread_id=thread_id,
        reply_to_message_id=reply_to_message_id,
        subject=meeting_request.subject,
    )

    if not send_success:
        return False

    user_first_delay, user_second_delay = get_follow_up_delays(user)
    meeting_request.last_agent_reply_at = datetime.utcnow()
    _update_follow_up_schedule_after_send(meeting_request, user_first_delay, user_second_delay)
    return True


def send_due_followups(limit: int = 25) -> Dict[str, int]:
    """
    Send follow-ups for meeting requests whose timers have elapsed.
    """
    now = datetime.utcnow()
    query = (
        MeetingRequest.query.filter(
            MeetingRequest.next_follow_up_at.isnot(None),
            MeetingRequest.next_follow_up_at <= now,
            MeetingRequest.follow_up_count < MAX_FOLLOW_UPS,
            MeetingRequest.status.in_(["proposed", "collecting"]),
            MeetingRequest.confirmed_slot_json.is_(None),
        )
        .order_by(MeetingRequest.next_follow_up_at.asc())
    )
    if limit:
        due_requests = query.limit(limit).all()
    else:
        due_requests = query.all()

    processed = 0
    sent = 0
    for meeting_request in due_requests:
        processed += 1
        try:
            sent_this = _send_follow_up_for_request(meeting_request)
        except Exception as exc:
            logger.exception(
                "Error sending follow-up for meeting_request %s: %s",
                meeting_request.id,
                exc,
            )
            sent_this = False
        if sent_this:
            sent += 1

    db.session.commit()
    return {"processed": processed, "sent": sent}
