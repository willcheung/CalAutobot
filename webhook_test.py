#!/usr/bin/env python3
"""
Google Calendar Webhook Test Script

This script helps test the Google Calendar webhook functionality by:
1. Testing the webhook endpoint
2. Setting up webhooks for existing users
3. Verifying webhook configurations

Usage:
    python webhook_test.py [command] [options]

Commands:
    test       - Test webhook endpoint
    setup      - Set up webhook for a user
    status     - Check webhook status for a user
    cleanup    - Stop webhook for a user
"""

import os
import sys
import json
import requests
from datetime import datetime

# Add the app directory to the path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_webhook_endpoint(base_url=None):
    """Test that the webhook endpoint is responding"""
    if not base_url:
        base_url = os.environ.get('WEBHOOK_BASE_URL', 'http://localhost:5000')
    
    webhook_url = f"{base_url}/webhook/google-calendar/test"
    
    print(f"Testing webhook endpoint: {webhook_url}")
    
    try:
        # Test GET request
        response = requests.get(webhook_url, timeout=10)
        print(f"GET request status: {response.status_code}")
        if response.status_code == 200:
            print(f"Response: {response.json()}")
        
        # Test POST request (simulate webhook)
        test_headers = {
            'X-Goog-Channel-ID': 'test-channel-123',
            'X-Goog-Resource-ID': 'test-resource-456',
            'X-Goog-Resource-State': 'sync',
            'X-Goog-Channel-Token': 'cal-autobot-test'
        }
        
        response = requests.post(webhook_url, headers=test_headers, timeout=10)
        print(f"POST request status: {response.status_code}")
        if response.status_code == 200:
            print(f"Response: {response.json()}")
        
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"Error testing webhook endpoint: {e}")
        return False

def setup_webhook_for_user(user_email, base_url=None):
    """Set up webhook for a specific user"""
    if not base_url:
        base_url = os.environ.get('WEBHOOK_BASE_URL', 'http://localhost:5000')
    
    setup_url = f"{base_url}/webhook/google-calendar/setup"
    
    print(f"Setting up webhook for user: {user_email}")
    
    # This would require authentication in a real scenario
    # For testing, we might need to simulate or use the database directly
    print("Note: This requires user authentication. Use the web interface to set up webhooks.")
    
    return False

def check_webhook_status():
    """Check webhook status for users in the database"""
    try:
        from app import app, db
        from models import User
        
        with app.app_context():
            users_with_webhooks = User.query.filter(
                User.webhook_channel_id.isnot(None)
            ).all()
            
            print(f"Found {len(users_with_webhooks)} users with webhooks:")
            
            for user in users_with_webhooks:
                status = "Active"
                if user.webhook_expiration and user.webhook_expiration < datetime.utcnow():
                    status = "Expired"
                
                print(f"  {user.email}:")
                print(f"    Channel ID: {user.webhook_channel_id}")
                print(f"    Resource ID: {user.webhook_resource_id}")
                print(f"    Expiration: {user.webhook_expiration}")
                print(f"    Status: {status}")
                print()
    
    except Exception as e:
        print(f"Error checking webhook status: {e}")

def cleanup_webhook_for_user(user_email):
    """Stop webhook for a specific user"""
    try:
        from app import app, db
        from models import User
        from google_calendar import stop_calendar_webhook_for_user
        
        with app.app_context():
            user = User.query.filter_by(email=user_email).first()
            if not user:
                print(f"User not found: {user_email}")
                return False
            
            print(f"Stopping webhook for user: {user_email}")
            result = stop_calendar_webhook_for_user(user)
            
            if result:
                print("Webhook stopped successfully")
            else:
                print("Failed to stop webhook")
            
            return result
    
    except Exception as e:
        print(f"Error stopping webhook: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'test':
        base_url = sys.argv[2] if len(sys.argv) > 2 else None
        success = test_webhook_endpoint(base_url)
        sys.exit(0 if success else 1)
    
    elif command == 'setup':
        if len(sys.argv) < 3:
            print("Usage: python webhook_test.py setup <user_email>")
            sys.exit(1)
        user_email = sys.argv[2]
        base_url = sys.argv[3] if len(sys.argv) > 3 else None
        success = setup_webhook_for_user(user_email, base_url)
        sys.exit(0 if success else 1)
    
    elif command == 'status':
        check_webhook_status()
    
    elif command == 'cleanup':
        if len(sys.argv) < 3:
            print("Usage: python webhook_test.py cleanup <user_email>")
            sys.exit(1)
        user_email = sys.argv[2]
        success = cleanup_webhook_for_user(user_email)
        sys.exit(0 if success else 1)
    
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

if __name__ == '__main__':
    main()