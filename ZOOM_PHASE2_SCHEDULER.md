# Zoom Scheduler Integration - Phase 2 (Future)

## Goal

Add Zoom Scheduler as an alternative scheduling backend (like Calendly).

## Why Phase 2?

- Phase 1 (Zoom Meetings) provides immediate value: video links for all bookings
- Zoom Scheduler is more complex: webhooks, external bookings, schedule management
- Users already have Calendly working as primary scheduler
- Zoom Scheduler provides alternative for users who prefer Zoom ecosystem

## What Zoom Scheduler Provides

✅ **Public booking pages** (like Calendly)
✅ **Schedule management** (event types)
✅ **Availability rules**
✅ **List scheduled events** via API
✅ **Update/cancel events** via API
✅ **Webhooks** for external bookings
❌ **Cannot create bookings via API** (limitation)

## Architecture

```
PUBLIC BOOKINGS:
User shares Zoom Scheduler link → Books via Zoom UI → Webhook syncs to CalAutobot

COMPARISON TO CALENDLY:
Calendly: Booking page + webhook + API for agent bookings
Zoom Scheduler: Booking page + webhook (no API for agent bookings)
```

## Key Zoom Scheduler API Endpoints

- **GET /scheduler/schedules** - List schedules (event types)
- **POST /scheduler/schedules** - Create schedule
- **GET /scheduler/events** - List scheduled events
- **PATCH /scheduler/events/{id}** - Update event
- **DELETE /scheduler/events/{id}** - Cancel event
- **GET /scheduler/availability** - List availability schedules
- **Webhooks:** `scheduler.scheduled_event_created`, `scheduler.scheduled_event_canceled`

## Database Changes (Additional)

### User model
```python
zoom_scheduler_access_token = db.Column(db.Text, nullable=True)
zoom_scheduler_refresh_token = db.Column(db.Text, nullable=True)
zoom_scheduler_connected_at = db.Column(db.DateTime, nullable=True)
```

Note: Can reuse same Zoom OAuth tokens from Phase 1, just need additional scopes.

### EventType model
```python
zoom_schedule_id = db.Column(db.String(255), nullable=True)
zoom_schedule_url = db.Column(db.String(512), nullable=True)
```

### Event model
```python
zoom_scheduler_event_id = db.Column(db.String(255), nullable=True)
```

## New Files (Phase 2)

### 1. app/services/zoom_scheduler_api.py
Scheduler-specific API client:
```python
class ZoomSchedulerAPIClient:
    def get_schedules(self, user):
        """List user's Zoom Scheduler schedules (event types)."""
        pass

    def create_schedule(self, user, name, duration, ...):
        """Create a new schedule."""
        pass

    def get_events(self, user, from_date, to_date):
        """List scheduled events."""
        pass

    def delete_event(self, user, event_id):
        """Cancel a scheduled event."""
        pass
```

### 2. app/routes/zoom_scheduler_webhooks.py
Webhook handlers:
```python
@zoom_scheduler_webhooks.route('/webhooks/zoom/scheduler', methods=['POST'])
def handle_webhook():
    payload = request.json
    event_type = payload.get('event')

    if event_type == 'scheduler.scheduled_event_created':
        return handle_event_created(payload)
    elif event_type == 'scheduler.scheduled_event_canceled':
        return handle_event_canceled(payload)

    return jsonify({'status': 'ignored'}), 200
```

### 3. Tests
- `tests/test_zoom_scheduler_api.py` - Scheduler API tests
- `tests/test_zoom_scheduler_webhooks.py` - Webhook tests

## Modified Files (Phase 2)

### app/routes/zoom_auth.py
Add Scheduler OAuth:
```python
@zoom_auth.route('/auth/zoom/scheduler')
def connect_scheduler():
    # OAuth with scheduler scopes
    pass
```

### app/services/public_booking.py
Handle Zoom Scheduler cancellations:
```python
def cancel_booking_event(user, event):
    # ... existing Calendly/Google cancellation

    # Cancel Zoom Scheduler event (if booked via Zoom)
    if event.zoom_scheduler_event_id and user.zoom_scheduler_access_token:
        try:
            zoom_scheduler_client = ZoomSchedulerAPIClient(user)
            zoom_scheduler_client.delete_event(event.zoom_scheduler_event_id)
        except Exception as exc:
            logger.warning(f"Failed to cancel Zoom Scheduler event: {exc}")

    # ... existing Zoom Meetings deletion
```

### app/templates/settings/calendar.html
Add Zoom Scheduler section:
```html
<div class="settings-section card shadow-sm mb-3">
    <div class="card-body">
        <h5 class="card-title">Zoom Scheduler</h5>
        <p class="text-muted small">Alternative scheduling pages powered by Zoom</p>

        {% if current_user.zoom_scheduler_access_token %}
            <div class="alert alert-success">
                Zoom Scheduler Connected
                <a href="{{ user_zoom_schedule_url }}" target="_blank">View booking page</a>
            </div>
        {% else %}
            <div class="alert alert-info">
                Connect Zoom Scheduler for Zoom-powered booking pages.
            </div>
        {% endif %}
    </div>
</div>
```

## Environment Variables (Additional)

```bash
ZOOM_SCHEDULER_WEBHOOK_SECRET=your_webhook_secret
```

## OAuth Scopes (Combined Phase 1 + 2)

```
meeting:write meeting:read scheduler:write scheduler:read
```

## Implementation Checklist (Phase 2)

- [ ] Database migration (add zoom_scheduler fields)
- [ ] Zoom Scheduler API client
- [ ] OAuth routes (add scheduler scopes)
- [ ] Webhook handlers (scheduler events)
- [ ] Update `cancel_booking_event()` for Zoom Scheduler
- [ ] Update settings UI (Zoom Scheduler section)
- [ ] Environment variables (webhook secret)
- [ ] Tests (15+ tests)
- [ ] Configure webhook in Zoom dashboard

## User Benefits

**With Zoom Scheduler:**
- Users can share Zoom-branded booking pages
- All-in-one Zoom experience (scheduling + video)
- External bookings sync automatically
- Alternative to Calendly for Zoom-centric users

**Still using Calendly:**
- Calendly as primary scheduler
- Zoom for video links only
- Best of both worlds

## Limitation to Remember

⚠️ **Cal agent cannot book via Zoom Scheduler API**

Because there's no `POST /scheduler/events` endpoint, the Cal AI agent will continue using:
- Calendly API for agent bookings (preferred)
- Zoom Meetings API for video links

This is fine because:
1. Agent bookings are handled by Calendly (which has full API)
2. Zoom Scheduler is for public bookings only
3. Zoom Meetings still provides video links for all bookings

## When to Implement Phase 2

Consider Phase 2 when:
- Users request Zoom Scheduler specifically
- You want to reduce dependency on Calendly
- Users prefer all-Zoom ecosystem
- You have bandwidth for webhook management

## Estimated Time: 4-5 hours

Similar complexity to Calendly integration, mainly webhooks and schedule management.

---

## For Now: Phase 1 Only

Focus on **Phase 1 (Zoom Meetings)** first:
- Simple video link generation
- Works with existing Calendly infrastructure
- Immediate user value
- No webhook complexity

Phase 2 can wait until there's user demand or strategic need for Zoom Scheduler alternative.
