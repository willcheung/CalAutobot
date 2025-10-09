#!/usr/bin/env python3
"""
Quick script to fetch all Gmail labels and their IDs
"""
import os
import sys
import json
from app.services.gmail_service import GmailService

def get_all_labels():
    """Fetch and display all Gmail labels"""
    try:
        # Initialize Gmail service
        gmail = GmailService()
        service = gmail.get_service()
        
        if not service:
            print("❌ Failed to initialize Gmail service. Check your credentials:")
            print("   - GMAIL_CLIENT_ID")
            print("   - GMAIL_CLIENT_SECRET")
            print("   - GMAIL_REFRESH_TOKEN")
            return
        
        # Fetch all labels
        print("📧 Fetching Gmail labels...\n")
        results = service.users().labels().list(userId='me').execute()
        labels = results.get('labels', [])
        
        if not labels:
            print("No labels found.")
            return
        
        # Display labels
        print(f"✅ Found {len(labels)} labels:\n")
        print(f"{'Label Name':<40} {'Label ID':<40} {'Type':<15}")
        print("-" * 95)
        
        for label in sorted(labels, key=lambda x: x['name']):
            label_name = label['name']
            label_id = label['id']
            label_type = label.get('type', 'user')
            
            print(f"{label_name:<40} {label_id:<40} {label_type:<15}")
        
        # Also save to JSON file
        output_file = 'gmail_labels.json'
        with open(output_file, 'w') as f:
            json.dump(labels, f, indent=2)
        
        print(f"\n💾 Labels saved to: {output_file}")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    get_all_labels()
