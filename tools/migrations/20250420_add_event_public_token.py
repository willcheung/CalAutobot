#!/usr/bin/env python3
"""Add public_token column to event table if missing."""

import sys
from sqlalchemy import inspect

sys.path.insert(0, ".")

from app import app, db  # noqa: E402

TABLE_NAME = "event"
COLUMN_NAME = "public_token"


def column_exists(inspector) -> bool:
    return COLUMN_NAME in {col["name"] for col in inspector.get_columns(TABLE_NAME)}


def ensure_column():
    inspector = inspect(db.engine)
    if column_exists(inspector):
        app.logger.info(
            "Column %s already exists on table %s; skipping.",
            COLUMN_NAME,
            TABLE_NAME,
        )
        return

    app.logger.info("Adding column %s to table %s", COLUMN_NAME, TABLE_NAME)
    with db.engine.connect() as conn:
        conn.execute(
            db.text(
                f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN {COLUMN_NAME} VARCHAR(64)'
            )
        )
        conn.commit()


def main():
    with app.app_context():
        ensure_column()
        app.logger.info("Migration completed successfully.")


if __name__ == "__main__":
    main()
