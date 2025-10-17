from typing import Optional

from sqlalchemy import func

from app import db
from app.models import User
from app.services.event_types import slugify


def normalize_handle(value: str) -> str:
    """Convert arbitrary text into a URL-safe handle fragment."""
    return slugify(value or "")


def is_handle_available(handle: str, *, exclude_user_id: Optional[int] = None) -> bool:
    """Check if a handle is available (case-insensitive uniqueness)."""
    if not handle:
        return False

    query = User.query.filter(func.lower(User.handle) == handle.lower())
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.first() is None


def generate_unique_handle(seed: str, *, exclude_user_id: Optional[int] = None) -> str:
    """Generate a unique handle by appending a numeric suffix if needed."""
    base = normalize_handle(seed)
    if not base:
        base = "user"

    if is_handle_available(base, exclude_user_id=exclude_user_id):
        return base

    counter = 2
    while True:
        candidate = f"{base}-{counter}"
        if is_handle_available(candidate, exclude_user_id=exclude_user_id):
            return candidate
        counter += 1


def assign_unique_handle(user: User, seed: Optional[str] = None) -> None:
    """
    Assign a unique handle to the provided user instance.

    Callers are responsible for committing the session afterwards.
    """
    basis = seed or user.handle or user.username or user.email or "user"
    user.handle = generate_unique_handle(basis, exclude_user_id=user.id if user.id else None)
    db.session.add(user)
