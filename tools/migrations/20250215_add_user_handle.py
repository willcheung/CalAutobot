#!/usr/bin/env python3
"""
Migration script to add the user.handle column and backfill existing users.

Run with:
    python tools/migrations/20250215_add_user_handle.py

The script is idempotent.
"""

import sys
sys.path.insert(0, ".")

from sqlalchemy import inspect

from app import app, db
from app.models import User
from app.services.users import assign_unique_handle

TABLE_NAME = "user"
COLUMN_NAME = "handle"
INDEX_NAME = "ix_user_handle"


def column_exists(inspector) -> bool:
    columns = [col["name"] for col in inspector.get_columns(TABLE_NAME)]
    return COLUMN_NAME in columns


def ensure_column():
    inspector = inspect(db.engine)
    if column_exists(inspector):
        app.logger.info("Column %s already exists on table %s", COLUMN_NAME, TABLE_NAME)
        return

    app.logger.info("Adding column %s to table %s", COLUMN_NAME, TABLE_NAME)
    with db.engine.connect() as conn:
        conn.execute(db.text(f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN {COLUMN_NAME} VARCHAR(64)'))
        conn.commit()


def ensure_index():
    inspector = inspect(db.engine)
    indexes = [idx["name"] for idx in inspector.get_indexes(TABLE_NAME)]
    if INDEX_NAME in indexes:
        app.logger.info("Index %s already exists on table %s", INDEX_NAME, TABLE_NAME)
        return

    app.logger.info("Creating unique index %s on %s.%s", INDEX_NAME, TABLE_NAME, COLUMN_NAME)
    with db.engine.connect() as conn:
        conn.execute(db.text(f'CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} ON "{TABLE_NAME}" ({COLUMN_NAME})'))
        conn.commit()


def backfill_handles():
    users = User.query.filter((User.handle.is_(None)) | (User.handle == "")).all()
    if not users:
        app.logger.info("All users already have handles.")
        return

    app.logger.info("Assigning handles for %d users", len(users))
    for user in users:
        seed = user.username or user.email or "user"
        assign_unique_handle(user, seed)
    db.session.commit()


def main():
    with app.app_context():
        ensure_column()
        ensure_index()
        backfill_handles()
        app.logger.info("Handle migration complete.")


if __name__ == "__main__":
    main()
