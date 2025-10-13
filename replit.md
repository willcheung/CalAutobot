# Calendar AI - Text to Calendar Events Service

## Overview
Calendar AI is a Flask-based application that turns unstructured inputs (emails, documents, screenshots, itineraries) into structured Google Calendar events via OpenAI extraction. It provides a web dashboard, Gmail ingestion pipeline, and Chrome extension so users can review, edit, and automatically sync detected events. The goal is to reduce manual data entry while keeping a clear audit trail of the original content.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Backend
- **Framework**: Flask with SQLAlchemy ORM.
- **Database**: PostgreSQL in production, SQLite fallback for local/dev and tests.
- **Authentication**: Google OAuth 2.0 with Flask-Login, including provisional-to-authenticated upgrade flow.
- **AI Integration**: OpenAI `gpt-4.1-mini` model for text and attachment extraction.
- **Deployment**: Gunicorn WSGI server.
- **Core Components**:
    - **User Authentication**: Handles Google OAuth, token refresh handling, session management, and provisional user upgrades.
    - **Provisional User System**: Emails to go@calautobot.com create provisional accounts capped at two processed messages; OAuth signup upgrades the account and auto-syncs stored events.
    - **AI Event Extraction**: Structured prompting, timezone-aware date resolution, emoji tagging, validation, and persistence via `process_text_to_events`.
    - **Google Calendar Integration**: Manages calendar creation, event CRUD, webhook registration, and token refresh via `app/services/google_calendar.py`.
    - **Gmail Ingestion**: Polling (cron) and push (Pub/Sub) processors download messages, filter attachments, deduplicate events, and mark mail as read.
    - **Database Models**: `User`, `Event`, `TextInput`, `EmailAttachment`, `GmailPushState`, and `CalWaitlist` capture user data, extraction history, attachments, push state, and waitlist entries.
    - **Web Routes**: Blueprints in `app/routes` provide dashboard UI, REST endpoints, webhook handlers, and Chrome-extension APIs.
    - **Data Flow**: Inputs (manual, Gmail, Chrome extension) go through `process_text_to_events`, which orchestrates OpenAI extraction, sanitization, database writes, and optional calendar sync.
    - **Webhook System**: Google Calendar webhook verifies tokens, spawns background deletion workers, and keeps database in sync with remote deletions.
    - **Email Templates**: `templates/emails/limit_reached.html` notifies provisional users who hit their quota.

### Frontend
- **Templates**: Jinja2 with Bootstrap 5.
- **Styling**: Custom CSS with Inter font family and consistent color scheme (e.g., secondary light styling for Chrome extension buttons, blue primary for extract events).
- **JavaScript**: Vanilla JS for UX enhancements and form validation.
- **Icons**: Feather Icons.
- **UI/UX Decisions**: Responsive design, consistent iconography, clear user journey (e.g., "Forward Email or Take Screenshot" -> "AI Processes Your Content" -> "Auto-Sync to Google Calendar"), optimized dashboard layout, mobile responsiveness with hidden navbar buttons and dedicated mobile sections.

### Chrome Extension
- **Functionality**: Chrome extension with popup, background service worker, and content scripts. Supports text input, context menu extraction, screenshot uploads, and Google authentication.
- **Architecture**: `manifest.json`, `popup.html/js`, `background.js`, `content.js`, and dedicated API endpoints (`chrome_extension_api.py`) with CORS support.
- **User Experience**: Real-time feedback via toast notifications, auto-sync with Google Calendar, and keyboard shortcuts.

### Error Handling & Monitoring
- **Error Management**: Sentry integration for error tracking, rate limiting with exponential backoff for OpenAI API, specific Google Calendar error handling, global exception handlers, and structured logging.
- **Error Recovery**: Automatic retry for OpenAI rate limits, graceful degradation for Google API failures, database rollbacks, and clear user feedback.

## External Dependencies

### Services
- **OpenAI API**: `gpt-4.1-mini` for AI event extraction.
- **Google OAuth 2.0**: User authentication and refresh tokens.
- **Google Calendar API**: Calendar creation, event sync, and push notifications.
- **Gmail API**: Email ingestion, attachment download, history streaming, and Pub/Sub watch management.
- **Google Pub/Sub**: Push delivery of Gmail history updates (via configured topic).
- **PostgreSQL**: Primary production database.
- **Sentry**: Error tracking and monitoring.

### Python Packages
- Flask ecosystem (Flask, Flask-SQLAlchemy, Flask-Login)
- Google client libraries (google-auth, google-api-python-client)
- OpenAI Python client
- Authentication libraries (oauthlib, requests)
- Database drivers (psycopg2-binary)
- Testing stack (pytest, pytest-flask) via optional `test` extras

## Project Layout Notes
- `app/` is the main application package. Core modules (`models.py`, `event_extractor.py`), helpers, services, and blueprints live under `app/` (e.g., `app/routes/`, `app/helpers/`, `app/services/`). Templates and static assets are under `app/templates/` and `app/static/`.
- `tools/` contains operational scripts such as the cron-friendly Gmail checker (`tools/check_emails.py`).
- Dependencies are managed via `pyproject.toml`/`uv.lock`; tests live in `tests/` with fixtures that create isolated SQLite databases.

## Documentation Practice
- Update this file whenever architecture, dependencies, or user flows change.
- Record new features and integration points here as they ship so scheduled deployments and collaborators stay informed.
```
