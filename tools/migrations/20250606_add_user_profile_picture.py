#!/usr/bin/env python3
"""
Migration to add profile_picture_url column to the user table.

Run with:
    python tools/migrations/20250606_add_user_profile_picture.py

The migration is idempotent and will only add the column if it is missing.
"""

import sys
from sqlalchemy import inspect

sys.path.insert(0, ".")

from app import app, db  # noqa: E402

TABLE_NAME = "user"
COLUMN_NAME = "profile_picture_url"
COLUMN_TYPE = "VARCHAR(512)"


def column_exists(inspector) -> bool:
    return COLUMN_NAME in {col["name"] for col in inspector.get_columns(TABLE_NAME)}


def ensure_column():
    inspector = inspect(db.engine)
    if column_exists(inspector):
        app.logger.info(
            "Column %s already exists on table %s; skipping", COLUMN_NAME, TABLE_NAME
        )
        return

    app.logger.info("Adding column %s to table %s", COLUMN_NAME, TABLE_NAME)
    with db.engine.connect() as conn:
        conn.execute(
            db.text(f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN {COLUMN_NAME} {COLUMN_TYPE}')
        )
        conn.commit()


def main():
    with app.app_context():
        ensure_column()
        app.logger.info("Migration completed successfully.")


if __name__ == "__main__":
    main()
