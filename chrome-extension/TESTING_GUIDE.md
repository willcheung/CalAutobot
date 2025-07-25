# Chrome Extension Testing Guide

## Quick Installation & Testing

### Step 1: Install the Extension
1. Open Chrome and go to `chrome://extensions/`
2. Enable "Developer mode" toggle (top right)
3. Click "Load unpacked"
4. Select the entire `chrome-extension` folder from your project
5. Extension should appear with Calendar AI icon

### Step 2: Pin Extension (Recommended)
1. Click the puzzle piece icon in Chrome toolbar
2. Find "Calendar AI" and click the pin icon
3. Extension will be visible in your toolbar

### Step 3: Test Authentication
1. Click the Calendar AI extension icon
2. You should see "Not signed in" status
3. Click "Sign in with Google"
4. Complete Google OAuth (same as web app)
5. Status should change to "Signed in as [your email]"

## Test Scenarios

### Test 1: Basic Text Processing
**Objective**: Extract events from pasted text

1. Click extension icon
2. Paste this sample text in the text area:
```
Team meeting tomorrow at 2 PM in Conference Room A
Quarterly review on Friday January 26th at 10:00 AM
Product demo next Tuesday at 3:30 PM
```
3. Click "Extract Events"
4. Check for success message showing events extracted
5. Go to your Google Calendar to verify events were created

### Test 2: Screenshot Analysis
**Objective**: Extract events from visual content

1. Navigate to any website with event information (calendars, schedules, etc.)
2. Click extension icon
3. Click "Take Screenshot"
4. Extension captures current page and processes it
5. Check for success message and new calendar events

### Test 3: Context Menu Integration
**Objective**: Extract events from selected text

1. Go to any webpage with event text
2. Select text containing event information
3. Right-click and choose "Extract Calendar Events"
4. Extension processes selected text automatically
5. Check for notification and calendar events

### Test 4: Keyboard Shortcut
**Objective**: Quick processing with hotkey

1. Go to any webpage
2. Select text with event information
3. Press `Ctrl+Alt+C`
4. Extension processes selected text
5. Look for toast notification showing results

### Test 5: Dashboard Integration
**Objective**: Verify links work properly

1. Click extension icon
2. Click "Open Dashboard"
3. Should open Calendar AI web app in new tab
4. Click "Forward Email to Calendar AI"
5. Should show email forwarding instructions

## Expected Results

### Successful Text Processing
- Green success message: "Success! Extracted X events, Y synced to calendar"
- New events appear in your Google Calendar
- Events created in "Cal Pilot" calendar

### Successful Screenshot Processing
- Processing message followed by success notification
- Events extracted from visual content
- Calendar events created automatically

### Authentication Success
- Status changes to "Signed in as [email]"
- Text and screenshot buttons become enabled
- Same authentication as web app

## Troubleshooting

### "Authentication Required" Error
- Sign out and sign in again through extension
- Check that popup shows correct email
- Verify you can access Calendar AI web app

### "Processing Failed" Error
- Try with different/simpler text
- Check internet connection
- Verify Calendar AI backend is running at calautobot.com

### Extension Won't Load
- Check all files are present in chrome-extension folder
- Verify manifest.json syntax is correct
- Look at Chrome extension console for errors

### No Events Created
- Check Calendar AI dashboard to see if events were extracted
- Verify text contains clear date/time information
- Try with more detailed event descriptions

## Development Testing

### Console Debugging
1. Right-click extension icon → "Inspect popup"
2. Check console for JavaScript errors
3. Look for API response messages

### Background Script Debugging
1. Go to `chrome://extensions/`
2. Click "Service worker" under Calendar AI
3. Check console for background script logs

### Network Debugging
1. Open DevTools → Network tab
2. Trigger extension actions
3. Look for API calls to calautobot.com
4. Check request/response details

## API Testing

The extension uses these endpoints:
- `POST /api/extension/process` - Main processing endpoint
- `POST /api/extension/auth/verify` - Authentication verification

You can test these directly if needed:
```bash
curl -X POST https://calautobot.com/api/extension/process \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"text": "Meeting tomorrow at 2 PM", "user_email": "test@example.com"}'
```

## Success Criteria

✅ Extension installs without errors
✅ Authentication works (same as web app)
✅ Text processing extracts events correctly
✅ Screenshot analysis works on visual content
✅ Context menu integration functions
✅ Keyboard shortcut responds properly
✅ Dashboard links open correctly
✅ Events sync to Google Calendar
✅ Same functionality as web application