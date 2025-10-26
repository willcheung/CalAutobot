"""
Migration: add follow-up configuration columns for users and meeting requests.

Run with:
    python tools/migrations/20250601_add_follow_up_fields.py

The script is idempotent; it checks for existing columns before mutating the schema.
"""

from sqlalchemy import inspect, text

from app import app, db


USER_COLUMNS = (
    ("user", "follow_up_enabled", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("user", "follow_up_first_delay_days", "INTEGER NOT NULL DEFAULT 1"),
    ("user", "follow_up_second_delay_days", "INTEGER NOT NULL DEFAULT 2"),
    ("user", "meeting_reminder_lead_hours", "INTEGER NOT NULL DEFAULT 24"),
)

MEETING_REQUEST_COLUMNS = (
    ("meeting_request", "last_agent_reply_at", "TIMESTAMP"),
    ("meeting_request", "next_follow_up_at", "TIMESTAMP"),
    ("meeting_request", "follow_up_count", "INTEGER NOT NULL DEFAULT 0"),
)

EVENT_COLUMNS = (
    ("event", "invitee_email", "VARCHAR(255)"),
    ("event", "invitee_name", "VARCHAR(255)"),
    ("event", "meeting_request_id", "INTEGER"),
    ("event", "reminder_sent_at", "TIMESTAMP"),
)


def column_exists(inspector, table_name: str, column_name: str) -> bool:
    try:
        columns = inspector.get_columns(table_name)
    except Exception:
        return False
    return any(col["name"] == column_name for col in columns)


def add_missing_columns(column_specs):
    inspector = inspect(db.engine)
    for table_name, column_name, ddl in column_specs:
        if column_exists(inspector, table_name, column_name):
            continue
        ddl_sql = f'ALTER TABLE "{table_name}" ADD COLUMN {column_name} {ddl}'
        app.logger.info("Adding column %s.%s", table_name, column_name)
        with db.engine.begin() as conn:
            conn.execute(text(ddl_sql))


def main():
    with app.app_context():
        add_missing_columns(USER_COLUMNS)
        add_missing_columns(MEETING_REQUEST_COLUMNS)
        add_missing_columns(EVENT_COLUMNS)
        app.logger.info("Follow-up columns migration completed successfully.")


if __name__ == "__main__":
    main()
