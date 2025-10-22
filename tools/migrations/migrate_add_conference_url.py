#!/usr/bin/env python3
"""
Migration script to add conference_url column to Event table.

Run once to update existing database schema.
"""

from app import app, db


def migrate_add_conference_url():
    with app.app_context():
        from sqlalchemy import inspect

        inspector = inspect(db.engine)
        columns = [column["name"] for column in inspector.get_columns("event")]

        if "conference_url" in columns:
            print("conference_url column already exists on event table.")
            return

        print("Adding conference_url column to event table...")
        with db.engine.connect() as conn:
            conn.execute(
                db.text('ALTER TABLE "event" ADD COLUMN conference_url VARCHAR(500)')
            )
            conn.commit()
        print("conference_url column added successfully.")


if __name__ == "__main__":
    migrate_add_conference_url()
