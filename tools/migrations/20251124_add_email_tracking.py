"""
Migration: Add email tracking tables and contact engagement fields
Date: 2025-11-24
Description: Adds tracking_request, tracking_recipient, and tracking_event tables
             plus engagement metrics to Contact model

Usage:
    python tools/migrations/20251124_add_email_tracking.py
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
    """Add email tracking tables and contact engagement fields."""

    with app.app_context():
        print("Starting migration: Add email tracking...")

        # Check existing tables
        with db.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name IN ('tracking_request', 'tracking_recipient', 'tracking_event')
            """))
            existing_tables = {row[0] for row in result}

        # Check existing contact columns
        with db.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'contact'
                AND column_name IN ('emails_received', 'emails_opened', 'last_email_opened_at')
            """))
            existing_contact_columns = {row[0] for row in result}

        if (existing_tables == {'tracking_request', 'tracking_recipient', 'tracking_event'}
            and len(existing_contact_columns) == 3):
            print("✅ All tracking tables and columns already exist. Nothing to migrate.")
            return

        print("\n📋 Creating tracking tables and columns...")

        with db.engine.connect() as conn:
            # 1. Add engagement fields to contact table
            if 'emails_received' not in existing_contact_columns:
                print("  - Adding emails_received to contact table")
                conn.execute(text("""
                    ALTER TABLE contact
                    ADD COLUMN emails_received INTEGER NOT NULL DEFAULT 0
                """))
                conn.commit()

            if 'emails_opened' not in existing_contact_columns:
                print("  - Adding emails_opened to contact table")
                conn.execute(text("""
                    ALTER TABLE contact
                    ADD COLUMN emails_opened INTEGER NOT NULL DEFAULT 0
                """))
                conn.commit()

            if 'last_email_opened_at' not in existing_contact_columns:
                print("  - Adding last_email_opened_at to contact table")
                conn.execute(text("""
                    ALTER TABLE contact
                    ADD COLUMN last_email_opened_at TIMESTAMP
                """))
                conn.commit()

            # 2. Create tracking_request table
            if 'tracking_request' not in existing_tables:
                print("  - Creating tracking_request table")
                conn.execute(text("""
                    CREATE TABLE tracking_request (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
                        tracking_id VARCHAR(64) NOT NULL UNIQUE,
                        subject VARCHAR(500),
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        tracking_enabled_at_send BOOLEAN NOT NULL DEFAULT TRUE,
                        sent_at TIMESTAMP NOT NULL,
                        first_opened_at TIMESTAMP,
                        last_opened_at TIMESTAMP,
                        open_count INTEGER NOT NULL DEFAULT 0,
                        unique_open_count INTEGER NOT NULL DEFAULT 0,
                        gmail_message_id VARCHAR(255),
                        gmail_thread_id VARCHAR(255),
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL
                    )
                """))
                conn.commit()

                print("  - Creating indexes on tracking_request")
                conn.execute(text("""
                    CREATE INDEX ix_tracking_request_user_id ON tracking_request(user_id)
                """))
                conn.execute(text("""
                    CREATE INDEX ix_tracking_request_tracking_id ON tracking_request(tracking_id)
                """))
                conn.execute(text("""
                    CREATE INDEX ix_tracking_request_sent_at ON tracking_request(sent_at)
                """))
                conn.execute(text("""
                    CREATE INDEX ix_tracking_request_gmail_thread_id ON tracking_request(gmail_thread_id)
                """))
                conn.commit()

            # 3. Create tracking_recipient junction table
            if 'tracking_recipient' not in existing_tables:
                print("  - Creating tracking_recipient table")
                conn.execute(text("""
                    CREATE TABLE tracking_recipient (
                        id SERIAL PRIMARY KEY,
                        tracking_request_id INTEGER NOT NULL REFERENCES tracking_request(id) ON DELETE CASCADE,
                        contact_id INTEGER NOT NULL REFERENCES contact(id) ON DELETE CASCADE,
                        recipient_type VARCHAR(10) NOT NULL,
                        has_opened BOOLEAN NOT NULL DEFAULT FALSE,
                        first_opened_at TIMESTAMP,
                        open_count INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMP NOT NULL
                    )
                """))
                conn.commit()

                print("  - Creating indexes on tracking_recipient")
                conn.execute(text("""
                    CREATE INDEX ix_tracking_recipient_tracking_request_id
                    ON tracking_recipient(tracking_request_id)
                """))
                conn.execute(text("""
                    CREATE INDEX ix_tracking_recipient_contact_id
                    ON tracking_recipient(contact_id)
                """))
                conn.commit()

            # 4. Create tracking_event table
            if 'tracking_event' not in existing_tables:
                print("  - Creating tracking_event table")
                conn.execute(text("""
                    CREATE TABLE tracking_event (
                        id SERIAL PRIMARY KEY,
                        tracking_request_id INTEGER NOT NULL REFERENCES tracking_request(id) ON DELETE CASCADE,
                        opened_at TIMESTAMP NOT NULL,
                        ip_hash VARCHAR(64),
                        user_agent_parsed JSONB,
                        country_code VARCHAR(2),
                        city VARCHAR(100),
                        timezone VARCHAR(50),
                        is_first_open BOOLEAN NOT NULL DEFAULT FALSE
                    )
                """))
                conn.commit()

                print("  - Creating indexes on tracking_event")
                conn.execute(text("""
                    CREATE INDEX ix_tracking_event_tracking_request_id
                    ON tracking_event(tracking_request_id)
                """))
                conn.execute(text("""
                    CREATE INDEX ix_tracking_event_opened_at
                    ON tracking_event(opened_at)
                """))
                conn.execute(text("""
                    CREATE INDEX ix_tracking_event_ip_hash
                    ON tracking_event(ip_hash)
                """))
                conn.commit()

        print("\n✅ Migration completed successfully!")
        print("\nCreated tables:")
        print("  - tracking_request (email tracking metadata)")
        print("  - tracking_recipient (junction table: tracking ↔ contact)")
        print("  - tracking_event (email open events)")
        print("\nAdded to Contact model:")
        print("  - emails_received (INT)")
        print("  - emails_opened (INT)")
        print("  - last_email_opened_at (TIMESTAMP)")

if __name__ == "__main__":
    run_migration()
