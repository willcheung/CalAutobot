"""
Migration: Add additional Calendly fields to EventType model.

Run with:
    python tools/migrations/20251116_add_calendly_event_type_fields.py

This migration adds:
- calendly_scheduling_url: Direct link to Calendly event type booking page
- calendly_location_json: JSON storage for Calendly location/conferencing settings
- calendly_kind: Type of Calendly event (solo, group, collective, etc.)

The script is idempotent and safe to rerun. It only adds columns, no data deletion.
"""

import sys

from sqlalchemy import inspect, text

sys.path.insert(0, ".")

from app import app, db  # noqa: E402


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(db.engine)
    try:
        columns = inspector.get_columns(table_name)
    except Exception:
        return False
    return any(col["name"] == column_name for col in columns)


def add_calendly_event_type_fields() -> None:
    """Add additional Calendly fields to EventType table."""
    columns_to_add = [
        ("calendly_scheduling_url", "VARCHAR(512)"),
        ("calendly_location_json", "TEXT"),
        ("calendly_kind", "VARCHAR(50)"),
    ]

    with db.engine.begin() as conn:
        for column_name, column_type in columns_to_add:
            if not _column_exists("event_type", column_name):
                app.logger.info(f"Adding column event_type.{column_name}")
                conn.execute(text(f"ALTER TABLE event_type ADD COLUMN {column_name} {column_type}"))
            else:
                app.logger.info(f"Column event_type.{column_name} already exists, skipping")


def main():
    with app.app_context():
        app.logger.info("Starting Calendly EventType fields migration...")
        add_calendly_event_type_fields()
        db.session.commit()
        app.logger.info("Calendly EventType fields migration completed successfully.")


if __name__ == "__main__":
    main()
