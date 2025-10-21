#!/usr/bin/env python3
"""Add status and source columns to event table if missing."""

import sys
from sqlalchemy import inspect

sys.path.insert(0, ".")

from app import app, db  # noqa: E402

TABLE_NAME = "event"
STATUS_COLUMN = "status"
SOURCE_COLUMN = "source"


def column_exists(inspector, column_name: str) -> bool:
    return column_name in {col["name"] for col in inspector.get_columns(TABLE_NAME)}


def ensure_status_column(inspector) -> None:
    if column_exists(inspector, STATUS_COLUMN):
        app.logger.info("Column %s already exists on %s", STATUS_COLUMN, TABLE_NAME)
        return

    app.logger.info("Adding column %s to %s", STATUS_COLUMN, TABLE_NAME)
    with db.engine.connect() as conn:
        conn.execute(
            db.text(
                f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN {STATUS_COLUMN} VARCHAR(20) DEFAULT \'scheduled\''
            )
        )
        conn.execute(
            db.text(
                f'UPDATE "{TABLE_NAME}" SET {STATUS_COLUMN} = \'scheduled\' WHERE {STATUS_COLUMN} IS NULL'
            )
        )
        conn.execute(
            db.text(
                f'ALTER TABLE "{TABLE_NAME}" ALTER COLUMN {STATUS_COLUMN} SET NOT NULL'
            )
        )
        conn.commit()


def ensure_source_column(inspector) -> None:
    if column_exists(inspector, SOURCE_COLUMN):
        app.logger.info("Column %s already exists on %s", SOURCE_COLUMN, TABLE_NAME)
        return

    app.logger.info("Adding column %s to %s", SOURCE_COLUMN, TABLE_NAME)
    with db.engine.connect() as conn:
        conn.execute(
            db.text(
                f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN {SOURCE_COLUMN} VARCHAR(20) DEFAULT \'unknown\''
            )
        )
        conn.execute(
            db.text(
                f'UPDATE "{TABLE_NAME}" SET {SOURCE_COLUMN} = \'extracted\' WHERE {SOURCE_COLUMN} IS NULL AND text_input_id IS NOT NULL'
            )
        )
        conn.execute(
            db.text(
                f'UPDATE "{TABLE_NAME}" SET {SOURCE_COLUMN} = \'public_booking\' WHERE text_input_id IS NULL AND public_token IS NOT NULL'
            )
        )
        conn.execute(
            db.text(
                f'UPDATE "{TABLE_NAME}" SET {SOURCE_COLUMN} = \'unknown\' WHERE {SOURCE_COLUMN} IS NULL'
            )
        )
        conn.execute(
            db.text(
                f'ALTER TABLE "{TABLE_NAME}" ALTER COLUMN {SOURCE_COLUMN} SET NOT NULL'
            )
        )
        conn.commit()


def main():
    with app.app_context():
        inspector = inspect(db.engine)
        ensure_status_column(inspector)
        # refresh inspector after altering table
        inspector = inspect(db.engine)
        ensure_source_column(inspector)
        with db.engine.connect() as conn:
            conn.execute(
                db.text(
                    f'ALTER TABLE "{TABLE_NAME}" ALTER COLUMN {STATUS_COLUMN} SET DEFAULT \'scheduled\''
                )
            )
            conn.execute(
                db.text(
                    f'ALTER TABLE "{TABLE_NAME}" ALTER COLUMN {SOURCE_COLUMN} SET DEFAULT \'unknown\''
                )
            )
            conn.commit()
        app.logger.info("Migration completed successfully.")


if __name__ == "__main__":
    main()
