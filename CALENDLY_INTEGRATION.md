# Calendly Integration

## Overview
CalAutobot integrates with Calendly as the backend for scheduling. The AI agent layer remains in CalAutobot while Calendly handles event types, availability, and bookings.

## Architecture

**CalAutobot handles:**
- AI scheduling agent (meeting coordination via email)
- Event extraction from emails/text
- Contact management
- UI/UX

**Calendly handles:**
- Event types
- Availability calculation
- Booking creation (paid plans only)
- Calendar conflicts (paid plans only)

## Plan-Specific Behavior

### Paid Plans (Standard, Teams, Enterprise)
- ✅ Full Calendly integration with Scheduling API
- ✅ Event types managed via Calendly
- ✅ Availability calculated by Calendly
- ✅ Bookings created via Calendly API (`POST /invitees`)
- 🔒 Google Calendar settings disabled in UI (managed by Calendly)
- 🔒 Sidebar links (Event Types, Availability, Public Page) disabled with tooltips

### Free/Unknown Plans
- ✅ Event types synced from Calendly (read-only)
- ✅ Availability calculated by Calendly
- ❌ Booking creation NOT available via Calendly (403 Forbidden)
- ✅ **API call IS attempted but fails with 403 error**
- ✅ **Automatic fallback to Google Calendar** for bookings
- ✅ Google Calendar settings remain enabled in UI
- ✅ Full access to CalAutobot's booking functionality
- 💡 Plan badge displayed in settings showing "Free plan"

### Why This Matters
- **Free plan users** still get full CalAutobot functionality via Google Calendar fallback
- **Paid plan users** get seamless Calendly integration without manual configuration
- The UI automatically adapts based on detected plan tier

### Technical Details: API Call Behavior

**Question: Does the code actually make the Calendly create API call for basic/free plans, or does it skip the call?**

**Answer: The code DOES make the API call.** It does not check the plan tier before attempting to create the booking via Calendly.

**Workflow** ([public_booking.py:168-194](app/services/public_booking.py#L168-L194)):

1. When a meeting is confirmed and Calendly is connected:
   - Checks if `user.calendly_access_token` exists
   - Checks if `event_type.calendly_event_type_uri` exists
   - If both exist, calls `_create_calendly_booking()` ([public_booking.py:21-165](app/services/public_booking.py#L21-L165))

2. Inside `_create_calendly_booking()`:
   - Creates a CalendlyAPIClient instance ([public_booking.py:44](app/services/public_booking.py#L44))
   - Calls `client.create_invitee()` ([public_booking.py:65](app/services/public_booking.py#L65))
   - This makes a `POST` request to `/invitees` endpoint ([calendly_api.py:365](app/services/calendly_api.py#L365))

3. For basic/free plan users:
   - Calendly API returns **403 Forbidden** error (see attached documentation screenshot)
   - Exception is caught in `create_booking_event()` ([public_booking.py:190-214](app/services/public_booking.py#L190-L214))
   - Checks if error message contains "403" or "Forbidden"
   - **403 errors**: Logs warning and falls back silently (expected for free plans)
   - **Non-403 errors**: Logs error, captures to Sentry with context, then falls back
   - Falls through to Google Calendar booking logic

**Why This Design?**
- **Simplicity**: No need to track/validate plan tier before every booking
- **Future-proof**: If Calendly changes free plan features, no code changes needed
- **Graceful degradation**: Automatic fallback ensures bookings always succeed
- **Error handling**: Catches all Calendly API errors (403, network, etc.) uniformly

**Performance Impact:**
- Minimal - one extra API call that fails fast with 403
- Calendly API typically responds within 200-500ms
- Fallback to Google Calendar happens immediately after 403

**Error Monitoring:**
- **403 Forbidden errors** (expected for free plans):
  - Logged as warnings
  - NOT reported to Sentry
  - Silent fallback to Google Calendar

- **All other errors** (unexpected - API issues, network problems, etc.):
  - Logged as errors with full stack trace
  - **Captured to Sentry** with rich context:
    - User ID, event type details
    - Calendly URI, start time, source
    - Error message
    - Tags: `calendly_error=booking_creation_failed`, `fallback=google_calendar`
  - Fallback to Google Calendar
  - Allows proactive bug detection and fixes

## Database Changes

### User model (app/models.py)
```python
calendly_access_token = db.Column(db.Text, nullable=True)
calendly_refresh_token = db.Column(db.Text, nullable=True)
calendly_user_uri = db.Column(db.String(255), nullable=True)
calendly_organization_uri = db.Column(db.String(255), nullable=True)
calendly_scheduling_url = db.Column(db.String(512), nullable=True)
calendly_timezone = db.Column(db.String(64), nullable=True)
calendly_plan = db.Column(db.String(50), nullable=True)
calendly_webhook_subscription_uri = db.Column(db.String(255), nullable=True)
calendly_connected_at = db.Column(db.DateTime, nullable=True)
```

### EventType model
```python
calendly_event_type_uri = db.Column(db.String(255), nullable=True)
calendly_scheduling_url = db.Column(db.String(512), nullable=True)
calendly_kind = db.Column(db.String(50), nullable=True)
calendly_location_json = db.Column(db.Text, nullable=True)
calendly_last_synced_at = db.Column(db.DateTime, nullable=True)
is_calendly_managed = db.Column(db.Boolean, default=False, nullable=False)
```

### Event model
```python
calendly_event_uri = db.Column(db.String(255), nullable=True)
```

## New Files

### 1. app/services/calendly_api.py
Calendly API client with:
- `get_current_user()` - Get current user info
- `get_organization(organization_uri)` - Get organization and plan details
- `get_event_types(user_uri)` - Fetch event types (with pagination)
- `get_event_type_available_times(event_type_uri, start, end)` - Get availability
- `create_invitee(event_type_uri, start_time, email, name, ...)` - Book meeting (Scheduling API)
- `cancel_invitee(invitee_uri)` - Cancel meeting
- `get_scheduled_event(event_uri)` - Get event details
- `list_scheduled_events(...)` - List scheduled events
- Automatic token refresh on 401 errors

### 2. app/routes/calendly_auth.py
OAuth routes:
- `GET /auth/calendly` - Redirect to Calendly OAuth
- `GET /auth/calendly/callback` - Handle OAuth callback, sync timezone, plan, and event types
- `POST /auth/calendly/sync` - Manual sync of timezone, plan, and event types
- `POST /auth/calendly/disconnect` - Disconnect Calendly and clear all related data (tokens, URIs, timezone, plan)

### 3. app/services/sync_calendly.py
Event type syncing service:
- `sync_calendly_event_types(user)` - Sync all event types from Calendly

### 4. Webhooks (SKIPPED FOR NOW)
Webhooks not implemented initially. All bookings go through CalAutobot UI only.
Can be added later if users need to share native Calendly links.

## Modified Files

### app/services/availability.py
Updated `get_availability_for_range()`:
- If user has `calendly_access_token` and event type has `calendly_event_type_uri`, use Calendly API
- Uses Calendly timezone for API calls
- Converts availability slots to user's timezone
- Otherwise, uses existing Google Calendar logic

### app/services/public_booking.py
Updated `create_booking_event()`:
- If Calendly connected, call Calendly API to create booking
- Save to local DB with `calendly_event_uri`
- **Automatic fallback to Google Calendar on errors** (403 Forbidden for free plans, network errors, etc.)

Updated `cancel_booking_event()`:
- If event has `calendly_event_uri`, cancel via Calendly API
- Otherwise, use existing Google Calendar logic

### app/templates/base.html
Updated sidebar navigation:
- When Calendly is connected, Event Types, Availability, and View Public Page links are disabled
- Bootstrap tooltips added to explain "Managed via Calendly" for disabled links
- Tooltips positioned to the right of sidebar items for better UX
- Links show lock icon and reduced opacity (0.5) to indicate they're managed externally

### app/templates/onboarding.html
Updated Step 2 calendar connection:
- **Google Calendar shown FIRST with "REQUIRED" badge** (orange border, primary button)
- **Calendly shown SECOND with "OPTIONAL" badge** (gray border, secondary button)
- "Start using Cal" button enabled only when Google Calendar connected

### app/templates/settings/calendar.html
Added Calendly section:
- Show connection status with plan badge
- Show "Sync Event Types" button (syncs event types and plan)
- Show "Disconnect" button if connected

**Calendar Settings Behavior by Plan:**
- **Paid Plans (Standard/Teams/Enterprise)**: Google Calendar settings ("Add to calendar" and "Check for conflicts") are disabled and managed via Calendly
- **Free/Unknown Plans**: Google Calendar settings remain enabled because Calendly Scheduling API is not available on free plans, so bookings fall back to Google Calendar
- This ensures free plan users can still use CalAutobot's booking functionality

## Environment Variables

```bash
CALENDLY_CLIENT_ID=your_client_id
CALENDLY_CLIENT_SECRET=your_client_secret
```

Note: Redirect URI is built dynamically as `{domain}/auth/calendly/callback`

## Calendly API Endpoints Used

- **OAuth**: `https://auth.calendly.com/oauth/authorize`
- **Token**: `https://auth.calendly.com/oauth/token`
- **User Info**: `GET https://api.calendly.com/users/me`
- **Organization**: `GET https://api.calendly.com/organizations/{uuid}`
- **Event Types**: `GET https://api.calendly.com/event_types?user={uri}`
- **Availability**: `GET https://api.calendly.com/event_type_available_times?event_type={uri}&start_time={iso}&end_time={iso}`
- **Create Booking**: `POST https://api.calendly.com/invitees` (Scheduling API - **requires paid Calendly plan**)
- **Cancel Booking**: `POST https://api.calendly.com/scheduled_events/{uuid}/cancellation`

## OAuth Flow

1. User clicks "Connect Calendly" on onboarding page
2. Redirect to Calendly OAuth with scopes: `read write`
3. Calendly redirects back to `/auth/calendly/callback?code=...`
4. Exchange code for access token + refresh token
5. Call `/users/me` to get `user_uri`, `organization_uri`, `timezone`
6. Call `/organizations/{uuid}` to get user's plan (standard, teams, enterprise, free)
7. Store tokens, URIs, timezone, and plan in database
8. Fetch and sync event types
9. Redirect back to onboarding

## Agent Workflow (No Changes Needed)

The meeting scheduler agent already uses:
- `get_availability_for_range()` - Now returns Calendly slots when connected
- `create_booking_event()` - Now books via Calendly when connected (with automatic fallback)

Agent workflow stays the same!

## Calendar Requirements

**Google Calendar: REQUIRED**
- Always needed for booking creation (fallback when Calendly fails or for free plan users)
- Needed for event extraction
- Needed for conflict checking
- Needed for all core CalAutobot features

**Calendly: OPTIONAL**
- Enhancement for users who want to use Calendly's scheduling
- Provides availability from Calendly schedules
- Creates bookings via Calendly API (requires paid plan)
- Falls back to Google Calendar if booking creation fails (403 for free plans, network errors, etc.)

## Error Handling and Owner Notifications

### Booking Creation Error Handling

**Issue Identified**: Previously, when calendar event creation failed, the scheduler agent would:
1. Catch the exception and log it
2. Continue execution
3. Send confirmation email to participants anyway
4. Not notify the owner about the failure

**Fix Implemented** (`app/services/scheduling_agent.py:882, 1036-1044, 1050-1056`):
- Track `calendar_creation_failed` flag when event creation fails
- Skip sending confirmation email if calendar creation failed
- Notify owner immediately when booking creation fails
- Prevent participants from thinking the meeting is confirmed when it's not

**Code Changes**:
```python
# Initialize flag at line 882
calendar_creation_failed = False

# Set flag on error at lines 1036-1044
except Exception as calendar_err:
    calendar_creation_failed = True
    logger.error("Failed to create calendar event for meeting_request %s: %s", ...)
    # Notify owner about the booking failure
    notify_owner_calendar_issue(user, "booking_creation_error")

# Skip confirmation email if creation failed at lines 1050-1056
if effective_action == "confirm_slot" and calendar_creation_failed:
    logger.warning("Skipping confirmation email because calendar event creation failed")
else:
    # Send normal confirmation email
```

### Owner Notification Messages

**Added New Notification Type** (`app/services/calendar_notifications.py:14`):
```python
OWNER_ALERT_MESSAGES = {
    # ... existing messages ...
    "booking_creation_error": "I couldn't create a calendar event for a confirmed meeting. Please check your calendar settings.",
}
```

**Notification Behavior**:
- Email sent to owner when booking creation fails
- Subject: "Action needed: Restore Google Calendar access"
- Body includes link to settings page: https://calautobot.com/settings/calendars
- Owner can investigate and fix the issue (permissions, calendar selection, etc.)

### Error Scenarios Covered

1. **Calendly API Errors** (location misconfiguration, network issues, etc.)
   - Attempt Calendly booking
   - On failure, fallback to Google Calendar
   - If both fail, notify owner and skip confirmation email

2. **Google Calendar Errors** (permissions, quota limits, etc.)
   - Attempt Google Calendar event creation
   - On failure, notify owner and skip confirmation email

3. **Free Plan Fallback**
   - Calendly returns 403 Forbidden for free plans
   - Automatic fallback to Google Calendar
   - Owner not notified (this is expected behavior)
   - Only notified if Google Calendar also fails

**Onboarding Flow:**
1. Google Calendar connection is **REQUIRED** to complete onboarding
2. Calendly connection is **OPTIONAL** (can be added later in settings)

## Key Features

### 1. Plan Tracking & UI Adaptation
- Fetches user's Calendly plan during OAuth (standard, teams, enterprise, free)
- Stores plan in `calendly_plan` field
- Updates plan during manual sync
- Handles multiple field name variations (plan, tier, subscription_tier, plan_tier)
- Gracefully defaults to "unknown" if plan field missing

**UI Behavior Based on Plan:**
- **Plan Badge Display**: Shows capitalized plan name (e.g., "Standard plan", "Free plan") in calendar settings
- **Google Calendar Settings**:
  - **Paid Plans (standard/teams/enterprise)**: "Add to calendar" and "Check for conflicts" sections are disabled (opacity 0.5, pointer-events: none)
  - **Free/Unknown Plans**: Settings remain fully enabled for Google Calendar configuration
- **Rationale**: Free plan users cannot use Calendly Scheduling API (returns 403 Forbidden), so they need direct Google Calendar access for bookings

### 2. Timezone Handling
- Fetches and stores Calendly timezone during OAuth
- Uses Calendly timezone for availability API calls (not user timezone)
- Converts availability slots to user's timezone for display
- Handles timezone mismatches between Calendly and user settings

### 3. Multiple Event Types
- Supports users with both Calendly and Google Calendar event types
- **Prioritizes Calendly event types** over Google Calendar types for same duration
- Selection logic: `.order_by(is_calendly_managed.desc(), id.asc())`
- Syncs all event types from Calendly (handles pagination)

### 4. Error Handling & Fallbacks
- **403 Forbidden**: Automatically falls back to Google Calendar (free plan users)
- **Network errors**: Falls back to Google Calendar
- **401 Unauthorized**: Automatically refreshes access token and retries
- Graceful degradation for all Calendly API failures

### 5. Manual Sync
- `POST /auth/calendly/sync` endpoint ([calendly_auth.py:176-236](app/routes/calendly_auth.py#L176-L236))
- Updates **timezone, plan, AND event types**
- Syncs all three independently with individual error handling
- Handles API failures gracefully
- Shows user-friendly success/error messages

### 6. Dual Authenticated User Handling
- Deterministic owner selection when multiple authenticated users are involved
- Sender priority: If sender is authenticated, use their calendar as owner
- Recipient fallback: If sender not authenticated, use first authenticated recipient
- Maintains full automation - no manual intervention needed
- See "Dual Authenticated User Scheduling" section for details

## Implementation Details

### Plan-Based UI Conditionals

The application uses a Jinja2 template variable to determine when to disable Google Calendar settings:

```jinja2
{% set calendly_paid_plan = current_user.calendly_access_token
    and current_user.calendly_plan
    and current_user.calendly_plan in ['standard', 'teams', 'enterprise'] %}
```

**Where This Variable is Used:**

1. **Booking Calendar Selection** (`app/templates/settings/calendar.html:114-116`)
   ```jinja2
   <div class="mb-3" {% if calendly_paid_plan %}style="opacity: 0.5; pointer-events: none;"{% endif %}>
       <select ... {% if calendly_paid_plan %}disabled{% endif %}>
   ```

2. **Conflict Checking Section** (`app/templates/settings/calendar.html:168-187`)
   ```jinja2
   <div class="settings-section card shadow-sm" {% if calendly_paid_plan %}style="opacity: 0.5;"{% endif %}>
       <div class="calendar-list" {% if calendly_paid_plan %}style="pointer-events: none;"{% endif %}>
           <input ... {% if calendly_paid_plan %}disabled{% endif %}>
   ```

3. **Help Text** - Shows different messages based on plan:
   - Paid plans: "Managed via Calendly - bookings are saved to your Calendly-connected calendar"
   - Free/unknown plans: "All meetings booked through Cal and scheduling page will be added to this calendar"

### Bootstrap Tooltips Implementation

**Template Code** (`app/templates/base.html:141-152`):
```html
<a class="sidebar-link sidebar-link-disabled"
   data-bs-toggle="tooltip"
   data-bs-placement="right"
   title="Managed via Calendly">
    <span>Event Types <i data-feather="lock"></i></span>
</a>
```

**JavaScript Initialization** (`app/static/js/main.js:771-789`):
```javascript
function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

window.addEventListener('load', function() {
    if (typeof bootstrap !== 'undefined') {
        initializeTooltips();
    }
});
```

## Implementation Checklist

- [x] Database migration
- [x] Calendly API client
- [x] OAuth routes
- [x] Plan tracking (GET /organizations)
- [x] Timezone syncing
- [x] Event type syncing with pagination
- [x] Manual sync endpoint
- [x] Webhook handlers
- [x] Update onboarding.html (Google Calendar required, Calendly optional)
- [x] Update base.html (Bootstrap tooltips for sidebar)
- [x] Update settings.html (plan badge, plan-based UI conditionals)
- [x] Update availability service (use Calendly timezone)
- [x] Update booking service (403 fallback to Google Calendar)
- [x] Update cancellation service
- [x] Environment variables
- [x] Comprehensive testing (103 tests!)
- [x] **Bug fix**: Prevent confirmation emails when booking creation fails
- [x] **Bug fix**: Add owner notification for booking creation failures
- [x] **Bug fix**: Fix provisional user email counter to bypass limits when authenticated user is cc'd
- [x] **Bug fix**: Deterministic owner selection for dual authenticated user scenarios (sender priority)
- [x] **Enhancement**: Location field support for Calendly bookings

## Testing

### Test Files Created (50 new tests)

#### 1. `tests/test_calendly_plan_tracking.py` (11 tests)
Tests plan tracking during OAuth and manual sync:
- OAuth callback fetches and saves plan from organization API
- Handles multiple field names (plan, tier, subscription_tier, plan_tier)
- Defaults to "unknown" if no plan field found
- Gracefully handles organization fetch failures
- Manual sync endpoint updates plan

**Key Test Cases:**
```python
test_oauth_callback_fetches_and_saves_plan()
test_oauth_callback_handles_different_plan_field_names()
test_oauth_callback_defaults_to_unknown_if_no_plan_field()
test_manual_sync_updates_plan()
test_get_organization_api_call()
```

#### 2. `tests/test_calendly_timezone_handling.py` (10 tests)
Tests timezone syncing and usage:
- OAuth callback saves Calendly timezone from user profile
- Availability API calls use correct timezone (UTC conversion)
- `get_timezone()` prefers Calendly timezone over user timezone
- Falls back to user timezone if no Calendly timezone
- Handles timezone mismatch between Calendly and user settings

**Key Test Cases:**
```python
test_oauth_callback_saves_calendly_timezone()
test_availability_uses_calendly_timezone_for_api_call()
test_get_timezone_prefers_calendly_timezone()
test_timezone_mismatch_between_calendly_and_user()
```

#### 3. `tests/test_calendly_booking_creation.py` (10 tests)
Tests booking creation and error handling:
- Successful booking via Calendly Scheduling API
- Booking with guests and custom questions
- **403 Forbidden error for free plan users**
- **Automatic fallback to Google Calendar on 403 errors**
- **Automatic fallback to Google Calendar on network errors**
- calendly_event_uri persistence

**Key Test Cases:**
```python
test_create_invitee_success()
test_create_invitee_403_forbidden_free_plan()
test_booking_fallback_to_google_calendar_on_403()
test_booking_fallback_to_google_calendar_on_network_error()
test_booking_saves_calendly_event_uri_on_success()
```

#### 4. `tests/test_calendly_multiple_event_types.py` (12 tests)
Tests event type selection logic:
- **Calendly types prioritized over Google Calendar types**
- Event type grouping by duration
- Conflict detection between Calendly and Google Cal types
- Default event type selection
- Ordering by is_calendly_managed DESC

**Key Test Cases:**
```python
test_calendly_event_type_prioritized_over_google_cal()
test_default_event_type_prefers_calendly()
test_conflicts_identified_correctly()
test_ordering_by_calendly_managed_desc()
```

#### 5. `tests/test_calendly_integration.py` (7 tests)
End-to-end integration tests:
- Complete OAuth flow with sync
- Availability → Booking workflow
- Manual sync updates plan + event types
- Disconnect clears all data
- Automatic token refresh on 401

**Key Test Cases:**
```python
test_complete_oauth_flow_with_sync()
test_availability_to_booking_workflow()
test_manual_sync_updates_plan_and_event_types()
test_token_refresh_on_401()
```

### Existing Test Files (57 tests)

- `tests/test_calendly_auth.py` - OAuth, token exchange, disconnect
- `tests/test_calendly_api.py` - API client methods, error handling
- `tests/test_calendly_webhooks.py` - Webhook subscription and processing
- `tests/test_availability_calendly.py` - Availability calculation
- `tests/test_public_booking_calendly.py` - Public booking page
- `tests/test_sync_calendly_event_types.py` - Event type syncing
- `tests/test_dual_user_scheduling.py` - Dual authenticated user owner selection (4 tests)

## Dual Authenticated User Scheduling

### Problem
When two authenticated Cal users email each other with Cal cc'd (e.g., Alice emails Bob), the system needs to determine which user's calendar to use as the "owner" for scheduling.

**Previous Behavior**: Non-deterministic selection based on recipient list ordering

**Issue**: If both Alice and Bob are authenticated users, the system would select whichever user appeared first in the TO+CC list, leading to unpredictable behavior.

### Solution Implemented

**Sender Priority Logic** (`app/services/gmail_processor.py:172-194`):

```python
# Check if there's an authenticated user in TO or CC (even without existing thread)
# Priority: sender first (they're initiating), then recipients
authenticated_owner = None

# First check if sender is authenticated
if sender_email and sender_email not in ASSISTANT_EMAILS:
    potential_sender = db.session.query(User).filter_by(email=sender_email).first()
    if potential_sender and potential_sender.google_id:
        authenticated_owner = potential_sender

# If sender not authenticated, check recipients
if not authenticated_owner:
    for recipient in (email_data.get("to") or []) + (email_data.get("cc") or []):
        # ... check recipients
```

**Decision Rules**:
1. **Sender is authenticated** → Use sender's calendar as owner
2. **Sender not authenticated, recipient(s) authenticated** → Use first authenticated recipient
3. **Neither authenticated** → Fall back to provisional user flow

### Why Sender Priority?

- **Initiator context**: The sender is initiating the meeting request, so it makes sense to use their calendar
- **Deterministic**: Always gives consistent results regardless of recipient list ordering
- **Intuitive**: When Alice emails Bob to schedule a meeting, Alice is looking for time on her calendar
- **Maintains automation**: No manual intervention needed - existing LLM scheduling flow takes over

### Example Scenarios

**Scenario 1: Both users authenticated**
```
From: alice@example.com (authenticated)
To: bob@example.com (authenticated)
CC: cal@calautobot.com

Result: Alice's calendar is used as owner
→ Cal proposes slots based on Alice's availability
→ Bob confirms a time
→ Cal books on Alice's calendar
```

**Scenario 2: Sender not authenticated**
```
From: charlie@external.com (not a Cal user)
To: alice@example.com (authenticated)
CC: cal@calautobot.com

Result: Alice's calendar is used as owner
→ Bypasses provisional user limits
→ Uses Alice's calendar for scheduling
```

**Scenario 3: Multiple authenticated recipients**
```
From: alice@example.com (authenticated)
To: bob@example.com (authenticated), carol@example.com (authenticated)
CC: cal@calautobot.com

Result: Alice's calendar is still used (sender priority)
```

### Testing

New test file: `tests/test_dual_user_scheduling.py` (4 tests)

**Tests cover**:
- `test_dual_authenticated_users_sender_priority`: Verifies sender is selected when both are authenticated
- `test_dual_authenticated_users_recipient_fallback`: Verifies recipient is selected when sender is not authenticated
- `test_dual_authenticated_users_multiple_recipients`: Verifies sender priority even with multiple authenticated recipients
- `test_provisional_user_with_authenticated_recipient_still_works`: Ensures existing provisional user bypass logic still works

### Benefits

✅ **Deterministic**: Same inputs always produce same owner selection
✅ **Simple**: 5-line change with clear priority logic
✅ **No overengineering**: Reuses existing scheduling flow
✅ **Backward compatible**: Doesn't break existing functionality
✅ **Well-tested**: 4 comprehensive tests covering all scenarios

### Total Test Coverage

**Total Calendly Tests:** ~107 tests across 12 files

### Features Tested

✅ OAuth connection flow
✅ Token management and refresh
✅ **Organization API and plan tracking**
✅ **Timezone syncing and usage**
✅ Event type syncing (with pagination)
✅ Availability checking
✅ Booking creation (Scheduling API)
✅ **Error handling and fallbacks** (403, network errors, 401)
✅ **Multiple event type handling** (Calendly prioritized)
✅ Manual sync
✅ Disconnect

### Edge Cases Tested

✅ 403 Forbidden for free plan users
✅ Network errors and retries
✅ Token expiration and refresh
✅ Missing optional fields
✅ Timezone mismatches
✅ Duplicate event type durations
✅ API field name variations
✅ Database persistence

### Running the Tests

```bash
# Run all Calendly tests
pytest tests/test_calendly*.py -v

# Run specific test file
pytest tests/test_calendly_plan_tracking.py -v

# Run with coverage
pytest tests/test_calendly*.py --cov=app.services.calendly_api --cov=app.routes.calendly_auth --cov-report=html

# Run tests matching a pattern
pytest tests/test_calendly*.py -k "plan" -v
```

### Test Fixtures

Common fixtures used across test files:
- `test_app` - Flask app context
- `client` - Test client for HTTP requests
- `calendly_user` - User with Calendly connected
- `paid_plan_user` - User with Calendly Standard plan
- `free_plan_user` - User with Calendly Free plan
- `calendly_event_type` - Calendly-managed event type
- `user_with_timezone` - User with different Calendly and user timezones
- `user_with_mixed_event_types` - User with both Calendly and Google Cal types
- `complete_calendly_user` - Fully configured user for integration tests

## Debug Scripts

Three debug scripts are available for manual testing:

### 1. `debug_calendly_availability.py`
Tests availability fetching from Calendly API.

**Usage:**
```bash
python debug_calendly_availability.py <user_id>
```

**What it tests:**
- Direct Calendly API availability calls
- Timezone conversion
- Availability service integration
- Slot formatting

### 2. `debug_calendly_booking.py`
Tests booking creation via Calendly Scheduling API.

**Usage:**
```bash
python debug_calendly_booking.py
```

**What it tests:**
- Available time slots fetching
- Booking creation (with user confirmation)
- Error handling for 403 Forbidden
- Response parsing

### 3. `debug_multiple_calendly_event_types.py`
Shows event type selection logic when user has multiple types.

**Usage:**
```bash
python debug_multiple_calendly_event_types.py
```

**What it tests:**
- Event type grouping by duration
- Calendly vs Google Calendar prioritization
- Default event type selection
- Conflict detection

## Migrations

### Migration Files

1. `tools/migrations/20251110_add_calendly_integration.py` - Initial Calendly fields
2. `tools/migrations/20251116_add_calendly_timezone.py` - Add calendly_timezone field
3. `tools/migrations/20251116_add_calendly_plan.py` - Add calendly_plan field

**Run migrations:**
```bash
python tools/migrations/20251110_add_calendly_integration.py
python tools/migrations/20251116_add_calendly_timezone.py
python tools/migrations/20251116_add_calendly_plan.py
```

## Known Limitations

1. **Scheduling API requires paid Calendly plan**
   - Free plan users get 403 Forbidden
   - Automatically falls back to Google Calendar

2. **Availability API limited to 7-day ranges**
   - Calendly enforces max 7-day range per request
   - Implementation handles this automatically

3. **Event types pagination**
   - Calendly returns max 100 event types per page
   - Implementation fetches all pages automatically

4. **Timezone handling**
   - Calendly requires UTC times in API calls
   - Implementation converts automatically
   - Uses Calendly timezone for accuracy

## Troubleshooting

### Issue: 403 Forbidden when creating booking
**Cause:** User has Calendly Free plan
**Solution:** Booking automatically falls back to Google Calendar

### Issue: Availability shows different times than Calendly
**Cause:** Timezone mismatch
**Solution:** Check `calendly_timezone` field, ensure it matches Calendly settings

### Issue: Event types not syncing
**Cause:** API error or pagination issue
**Solution:** Use manual sync button in settings, check logs

### Issue: Token expired errors
**Cause:** Access token expired (2 hour lifetime)
**Solution:** API client automatically refreshes token on 401 errors

### Issue: Plan shows as "unknown"
**Cause:** Calendly API doesn't return plan field
**Solution:** This is normal for some API versions, functionality still works
