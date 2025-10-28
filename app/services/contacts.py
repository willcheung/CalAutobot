from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import joinedload

from app import db
from app.models import Contact, ContactLabel, ContactLabelLink, User


def _normalise_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    normalised = email.strip().lower()
    return normalised or None


def ensure_contact(
    user: User,
    email: Optional[str],
    *,
    display_name: Optional[str] = None,
    phone_number: Optional[str] = None,
    timezone: Optional[str] = None,
    company: Optional[str] = None,
    job_title: Optional[str] = None,
    address: Optional[str] = None,
    notes: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    first_seen_source: Optional[str] = None,
    first_seen_at: Optional[datetime] = None,
) -> Optional[Contact]:
    """
    Ensure we have a Contact row for this user/email combination.
    Returns the Contact instance or None if the email is empty/invalid.
    """
    normalised = _normalise_email(email)
    if not user or not normalised:
        return None

    contact = (
        Contact.query.options(joinedload(Contact.label_links))
        .filter_by(user_id=user.id, email=normalised)
        .first()
    )

    created_now = False
    timestamp = first_seen_at or datetime.utcnow()
    if not contact:
        contact = Contact(
            user_id=user.id,
            email=normalised,
            first_seen_source=first_seen_source,
            first_seen_at=timestamp,
        )
        db.session.add(contact)
        created_now = True

    # Only fill missing profile fields so we don't overwrite user edits.
    field_updates = {
        "display_name": display_name,
        "phone_number": phone_number,
        "timezone": timezone,
        "company": company,
        "job_title": job_title,
        "address": address,
        "linkedin_url": linkedin_url,
    }
    for field, value in field_updates.items():
        if value and not getattr(contact, field, None):
            setattr(contact, field, value.strip())

    if notes:
        # Append notes if the contact already has human-written content.
        if contact.notes:
            if notes.strip() not in contact.notes:
                contact.notes = f"{contact.notes}\n\n{notes.strip()}"
        else:
            contact.notes = notes.strip()

    if not contact.first_seen_at:
        contact.first_seen_at = timestamp
    if not contact.first_seen_source:
        contact.first_seen_source = first_seen_source

    if created_now:
        db.session.flush()

    return contact


def record_interaction(
    contact: Optional[Contact],
    *,
    occurred_at: Optional[datetime] = None,
    incoming: bool = False,
    outgoing: bool = False,
    follow_up_increment: bool = False,
) -> None:
    """
    Update interaction timestamps and counters for a contact.
    """
    if not contact:
        return

    event_time = occurred_at or datetime.utcnow()

    def _update_latest(current: Optional[datetime], candidate: datetime) -> datetime:
        if current is None or candidate > current:
            return candidate
        return current

    if incoming:
        contact.last_incoming_email_at = _update_latest(contact.last_incoming_email_at, event_time)
    if outgoing:
        contact.last_outgoing_email_at = _update_latest(contact.last_outgoing_email_at, event_time)

    if incoming or outgoing:
        contact.last_interaction_at = _update_latest(contact.last_interaction_at, event_time)

    if follow_up_increment:
        current = contact.follow_up_count or 0
        contact.follow_up_count = current + 1

    contact.updated_at = event_time


def ensure_label(
    user: User,
    name: str,
    *,
    color: Optional[str] = None,
    description: Optional[str] = None,
) -> Optional[ContactLabel]:
    """
    Return an existing label for this user or create a new one.
    """
    if not user:
        return None

    clean_name = (name or "").strip()
    if not clean_name:
        return None

    label = ContactLabel.query.filter_by(user_id=user.id, name=clean_name).first()
    if not label:
        label = ContactLabel(user_id=user.id, name=clean_name, color=color, description=description)
        db.session.add(label)
        db.session.flush()
    else:
        if color and not label.color:
            label.color = color
        if description and not label.description:
            label.description = description
    return label


def assign_label(
    contact: Optional[Contact],
    label_name: str,
    *,
    applied_by: Optional[User] = None,
    color: Optional[str] = None,
    description: Optional[str] = None,
) -> Optional[ContactLabel]:
    """
    Ensure the contact has the given label attached.
    """
    if not contact or not label_name:
        return None

    owner = contact.user or applied_by
    if not owner:
        return None

    label = ensure_label(owner, label_name, color=color, description=description)
    if not label:
        return None

    existing_link = next(
        (link for link in contact.label_links if link.label_id == label.id),
        None,
    )
    if existing_link:
        return label

    link = ContactLabelLink(contact=contact, label=label)
    if applied_by:
        link.applied_by_user_id = applied_by.id
    db.session.add(link)
    db.session.flush()
    return label
