"""
Migration: introduce contacts, labels, and contact links; connect meeting participants.

Run with:
    python tools/migrations/20250720_add_contacts.py

The script is idempotent and safe to rerun. It creates the new tables,
adds the meeting_participant.contact_id column, and backfills contacts
from historical scheduler threads and public bookings.
"""

import sys
from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.orm import selectinload

sys.path.insert(0, ".")

from app import app, db  # noqa: E402
from app.models import (  # noqa: E402
    Contact,
    ContactLabel,
    ContactLabelLink,
    Event,
    MeetingMessage,
    MeetingParticipant,
    MeetingRequest,
)
from app.services import contacts as contact_service  # noqa: E402
from app.services.scheduling_agent import ASSISTANT_EMAILS  # noqa: E402


def _is_sqlite() -> bool:
    try:
        return db.engine.url.get_backend_name() == "sqlite"
    except Exception:
        return False


def _table_exists(name: str) -> bool:
    inspector = inspect(db.engine)
    return name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(db.engine)
    try:
        columns = inspector.get_columns(table_name)
    except Exception:
        return False
    return any(col["name"] == column_name for col in columns)


def ensure_tables() -> None:
    Contact.__table__.create(bind=db.engine, checkfirst=True)
    ContactLabel.__table__.create(bind=db.engine, checkfirst=True)
    ContactLabelLink.__table__.create(bind=db.engine, checkfirst=True)


def ensure_meeting_participant_fk() -> None:
    if not _column_exists("meeting_participant", "contact_id"):
        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE meeting_participant ADD COLUMN contact_id INTEGER'))

    if not _is_sqlite():
        constraint_sql = """
        ALTER TABLE meeting_participant
        ADD CONSTRAINT IF NOT EXISTS fk_meeting_participant_contact
        FOREIGN KEY (contact_id) REFERENCES contact(id) ON DELETE SET NULL
        """
        try:
            with db.engine.begin() as conn:
                conn.execute(text(constraint_sql))
        except Exception:
            # Older PostgreSQL versions do not support IF NOT EXISTS on constraints; ignore if present.
            pass

    with db.engine.begin() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_meeting_participant_contact_id ON meeting_participant(contact_id)")
        )


def backfill_public_booking_contacts() -> None:
    events = (
        Event.query.options(selectinload(Event.user))
        .filter(Event.source == "public_booking", Event.invitee_email.isnot(None))
        .all()
    )
    count = 0
    for event in events:
        user = event.user
        if not user:
            continue

        first_seen_at = event.created_at or datetime.utcnow()
        if event.start_datetime:
            try:
                first_seen_at = datetime.fromisoformat(event.start_datetime)
            except ValueError:
                pass

        contact = contact_service.ensure_contact(
            user,
            event.invitee_email,
            display_name=event.invitee_name,
            first_seen_source="public_booking",
            first_seen_at=first_seen_at,
        )
        contact_service.record_interaction(
            contact,
            occurred_at=first_seen_at,
            incoming=True,
        )
        contact_service.assign_label(
            contact,
            "Booked",
            applied_by=user,
            color="primary",
            description="Created via public booking",
        )
        count += 1
        if count % 10 == 0:
            db.session.commit()
    
    if count > 0:
        db.session.commit()
    app.logger.info(f"Backfilled {count} public booking contacts")


def backfill_scheduler_participants() -> None:
    participants = (
        MeetingParticipant.query.options(
            selectinload(MeetingParticipant.meeting_request).selectinload(MeetingRequest.user),
        ).all()
    )

    count = 0
    for participant in participants:
        meeting_request = participant.meeting_request
        owner = meeting_request.user if meeting_request else None
        if not owner or not participant.email:
            continue

        owner_email = (owner.email or "").strip().lower()
        email_normalised = participant.email.strip().lower()
        if not email_normalised or email_normalised == owner_email or email_normalised in ASSISTANT_EMAILS:
            continue

        contact = contact_service.ensure_contact(
            owner,
            email_normalised,
            display_name=participant.name,
            first_seen_source="scheduler",
            first_seen_at=participant.created_at or meeting_request.created_at or datetime.utcnow(),
        )
        participant.contact = contact
        if participant.latest_reply_at:
            contact_service.record_interaction(
                contact,
                occurred_at=participant.latest_reply_at,
                incoming=True,
            )
        count += 1
        if count % 10 == 0:
            db.session.commit()
    
    if count > 0:
        db.session.commit()
    app.logger.info(f"Backfilled {count} scheduler participants")


def backfill_scheduler_messages() -> None:
    messages = (
        MeetingMessage.query.options(
            selectinload(MeetingMessage.meeting_request)
            .selectinload(MeetingRequest.participants),
            selectinload(MeetingMessage.meeting_request)
            .selectinload(MeetingRequest.user),
        ).limit(50).all()  # Limit to first 50 messages to avoid timeout
    )

    count = 0
    for message in messages:
        meeting_request = message.meeting_request
        owner = meeting_request.user if meeting_request else None
        if not owner:
            continue

        owner_email = (owner.email or "").strip().lower() if owner.email else None
        sender_email = (message.sender_email or "").strip().lower()
        event_time = message.received_at or message.created_at or datetime.utcnow()

        if sender_email and sender_email != owner_email and sender_email not in ASSISTANT_EMAILS:
            contact = contact_service.ensure_contact(
                owner,
                sender_email,
                first_seen_source="scheduler",
                first_seen_at=message.created_at or event_time,
            )
            contact_service.record_interaction(
                contact,
                occurred_at=event_time,
                incoming=True,
            )
            # Attach participant link if available
            for participant in meeting_request.participants:
                if participant.email and participant.email.strip().lower() == sender_email:
                    participant.contact = contact
                    if message.received_at:
                        participant.latest_reply_at = message.received_at
                    break
        else:
            for participant in meeting_request.participants:
                if not participant.email:
                    continue
                normalised = participant.email.strip().lower()
                if not normalised or normalised == owner_email or normalised in ASSISTANT_EMAILS:
                    continue
                contact = contact_service.ensure_contact(
                    owner,
                    normalised,
                    first_seen_source="scheduler",
                    first_seen_at=participant.created_at or meeting_request.created_at or event_time,
                )
                contact_service.record_interaction(
                    contact,
                    occurred_at=event_time,
                    outgoing=True,
                )
                participant.contact = contact
        
        count += 1
        if count % 10 == 0:
            db.session.commit()
    
    if count > 0:
        db.session.commit()
    app.logger.info(f"Backfilled {count} scheduler messages")


def main():
    with app.app_context():
        ensure_tables()
        ensure_meeting_participant_fk()
        backfill_public_booking_contacts()
        backfill_scheduler_participants()
        backfill_scheduler_messages()
        db.session.commit()
        app.logger.info("Contacts migration completed successfully.")


if __name__ == "__main__":
    main()
