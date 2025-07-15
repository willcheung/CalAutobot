
#!/usr/bin/env python3
"""
Migration script to remove is_verified column from user_email table
"""

import os
import sys
from sqlalchemy import create_engine, text

def get_database_url():
    """Get database URL from environment variables"""
    # Try PostgreSQL first (Replit's preferred database)
    db_url = os.environ.get('DATABASE_URL')
    if db_url and db_url.startswith('postgres://'):
        # Fix for newer SQLAlchemy versions
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    elif db_url and db_url.startswith('postgresql://'):
        pass  # Already correct
    else:
        # Fallback to SQLite for development
        db_url = 'sqlite:///instance/calendar.db'
    
    return db_url

def main():
    """Run the migration"""
    db_url = get_database_url()
    print(f"Connecting to database: {db_url.split('@')[0]}@..." if '@' in db_url else db_url)
    
    try:
        engine = create_engine(db_url)
        
        with engine.connect() as conn:
            # Check if column exists first
            if 'postgresql' in db_url:
                # PostgreSQL
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'user_email' AND column_name = 'is_verified'
                """))
                
                if result.fetchone():
                    print("Removing is_verified column from user_email table...")
                    conn.execute(text("ALTER TABLE user_email DROP COLUMN is_verified"))
                    conn.commit()
                    print("✅ Successfully removed is_verified column")
                else:
                    print("ℹ️  Column is_verified does not exist in user_email table")
                    
            else:
                # SQLite
                print("⚠️  SQLite detected. Column removal requires table recreation.")
                print("Checking if column exists...")
                
                # Check if column exists
                result = conn.execute(text("PRAGMA table_info(user_email)"))
                columns = [row[1] for row in result.fetchall()]
                
                if 'is_verified' in columns:
                    print("Creating new table without is_verified column...")
                    
                    # Create new table without is_verified
                    conn.execute(text("""
                        CREATE TABLE user_email_new (
                            id INTEGER PRIMARY KEY,
                            user_id INTEGER NOT NULL,
                            email VARCHAR(120) NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES user(id),
                            UNIQUE (email)
                        )
                    """))
                    
                    # Copy data
                    conn.execute(text("""
                        INSERT INTO user_email_new (id, user_id, email, created_at)
                        SELECT id, user_id, email, created_at FROM user_email
                    """))
                    
                    # Drop old table and rename new one
                    conn.execute(text("DROP TABLE user_email"))
                    conn.execute(text("ALTER TABLE user_email_new RENAME TO user_email"))
                    
                    # Recreate index
                    conn.execute(text("CREATE INDEX idx_user_email_email ON user_email(email)"))
                    
                    conn.commit()
                    print("✅ Successfully removed is_verified column")
                else:
                    print("ℹ️  Column is_verified does not exist in user_email table")
                    
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
