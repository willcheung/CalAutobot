#!/usr/bin/env python3
"""
Gmail Email Checker Script for Replit Scheduled Deployments

This script is designed to run as a scheduled deployment in Replit.
It checks for new emails in the Gmail inbox and processes them for event extraction.

Schedule: Run every 5 minutes (or as configured in Replit Deployments)
Command: python check_emails.py
"""

import sys
import os
import logging
from datetime import datetime

# Add current directory to Python path
sys.path.append('.')

# Import Flask app first to initialize database
from app import app

# Set up logging for scheduled execution
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Main function called by scheduled deployment"""
    try:
        logger.info("=" * 80)
        logger.info(f"GMAIL EMAIL CHECK STARTED - {datetime.utcnow().isoformat()}")
        logger.info("=" * 80)
        
        # Check required environment variables
        required_vars = [
            'GMAIL_CLIENT_ID',
            'GMAIL_CLIENT_SECRET', 
            'GMAIL_REFRESH_TOKEN'
        ]
        
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        if missing_vars:
            logger.error(f"❌ Missing required environment variables: {missing_vars}")
            print(f"ERROR: Missing environment variables: {missing_vars}")
            sys.exit(1)
        
        logger.info("✅ Gmail credentials found in environment")
        
        # Initialize Flask app context for database operations
        with app.app_context():
            # Import within app context to avoid circular imports
            from gmail_processor import check_new_emails
            
            logger.info("🔄 Starting Gmail email check...")
            
            # Check for new emails and process them
            check_new_emails()
            
            logger.info("✅ Gmail email check completed successfully")
        
        logger.info("=" * 80)
        logger.info(f"GMAIL EMAIL CHECK FINISHED - {datetime.utcnow().isoformat()}")
        logger.info("=" * 80)
        
        print("SUCCESS: Email check completed")
        
    except Exception as e:
        logger.error(f"❌ FATAL ERROR in scheduled email check: {str(e)}")
        print(f"ERROR: {str(e)}")
        
        # Import sentry if available for error reporting
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except ImportError:
            pass
        
        sys.exit(1)

if __name__ == "__main__":
    main()