"""
Migration: Add Calendly integration fields to User, EventType, and Event models.

Run with:
    python tools/migrations/20251110_add_calendly_integration.py

The script is idempotent and safe to rerun. It adds columns for Calendly OAuth tokens,
user URIs, and event URIs to enable Calendly integration.
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


def add_calendly_user_fields() -> None:
    """Add Calendly OAuth and user fields to User table."""
    columns_to_add = [
        ("calendly_access_token", "TEXT"),
        ("calendly_refresh_token", "TEXT"),
        ("calendly_user_uri", "VARCHAR(255)"),
        ("calendly_organization_uri", "VARCHAR(255)"),
        ("calendly_scheduling_url", "VARCHAR(512)"),
        ("calendly_webhook_subscription_uri", "VARCHAR(255)"),
        ("calendly_connected_at", "TIMESTAMP"),
    ]

    with db.engine.begin() as conn:
        for column_name, column_type in columns_to_add:
            if not _column_exists("user", column_name):
                app.logger.info(f"Adding column user.{column_name}")
                conn.execute(text(f"ALTER TABLE user ADD COLUMN {column_name} {column_type}"))
            else:
                app.logger.info(f"Column user.{column_name} already exists, skipping")


def add_calendly_event_type_fields() -> None:
    """Add Calendly fields to EventType table."""
    columns_to_add = [
        ("calendly_event_type_uri", "VARCHAR(255)"),
        ("is_calendly_managed", "BOOLEAN DEFAULT FALSE"),
        ("calendly_last_synced_at", "TIMESTAMP"),
    ]

    with db.engine.begin() as conn:
        for column_name, column_type in columns_to_add:
            if not _column_exists("event_type", column_name):
                app.logger.info(f"Adding column event_type.{column_name}")
                conn.execute(text(f"ALTER TABLE event_type ADD COLUMN {column_name} {column_type}"))
            else:
                app.logger.info(f"Column event_type.{column_name} already exists, skipping")

        # Add unique constraint on calendly_event_type_uri
        if _column_exists("event_type", "calendly_event_type_uri"):
            try:
                app.logger.info("Adding unique constraint on event_type.calendly_event_type_uri")
                conn.execute(
                    text("CREATE UNIQUE INDEX IF NOT EXISTS uq_event_type_calendly_uri ON event_type(calendly_event_type_uri)")
                )
            except Exception as e:
                app.logger.warning(f"Could not create unique index: {e}")


def add_calendly_event_fields() -> None:
    """Add Calendly fields to Event table."""
    columns_to_add = [
        ("calendly_event_uri", "VARCHAR(255)"),
        ("calendly_invitee_uri", "VARCHAR(255)"),
        ("calendly_last_synced_at", "TIMESTAMP"),
    ]

    with db.engine.begin() as conn:
        for column_name, column_type in columns_to_add:
            if not _column_exists("event", column_name):
                app.logger.info(f"Adding column event.{column_name}")
                conn.execute(text(f"ALTER TABLE event ADD COLUMN {column_name} {column_type}"))
            else:
                app.logger.info(f"Column event.{column_name} already exists, skipping")

        # Add unique constraint on calendly_event_uri
        if _column_exists("event", "calendly_event_uri"):
            try:
                app.logger.info("Adding unique constraint on event.calendly_event_uri")
                conn.execute(
                    text("CREATE UNIQUE INDEX IF NOT EXISTS uq_event_calendly_uri ON event(calendly_event_uri)")
                )
            except Exception as e:
                app.logger.warning(f"Could not create unique index: {e}")


def main():
    with app.app_context():
        app.logger.info("Starting Calendly integration migration...")
        add_calendly_user_fields()
        add_calendly_event_type_fields()
        add_calendly_event_fields()
        db.session.commit()
        app.logger.info("Calendly integration migration completed successfully.")


if __name__ == "__main__":
    main()
