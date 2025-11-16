# Calendly Integration Plan

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
- Booking creation
- Calendar conflicts

## Database Changes

### User model (app/models.py)
```python
calendly_access_token = db.Column(db.Text, nullable=True)
calendly_refresh_token = db.Column(db.Text, nullable=True)
calendly_user_uri = db.Column(db.String(255), nullable=True)
calendly_organization_uri = db.Column(db.String(255), nullable=True)
calendly_scheduling_url = db.Column(db.String(512), nullable=True)
calendly_connected_at = db.Column(db.DateTime, nullable=True)
```

### EventType model
```python
calendly_event_type_uri = db.Column(db.String(255), nullable=True)
```

### Event model
```python
calendly_event_uri = db.Column(db.String(255), nullable=True)
```

## New Files

### 1. app/services/calendly_api.py
Calendly API client with:
- `get_available_times(event_type_uri, start, end)` - Get availability
- `create_invitee(event_type_uri, start_time, email, name)` - Book meeting
- `cancel_invitee(invitee_uri)` - Cancel meeting
- `get_event_types(user_uri)` - Fetch event types
- Token refresh logic

### 2. app/routes/calendly_auth.py
OAuth routes:
- `GET /auth/calendly` - Redirect to Calendly OAuth
- `GET /auth/calendly/callback` - Handle OAuth callback
- `POST /auth/calendly/disconnect` - Disconnect Calendly

### 3. Webhooks (SKIPPED FOR NOW)
Webhooks not implemented initially. All bookings go through CalAutobot UI only.
Can be added later if users need to share native Calendly links.

## Modified Files

### app/services/availability.py
Update `_collect_google_busy_slots()` or `get_availability_for_range()`:
- If user has `calendly_access_token` and event type has `calendly_event_type_uri`, use Calendly API
- Otherwise, use existing Google Calendar logic

### app/services/public_booking.py
Update `create_booking_event()`:
- If Calendly connected, call Calendly API to create booking
- Save to local DB with `calendly_event_uri`
- Otherwise, use existing Google Calendar logic

Update `cancel_booking_event()`:
- If event has `calendly_event_uri`, cancel via Calendly API
- Otherwise, use existing Google Calendar logic

### app/templates/onboarding.html
Add Calendly connection to Step 2 (alongside Google Calendar):
- Show Calendly logo and "Connect" button if not connected
- Show checkmark if connected

### app/templates/settings.html
Add Calendly section:
- Show connection status
- Show "Disconnect" button if connected
- No "Connect" button (only in onboarding)

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
- **Event Types**: `GET https://api.calendly.com/event_types?user={uri}`
- **Availability**: `GET https://api.calendly.com/event_type_available_times?event_type={uri}&start_time={iso}&end_time={iso}`
- **Create Booking**: `POST https://api.calendly.com/invitees` (Scheduling API - requires paid Calendly plan)
- **Cancel Booking**: `POST https://api.calendly.com/scheduled_events/{uuid}/cancellation`

## OAuth Flow

1. User clicks "Connect Calendly" on onboarding page
2. Redirect to Calendly OAuth with scopes: `read write`
3. Calendly redirects back to `/auth/calendly/callback?code=...`
4. Exchange code for access token + refresh token
5. Call `/users/me` to get `user_uri`
6. Store tokens and `user_uri` in database
7. Fetch and sync event types
8. Redirect back to onboarding

## Agent Workflow (No Changes Needed)

The meeting scheduler agent already uses:
- `get_availability_for_range()` - Now returns Calendly slots when connected
- `create_booking_event()` - Now books via Calendly when connected

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
- Falls back to Google Calendar if booking creation fails

**Onboarding Flow:**
1. Google Calendar connection is REQUIRED to complete onboarding
2. Calendly connection is OPTIONAL (can be added later in settings)

## Implementation Checklist

- [x] Database migration
- [x] Calendly API client
- [x] OAuth routes
- [x] Webhook handlers
- [x] Update onboarding.html
- [x] Update settings.html
- [x] Update availability service
- [x] Update booking service
- [x] Update cancellation service
- [x] Environment variables
- [x] Testing (53 tests written!)

## Testing

1. Test OAuth flow (connect/disconnect)
2. Test availability API (should return Calendly slots)
3. Test booking creation (should create in Calendly + save to DB)
4. Test cancellation (should cancel in Calendly + update DB)
5. Test webhooks (should sync bookings from Calendly)
6. Test agent workflow (should work with Calendly backend)
