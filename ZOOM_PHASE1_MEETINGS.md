# Zoom Meetings Integration - Phase 1

## Goal

Auto-generate Zoom meeting links for all bookings (Calendly or Google Calendar).

## Simple Flow

```
User books meeting via Calendly
       ↓
CalAutobot creates Event in DB
       ↓
Auto-create Zoom meeting via API
       ↓
Store zoom_meeting_id and zoom_join_url
       ↓
Display Zoom link on confirmation page
```

## Key Zoom Meetings API Endpoints

- **POST /users/{userId}/meetings** - Create meeting with video link
- **DELETE /meetings/{meetingId}** - Delete meeting
- OAuth scopes: `meeting:write meeting:read`

## Database Changes

### User model
```python
zoom_access_token = db.Column(db.Text, nullable=True)
zoom_refresh_token = db.Column(db.Text, nullable=True)
zoom_user_id = db.Column(db.String(255), nullable=True)
zoom_connected_at = db.Column(db.DateTime, nullable=True)
```

### Event model
```python
zoom_meeting_id = db.Column(db.String(255), nullable=True)
zoom_join_url = db.Column(db.String(512), nullable=True)
zoom_start_url = db.Column(db.String(512), nullable=True)  # For host
zoom_password = db.Column(db.String(100), nullable=True)
```

## New Files

### 1. tools/migrations/20251111_add_zoom_meetings.py
Add Zoom fields to User and Event models.

### 2. app/services/zoom_api.py
Simple API client:
```python
class ZoomAPIClient:
    def __init__(self, user):
        self.access_token = user.zoom_access_token
        self.user = user

    def create_meeting(self, topic, start_time, duration, timezone):
        """Create a Zoom meeting and return join URL."""
        # POST /users/me/meetings
        pass

    def delete_meeting(self, meeting_id):
        """Delete a Zoom meeting."""
        # DELETE /meetings/{meeting_id}
        pass
```

### 3. app/routes/zoom_auth.py
OAuth routes:
```python
@zoom_auth.route('/auth/zoom')
def connect():
    # Redirect to Zoom OAuth with scopes: meeting:write meeting:read
    pass

@zoom_auth.route('/auth/zoom/callback')
def callback():
    # Exchange code for tokens
    # Store in user.zoom_access_token
    pass

@zoom_auth.route('/auth/zoom/disconnect', methods=['POST'])
def disconnect():
    # Clear tokens from user
    pass
```

### 4. Tests (TDD)
- `tests/test_zoom_api.py` - API client tests (8 tests)
- `tests/test_zoom_auth.py` - OAuth tests (6 tests)
- `tests/test_public_booking_zoom.py` - Integration tests (8 tests)

## Modified Files

### app/services/public_booking.py

Add video link after creating booking:

```python
def create_booking_event(user, event_type, start_dt, invitee_name, invitee_email, ...):
    end_dt = start_dt + timedelta(minutes=event_type.duration_minutes)

    # 1. Create booking via Calendly (existing)
    if user.calendly_access_token and event_type.calendly_event_type_uri:
        try:
            event = _create_calendly_booking(...)
        except Exception as exc:
            logger.warning(f"Calendly failed, falling back: {exc}")
            event = _create_google_calendar_booking(...)
    else:
        event = _create_google_calendar_booking(...)

    # 2. Auto-create Zoom meeting link (NEW)
    if user.zoom_access_token:
        try:
            zoom_client = ZoomAPIClient(user)
            meeting = zoom_client.create_meeting(
                topic=f"{event_type.name} with {invitee_name}",
                start_time=start_dt,
                duration=event_type.duration_minutes,
                timezone=user.timezone or 'UTC',
            )
            event.zoom_meeting_id = meeting['id']
            event.zoom_join_url = meeting['join_url']
            event.zoom_start_url = meeting['start_url']
            event.zoom_password = meeting.get('password')
            db.session.commit()
            logger.info(f"Created Zoom meeting {meeting['id']} for event {event.id}")
        except Exception as exc:
            logger.warning(f"Failed to create Zoom meeting: {exc}")
            # Booking still succeeds without video link

    return event
```

Update cancellation:

```python
def cancel_booking_event(user, event):
    if event.status == "cancelled":
        return

    # Cancel Calendly event
    if event.calendly_invitee_uri and user.calendly_access_token:
        try:
            client = CalendlyAPIClient(user)
            client.cancel_invitee(event.calendly_invitee_uri, reason="Cancelled by host")
        except Exception as exc:
            logger.warning(f"Failed to cancel Calendly event: {exc}")

    # Cancel Google Calendar event
    elif event.google_event_id and user.google_calendar_token:
        # ... existing code

    # Delete Zoom meeting (NEW)
    if event.zoom_meeting_id and user.zoom_access_token:
        try:
            zoom_client = ZoomAPIClient(user)
            zoom_client.delete_meeting(event.zoom_meeting_id)
            logger.info(f"Deleted Zoom meeting {event.zoom_meeting_id}")
        except Exception as exc:
            logger.warning(f"Failed to delete Zoom meeting: {exc}")

    event.status = 'cancelled'
    db.session.commit()
```

### app/__init__.py
Register Zoom auth blueprint:
```python
from app.routes.zoom_auth import zoom_auth
app.register_blueprint(zoom_auth)
```

### app/templates/onboarding.html

Add Zoom connection (optional):

```html
<!-- After Google Calendar -->
<div class="calendar-connection-status mt-3">
    <p class="text-muted mb-2" style="font-size: 0.85rem;">Optional: Connect Zoom for video meetings</p>
    {% if current_user.zoom_access_token %}
        <div class="alert alert-permanent alert-success d-flex align-items-center gap-2 mb-0">
            <i data-feather="check-circle"></i>
            <span style="font-weight: 500;">Zoom connected</span>
        </div>
    {% else %}
        <div class="d-flex align-items-center gap-3 p-3" style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px;">
            <div style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; background: #2D8CFF; border-radius: 8px;">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="white">
                    <path d="M2 8.5C2 7.119 3.119 6 4.5 6h11C16.881 6 18 7.119 18 8.5v7c0 1.381-1.119 2.5-2.5 2.5h-11C3.119 18 2 16.881 2 15.5v-7zm16.5 3l3.5-2v7l-3.5-2v-3z"/>
                </svg>
            </div>
            <div class="flex-grow-1">
                <div class="fw-semibold mb-1" style="color: #0f172a;">Zoom</div>
                <span style="display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; background: #fee2e2; color: #991b1b; border-radius: 999px; font-size: 0.8rem; font-weight: 500;">
                    <span style="width: 6px; height: 6px; background: #dc2626; border-radius: 50%;"></span>
                    Not connected
                </span>
            </div>
            <a href="{{ url_for('zoom_auth.connect') }}" class="btn btn-outline-secondary btn-sm">
                Connect
            </a>
        </div>
    {% endif %}
</div>
```

### app/templates/settings/calendar.html

Add Zoom section:

```html
<!-- After Calendly Integration Status -->
<div class="settings-section card shadow-sm mb-3">
    <div class="card-body">
        <h5 class="card-title mb-1">Zoom Meetings</h5>
        <p class="text-muted small mb-0">Auto-generate Zoom meeting links for your bookings</p>

        <div class="mt-3">
            {% if current_user.zoom_access_token %}
                <div class="d-flex align-items-center gap-3 p-3" style="background: #dcfce7; border: 1px solid #86efac; border-radius: 8px;">
                    <div style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; background: #2D8CFF; border-radius: 8px;">
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="white">
                            <path d="M2 8.5C2 7.119 3.119 6 4.5 6h11C16.881 6 18 7.119 18 8.5v7c0 1.381-1.119 2.5-2.5 2.5h-11C3.119 18 2 16.881 2 15.5v-7zm16.5 3l3.5-2v7l-3.5-2v-3z"/>
                        </svg>
                    </div>
                    <div class="flex-grow-1">
                        <div class="fw-semibold mb-1" style="color: #15803d;">Zoom Connected</div>
                        {% if current_user.zoom_connected_at %}
                            <div class="small text-muted">
                                Connected on {{ current_user.zoom_connected_at.strftime('%B %d, %Y') }}
                            </div>
                        {% endif %}
                    </div>
                    <form method="post" action="{{ url_for('zoom_auth.disconnect') }}">
                        <button type="submit" class="btn btn-outline-danger btn-sm" onclick="return confirm('Disconnect Zoom? Future bookings will not have video links.');">
                            Disconnect
                        </button>
                    </form>
                </div>
            {% else %}
                <div class="alert alert-info mb-0">
                    <strong>Zoom is not connected.</strong> Connect Zoom to auto-generate video meeting links for all your bookings.
                </div>
            {% endif %}
        </div>
    </div>
</div>
```

### app/templates/booking_confirmation.html

Display Zoom link (if available):

```html
<!-- After booking details -->
{% if event.zoom_join_url %}
<div class="card shadow-sm mt-4">
    <div class="card-body">
        <h5 class="card-title mb-3">
            <i data-feather="video"></i> Join Video Meeting
        </h5>

        <div class="d-flex align-items-center gap-3 mb-3">
            <div style="width: 48px; height: 48px; background: #2D8CFF; border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="white">
                    <path d="M2 8.5C2 7.119 3.119 6 4.5 6h11C16.881 6 18 7.119 18 8.5v7c0 1.381-1.119 2.5-2.5 2.5h-11C3.119 18 2 16.881 2 15.5v-7zm16.5 3l3.5-2v7l-3.5-2v-3z"/>
                </svg>
            </div>
            <div class="flex-grow-1">
                <div class="fw-semibold">Zoom Meeting</div>
                <div class="small text-muted">Video conferencing included</div>
            </div>
        </div>

        <a href="{{ event.zoom_join_url }}" class="btn btn-primary w-100 mb-2" target="_blank" rel="noopener">
            <i data-feather="video"></i> Join Zoom Meeting
        </a>

        {% if event.zoom_password %}
        <div class="alert alert-light mb-0">
            <small><strong>Meeting Password:</strong> <code>{{ event.zoom_password }}</code></small>
        </div>
        {% endif %}
    </div>
</div>
{% endif %}
```

## Environment Variables

```bash
ZOOM_CLIENT_ID=your_zoom_client_id
ZOOM_CLIENT_SECRET=your_zoom_client_secret
```

Note: Redirect URI is built dynamically: `{domain}/auth/zoom/callback`

## Implementation Checklist

- [ ] Database migration (User + Event models)
- [ ] Zoom API client (create_meeting, delete_meeting)
- [ ] OAuth routes (connect, callback, disconnect)
- [ ] Update `create_booking_event()` to add Zoom link
- [ ] Update `cancel_booking_event()` to delete Zoom meeting
- [ ] Update onboarding.html (Zoom connection)
- [ ] Update settings/calendar.html (Zoom section)
- [ ] Update booking confirmation template (show Zoom link)
- [ ] Environment variables (CLIENT_ID, CLIENT_SECRET)
- [ ] Tests (22 tests following TDD)

## Testing

### Automated Tests (TDD):
```bash
# Write tests first, then implement
pytest tests/test_zoom_api.py -v          # 8 tests
pytest tests/test_zoom_auth.py -v         # 6 tests
pytest tests/test_public_booking_zoom.py -v  # 8 tests
```

### Manual Testing:
1. Connect Zoom via OAuth in onboarding
2. Create booking via Calendly
3. Verify Zoom meeting link appears on confirmation page
4. Click Zoom link → verify it works
5. Cancel booking
6. Verify Zoom meeting is deleted (try to join → should fail)
7. Test with Zoom disconnected → booking should still work, just no video link

## Expected Behavior

**With Zoom connected:**
- Every booking gets a Zoom meeting link
- Link shown on confirmation page
- Link included in booking emails
- Zoom meeting auto-deleted when booking cancelled

**Without Zoom connected:**
- Bookings work normally (via Calendly/Google Calendar)
- No video link generated
- No errors or disruptions

## Benefits

1. **Simple integration** - Just adds video links, no complex scheduling logic
2. **Optional** - Bookings work fine without Zoom
3. **Reuses Calendly pattern** - Same OAuth/API client structure
4. **Auto-cleanup** - Deletes Zoom meetings when bookings cancelled
5. **Universal** - Works with both Calendly and Google Calendar bookings

---

## Estimated Time: 3-4 hours

Following TDD approach, same as Calendly integration.

**Ready to implement Phase 1?**
