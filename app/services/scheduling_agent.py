import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

from app import db
from app.models import (
    Event,
    MeetingMessage,
    MeetingParticipant,
    MeetingRequest,
    TextInput,
    User,
    EventType,
)
from app.agents.meeting_scheduler import run_meeting_scheduler_agent
from app.helpers.text_processing import sanitize_text_for_db
from app.services import availability as availability_service
from app.services.availability import AvailabilityBatch, AvailabilityError
from app.services.public_booking import create_booking_event, cancel_booking_event
from app.services.gmail_service import gmail_service
from app.services.calendar_notifications import (
    OWNER_ALERT_MESSAGES,
    notify_owner_calendar_issue,
)

logger = logging.getLogger(__name__)

ASSISTANT_EMAILS = {"go@calautobot.com", "cal@calautobot.com"}
MAX_FOLLOW_UPS = 2

# Backward compatibility for existing imports/tests
_notify_owner_calendar_issue = notify_owner_calendar_issue


def _normalise_addresses(raw_addresses) -> List[str]:
    addresses = []
    for address in raw_addresses or []:
        if not address:
            continue
        addresses.append(address.strip().lower())
    return addresses


def _format_slot_for_email_line(slot, tz) -> str:
    start_local = slot.start.astimezone(tz)
    end_local = slot.end.astimezone(tz)
    return (
        f"- {start_local.strftime('%b %d (%a) %I:%M %p %Z')}"
        f" to {end_local.strftime('%I:%M %p %Z')}"
    )


def _compose_system_issue_reply(owner_name: str) -> str:
    return (
        "Hi there,\n\n"
        f"This is Cal, {owner_name}'s assistant. I'm running into a system issue with our "
        "calendar right now, so I can't check availability or send confirmations at the moment. "
        "I'll follow up as soon as it's resolved. Thanks for your patience!\n\n"
        "Best,\nCal"
    )


def _compose_slot_taken_reply(owner_name: str, slot_start: datetime, tz, fallback_lines) -> str:
    slot_label = slot_start.astimezone(tz).strftime('%b %d (%a) %I:%M %p %Z')
    lines = [
        "Hi there,",
        "",
        f"This is Cal, {owner_name}'s assistant. It looks like the {slot_label} time was just booked.",
    ]
    if fallback_lines:
        lines.append("Here are a few other openings:")
        lines.extend(fallback_lines)
    else:
        lines.append("I'll circle back with new options shortly.")
    lines.append("")
    lines.append("Best,")
    lines.append("Cal")
    return "\n".join(lines)


def _slot_matches_target(slot_start: datetime, candidates: List["Slot"], tolerance_seconds: int = 60) -> bool:
    for candidate in candidates:
        if abs((candidate.start - slot_start).total_seconds()) < tolerance_seconds:
            return True
    return False


def _system_issue_agent_result(owner_name: str, note: str) -> Dict[str, object]:
    return {
        "action": "request_clarification",
        "reply": _compose_system_issue_reply(owner_name),
        "proposed_slots": [],
        "confirmed_slot": None,
        "notes": note,
    }


def _find_fallback_slots(
    user: User,
    event_type: EventType,
    slot_start: datetime,
    limit: int = 5,
) -> List["Slot"]:
    tz_local = availability_service.get_timezone(user)
    today = datetime.now(tz_local).date()
    start_date = max(slot_start.date(), today)
    end_date = start_date + timedelta(days=13)

    fresh_batch = availability_service.get_availability_for_range(
        user,
        event_type,
        start_date,
        end_date,
    )

    fallback_slots: List["Slot"] = []
    for day_key in sorted(fresh_batch.slots_by_date.keys()):
        for alt_slot in fresh_batch.slots_by_date[day_key]:
            if abs((alt_slot.start - slot_start).total_seconds()) < 60:
                continue
            fallback_slots.append(alt_slot)
            if len(fallback_slots) >= limit:
                return fallback_slots
    return fallback_slots


def _validate_confirmed_slot(
    user: User,
    event_type: EventType,
    slot_start: datetime,
    owner_name: str,
) -> Optional[Dict[str, object]]:
    try:
        day_slots = availability_service.get_slots_for_date(
            user,
            event_type,
            slot_start.date(),
        )
    except AvailabilityError:
        return _system_issue_agent_result(owner_name, "availability_verify_error")

    if day_slots and not _slot_matches_target(slot_start, day_slots):
        tz_local = availability_service.get_timezone(user)
        try:
            fallback_slots = _find_fallback_slots(user, event_type, slot_start)
        except AvailabilityError:
            return _system_issue_agent_result(owner_name, "availability_refresh_error")

        fallback_lines = [
            _format_slot_for_email_line(alt_slot, tz_local) for alt_slot in fallback_slots
        ]
        proposed_slots = [
            {"start": alt_slot.start.isoformat(), "end": alt_slot.end.isoformat()}
            for alt_slot in fallback_slots
        ]
        return {
            "action": "propose_slots",
            "reply": _compose_slot_taken_reply(owner_name, slot_start, tz_local, fallback_lines),
            "proposed_slots": proposed_slots,
            "confirmed_slot": None,
            "notes": "slot_taken",
        }

    return None


def _find_event_for_cancellation(user: User, confirmed_info: Optional[Dict[str, object]]) -> Optional[Event]:
    if not confirmed_info:
        return None

    google_event_id = None
    start_iso = None
    if isinstance(confirmed_info, dict):
        google_event_id = confirmed_info.get("google_event_id")
        start_iso = confirmed_info.get("start")

    if google_event_id:
        event = Event.query.filter_by(user_id=user.id, google_event_id=google_event_id).first()
        if event:
            return event

    if start_iso:
        return (
            Event.query.filter_by(user_id=user.id, start_datetime=start_iso)
            .order_by(Event.id.desc())
            .first()
        )

    return None


def _apply_cancellation_state(meeting_request: MeetingRequest) -> None:
    meeting_request.proposed_slots = []
    meeting_request.status = "cancelled"
    meeting_request.current_step = "cancelled"
    meeting_request.next_follow_up_at = None
    meeting_request.follow_up_count = 0
    meeting_request.updated_at = datetime.utcnow()


def _coalesce_availability_windows(
    availability_batch: AvailabilityBatch,
    window_start_date,
    max_blocks: int = 8,
) -> List[Dict[str, str]]:
    """
    Merge contiguous 30-minute slots into larger availability windows.
    """
    blocks: List[Dict[str, str]] = []
    sorted_days = sorted(availability_batch.slots_by_date.keys())

    for day in sorted_days:
        if day < window_start_date:
            continue

        day_slots = sorted(
            availability_batch.slots_by_date.get(day, []),
            key=lambda slot: slot.start,
        )

        current_start = None
        current_end = None

        for slot in day_slots:
            if current_start is None:
                current_start = slot.start
                current_end = slot.end
                continue

            gap_seconds = (slot.start - current_end).total_seconds()
            if gap_seconds <= 60:
                current_end = max(current_end, slot.end)
            else:
                blocks.append({"start": current_start.isoformat(), "end": current_end.isoformat()})
                if len(blocks) >= max_blocks:
                    return blocks
                current_start = slot.start
                current_end = slot.end

        if current_start is not None:
            blocks.append({"start": current_start.isoformat(), "end": current_end.isoformat()})
            if len(blocks) >= max_blocks:
                return blocks

    return blocks


def _get_or_create_meeting_request(
    user: User, email_data: Dict, text_input: TextInput
) -> MeetingRequest:
    thread_id = email_data.get("thread_id")
    message_id = email_data.get("message_id")

    meeting_request = None
    if thread_id:
        meeting_request = (
            MeetingRequest.query.join(MeetingMessage)
            .filter(MeetingMessage.thread_id == thread_id)
            .order_by(MeetingRequest.created_at.desc())
            .first()
        )

    if not meeting_request and message_id:
        meeting_request = (
            MeetingRequest.query.join(MeetingMessage)
            .filter(MeetingMessage.message_id == message_id)
            .first()
        )

    if meeting_request:
        logger.info(
            "Found existing meeting request %s for thread %s",
            meeting_request.id,
            thread_id,
        )
        if text_input and not meeting_request.text_input_id:
            meeting_request.text_input = text_input
        return meeting_request

    meeting_request = MeetingRequest(
        user_id=user.id,
        text_input=text_input,
        subject=email_data.get("subject"),
        status="pending",
        current_step="reviewing",
        last_message_at=datetime.utcnow(),
    )
    db.session.add(meeting_request)
    db.session.flush()
    logger.info("Created new meeting request %s", meeting_request.id)
    return meeting_request


def _sync_participants(meeting_request: MeetingRequest, email_data: Dict):
    seen = {participant.email.lower() for participant in meeting_request.participants}
    potential = set()

    sender = (email_data.get("sender") or "").strip().lower()
    if sender and sender not in ASSISTANT_EMAILS:
        potential.add((sender, email_data.get("sender_name")))

    for field in ("to", "cc"):
        for entry in email_data.get(field) or []:
            addr = entry.strip().lower()
            if not addr or addr in ASSISTANT_EMAILS:
                continue
            potential.add((addr, None))

    for email, name in potential:
        if email in seen:
            continue
        participant = MeetingParticipant(
            meeting_request_id=meeting_request.id,
            email=email,
            name=name,
            role="participant" if email != meeting_request.user.email else "organizer",
        )
        db.session.add(participant)
        seen.add(email)


def _record_meeting_message(
    meeting_request: MeetingRequest, email_data: Dict
) -> MeetingMessage:
    raw_headers = email_data.get("raw_headers")
    if isinstance(raw_headers, (dict, list)):
        raw_headers = json.dumps(raw_headers)

    received_at = email_data.get("received_at")
    if isinstance(received_at, datetime):
        if received_at.tzinfo:
            received_at = received_at.astimezone(timezone.utc).replace(tzinfo=None)

    message = MeetingMessage(
        meeting_request_id=meeting_request.id,
        sender_email=(email_data.get("sender") or "").strip().lower(),
        message_id=email_data.get("message_id"),
        thread_id=email_data.get("thread_id"),
        body_text=email_data.get("body_text"),
        body_html=email_data.get("body_html"),
        metadata_json=raw_headers,
        received_at=received_at,
    )
    db.session.add(message)
    db.session.flush()
    return message


def _export_messages_for_agent(
    meeting_request: MeetingRequest,
) -> List[Dict[str, str]]:
    history = []
    for message in sorted(
        meeting_request.messages, key=lambda m: m.created_at or datetime.utcnow()
    ):
        history.append(
            {
                "sender": message.sender_email,
                "timestamp": (message.received_at or message.created_at).isoformat()
                if (message.received_at or message.created_at)
                else "",
                "body": message.body_text or "",
            }
        )
    return history


def prepare_agent_context_for_request(
    user: User,
    meeting_request: MeetingRequest,
) -> Dict[str, object]:
    """
    Build agent inputs, conversation history, and availability data for a meeting request.
    """
    agent_input: Dict[str, object] = {
        "subject": meeting_request.subject,
        "owner_email": user.email,
        "owner_name": user.username or user.email,
        "participants": [p.email for p in meeting_request.participants],
        "status": meeting_request.status,
        "timezone": user.timezone or "UTC",
        "current_date": datetime.utcnow().date().isoformat(),
    }
    agent_input["availability_note"] = None
    history = _export_messages_for_agent(meeting_request)
    latest_message = history[-1] if history else {
        "sender": user.email,
        "timestamp": datetime.utcnow().isoformat(),
        "body": "",
    }

    availability_blocks: List[Dict[str, str]] = []
    extended_availability_blocks: List[Dict[str, str]] = []
    availability_lookup_error = None
    default_event_type = (
        EventType.query.filter_by(user_id=user.id, is_active=True)
        .order_by(EventType.duration_minutes.asc())
        .first()
    )
    event_duration_minutes = (
        default_event_type.duration_minutes
        if default_event_type and default_event_type.duration_minutes
        else 30
    )
    agent_input["event_duration_minutes"] = event_duration_minutes

    if default_event_type:
        tz = availability_service.get_timezone(user)
        start_date = datetime.now(tz).date()
        end_date = start_date + timedelta(days=13)
        try:
            availability_batch = availability_service.get_availability_for_range(
                user, default_event_type, start_date, end_date
            )
        except AvailabilityError as exc:
            availability_lookup_error = str(exc) or "A system issue prevented us from checking the calendar."
        else:
            availability_blocks = _coalesce_availability_windows(availability_batch, start_date)
            if not availability_blocks:
                extended_start = end_date + timedelta(days=1)
                extended_end = extended_start + timedelta(days=13)
                try:
                    extended_batch = availability_service.get_availability_for_range(
                        user, default_event_type, extended_start, extended_end
                    )
                except AvailabilityError:
                    extended_availability_blocks = []
                else:
                    extended_availability_blocks = _coalesce_availability_windows(
                        extended_batch, extended_start
                    )

    availability = []
    if availability_lookup_error:
        availability = []
    else:
        availability = availability_blocks
        if not availability and extended_availability_blocks:
            availability = extended_availability_blocks
            agent_input[
                "availability_note"
            ] = "No availability in the next two weeks; showing openings slightly further out."
        elif not availability:
            agent_input[
                "availability_note"
            ] = "No availability found in the next two weeks."

    return {
        "agent_input": agent_input,
        "history": history,
        "latest_message": latest_message,
        "availability": availability,
        "availability_error": availability_lookup_error,
        "default_event_type": default_event_type,
    }


def send_agent_reply_email(
    user: User,
    meeting_request: MeetingRequest,
    reply_text: str,
    *,
    thread_id: Optional[str],
    reply_to_message_id: Optional[str],
    subject: Optional[str],
    extra_recipients: Optional[List[str]] = None,
) -> bool:
    """
    Send the agent's reply email and return True on success.
    """
    if not reply_text:
        return False

    recipient_set = {p.email.lower() for p in meeting_request.participants if p.email}
    owner_email = (user.email or "").strip().lower()
    if owner_email:
        recipient_set.add(owner_email)

    for address in extra_recipients or []:
        if not address:
            continue
        recipient_set.add(address.strip().lower())

    for assistant in ASSISTANT_EMAILS:
        recipient_set.discard(assistant)

    recipients_sorted = sorted(addr for addr in recipient_set if addr)
    if not recipients_sorted:
        return False

    to_header = ", ".join(recipients_sorted)
    cc_recipients = None

    final_subject = subject or meeting_request.subject or "Meeting coordination"
    if final_subject and not final_subject.lower().startswith("re:"):
        final_subject = f"Re: {final_subject}"

    try:
        gmail_service.send_email(
            to_header,
            final_subject,
            text_body=reply_text,
            thread_id=thread_id,
            reply_to_message_id=reply_to_message_id,
            cc_recipients=cc_recipients,
        )
        return True
    except Exception as send_exc:
        logger.error(
            "Failed to send scheduling reply for meeting_request %s: %s",
            meeting_request.id,
            send_exc,
        )
        return False


def handle_scheduling_email(email_data: Dict, owner_user: User) -> Optional[Dict[str, object]]:
    """
    Entry point for scheduling workflow from Gmail ingestion.

    Returns agent output dict or None if processing failed.
    """
    user = owner_user

    # Persist text input for traceability
    raw_headers = email_data.get("raw_headers")
    if isinstance(raw_headers, (dict, list)):
        raw_headers = json.dumps(raw_headers)

    text_input = TextInput(
        user_id=user.id,
        original_text=sanitize_text_for_db(email_data.get("body_text") or ""),
        source_type="email",
        from_email=(email_data.get("sender") or "").strip().lower(),
        task_type="schedule_meeting",
        raw_email_context=raw_headers,
        processing_status="pending",
    )
    db.session.add(text_input)
    db.session.flush()

    meeting_request = _get_or_create_meeting_request(user, email_data, text_input)
    _sync_participants(meeting_request, email_data)
    meeting_message = _record_meeting_message(meeting_request, email_data)

    meeting_request.last_message_at = meeting_message.received_at or datetime.utcnow()
    meeting_request.updated_at = datetime.utcnow()
    meeting_request.follow_up_count = 0
    meeting_request.next_follow_up_at = None

    context = prepare_agent_context_for_request(user, meeting_request)
    agent_input = context["agent_input"]
    history = context["history"]
    latest_message = context["latest_message"]
    availability = context["availability"]
    availability_lookup_error = context["availability_error"]
    default_event_type = context["default_event_type"]

    if availability_lookup_error:
        agent_result = {
            "action": "request_clarification",
            "reply": _compose_system_issue_reply(agent_input.get("owner_name") or user.email),
            "proposed_slots": [],
            "confirmed_slot": None,
            "notes": "availability_fetch_error",
        }
    else:
        agent_result = run_meeting_scheduler_agent(
            agent_input,
            history,
            latest_message,
            availability=availability,
        )

    logger.info(
        "Scheduler agent result for meeting_request %s: action=%s proposed=%s confirmed=%s",
        meeting_request.id,
        agent_result.get("action"),
        agent_result.get("proposed_slots"),
        agent_result.get("confirmed_slot"),
    )

    action = agent_result.get("action")
    proposed_slots = agent_result.get("proposed_slots")
    new_confirmed_slot = agent_result.get("confirmed_slot")
    previous_confirmed_slot = meeting_request.confirmed_slot

    meeting_request.proposed_slots = proposed_slots
    meeting_request.confirmed_slot = new_confirmed_slot or previous_confirmed_slot
    text_input.processing_status = "completed"
    meeting_request.current_step = action

    if action == "cancel_meeting":
        slot_reference = previous_confirmed_slot or new_confirmed_slot
        event_to_cancel = _find_event_for_cancellation(user, slot_reference)
        cancellation_failed = False
        if event_to_cancel:
            try:
                cancel_booking_event(user, event_to_cancel)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to cancel event %s for meeting_request %s: %s",
                    event_to_cancel.id,
                    meeting_request.id,
                    exc,
                )
                cancellation_failed = True
            else:
                logger.info(
                    "Cancelled event %s for meeting_request %s",
                    event_to_cancel.id,
                    meeting_request.id,
                )
        else:
            logger.warning(
                "Unable to locate event to cancel for meeting_request %s",
                meeting_request.id,
            )
            cancellation_failed = True

        if cancellation_failed:
            if reply_text:
                reply_text = (
                    reply_text.rstrip()
                    + "\n\n"
                    + "I couldn't find that meeting on the calendar. Please remove it manually if it still appears."
                )
            meeting_request.notes = "cancel_unverified"
        else:
            _apply_cancellation_state(meeting_request)
    elif action == "confirm_slot" and meeting_request.confirmed_slot:
        meeting_request.status = "confirmed"
    elif action == "request_clarification":
        meeting_request.status = "collecting"
    else:
        meeting_request.status = "proposed"

    calendar_event_id = None
    if action == "confirm_slot" and meeting_request.confirmed_slot:
        confirmed_info = meeting_request.confirmed_slot or {}
        existing_event_id = None
        if isinstance(confirmed_info, dict):
            existing_event_id = confirmed_info.get("google_event_id")

        conference_url = None
        if existing_event_id:
            existing_event = (
                Event.query.filter_by(user_id=user.id, google_event_id=existing_event_id).first()
            )
            if existing_event and existing_event.conference_url:
                conference_url = existing_event.conference_url
                if "conference_url" not in confirmed_info:
                    updated_confirmed = dict(confirmed_info)
                    updated_confirmed["conference_url"] = conference_url
                    meeting_request.confirmed_slot = updated_confirmed
                    confirmed_info = updated_confirmed
            if existing_event:
                if existing_event.meeting_request_id != meeting_request.id:
                    existing_event.meeting_request_id = meeting_request.id
                if invitee_email and not existing_event.invitee_email:
                    existing_event.invitee_email = invitee_email.strip().lower()
                if invitee_name and not existing_event.invitee_name:
                    existing_event.invitee_name = invitee_name

        if not existing_event_id:
            start_iso = confirmed_info.get("start")
            end_iso = confirmed_info.get("end")

            if not start_iso or not end_iso:
                logger.error("Confirmed slot missing start for meeting_request %s", meeting_request.id)
            else:
                try:
                    slot_start = datetime.fromisoformat(start_iso)
                    slot_end = datetime.fromisoformat(end_iso)
                except ValueError:
                    logger.error("Invalid ISO format for confirmed slot: %s", start_iso)
                    slot_start = None
                    slot_end = None

                if slot_start is not None and slot_end is not None:
                    tz = availability_service.get_timezone(user)
                    if slot_start.tzinfo is None:
                        slot_start = tz.localize(slot_start)
                    else:
                        slot_start = slot_start.astimezone(tz)

                    if slot_end.tzinfo is None:
                        slot_end = tz.localize(slot_end)
                    else:
                        slot_end = slot_end.astimezone(tz)

                    duration_minutes = int((slot_end - slot_start).total_seconds() // 60)
                    selected_event_type = (
                        EventType.query.filter_by(
                            user_id=user.id,
                            duration_minutes=duration_minutes,
                            is_active=True,
                        )
                        .first()
                        or default_event_type
                    )
                    if not selected_event_type:
                        selected_event_type = SimpleNamespace(
                            title=meeting_request.subject or "Meeting",
                            description=None,
                            duration_minutes=duration_minutes or 30,
                        )

                    owner_name = agent_input.get("owner_name") or (user.username or user.email)
                    validation_result = _validate_confirmed_slot(
                        user,
                        selected_event_type,
                        slot_start,
                        owner_name,
                    )

                    if validation_result:
                        agent_result = validation_result
                        action = validation_result["action"]
                        meeting_request.proposed_slots = validation_result.get("proposed_slots", [])
                        meeting_request.confirmed_slot = None
                        meeting_request.status = (
                            "collecting" if action == "request_clarification" else "proposed"
                        )
                        meeting_request.current_step = action
                        calendar_event_id = None
                    else:
                        invitee = next(
                            (p for p in meeting_request.participants if p.email and p.email.lower() != (user.email or "").lower()),
                            None,
                        )
                        invitee_email = invitee.email if invitee else None
                        invitee_name = invitee.name or invitee_email if invitee else None

                        if not invitee_email:
                            for field in ("to", "cc"):
                                for addr in email_data.get(field) or []:
                                    cleaned = (addr or "").strip().lower()
                                    if not cleaned:
                                        continue
                                    if cleaned == (user.email or "").lower() or cleaned in ASSISTANT_EMAILS:
                                        continue
                                    invitee_email = cleaned
                                    invitee_name = cleaned
                                    break
                                if invitee_email:
                                    break

                        if not invitee_email:
                            invitee_email = user.email
                            invitee_name = user.username

                        booking_event_type = selected_event_type or SimpleNamespace(
                            title=meeting_request.subject or "Meeting",
                            description=None,
                            duration_minutes=duration_minutes or 30,
                        )

                        try:
                            created_event = create_booking_event(
                                user,
                                booking_event_type,
                                slot_start,
                                invitee_name,
                                invitee_email,
                                _build_calendar_description(
                                    history, user.username or user.email, user.email
                                ),
                                source="ai_booking",
                                meeting_request_id=meeting_request.id,
                            )
                            calendar_event_id = created_event.google_event_id
                            conference_url = getattr(created_event, "conference_url", None)
                            if calendar_event_id:
                                updated_confirmed = dict(confirmed_info)
                                updated_confirmed["google_event_id"] = calendar_event_id
                                if conference_url:
                                    updated_confirmed["conference_url"] = conference_url
                                meeting_request.confirmed_slot = updated_confirmed
                                confirmed_info = updated_confirmed
                        except Exception as calendar_err:
                            logger.warning(
                                "Failed to create calendar event for meeting_request %s: %s",
                                meeting_request.id,
                                calendar_err,
                            )

    notify_owner_calendar_issue(user, agent_result.get("notes"))

    reply_text = agent_result.get("reply")
    sent_reply = False
    if reply_text:
        if action == "confirm_slot":
            confirmed_info = meeting_request.confirmed_slot or {}
            conference_url = None
            if isinstance(confirmed_info, dict):
                conference_url = confirmed_info.get("conference_url")
            if conference_url and conference_url not in reply_text:
                reply_text = reply_text.rstrip() + f"\n\nVideo conference: {conference_url}\n"

        extra_recipients: List[str] = []
        sender_addr = (email_data.get("sender") or "").strip().lower()
        if sender_addr:
            extra_recipients.append(sender_addr)

        for field in ("to", "cc"):
            for addr in email_data.get(field) or []:
                clean = (addr or "").strip().lower()
                if clean:
                    extra_recipients.append(clean)

        sent_reply = send_agent_reply_email(
            user,
            meeting_request,
            reply_text,
            thread_id=email_data.get("thread_id"),
            reply_to_message_id=email_data.get("message_id"),
            subject=email_data.get("subject"),
            extra_recipients=extra_recipients,
        )

        if sent_reply:
            now = datetime.utcnow()
            meeting_request.last_agent_reply_at = now
            tracking_action = action in {"propose_slots", "request_clarification"}
            if tracking_action and (user.follow_up_enabled is None or user.follow_up_enabled):
                first_delay, _ = get_follow_up_delays(user)
                meeting_request.follow_up_count = 0
                meeting_request.next_follow_up_at = now + timedelta(days=first_delay)
            else:
                meeting_request.next_follow_up_at = None
                meeting_request.follow_up_count = 0

    db.session.commit()

    return {
        "meeting_request_id": meeting_request.id,
        "reply": agent_result.get("reply"),
        "action": action,
        "proposed_slots": meeting_request.proposed_slots,
        "confirmed_slot": meeting_request.confirmed_slot,
        "notes": agent_result.get("notes"),
    }

def _build_calendar_description(history: List[Dict[str, str]], owner_name: str, owner_email: str) -> str:
    if not history:
        return f"Coordinated by Cal on behalf of {owner_name} ({owner_email})."

    lines = [
        "Conversation summary:",
        "",
    ]

    for entry in history[-3:]:
        sender = entry.get("sender") or "unknown"
        timestamp = entry.get("timestamp") or ""
        body = (entry.get("body") or "").strip()
        if body:
            body = " ".join(body.split())
            if len(body) > 160:
                body = body[:157].rstrip() + "..."
            lines.append(f"- {timestamp} — {sender}: {body}")
        else:
            lines.append(f"- {timestamp} — {sender}")

    lines.extend(
        [
            "",
            f"Coordinated by Cal on behalf of {owner_name} ({owner_email}).",
        ]
    )

    return "\n".join(lines).strip()
def get_follow_up_delays(user: User) -> Tuple[int, int]:
    """
    Return sanitized follow-up delays (in days) for the user.
    The second follow-up is always at least one day after the first and capped at 30 days.
    """
    first = user.follow_up_first_delay_days or 1
    second = user.follow_up_second_delay_days or (first + 1)

    first = max(1, min(30, first))
    second = max(first + 1, min(30, second))
    if second <= first:
        second = min(30, first + 1)
    return first, second
