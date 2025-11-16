"""
Migration: Add calendly_plan to User model
Date: 2025-11-16
Description: Adds calendly_plan field to store user's Calendly subscription plan tier

Usage:
    python tools/migrations/20251116_add_calendly_plan.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from dotenv import load_dotenv
load_dotenv()

from app import app, db
from sqlalchemy import text

def run_migration():
    """Add calendly_plan column to user table."""

    with app.app_context():
        print("Starting migration: Add calendly_plan to User...")

        # Check if column already exists
        with db.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'user'
                AND column_name = 'calendly_plan'
            """))
            existing_columns = {row[0] for row in result}

        if 'calendly_plan' in existing_columns:
            print("  - calendly_plan already exists, skipping")
            print("\n✅ All columns already exist. Nothing to migrate.")
            return

        print("  - Will add calendly_plan")

        # Execute ALTER TABLE
        alter_statement = "ALTER TABLE \"user\" ADD COLUMN calendly_plan VARCHAR(50)"
        print(f"\nExecuting: {alter_statement}")

        with db.engine.connect() as conn:
            conn.execute(text(alter_statement))
            conn.commit()

        print("\n✅ Migration completed successfully!")
        print("Added field:")
        print("  - calendly_plan (VARCHAR 50) - Calendly plan tier (e.g., 'standard', 'teams', 'enterprise', 'free')")

if __name__ == "__main__":
    run_migration()
