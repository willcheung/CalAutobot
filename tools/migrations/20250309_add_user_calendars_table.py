#!/usr/bin/env python3
"""
Migration script to create the user_calendars table used by the calendar
settings page.

Run with:
    python tools/migrations/20250309_add_user_calendars_table.py

The script is idempotent. It only creates missing database structures.
"""

import sys
from sqlalchemy import inspect

sys.path.insert(0, ".")

from app import app, db  # noqa: E402
from app.models import UserCalendar  # noqa: E402

TABLE_NAME = UserCalendar.__table__.name
UNIQUE_CONSTRAINT = "uq_user_calendar"


def ensure_table():
    inspector = inspect(db.engine)
    if TABLE_NAME in inspector.get_table_names():
        app.logger.info("Table %s already exists; skipping creation", TABLE_NAME)
        return

    app.logger.info("Creating table %s", TABLE_NAME)
    UserCalendar.__table__.create(bind=db.engine, checkfirst=True)


def ensure_unique_constraint():
    inspector = inspect(db.engine)
    existing_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints(TABLE_NAME)
    }
    if UNIQUE_CONSTRAINT in existing_constraints:
        app.logger.info(
            "Unique constraint %s already present on %s", UNIQUE_CONSTRAINT, TABLE_NAME
        )
        return

    app.logger.info(
        "Adding unique constraint %s to %s", UNIQUE_CONSTRAINT, TABLE_NAME
    )
    with db.engine.connect() as conn:
        conn.execute(
            db.text(
                f'ALTER TABLE "{TABLE_NAME}" ADD CONSTRAINT {UNIQUE_CONSTRAINT} '
                "(user_id, calendar_id) UNIQUE"
            )
        )
        conn.commit()


def main():
    with app.app_context():
        ensure_table()
        ensure_unique_constraint()
        app.logger.info("User calendar migration completed successfully.")


if __name__ == "__main__":
    main()
