"""
Migration: add scheduling agent support tables and columns.

Run with:
    python tools/migrations/20250201_add_meeting_scheduler.py

The script is idempotent; it checks for columns/tables before creating them so it
can be executed safely in development and production environments.
"""

from sqlalchemy import inspect, text

from app import app, db
from app.models import MeetingMessage, MeetingParticipant, MeetingRequest


NEW_COLUMNS = (
    ("text_input", "task_type", "VARCHAR(50)"),
    ("text_input", "raw_email_context", "TEXT"),
)


def column_exists(inspector, table_name: str, column_name: str) -> bool:
    try:
        columns = inspector.get_columns(table_name)
    except Exception:
        return False
    return any(col["name"] == column_name for col in columns)


def table_exists(inspector, table_name: str) -> bool:
    try:
        return table_name in inspector.get_table_names()
    except Exception:
        return False


def add_missing_columns():
    inspector = inspect(db.engine)
    for table_name, column_name, ddl in NEW_COLUMNS:
        if column_exists(inspector, table_name, column_name):
            continue
        ddl_sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"
        app.logger.info("Adding column %s.%s", table_name, column_name)
        with db.engine.begin() as conn:
            conn.execute(text(ddl_sql))


def create_scheduler_tables():
    tables = [
        MeetingRequest.__table__,
        MeetingParticipant.__table__,
        MeetingMessage.__table__,
    ]
    inspector = inspect(db.engine)
    existing = set(inspector.get_table_names())
    for table in tables:
        if table.name in existing:
            continue
        app.logger.info("Creating table %s", table.name)
        table.create(bind=db.engine, checkfirst=True)


def main():
    with app.app_context():
        add_missing_columns()
        create_scheduler_tables()
        app.logger.info("Migration completed successfully.")


if __name__ == "__main__":
    main()
