import re
from typing import List, Optional

from app import db
from app.models import EventType

SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    base = (value or "").strip().lower()
    base = SLUG_PATTERN.sub("-", base).strip("-")
    return base or "event"


def generate_unique_slug(user_id: int, title: str, candidate: Optional[str] = None) -> str:
    """Generate a slug unique per user."""
    base_slug = slugify(candidate or title)
    existing_rows = (
        EventType.query.filter_by(user_id=user_id)
        .with_entities(EventType.slug)
        .all()
    )
    existing = {row[0] for row in existing_rows}

    if base_slug not in existing:
        return base_slug

    counter = 2
    while True:
        slug = f"{base_slug}-{counter}"
        if slug not in existing:
            return slug
        counter += 1


def list_event_types(user_id: int) -> List[EventType]:
    return (
        EventType.query.filter_by(user_id=user_id)
        .order_by(EventType.created_at.asc())
        .all()
    )


def create_event_type(user_id: int, title: str, duration_minutes: int, description: str = "", slug: Optional[str] = None, is_public: bool = True) -> EventType:
    slug_value = generate_unique_slug(user_id, title, slug)
    event_type = EventType(
        user_id=user_id,
        title=title.strip() or "Meeting",
        description=description.strip() if description else None,
        duration_minutes=max(5, duration_minutes),
        slug=slug_value,
        is_public=is_public,
    )
    db.session.add(event_type)
    db.session.commit()
    return event_type


def update_event_type(event_type: EventType, title: str, duration_minutes: int, description: str = "", is_public: bool = True):
    event_type.title = title.strip() or event_type.title
    event_type.duration_minutes = max(5, duration_minutes)
    event_type.description = description.strip() if description else None
    event_type.is_public = is_public
    db.session.commit()


def set_event_type_active(event_type: EventType, is_active: bool):
    event_type.is_active = is_active
    db.session.commit()


def get_event_type_by_slug(user_id: int, slug: str) -> Optional[EventType]:
    return EventType.query.filter_by(user_id=user_id, slug=slug).first()


def delete_event_type(event_type: EventType):
    db.session.delete(event_type)
    db.session.commit()
