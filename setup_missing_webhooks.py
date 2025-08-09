#!/usr/bin/env python3
"""
Setup webhooks for existing users who have Calendar Autobot calendars but no webhooks.
This script retroactively adds webhook functionality to users who created calendars
before the webhook system was implemented.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User
from google_calendar import setup_calendar_webhook_for_user, refresh_google_token
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def find_users_needing_webhooks():
    """
    Find users who have Calendar Autobot calendars but no webhook setup.
    
    Returns:
        list: List of User objects who need webhook setup
    """
    try:
        with app.app_context():
            # Find users with Calendar Autobot calendars but no webhook
            users_needing_webhooks = User.query.filter(
                User.textbot_calendar_id.isnot(None),  # Has a calendar
                User.webhook_channel_id.is_(None)      # But no webhook
            ).all()
            
            logger.info(f"Found {len(users_needing_webhooks)} users needing webhook setup")
            
            for user in users_needing_webhooks:
                logger.info(f"  - {user.email}: Calendar {user.textbot_calendar_id}")
            
            return users_needing_webhooks
            
    except Exception as e:
        logger.error(f"Error finding users needing webhooks: {str(e)}")
        return []

def setup_webhook_for_user(user):
    """
    Set up webhook for a single user.
    
    Args:
        user: User object to set up webhook for
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        # Get fresh access token
        access_token = refresh_google_token(user)
        if not access_token:
            return False, f"Could not refresh token for user {user.email}"
        
        # Set up webhook
        webhook_data = setup_calendar_webhook_for_user(user, access_token, user.textbot_calendar_id)
        
        if webhook_data:
            return True, f"Successfully set up webhook for {user.email}"
        else:
            return False, f"Failed to set up webhook for {user.email} (no webhook data returned)"
            
    except Exception as e:
        error_msg = f"Error setting up webhook for {user.email}: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def setup_all_missing_webhooks(dry_run=False):
    """
    Set up webhooks for all users who need them.
    
    Args:
        dry_run: If True, only show what would be done without making changes
    
    Returns:
        dict: Summary of results
    """
    try:
        with app.app_context():
            users_needing_webhooks = find_users_needing_webhooks()
            
            if not users_needing_webhooks:
                logger.info("No users need webhook setup")
                return {"total": 0, "success": 0, "failed": 0, "messages": []}
            
            if dry_run:
                logger.info(f"DRY RUN: Would set up webhooks for {len(users_needing_webhooks)} users")
                for user in users_needing_webhooks:
                    logger.info(f"  Would setup webhook for: {user.email}")
                return {"total": len(users_needing_webhooks), "success": 0, "failed": 0, "messages": ["Dry run completed"]}
            
            results = {
                "total": len(users_needing_webhooks),
                "success": 0,
                "failed": 0,
                "messages": []
            }
            
            logger.info(f"Setting up webhooks for {len(users_needing_webhooks)} users...")
            
            for user in users_needing_webhooks:
                logger.info(f"Setting up webhook for {user.email}...")
                
                success, message = setup_webhook_for_user(user)
                
                if success:
                    results["success"] += 1
                    logger.info(f"✓ {message}")
                else:
                    results["failed"] += 1
                    logger.error(f"✗ {message}")
                
                results["messages"].append(f"{'✓' if success else '✗'} {user.email}: {message}")
            
            logger.info(f"\nWebhook setup completed:")
            logger.info(f"  Total users: {results['total']}")
            logger.info(f"  Successful: {results['success']}")
            logger.info(f"  Failed: {results['failed']}")
            
            return results
            
    except Exception as e:
        logger.error(f"Error in setup_all_missing_webhooks: {str(e)}")
        return {"total": 0, "success": 0, "failed": 1, "messages": [f"Script error: {str(e)}"]}

def check_webhook_status():
    """
    Check and display current webhook status for all users.
    """
    try:
        with app.app_context():
            # Users with webhooks
            users_with_webhooks = User.query.filter(
                User.webhook_channel_id.isnot(None)
            ).all()
            
            # Users with calendars but no webhooks
            users_needing_webhooks = User.query.filter(
                User.textbot_calendar_id.isnot(None),
                User.webhook_channel_id.is_(None)
            ).all()
            
            # Users with neither
            users_no_calendar = User.query.filter(
                User.textbot_calendar_id.is_(None)
            ).all()
            
            logger.info("=== WEBHOOK STATUS REPORT ===")
            logger.info(f"Users with active webhooks: {len(users_with_webhooks)}")
            
            for user in users_with_webhooks:
                status = "Active"
                if user.webhook_expiration and user.webhook_expiration < datetime.utcnow():
                    status = "Expired"
                logger.info(f"  ✓ {user.email} - {status}")
            
            logger.info(f"\nUsers needing webhook setup: {len(users_needing_webhooks)}")
            for user in users_needing_webhooks:
                logger.info(f"  ⚠ {user.email} - Has calendar: {user.textbot_calendar_id[:20]}...")
            
            logger.info(f"\nUsers without Calendar Autobot: {len(users_no_calendar)}")
            logger.info("  (These users don't need webhooks yet)")
            
    except Exception as e:
        logger.error(f"Error checking webhook status: {str(e)}")

def main():
    """Main script function"""
    if len(sys.argv) < 2:
        print("Usage: python setup_missing_webhooks.py [command]")
        print("Commands:")
        print("  status     - Show current webhook status")
        print("  dry-run    - Show what would be done without making changes")
        print("  setup      - Set up webhooks for all users who need them")
        print("  help       - Show this help message")
        return
    
    command = sys.argv[1].lower()
    
    if command == 'status':
        check_webhook_status()
    
    elif command == 'dry-run':
        results = setup_all_missing_webhooks(dry_run=True)
        print(f"\nDry run summary: {results['total']} users would get webhook setup")
    
    elif command == 'setup':
        print("Setting up webhooks for existing users...")
        results = setup_all_missing_webhooks(dry_run=False)
        print(f"\nSetup completed:")
        print(f"  Total: {results['total']}")
        print(f"  Success: {results['success']}")
        print(f"  Failed: {results['failed']}")
        
        if results['messages']:
            print("\nDetailed results:")
            for message in results['messages']:
                print(f"  {message}")
    
    elif command == 'help':
        main()
    
    else:
        print(f"Unknown command: {command}")
        print("Use 'help' to see available commands")

if __name__ == '__main__':
    main()