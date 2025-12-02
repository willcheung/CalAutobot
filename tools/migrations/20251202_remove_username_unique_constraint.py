"""
Migration: Remove unique constraint from username column
Date: 2025-12-02
Reason: Usernames are not actually unique (multiple people can have same name).
        Email and google_id are the proper unique identifiers.
"""

from sqlalchemy import text


def upgrade(connection):
    """Remove unique constraint from user.username"""
    print("Removing unique constraint from user.username...")

    # Drop the unique constraint
    connection.execute(text("""
        ALTER TABLE "user" DROP CONSTRAINT IF EXISTS user_username_key;
    """))

    # Create a regular index for performance (optional)
    connection.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_user_username ON "user"(username);
    """))

    print("✅ Removed unique constraint from username")


def downgrade(connection):
    """Add back unique constraint (not recommended - will fail if duplicates exist)"""
    print("⚠️  Warning: This will fail if duplicate usernames exist")
    connection.execute(text("""
        ALTER TABLE "user" ADD CONSTRAINT user_username_key UNIQUE (username);
    """))
    connection.execute(text("""
        DROP INDEX IF EXISTS idx_user_username;
    """))
    print("✅ Added back unique constraint to username")


if __name__ == "__main__":
    # Test the migration locally
    from app import app, db

    with app.app_context():
        with db.engine.connect() as conn:
            upgrade(conn)
            conn.commit()
            print("Migration completed successfully")
