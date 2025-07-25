# Calendar AI Chrome Extension - Installation Instructions

## Quick Setup

### 1. Download Extension
- Download the `chrome-extension` folder from your Calendar AI project
- Make sure you have all files: manifest.json, popup.html, popup.js, background.js, content.js, icons/

### 2. Configure Google OAuth
**Important**: You need to configure the Google Client ID for authentication.

In `manifest.json`, replace `YOUR_GOOGLE_CLIENT_ID` with your actual Google OAuth Client ID:
```json
"oauth2": {
  "client_id": "YOUR_ACTUAL_GOOGLE_CLIENT_ID.apps.googleusercontent.com",
  "scopes": [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.app.created"
  ]
}
```

**Note**: This should be the same Client ID used by your Calendar AI web application.

### 3. Install in Chrome
1. Open Chrome and navigate to `chrome://extensions/`
2. Enable "Developer mode" toggle in the top right corner
3. Click "Load unpacked" button
4. Select the `chrome-extension` folder
5. The Calendar AI extension should now appear in your extensions list

### 4. Pin Extension (Optional)
1. Click the puzzle piece icon in Chrome toolbar
2. Find "Calendar AI" and click the pin icon
3. Extension will now be visible in your toolbar

## First Use

### 1. Sign In
1. Click the Calendar AI extension icon
2. Click "Sign in with Google"
3. Complete Google OAuth flow
4. Extension will remember your authentication

### 2. Test Text Processing
1. Go to any webpage with event text (emails, schedules, etc.)
2. Select some text containing event information
3. Click the extension icon
4. Paste text in the input field
5. Click "Extract Events"
6. Events should be processed and synced to your calendar

### 3. Test Screenshot Processing
1. Navigate to a page with visual event information
2. Click the extension icon
3. Click "Take Screenshot" 
4. Extension captures and analyzes the page
5. Extracted events sync to your calendar

## Troubleshooting

### "Authentication Required" Error
- Make sure you've signed in through the extension popup
- Verify your Google Client ID is correctly configured
- Try signing out and signing in again

### "Processing Failed" Error
- Check your internet connection
- Ensure Calendar AI backend is running
- Try with different text/screenshots

### Extension Not Loading
- Make sure all files are present in the extension folder
- Check Chrome developer console for errors
- Verify manifest.json syntax is correct

### No Events Extracted
- Try with more detailed event text
- Ensure text contains dates, times, and event descriptions
- Check Calendar AI dashboard to see if events were created

## Features Overview

### Text Processing
- Paste text in popup interface
- Right-click context menu on selected text
- Keyboard shortcut: Ctrl+Alt+C on selected text

### Screenshot Analysis
- One-click screenshot capture from popup
- AI analyzes visual content for events
- Works on calendars, schedules, flyers, etc.

### Quick Actions
- Link to Calendar AI dashboard
- Email forwarding instructions
- Sign in/out functionality

### Auto-sync
- Events automatically sync to Google Calendar
- Works when you have Google authentication
- Same calendar as web application ("Cal Pilot")

## Advanced Configuration

### Custom Backend URL
If your Calendar AI is hosted elsewhere, update the API base URL in `popup.js`:
```javascript
this.apiBaseUrl = 'https://your-calendar-ai-domain.com';
```

### Additional Permissions
The extension uses these Chrome permissions:
- `activeTab` - Screenshot capture
- `storage` - Authentication persistence  
- `identity` - Google OAuth flow
- `contextMenus` - Right-click integration
- `notifications` - Status notifications
- `scripting` - Text selection detection

## Privacy & Security

- Extension only accesses pages when actively used
- Authentication tokens stored locally in extension
- All API calls use HTTPS encryption
- Same security model as Calendar AI web app
- No data collected or shared with third parties