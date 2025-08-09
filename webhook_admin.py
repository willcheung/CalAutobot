#!/usr/bin/env python3
"""
Simple webhook administration script for testing the Google Calendar webhook system.
This script helps create test scenarios and verify webhook functionality.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User, Event
from google_calendar import setup_calendar_webhook_for_user, stop_calendar_webhook_for_user
import json
from datetime import datetime, timedelta

def create_test_user_with_calendar():
    """Create a test user with a Calendar Autobot calendar for webhook testing"""
    try:
        with app.app_context():
            # Check if test user already exists
            test_user = User.query.filter_by(email='webhook-test@example.com').first()
            if test_user:
                print(f"Test user already exists: {test_user.email}")
                return test_user
            
            # Create test user
            test_user = User(
                username='Webhook Test User',
                email='webhook-test@example.com',
                google_id='test-google-id-123',
                timezone='UTC',
                textbot_calendar_id='test-calendar-id-123@group.calendar.google.com'
            )
            
            # Add some test Google token data (not functional, just for testing)
            test_token = {
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600
            }
            test_user.google_token = json.dumps(test_token)
            test_user.google_refresh_token = "test-refresh-token"
            
            db.session.add(test_user)
            db.session.commit()
            
            print(f"Created test user: {test_user.email}")
            print(f"Calendar ID: {test_user.textbot_calendar_id}")
            
            return test_user
            
    except Exception as e:
        print(f"Error creating test user: {e}")
        return None

def create_test_events_for_user(user):
    """Create some test events for the user"""
    try:
        with app.app_context():
            # Create test events
            test_events = [
                {
                    'event_name': 'Test Meeting 1',
                    'event_description': 'First test meeting for webhook testing',
                    'start_date': datetime.now().date(),
                    'google_event_id': 'test-event-1',
                    'is_synced': True
                },
                {
                    'event_name': 'Test Meeting 2', 
                    'event_description': 'Second test meeting for webhook testing',
                    'start_date': (datetime.now() + timedelta(days=1)).date(),
                    'google_event_id': 'test-event-2',
                    'is_synced': True
                },
                {
                    'event_name': 'Test Meeting 3',
                    'event_description': 'Third test meeting for webhook testing',
                    'start_date': (datetime.now() + timedelta(days=2)).date(),
                    'google_event_id': 'test-event-3',
                    'is_synced': True
                }
            ]
            
            created_events = []
            for event_data in test_events:
                # Check if event already exists
                existing_event = Event.query.filter_by(
                    user_id=user.id,
                    google_event_id=event_data['google_event_id']
                ).first()
                
                if not existing_event:
                    event = Event(
                        user_id=user.id,
                        event_name=event_data['event_name'],
                        event_description=event_data['event_description'],
                        start_date=event_data['start_date'],
                        google_event_id=event_data['google_event_id'],
                        is_synced=event_data['is_synced']
                    )
                    db.session.add(event)
                    created_events.append(event)
                else:
                    created_events.append(existing_event)
            
            db.session.commit()
            print(f"Created/found {len(created_events)} test events for user {user.email}")
            
            return created_events
            
    except Exception as e:
        print(f"Error creating test events: {e}")
        return []

def test_webhook_deletion_simulation():
    """Simulate webhook receiving a deletion notification"""
    try:
        with app.app_context():
            # Get test user
            user = User.query.filter_by(email='webhook-test@example.com').first()
            if not user:
                print("Test user not found. Run create_test_scenario first.")
                return
            
            # Get user's events
            events = Event.query.filter_by(user_id=user.id, is_synced=True).all()
            print(f"User has {len(events)} synced events before deletion simulation")
            
            # Simulate deletion of one event by removing it from our "mock Google Calendar"
            # In real scenario, the webhook would detect this was deleted from Google
            if events:
                event_to_delete = events[0]
                print(f"Simulating deletion of event: {event_to_delete.event_name} (ID: {event_to_delete.google_event_id})")
                
                # Delete the event (this simulates what would happen when webhook detects deletion)
                db.session.delete(event_to_delete)
                db.session.commit()
                
                # Count remaining events
                remaining_events = Event.query.filter_by(user_id=user.id, is_synced=True).all()
                print(f"User now has {len(remaining_events)} synced events after deletion")
                
                return True
            else:
                print("No events to delete")
                return False
                
    except Exception as e:
        print(f"Error simulating webhook deletion: {e}")
        return False

def show_webhook_status():
    """Show webhook status for all users"""
    try:
        with app.app_context():
            users_with_webhooks = User.query.filter(
                User.webhook_channel_id.isnot(None)
            ).all()
            
            print(f"Users with webhooks: {len(users_with_webhooks)}")
            
            for user in users_with_webhooks:
                status = "Active"
                if user.webhook_expiration and user.webhook_expiration < datetime.utcnow():
                    status = "Expired"
                
                print(f"\nUser: {user.email}")
                print(f"  Calendar ID: {user.textbot_calendar_id}")
                print(f"  Channel ID: {user.webhook_channel_id}")
                print(f"  Resource ID: {user.webhook_resource_id}")
                print(f"  Expiration: {user.webhook_expiration}")
                print(f"  Status: {status}")
                
                # Count events
                event_count = Event.query.filter_by(user_id=user.id, is_synced=True).count()
                print(f"  Synced Events: {event_count}")
            
            # Show users without webhooks too
            users_without_webhooks = User.query.filter(
                User.webhook_channel_id.is_(None)
            ).all()
            
            print(f"\nUsers without webhooks: {len(users_without_webhooks)}")
            for user in users_without_webhooks:
                event_count = Event.query.filter_by(user_id=user.id, is_synced=True).count()
                print(f"  {user.email} - Calendar: {user.textbot_calendar_id} - Events: {event_count}")
                
    except Exception as e:
        print(f"Error showing webhook status: {e}")

def cleanup_test_data():
    """Remove test data"""
    try:
        with app.app_context():
            # Delete test user and their events
            test_user = User.query.filter_by(email='webhook-test@example.com').first()
            if test_user:
                # Delete user's events first
                Event.query.filter_by(user_id=test_user.id).delete()
                # Delete user
                db.session.delete(test_user)
                db.session.commit()
                print("Cleaned up test data")
            else:
                print("No test data to clean up")
                
    except Exception as e:
        print(f"Error cleaning up test data: {e}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python webhook_admin.py [command]")
        print("Commands:")
        print("  create_test    - Create test user and events")
        print("  status         - Show webhook status")
        print("  simulate       - Simulate event deletion")
        print("  cleanup        - Remove test data")
        return
    
    command = sys.argv[1].lower()
    
    if command == 'create_test':
        user = create_test_user_with_calendar()
        if user:
            create_test_events_for_user(user)
    
    elif command == 'status':
        show_webhook_status()
    
    elif command == 'simulate':
        test_webhook_deletion_simulation()
    
    elif command == 'cleanup':
        cleanup_test_data()
    
    else:
        print(f"Unknown command: {command}")

if __name__ == '__main__':
    main()