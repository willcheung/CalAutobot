import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Dict, List, Optional

from app import db
from app.models import (
    MeetingMessage,
    MeetingParticipant,
    MeetingRequest,
    TextInput,
    User,
    EventType,
)
from app.agents.meeting_scheduler import (
    get_testing_availability,
    run_meeting_scheduler_agent,
)
from app.helpers.text_processing import sanitize_text_for_db
from app.services import availability as availability_service
from app.services.availability import AvailabilityError
from app.services.public_booking import create_booking_event
from app.services.gmail_service import gmail_service

logger = logging.getLogger(__name__)

ASSISTANT_EMAILS = {"go@calautobot.com", "cal@calautobot.com"}


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

    agent_input = {
        "subject": meeting_request.subject,
        "owner_email": user.email,
        "owner_name": user.username or user.email,
        "participants": [p.email for p in meeting_request.participants],
        "status": meeting_request.status,
        "timezone": user.timezone or "UTC",
        "current_date": datetime.utcnow().date().isoformat(),
    }
    history = _export_messages_for_agent(meeting_request)
    latest_message = history[-1] if history else {
        "sender": meeting_message.sender_email,
        "timestamp": datetime.utcnow().isoformat(),
        "body": meeting_message.body_text or "",
    }

    availability = []
    availability_batch = None
    availability_lookup_error = None
    default_event_type = (
        EventType.query.filter_by(user_id=user.id, is_active=True)
        .order_by(EventType.duration_minutes.asc())
        .first()
    )

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
            for day in sorted(availability_batch.slots_by_date.keys()):
                if day < start_date:
                    continue
                for slot in availability_batch.slots_by_date[day]:
                    availability.append(
                        {"start": slot.start.isoformat(), "end": slot.end.isoformat()}
                    )
                    if len(availability) >= 8:
                        break
                if len(availability) >= 8:
                    break

    if availability_lookup_error:
        agent_result = {
            "action": "request_clarification",
            "reply": _compose_system_issue_reply(agent_input.get("owner_name") or user.email),
            "proposed_slots": [],
            "confirmed_slot": None,
            "notes": "availability_fetch_error",
        }
        availability = []
    else:
        if not availability:
            availability = get_testing_availability(user.timezone or "UTC")
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
    meeting_request.proposed_slots = agent_result.get("proposed_slots")
    meeting_request.confirmed_slot = agent_result.get("confirmed_slot")
    text_input.processing_status = "completed"
    meeting_request.current_step = action

    if action == "confirm_slot" and meeting_request.confirmed_slot:
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
                    failure_reply = None
                    failure_action = None
                    failure_notes = None
                    failure_proposed_slots: List[Dict[str, str]] = []

                    if not failure_reply:
                        try:
                            day_slots = availability_service.get_slots_for_date(
                                user,
                                selected_event_type,
                                slot_start.date(),
                            )
                        except AvailabilityError:
                            failure_reply = _compose_system_issue_reply(owner_name)
                            failure_action = "request_clarification"
                            failure_notes = "availability_verify_error"
                        else:
                            if day_slots and not any(
                                abs((candidate.start - slot_start).total_seconds()) < 60 for candidate in day_slots
                            ):
                                # Slot is no longer available; prepare alternatives
                                tz_local = availability_service.get_timezone(user)
                                fallback_slots: List = []
                                try:
                                    fresh_batch = availability_service.get_availability_for_range(
                                        user,
                                        selected_event_type,
                                        max(slot_start.date(), datetime.now(tz_local).date()),
                                        max(slot_start.date(), datetime.now(tz_local).date()) + timedelta(days=13),
                                    )
                                except AvailabilityError:
                                    failure_reply = _compose_system_issue_reply(owner_name)
                                    failure_action = "request_clarification"
                                    failure_notes = "availability_refresh_error"
                                else:
                                    for day_key in sorted(fresh_batch.slots_by_date.keys()):
                                        for alt_slot in fresh_batch.slots_by_date[day_key]:
                                            if abs((alt_slot.start - slot_start).total_seconds()) < 60:
                                                continue
                                            fallback_slots.append(alt_slot)
                                            if len(fallback_slots) >= 5:
                                                break
                                        if len(fallback_slots) >= 5:
                                            break

                                    tz_for_lines = tz_local
                                    fallback_lines = [
                                        _format_slot_for_email_line(alt_slot, tz_for_lines)
                                        for alt_slot in fallback_slots
                                    ]
                                    failure_proposed_slots = [
                                        {"start": alt_slot.start.isoformat(), "end": alt_slot.end.isoformat()}
                                        for alt_slot in fallback_slots
                                    ]
                                    failure_reply = _compose_slot_taken_reply(
                                        owner_name,
                                        slot_start,
                                        tz_for_lines,
                                        fallback_lines,
                                    )
                                    failure_action = "propose_slots"
                                    failure_notes = "slot_taken"

                    if failure_reply:
                        agent_result = {
                            "action": failure_action,
                            "reply": failure_reply,
                            "proposed_slots": failure_proposed_slots,
                            "confirmed_slot": None,
                            "notes": failure_notes,
                        }
                        action = failure_action
                        meeting_request.proposed_slots = failure_proposed_slots
                        meeting_request.confirmed_slot = None
                        meeting_request.status = (
                            "collecting" if failure_action == "request_clarification" else "proposed"
                        )
                        meeting_request.current_step = failure_action
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
                                _build_calendar_description(history, user.username or user.email, user.email),
                            )
                            calendar_event_id = created_event.google_event_id
                            if calendar_event_id:
                                updated_confirmed = dict(confirmed_info)
                                updated_confirmed["google_event_id"] = calendar_event_id
                                meeting_request.confirmed_slot = updated_confirmed
                        except Exception as calendar_err:
                            logger.warning(
                                "Failed to create calendar event for meeting_request %s: %s",
                                meeting_request.id,
                                calendar_err,
                            )

    db.session.commit()

    reply_text = agent_result.get("reply")
    if reply_text:
        all_participants = {p.email for p in meeting_request.participants}
        all_participants.add(user.email)

        sender_addr = (email_data.get("sender") or "").strip().lower()
        if sender_addr:
            all_participants.add(sender_addr)

        for field in ("to", "cc"):
            for addr in email_data.get(field) or []:
                clean = addr.strip()
                if clean:
                    all_participants.add(clean.lower())

        for assistant in ASSISTANT_EMAILS:
            all_participants.discard(assistant)

        owner_email = user.email
        other_participants = sorted(addr for addr in all_participants if addr != owner_email)

        to_header = owner_email
        cc_recipients = other_participants if other_participants else None

        subject = email_data.get("subject") or "Meeting coordination"
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        try:
            gmail_service.send_email(
                to_header,
                subject,
                text_body=reply_text,
                thread_id=email_data.get("thread_id"),
                reply_to_message_id=email_data.get("message_id"),
                cc_recipients=cc_recipients,
            )
        except Exception as send_exc:
            logger.error(
                "Failed to send scheduling reply for meeting_request %s: %s",
                meeting_request.id,
                send_exc,
            )

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
        f"Coordinated by Cal on behalf of {owner_name} ({owner_email}).",
        "",
        "Conversation summary:" ,
    ]

    for entry in history[-5:]:
        sender = entry.get("sender") or "unknown"
        timestamp = entry.get("timestamp") or ""
        body = (entry.get("body") or "").strip()
        lines.append(f"- {timestamp} — {sender} wrote:")
        if body:
            lines.append(body)
        lines.append("")

    return "\n".join(lines).strip()
