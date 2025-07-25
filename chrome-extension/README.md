# Calendar AI Chrome Extension

AI-powered Chrome extension that extracts calendar events from text and screenshots using GPT-4o Vision.

## Features

- **Text Processing**: Paste or select text to extract calendar events
- **Screenshot Analysis**: Capture and analyze screenshots for event information
- **Google Calendar Sync**: Automatically sync extracted events to your calendar
- **Context Menu**: Right-click selected text to extract events
- **Keyboard Shortcut**: Press Ctrl+Alt+C to process selected text
- **Dashboard Integration**: Quick access to the main Calendar AI dashboard

## Installation

1. **Download Extension Files**: Clone or download the `chrome-extension` folder
2. **Configure Google OAuth**: 
   - Replace `YOUR_GOOGLE_CLIENT_ID` in `manifest.json` with your actual Google Client ID
   - Ensure the Client ID matches the one used by your Calendar AI backend
3. **Load in Chrome**:
   - Open Chrome and go to `chrome://extensions/`
   - Enable "Developer mode" in the top right
   - Click "Load unpacked" and select the `chrome-extension` folder
4. **Sign In**: Click the extension icon and sign in with your Google account

## Usage

### Text Extraction
1. Click the Calendar AI extension icon
2. Paste text into the text area or select text on any webpage
3. Click "Extract Events" to process the text
4. Events are automatically synced to your Google Calendar

### Screenshot Analysis
1. Navigate to a page with calendar information (schedules, events, etc.)
2. Click the extension icon
3. Click "Take Screenshot" to capture and analyze the current page
4. Extracted events are automatically synced to your calendar

### Quick Actions
- **Forward Email**: Shows instructions for email forwarding to Calendar AI
- **Dashboard**: Opens the Calendar AI web dashboard
- **Context Menu**: Right-click any selected text and choose "Extract Calendar Events"
- **Keyboard Shortcut**: Select text and press Ctrl+Alt+C for quick processing

## Architecture

The extension reuses the existing Calendar AI backend infrastructure:

- **API Endpoint**: Uses `/webhook/mailgun` for processing (same as email webhook)
- **Authentication**: Leverages existing Google OAuth flow
- **Processing**: Same AI extraction and validation pipeline
- **Storage**: Events stored in same database with user association
- **Calendar Sync**: Uses existing Google Calendar integration

## Code Reuse

95% of backend code is reused:
- `event_extractor.py` - AI processing unchanged
- `google_calendar.py` - Calendar integration unchanged  
- `helpers/event_processing.py` - Validation pipeline unchanged
- `models.py` - Database models unchanged
- `attachment_processor.py` - Screenshot processing unchanged

## Configuration

### Required Environment Variables
- `GOOGLE_OAUTH_CLIENT_ID` - Must match extension manifest
- `GOOGLE_OAUTH_CLIENT_SECRET` - Backend OAuth secret
- `OPENAI_API_KEY` - For GPT-4o processing
- `DATABASE_URL` - PostgreSQL database

### Permissions
The extension requires:
- `activeTab` - Screenshot capture
- `storage` - Authentication persistence  
- `identity` - Google OAuth flow
- `https://calautobot.com/*` - API access

## Development

### File Structure
```
chrome-extension/
├── manifest.json          # Extension configuration
├── popup.html             # Main popup interface  
├── popup.js               # Popup functionality
├── background.js          # Service worker
├── content.js             # Page interaction
├── icons/                 # Extension icons
└── README.md              # Documentation
```

### Key Components
- **Popup**: Main user interface for text input and screenshot capture
- **Background**: Handles authentication, notifications, and API communication
- **Content Script**: Page interaction, text selection, keyboard shortcuts
- **Context Menu**: Right-click integration for quick text processing

## Security

- Uses Chrome's identity API for secure OAuth flow
- Tokens stored in extension's local storage
- All API calls use HTTPS
- Same security model as Calendar AI web application

## Future Enhancements

- Visual event highlighting on pages
- Bulk screenshot processing  
- Email composition integration
- Calendar widget in popup
- Advanced text selection tools