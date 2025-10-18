#!/usr/bin/env python3
"""Rename user.textbot_calendar_id to user.extraction_calendar_id.

Run with:
    python tools/migrations/20250420_rename_textbot_calendar_column.py

The script is safe to run multiple times; it skips work if the column was
already renamed or never existed.
"""

import sys
from sqlalchemy import inspect

sys.path.insert(0, ".")

from app import app, db  # noqa: E402

TABLE_NAME = "user"
OLD_COLUMN = "textbot_calendar_id"
NEW_COLUMN = "extraction_calendar_id"


def existing_columns():
    inspector = inspect(db.engine)
    return {col["name"] for col in inspector.get_columns(TABLE_NAME)}


def rename_column():
    columns = existing_columns()

    if NEW_COLUMN in columns:
        app.logger.info(
            "Column %s already present on %s; nothing to rename.",
            NEW_COLUMN,
            TABLE_NAME,
        )
        return

    if OLD_COLUMN not in columns:
        app.logger.info(
            "Neither %s nor %s exists on %s; skipping.",
            OLD_COLUMN,
            NEW_COLUMN,
            TABLE_NAME,
        )
        return

    app.logger.info(
        "Renaming column %s.%s -> %s.%s",
        TABLE_NAME,
        OLD_COLUMN,
        TABLE_NAME,
        NEW_COLUMN,
    )

    with db.engine.connect() as conn:
        conn.execute(
            db.text(
                f'ALTER TABLE "{TABLE_NAME}" RENAME COLUMN {OLD_COLUMN} TO {NEW_COLUMN}'
            )
        )
        conn.commit()


def main():
    with app.app_context():
        rename_column()
        app.logger.info("Migration completed successfully.")


if __name__ == "__main__":
    main()
