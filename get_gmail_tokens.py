#!/usr/bin/env python3
"""
Simple script to get Gmail API refresh and access tokens.
Run this once to get the tokens you need for your environment variables.
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

# Gmail readonly scope
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def get_tokens():
    """Get Gmail API tokens using OAuth flow"""
    
    # You'll need to create this file with your credentials
    credentials_file = 'credentials.json'
    
    try:
        # Create the flow
        flow = InstalledAppFlow.from_client_secrets_file(
            credentials_file, 
            SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'
        )
        
        # Run the OAuth flow
        print("Opening browser for OAuth authorization...")
        creds = flow.run_local_server(port=0)
        
        # Print the tokens
        print("\n" + "="*50)
        print("SUCCESS! Here are your tokens:")
        print("="*50)
        print(f"ACCESS_TOKEN: {creds.token}")
        print(f"REFRESH_TOKEN: {creds.refresh_token}")
        print("="*50)
        
        print("\nAdd these to your Replit environment variables:")
        print(f"GMAIL_ACCESS_TOKEN={creds.token}")
        print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
        
        return creds
        
    except FileNotFoundError:
        print(f"Error: {credentials_file} not found!")
        print("\nTo create credentials.json:")
        print("1. Go to Google Cloud Console")
        print("2. APIs & Services → Credentials")
        print("3. Create OAuth 2.0 Client ID (Desktop application)")
        print("4. Download the JSON file and save as 'credentials.json'")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    get_tokens()