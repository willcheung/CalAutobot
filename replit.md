# Calendar AI - Text to Calendar Events Service

## Overview

Calendar AI is a Flask-based web application that transforms text input (emails, documents, itineraries) into structured calendar events using AI-powered extraction. The service integrates with Google Calendar to automatically create events and provides a clean, modern interface for users to manage their extracted events.

## System Architecture

### Backend Architecture
- **Framework**: Flask with SQLAlchemy ORM
- **Database**: PostgreSQL with Flask-SQLAlchemy
- **Authentication**: Google OAuth 2.0 with Flask-Login session management
- **AI Integration**: OpenAI GPT-4o for intelligent event extraction
- **Deployment**: Gunicorn WSGI server with autoscaling deployment

### Frontend Architecture
- **Templates**: Jinja2 templating with Bootstrap 5 for responsive design
- **Styling**: Custom CSS with Inter font family and consistent color scheme
- **JavaScript**: Vanilla JS for form validation, animations, and UX enhancements
- **Icons**: Feather Icons for consistent iconography

## Key Components

### 1. User Authentication (`google_auth.py`)
- Google OAuth 2.0 integration using oauthlib
- Automatic token refresh handling
- Calendar API scope permissions
- User session management with Flask-Login

### 2. AI Event Extraction (`event_extractor.py`)
- OpenAI GPT-4o integration for text analysis
- Structured prompt engineering for consistent event extraction
- Relative date resolution based on current date
- Email parsing for sender identification

### 3. Google Calendar Integration (`google_calendar.py`)
- Google Calendar API integration
- Event creation, updating, and deletion
- Token refresh management
- Calendar synchronization tracking

### 4. Database Models (`models.py`)
- **User**: Stores user profile, Google tokens, and relationships
- **Event**: Stores extracted event details with Google Calendar sync status
- **TextInput**: Stores original text inputs for audit trail and reprocessing

### 5. Web Routes (`routes.py`)
- Dashboard for event management
- Text input processing and event extraction
- Event editing and calendar sync operations
- RESTful API endpoints for CRUD operations

## Data Flow

1. **User Authentication**: Users sign in with Google OAuth, granting calendar access
2. **Text Input**: Users paste text (emails, documents) into the web interface
3. **AI Processing**: OpenAI GPT-4o analyzes text and extracts structured event data
4. **Event Storage**: Extracted events are saved to PostgreSQL database
5. **User Review**: Events displayed in card format for user review and editing
6. **Calendar Sync**: Approved events are created in Google Calendar via API
7. **Status Tracking**: Sync status and Google event IDs are tracked in database

## External Dependencies

### Required Services
- **OpenAI API**: GPT-4o model for event extraction
- **Google OAuth 2.0**: User authentication
- **Google Calendar API**: Calendar integration
- **PostgreSQL**: Primary database storage

### Python Packages
- Flask ecosystem (Flask, Flask-SQLAlchemy, Flask-Login)
- Google client libraries (google-auth, google-api-python-client)
- OpenAI Python client
- Authentication libraries (oauthlib, requests)
- Database drivers (psycopg2-binary)

## Deployment Strategy

### Production Setup
- **WSGI Server**: Gunicorn with autoscaling deployment
- **Environment Variables**: 
  - `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`
  - `OPENAI_API_KEY`
  - `DATABASE_URL`
  - `SESSION_SECRET`
- **Database**: PostgreSQL with connection pooling
- **SSL**: HTTPS required for OAuth redirect URIs

### Development Setup
- Local development server with hot reload
- SQLite fallback for local development
- Replit integration with dev domain handling

## User Preferences

Preferred communication style: Simple, everyday language.

## Chrome Extension Implementation

### Completed Chrome Extension Features
- **Full Chrome Extension**: Complete implementation with popup interface, background service, and content scripts
- **Dual API Support**: Dedicated `/api/extension/process` endpoint plus fallback to existing `/webhook/mailgun`
- **Text Processing**: Popup text input and context menu integration for selected text
- **Screenshot Analysis**: One-click screenshot capture with GPT-4o Vision processing
- **Google Authentication**: Same OAuth flow as web app with persistent session storage
- **Dashboard Integration**: Quick links to web dashboard and email forwarding instructions
- **Context Menu**: Right-click selected text to extract events instantly
- **Keyboard Shortcuts**: Ctrl+Alt+C hotkey for quick text processing
- **CORS Support**: Full cross-origin support for Chrome extension requests
- **Real-time Feedback**: Toast notifications and status updates throughout the extension
- **Auto-sync**: Automatic Google Calendar sync when user has authentication
- **Code Reuse**: 95% of existing backend code reused, only added thin API layer

### Chrome Extension Architecture
- **manifest.json**: Extension configuration with proper permissions
- **popup.html/js**: Main user interface for text input and screenshot capture  
- **background.js**: Service worker handling auth, notifications, and API communication
- **content.js**: Page interaction for text selection and keyboard shortcuts
- **chrome_extension_api.py**: Dedicated API endpoints with CORS support
- **Icons**: SVG-based extension icons for all sizes

## Error Handling & Monitoring

### Comprehensive Error Management
- **Sentry Integration**: Production-ready error tracking with structured logging
- **Rate Limiting Protection**: OpenAI API calls with exponential backoff retry logic
- **Google Calendar Error Handling**: Specific error codes and user-friendly messages
- **Global Exception Handlers**: 404, 500, and unhandled exception catching
- **Structured Logging**: JSON-formatted logs with severity levels

### Error Recovery Features
- **OpenAI Rate Limits**: Automatic retry with 5, 10, 20 second backoff intervals
- **Google API Failures**: Graceful degradation with actionable error messages
- **Database Rollbacks**: Automatic transaction rollback on failures
- **User Feedback**: Clear error messages without exposing technical details

## Changelog

- August 7, 2025:
  - **Updated Homepage "How It Works" Section**: Changed flow to "Forward Email or Take Screenshot" → "AI Processes Your Content" → "Auto-Sync to Google Calendar" for clearer user journey
  - **Enhanced Dashboard Layout**: Updated text input section width to match email forwarding CTA, added Chrome extension promotion card with consistent styling
  - **Improved Chrome Extension Branding**: Standardized all Chrome extension buttons to use official Google Chrome icon across homepage, dashboard, and header
  - **Refined Button Styling**: Changed Chrome extension buttons to secondary light styling to not compete with primary Google sign-up buttons, updated extract events button to blue primary styling
  - **Enhanced Mobile Responsiveness**: Hidden navbar buttons on mobile (≤768px) for logo-only header, fixed Google sign-in button deformation in tablet view (769px-991px)
  - **Optimized Dashboard Section Layout**: Swapped Chrome extension and additional emails sections - Chrome extension now appears next to email forwarding CTA, additional emails moved to text input area for better user flow
  - **Enhanced Mobile Dashboard**: Hidden Chrome extension section on mobile devices (≤768px) for cleaner, more focused mobile experience
- July 29, 2025:
  - **Fixed Chrome Extension Authentication Issues**: Resolved 404 errors and authentication detection problems
  - **Enhanced Extension Authentication Flow**: Extension now properly detects existing web app login sessions
  - **Improved Extension UI Design**: Implemented official Google sign-in styling and "Ways to Create Events" organization
  - **Removed Chrome Notification Dependencies**: Eliminated notification permission errors by using console logging
  - **Added Cross-Origin Support**: Enhanced manifest with proper host permissions for web app integration
  - **Streamlined Authentication Routes**: Extension now uses existing `/google_login` route instead of creating duplicate endpoints
- July 21, 2025:
  - **Unified Attachment Processing Workflow**: Updated attachment processing to use the same workflow as email text processing
  - **Automatic Calendar Sync for Attachments**: Attachment events now auto-sync to Google Calendar when user authentication is available
  - **Unified Email Confirmation**: Attachment events are included in confirmation emails with combined totals
  - **Enhanced Logging and Debugging**: Added comprehensive logging to track event extraction vs processing discrepancies
  - **Improved Error Handling**: Enhanced validation error logging for better debugging of event processing failures
  - **Code Reuse**: Leveraged existing `process_text_to_events` workflow for attachments to ensure consistency
- July 16, 2025:
  - Added comprehensive attachment processing system using direct file content
  - Enhanced OpenAI integration with multimodal GPT-4o for image and document processing
  - Added EmailAttachment model for tracking attachment processing status
  - Integrated Mailgun Email API for fetching stored emails and attachments
  - Implemented Mailgun storage key-based email retrieval with fallback to direct uploads
  - Added support for PDF, Word, and image file processing
  - Enhanced event extraction to handle visual content (calendars, schedules, itineraries)
  - Implemented direct attachment processing without temporary file storage
  - Removed all Object Store dependencies and switched to Mailgun Email API
  - Enhanced database schema to track attachment processing and event sources
- June 15, 2025:
  - Implemented minimal OAuth scope approach using only "calendar.app.created" permission
  - Added database storage for Cal Pilot calendar IDs to avoid duplicate calendar creation
  - Removed calendar listing permissions while maintaining full functionality
  - Enhanced user model with textbot_calendar_id field for calendar reuse
  - Added timezone detection and storage for proper calendar event scheduling
  - Updated token validation to use Google OAuth tokeninfo endpoint for restricted scopes
  - Completed timezone detection integration across all Google authentication buttons
  - All authentication flows now capture user timezone automatically via JavaScript
  - Updated OpenAI model to gpt-4o-mini for improved performance and cost efficiency
  - Fixed PostgreSQL SSL connection issues by adjusting database configuration
  - Added comprehensive error logging throughout application for better debugging
  - Enhanced event extraction with user timezone parameter for better time handling
  - Improved time format validation to handle multiple AI-generated time formats
  - Added combined datetime fields for direct Google Calendar API integration
  - Updated database schema to support RFC3339 datetime strings
  - Fixed double confirmation alerts for event deletion
  - Enhanced auto-sync functionality to properly use datetime fields
  - Unified event sync logic across auto-sync, manual sync, and edit operations
  - Resolved PostgreSQL SSL connection errors with improved database configuration
  - Added enhanced transaction retry logic with exponential backoff
  - Implemented database health checks to prevent connection failures
- June 14, 2025: 
  - Added comprehensive error handling with Sentry logging service integration
  - Implemented dedicated "Cal Pilot" calendar creation and management
  - Fixed None value validation errors in multi-event processing
  - Enhanced Google Calendar integration to use separate calendar for AI-generated events
- June 13, 2025: Initial setup