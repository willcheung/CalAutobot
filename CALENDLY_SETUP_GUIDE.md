# Calendly Integration Setup Guide

## ✅ Implementation Complete!

The Calendly integration has been successfully implemented following TDD principles. All core functionality is in place and tested.

---

## 🎯 What Was Built

### 1. **Database Schema** ✅
- User model: 7 new Calendly fields
- EventType model: 3 new Calendly fields
- Event model: 3 new Calendly fields
- Migration file: `tools/migrations/20251110_add_calendly_integration.py`

### 2. **API Client** ✅ (12 tests)
- `app/services/calendly_api.py`
- Methods: get_current_user, get_event_types, get_event_type_available_times, create_invitee, cancel_invitee, list_scheduled_events, create_webhook_subscription, delete_webhook_subscription
- Features: Automatic token refresh, error handling, logging

### 3. **OAuth Flow** ✅ (10 tests)
- `app/routes/calendly_auth.py`
- Routes: `/auth/calendly`, `/auth/calendly/callback`, `/auth/calendly/disconnect`
- Token refresh helper function

### 4. **Webhooks** ✅ (9 tests)
- `app/routes/calendly_webhooks.py`
- Handles: invitee.created, invitee.canceled
- Auto-syncs bookings from Calendly UI to local DB

### 5. **Availability Service** ✅ (10 tests - TDD)
- `app/services/availability.py`
- Uses Calendly API when user connected
- Falls back to local logic on error
- Handles Calendly's 7-day range limit
- Timezone conversion

### 6. **Public Booking Service** ✅ (12 tests - TDD)
- `app/services/public_booking.py`
- `_create_calendly_booking()` - Creates via Calendly API
- `create_booking_event()` - Tries Calendly first, falls back to Google
- `cancel_booking_event()` - Cancels via Calendly when applicable

### 7. **UI Updates** ✅
- `app/templates/onboarding.html` - Shows Calendly connection in Step 2
- `app/templates/settings/calendar.html` - Shows connection status, disconnect button

### 8. **Environment Variables** ✅
- `CALENDLY_CLIENT_ID` - Already configured
- `CALENDLY_CLIENT_SECRET` - Already configured
- `CALENDLY_WEBHOOK_SECRET` - Added (needs real value)

---

## 📊 Test Coverage

**Total: 53 comprehensive tests written!**

- API Client: 12 tests
- OAuth Routes: 10 tests
- Webhooks: 9 tests
- Availability (TDD): 10 tests
- Public Booking (TDD): 12 tests

All tests use mocking for external API calls.

---

## 🚀 Next Steps

### 1. Run Database Migration
```bash
python tools/migrations/20251110_add_calendly_integration.py
```

### 2. Configure Calendly OAuth App
Go to https://calendly.com/integrations/api_webhooks and:
- Register your OAuth application
- Set redirect URI: `https://yourdomain.com/auth/calendly/callback`
- Copy Client ID and Client Secret (already in .env)
- Set scopes: `read write`

### 3. Configure Calendly Webhook
In Calendly dashboard:
- Create webhook subscription
- Webhook URL: `https://yourdomain.com/webhooks/calendly`
- Subscribe to events: `invitee.created`, `invitee.canceled`
- Copy signing key and update `CALENDLY_WEBHOOK_SECRET` in .env

### 4. Test the Integration

#### Manual Testing Flow:
1. **OAuth Connection**
   - Go to onboarding page
   - Click "Connect Calendly"
   - Authorize the app
   - Verify redirect back to onboarding
   - Check database: user should have `calendly_access_token`

2. **Event Type Sync**
   - Create event types in Calendly dashboard
   - In CalAutobot, sync event types
   - Verify `calendly_event_type_uri` is stored

3. **Availability Check**
   - Query availability for a Calendly-connected user
   - Verify Calendly API is called (check logs)
   - Verify slots are returned correctly

4. **Create Booking**
   - Book a meeting through CalAutobot UI
   - Verify booking appears in Calendly dashboard
   - Verify event saved to CalAutobot DB with `calendly_event_uri`
   - Check contact was created

5. **Webhook Test**
   - Book a meeting directly in Calendly UI
   - Verify webhook fires to `/webhooks/calendly`
   - Verify event appears in CalAutobot DB

6. **Cancel Booking**
   - Cancel a Calendly booking through CalAutobot
   - Verify cancellation in Calendly dashboard
   - Verify event status updated in DB

#### Automated Testing:
```bash
# Run all Calendly tests
pytest tests/test_calendly_api.py -v
pytest tests/test_calendly_auth.py -v
pytest tests/test_calendly_webhooks.py -v
pytest tests/test_availability_calendly.py -v
pytest tests/test_public_booking_calendly.py -v
```

---

## 🔧 Architecture Overview

```
User Books Meeting
       ↓
CalAutobot UI → Check Availability
       ↓
availability.py → Calendly API (get_event_type_available_times)
       ↓
User selects slot
       ↓
public_booking.py → Calendly API (create_invitee)
       ↓
Event saved to CalAutobot DB with calendly_event_uri
       ↓
Contact created/updated
       ↓
User receives confirmation email from Calendly
```

**Webhook Flow:**
```
User books via Calendly UI
       ↓
Calendly fires webhook → /webhooks/calendly
       ↓
calendly_webhooks.py processes invitee.created
       ↓
Event saved to CalAutobot DB
       ↓
Contact created/updated
```

---

## 🎨 User Experience

### Onboarding
1. User signs up
2. Step 1: Select timezone
3. **Step 2: Connect Calendly** (primary) + Google Calendar (optional)
4. Step 3: Getting started tips
5. Click "Start using Cal" (requires Calendly connection)

### Settings
- **Calendly Integration** section at top
- Shows connection status
- Displays scheduling URL
- "Disconnect" button if connected
- Google Calendar settings below (for conflict checking)

---

## 📝 Key Design Decisions

1. **Calendly as Primary Backend**
   - All availability checks go through Calendly when connected
   - All bookings created via Calendly API
   - CalAutobot maintains local cache for analytics

2. **Backward Compatibility**
   - Falls back to Google Calendar if Calendly not connected
   - Falls back to local logic on Calendly errors
   - No breaking changes for existing users

3. **TDD Approach**
   - Tests written before implementation for services
   - Mocked external API calls
   - 53 comprehensive tests

4. **Webhook-based Sync**
   - Real-time sync when users book via Calendly UI
   - No polling required
   - Signature verification for security

---

## 🐛 Troubleshooting

### "No Calendly access token" error
- User hasn't completed OAuth flow
- Check `calendly_access_token` in User table
- Re-run OAuth flow

### Availability returns empty
- Check event type has `calendly_event_type_uri`
- Verify Calendly API credentials
- Check logs for API errors
- Test with Calendly dashboard directly

### Bookings not syncing
- Verify webhook is configured in Calendly
- Check webhook signature secret matches
- Test webhook endpoint with Calendly's webhook tester
- Check `/webhooks/calendly` logs

### Token expired errors
- Token refresh should happen automatically
- Check `calendly_refresh_token` exists
- Verify OAuth scopes include refresh token

---

## 📚 Documentation Links

- Calendly API Docs: https://developer.calendly.com/
- OAuth Guide: https://developer.calendly.com/how-to-authenticate-with-oauth
- Webhooks Guide: https://developer.calendly.com/webhooks-overview
- Scheduling API: https://developer.calendly.com/scheduling-api

---

## ✨ What's Next?

Optional enhancements:
1. Sync event types from Calendly automatically
2. Two-way sync for event updates (not just creation/cancellation)
3. Support for team event types
4. Advanced webhook handling (invitee_no_show, routing_form_submission)
5. Calendly workflow integration
6. Payment processing integration

---

**Integration Status: ✅ COMPLETE & READY FOR TESTING**

All code has been written, tested, and documented. Ready for deployment!
