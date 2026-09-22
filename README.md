# CalAutobot — an AI scheduling agent for email

## Overview

CalAutobot is an email-native meeting coordinator. Add `Cal@CalAutobot.com` to the CC line of a scheduling thread and Cal takes over the back-and-forth: it reads the conversation, checks connected calendars, proposes available times, negotiates with the participants, follows up when someone goes quiet, and books the agreed time.

The core product is meeting coordination inside an existing email conversation. People keep replying as they normally would; they don't have to open another app or work through a booking form.

CalAutobot can also extract events from text, emails, PDFs, images, and itineraries and add them to a calendar. That's a supporting feature, not the main product.

> **Service status:** CalAutobot is no longer accepting new customers and is being prepared for retirement. Existing customers can continue to sign in while the service remains available.

## How scheduling works

1. **CC Cal** on an email with the people you want to meet.
2. **Cal reads the thread** to understand who is involved, what the meeting is about, and any timing constraints already mentioned.
3. **Availability is checked** against the organizer's connected calendars and scheduling preferences.
4. **Cal proposes times** in the same email thread and interprets natural-language replies from the participants.
5. **The conversation continues** until everyone agrees on a slot. Cal can follow up, offer alternatives, reschedule, or cancel.
6. **The meeting is booked** in Google Calendar or Calendly and the participants receive the final confirmation.

## System Architecture

### Backend
- **Framework**: Flask with SQLAlchemy ORM
- **Database**: PostgreSQL (Neon)
- **Authentication**: Google OAuth 2.0 with Flask-Login
- **AI**: Google Gemini (via OpenAI-compatible client) for event extraction, email classification, and meeting scheduling
- **Deployment**: Vercel (Python runtime) / Gunicorn
- **Monitoring**: Sentry with structured JSON logging

### Frontend
- **Templates**: Jinja2 with Bootstrap 5
- **Styling**: Custom CSS with Inter font and Feather Icons
- **JavaScript**: Vanilla JS

## Key Features

### 1. Email-based meeting negotiation (`app/agents/meeting_scheduler.py`)
- CC-based workflow that stays inside the existing email thread
- Reads the full conversation and understands dates, preferences, constraints, and participant replies
- Checks the organizer's connected calendars before proposing times
- Coordinates one-to-one and multi-party meetings
- Tracks the full scheduling state: propose → collect replies → negotiate → confirm → create event
- Automatic follow-ups and reminders with configurable delays
- Rescheduling and cancellation handling

### 2. Real-time email processing (`app/services/gmail_processor.py`)
- Gmail push notifications via Google Cloud Pub/Sub
- Task classifier routes each email to meeting scheduling, event extraction, or no action
- Conversation and message history are stored so Cal can continue long-running scheduling threads
- Multi-mailbox support per user account

### 3. Calendar and availability integration
- Bidirectional sync: events created in CalAutobot appear in Google Calendar
- Webhook-based change notifications from Google Calendar
- Multi-calendar support with conflict checking
- Token refresh management
- Calendly integration with plan-aware availability and booking behavior

### 4. Event extraction (`app/agents/event_extractor.py`)
- Extracts structured calendar events from text, email, PDFs, screenshots, and other images
- Handles flight itineraries, invitations, relative dates, locations, and event details
- Lets users review extracted details before calendar sync
- Links extracted events to the source email and contacts

### 5. Public booking pages
- Shareable booking URLs for each event type
- Supports Google Meet, Zoom, and Microsoft Teams location types
- Timezone-aware availability display
- Booking confirmation with calendar event creation

### 6. Gmail Chrome extension (`chrome-extension-scheduler/`)
- Manifest V3 Gmail extension via InboxSDK
- "Insert availability" and "Insert booking link" buttons in Gmail compose
- Auto-syncs email recipients as contacts
- Email open tracking via tracking pixel injection

### 7. Email tracking
- Pixel-based open tracking with geolocation
- Per-contact engagement metrics
- Real-time open notifications

### 8. Contact management
- Automatic contact creation from email metadata
- Labels/tags for organization
- Engagement history linked to tracking data

### 9. Payments (Stripe)
- Checkout session creation
- Webhook handling for `checkout.session.completed`
- PDF delivery on purchase

## Data Flow

1. **An email arrives** → Gmail push notification triggers processing.
2. **The intent is classified** → schedule a meeting, extract an event, or take no action.
3. **For scheduling threads** → Cal loads the conversation and meeting state, checks availability, and decides whether to ask a question, propose times, follow up, or confirm.
4. **Participants reply** → Cal parses natural-language responses and continues the negotiation in the same thread.
5. **A time is agreed** → Cal creates the event in Google Calendar or through Calendly and sends confirmation.
6. **For event-extraction messages** → Gemini turns text or attachments into structured event details for calendar sync.

## Database Models

| Model | Purpose |
|-------|---------|
| User | Auth, Google/Calendly tokens, preferences |
| Event | Calendar events with sync status and source tracking |
| TextInput | Original text inputs and extraction results |
| MeetingRequest | Multi-party meeting coordination state machine |
| MeetingParticipant | Per-attendee tracking and response status |
| MeetingMessage | Email thread storage with parsed time slots |
| Contact | CRM records with engagement metrics |
| EventType | Booking types (duration, slug, Calendly sync) |
| AvailabilityWindow | Recurring availability blocks |
| EmailAttachment | Attachment metadata and processing status |
| GmailPushState | Gmail watch state (history ID, expiration) |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Google Gemini API access |
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth client secret |
| `DATABASE_URL` | PostgreSQL connection string |
| `SESSION_SECRET` | Flask session signing key |
| `GMAIL_CLIENT_ID` | Gmail API client ID |
| `GMAIL_CLIENT_SECRET` | Gmail API client secret |
| `GMAIL_REFRESH_TOKEN` | Gmail API refresh token |
| `CALENDLY_CLIENT_ID` | Calendly OAuth client ID |
| `CALENDLY_CLIENT_SECRET` | Calendly OAuth client secret |
| `STRIPE_SECRET_KEY` | Stripe API key |
| `SENTRY_DSN` | Sentry error tracking |

## Development Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env  # Then fill in values

# Run locally
python main.py
```

## Deployment

Deployed on Vercel with Python runtime (`vercel.json`). 120-second function timeout for long-running AI extraction.

## Tools

- `tools/migrations/` — Database schema migrations
- `tools/webhook_admin.py` — Gmail/Calendar webhook management
- `tools/check_emails.py` — Standalone email checking
- `tools/setup_missing_webhooks.py` — Bulk webhook setup
- `tools/renew_gmail_watch.py` — Gmail push notification renewal
