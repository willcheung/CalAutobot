"""
Migration: add event type and availability tables.

Run with:
    python tools/migrations/20251016_add_event_types_availability.py

The script is idempotent. It only creates missing tables and leaves existing
rows untouched.
"""

from sqlalchemy import inspect

from app import app, db
from app.models import AvailabilityWindow, EventType


def create_table_if_missing(table):
    inspector = inspect(db.engine)
    table_name = table.name
    if table_name in inspector.get_table_names():
        app.logger.info("Table %s already exists; skipping", table_name)
        return
    app.logger.info("Creating table %s", table_name)
    table.create(bind=db.engine, checkfirst=True)


def main():
    with app.app_context():
        create_table_if_missing(EventType.__table__)
        create_table_if_missing(AvailabilityWindow.__table__)
        app.logger.info("Migration completed successfully.")


if __name__ == "__main__":
    main()
