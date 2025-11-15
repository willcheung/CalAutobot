"""
Migration: Add Calendly event type sync fields
Date: 2025-11-16
Description: Adds calendly_scheduling_url, calendly_location_json, and calendly_kind to EventType model

Usage:
    python tools/migrations/20251116_add_calendly_event_type_fields.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app, db
from sqlalchemy import text

def run_migration():
    """Add new Calendly fields to event_type table."""
    app = create_app()

    with app.app_context():
        print("Starting migration: Add Calendly event type fields...")

        # Check if columns already exist
        with db.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'event_type'
                AND column_name IN ('calendly_scheduling_url', 'calendly_location_json', 'calendly_kind')
            """))
            existing_columns = {row[0] for row in result}

        columns_to_add = []

        if 'calendly_scheduling_url' not in existing_columns:
            columns_to_add.append(
                "ADD COLUMN calendly_scheduling_url VARCHAR(512)"
            )
            print("  - Will add calendly_scheduling_url")
        else:
            print("  - calendly_scheduling_url already exists, skipping")

        if 'calendly_location_json' not in existing_columns:
            columns_to_add.append(
                "ADD COLUMN calendly_location_json TEXT"
            )
            print("  - Will add calendly_location_json")
        else:
            print("  - calendly_location_json already exists, skipping")

        if 'calendly_kind' not in existing_columns:
            columns_to_add.append(
                "ADD COLUMN calendly_kind VARCHAR(50)"
            )
            print("  - Will add calendly_kind")
        else:
            print("  - calendly_kind already exists, skipping")

        if columns_to_add:
            # Execute ALTER TABLE with all columns at once
            alter_statement = f"ALTER TABLE event_type {', '.join(columns_to_add)}"
            print(f"\nExecuting: {alter_statement}")

            with db.engine.connect() as conn:
                conn.execute(text(alter_statement))
                conn.commit()

            print("\n✅ Migration completed successfully!")
            print("Added fields:")
            print("  - calendly_scheduling_url (VARCHAR 512) - Public Calendly booking page URL")
            print("  - calendly_location_json (TEXT) - Meeting location config as JSON")
            print("  - calendly_kind (VARCHAR 50) - Event type kind (solo/group/collective/round_robin)")
        else:
            print("\n✅ All columns already exist. Nothing to migrate.")

if __name__ == "__main__":
    run_migration()
