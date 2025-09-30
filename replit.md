# Calendar AI - Text to Calendar Events Service

## Overview
Calendar AI is a Flask-based web application designed to transform unstructured text (emails, documents, itineraries) into structured calendar events using AI. It integrates with Google Calendar for automatic event creation and offers a modern interface for managing extracted events. The project aims to streamline event organization, reduce manual data entry, and enhance productivity for users by leveraging advanced AI capabilities to interpret and schedule their daily information.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### Backend
- **Framework**: Flask with SQLAlchemy ORM.
- **Database**: PostgreSQL.
- **Authentication**: Google OAuth 2.0 with Flask-Login.
- **AI Integration**: OpenAI GPT-4o for event extraction.
- **Deployment**: Gunicorn WSGI server.
- **Core Components**:
    - **User Authentication**: Handles Google OAuth, token refresh, and session management.
    - **Provisional User System**: Public access via go@calautobot.com with 2-email limit before signup required. Provisional users (google_id=NULL) can send up to 2 emails and receive event extraction results. OAuth signup automatically upgrades provisional → authenticated users with auto-sync of stored events.
    - **AI Event Extraction**: Processes text using GPT-4o, applies structured prompting, resolves relative dates, and parses emails.
    - **Google Calendar Integration**: Manages event creation, updating, deletion, and token refresh with Google Calendar API. Optimized with try-first approach to reduce unnecessary token refreshes by ~66%.
    - **Database Models**: Defines `User`, `Event`, and `TextInput` models for data storage. User model includes `email_count` field for tracking provisional user limits.
    - **Web Routes**: Manages dashboard operations, text processing, event editing, and RESTful API endpoints.
    - **Data Flow**: Users authenticate, input text, AI processes it, events are stored, reviewed, and then synced to Google Calendar.
    - **Webhook System**: Implemented for real-time Google Calendar push notifications, including automatic event deletion sync, with token-based validation. Updated to use production domain (calautobot.com) for webhook endpoints with asynchronous processing to prevent worker timeouts.
    - **Email Templates**: Dedicated templates in `templates/emails/` for provisional user communications (provisional_summary.html for event results, limit_reached.html for signup prompt).

### Frontend
- **Templates**: Jinja2 with Bootstrap 5.
- **Styling**: Custom CSS with Inter font family and consistent color scheme (e.g., secondary light styling for Chrome extension buttons, blue primary for extract events).
- **JavaScript**: Vanilla JS for UX enhancements and form validation.
- **Icons**: Feather Icons.
- **UI/UX Decisions**: Responsive design, consistent iconography, clear user journey (e.g., "Forward Email or Take Screenshot" -> "AI Processes Your Content" -> "Auto-Sync to Google Calendar"), optimized dashboard layout, mobile responsiveness with hidden navbar buttons and dedicated mobile sections.

### Chrome Extension
- **Functionality**: Full Chrome Extension with popup, background service, content scripts. Supports text input, context menu integration, screenshot analysis with GPT-4o Vision, and Google Authentication.
- **Architecture**: `manifest.json`, `popup.html/js`, `background.js`, `content.js`, and dedicated API endpoints (`chrome_extension_api.py`) with CORS support.
- **User Experience**: Real-time feedback via toast notifications, auto-sync with Google Calendar, and keyboard shortcuts.

### Error Handling & Monitoring
- **Error Management**: Sentry integration for error tracking, rate limiting with exponential backoff for OpenAI API, specific Google Calendar error handling, global exception handlers, and structured logging.
- **Error Recovery**: Automatic retry for OpenAI rate limits, graceful degradation for Google API failures, database rollbacks, and clear user feedback.

## External Dependencies

### Services
- **OpenAI API**: GPT-4o model for AI event extraction.
- **Google OAuth 2.0**: For user authentication.
- **Google Calendar API**: For calendar integration and push notifications.
- **PostgreSQL**: Primary database storage.
- **Mailgun Email API**: For fetching stored emails and attachments.
- **Sentry**: For error tracking and monitoring.

### Python Packages
- Flask ecosystem (Flask, Flask-SQLAlchemy, Flask-Login)
- Google client libraries (google-auth, google-api-python-client)
- OpenAI Python client
- Authentication libraries (oauthlib, requests)
- Database drivers (psycopg2-binary)
```