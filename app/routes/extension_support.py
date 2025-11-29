"""Extension support routes for Chrome extension integration."""

from datetime import datetime, timedelta
from typing import Optional, Tuple
import base64
import io

from flask import jsonify, session, request, url_for, send_file, g
import requests
from flask_login import current_user

from app import app, db
from app.models import EventType, User, Contact, TrackingRequest, TrackingRecipient, TrackingEvent
from app.services import availability as availability_service, contacts as contact_service
from app.services.availability import AvailabilityError
from app.services import tracking_service

def add_cors_headers_for_extension(response):
    """Add proper CORS headers for Chrome extension requests"""
    origin = request.headers.get('Origin')
    if origin and origin.startswith('chrome-extension://'):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

def _resolve_extension_user() -> Tuple[Optional[User], Optional[str]]:
    """
    Return the authenticated user via session or Authorization header.
    Returns: (user, email)
    - user: User object if found
    - email: Email address if token is valid (even if user not found)
    """
    # Prioritize Authorization header (extension token) over session cookie
    # This prevents account mismatch if user is logged into web app with Account A
    # but using extension with Account B.
    auth_header = request.headers.get('Authorization')
    if auth_header:
        # Robustly parse Bearer token (handle multiple spaces, case insensitivity)
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            token = parts[1]
            
            # Verify token with Google
            try:
                resp = requests.get(
                    'https://www.googleapis.com/oauth2/v3/tokeninfo',
                    params={'access_token': token}
                )
            
                if resp.status_code == 200:
                    token_info = resp.json()
                    email = token_info.get('email')
                    
                    if email:
                        user = User.query.filter_by(email=email.strip().lower()).first()
                        return user, email
                
            except Exception as e:
                print(f"Token verification error: {e}")

    # Fallback to session user if no valid Authorization header found
    if current_user.is_authenticated:
        return current_user, current_user.email

    # Fallback to old method (trusted email param) ONLY if token verification failed
    # This allows for a transition period or local dev testing if needed
    # But ideally we should remove this once migration is complete
    email = request.args.get('user_email')
    if not email and request.is_json:
        payload = request.get_json(silent=True) or {}
        email = payload.get('user_email')
    if not email and request.form:
        email = request.form.get('user_email')
    if not email:
        email = request.headers.get('X-User-Email')
    if email:
        user = User.query.filter_by(email=email.strip().lower()).first()
        return user, email
            
    return None, None


def _select_default_event_type(user: User) -> Optional[EventType]:
    """Select the default event type, preferring Calendly-managed ones."""
    base_query = EventType.query.filter_by(user_id=user.id, is_active=True)
    if user.calendly_access_token:
        calendly_event_type = (
            base_query.filter(EventType.calendly_event_type_uri.isnot(None))
            .order_by(EventType.duration_minutes.asc(), EventType.id.asc())
            .first()
        )
        if calendly_event_type:
            return calendly_event_type

    return base_query.order_by(EventType.duration_minutes.asc(), EventType.id.asc()).first()


def _format_slot_display(slot, tz) -> str:
    start_local = slot.start.astimezone(tz)
    end_local = slot.end.astimezone(tz)
    start_str = start_local.strftime("%a %b %d, %I:%M %p").lstrip("0")
    end_str = end_local.strftime("%I:%M %p %Z").lstrip("0")
    return f"{start_str} - {end_str}"


def _consolidate_consecutive_slots(slots):
    """
    Consolidate consecutive 30-minute slots into continuous time ranges.
    
    For example, if we have:
    - 12:00 PM - 12:30 PM
    - 12:30 PM - 1:00 PM
    - 1:00 PM - 1:30 PM
    
    This will return:
    - 12:00 PM - 1:30 PM
    """
    if not slots:
        return []
    
    consolidated = []
    current_start = slots[0].start
    current_end = slots[0].end
    
    for i in range(1, len(slots)):
        slot = slots[i]
        # Check if this slot is consecutive (starts when previous ends)
        if slot.start == current_end:
            # Extend the current range
            current_end = slot.end
        else:
            # Gap found, save current range and start new one
            from app.services.availability import Slot
            consolidated.append(Slot(start=current_start, end=current_end))
            current_start = slot.start
            current_end = slot.end
    
    # Don't forget the last range
    from app.services.availability import Slot
    consolidated.append(Slot(start=current_start, end=current_end))
    
    return consolidated


def _flatten_slots(batch):
    ordered_dates = sorted(batch.slots_by_date.keys())
    slots = []
    for day in ordered_dates:
        daily = sorted(batch.slots_by_date[day], key=lambda s: s.start)
        slots.extend(daily)
    return slots

@app.route('/api/user/info', methods=['GET', 'OPTIONS'])
def get_user_info():
    """Get current user info for Chrome extension authentication check"""
    
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        origin = request.headers.get('Origin')
        if origin and origin.startswith('chrome-extension://'):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return response
    
    try:
        response_data = {'authenticated': False}
        status_code = 200
        
        if current_user.is_authenticated:
            response_data = {
                'id': current_user.id,
                'email': current_user.email,
                'username': current_user.username,
                'timezone': current_user.timezone,
                'authenticated': True
            }
        else:
            # Check if we have a valid token but no user (new user case)
            user, email = _resolve_extension_user()
            if user:
                response_data = {
                    'id': user.id,
                    'email': user.email,
                    'username': user.username,
                    'timezone': user.timezone,
                    'authenticated': True
                }
            elif email:
                # Valid token, but user not in DB -> Needs onboarding
                # We return authenticated=True so the extension proceeds to try fetching data
                # which will then trigger the SETUP_REQUIRED error and redirect
                response_data = {
                    'id': None,
                    'email': email,
                    'username': None,
                    'timezone': 'UTC',
                    'authenticated': True
                }
        
        response = jsonify(response_data)
        add_cors_headers_for_extension(response)
        return response, status_code
        
    except Exception as e:
        response = jsonify({'error': 'Failed to get user info', 'authenticated': False})
        add_cors_headers_for_extension(response)
        return response, 500


@app.route('/api/extension/availability_text', methods=['GET', 'OPTIONS'])
def extension_availability_text():
    """Return formatted availability text for the Chrome extension."""

    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        add_cors_headers_for_extension(response)
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return response

    user, email = _resolve_extension_user()
    if not user:
        if email:
            # Valid token but user not found -> Redirect to onboarding
            response = jsonify({
                'error': 'SETUP_REQUIRED',
                'message': 'Welcome! Please complete your setup to use the extension.',
                'setup_url': url_for('onboarding_routes.onboarding', _external=True)
            })
            add_cors_headers_for_extension(response)
            return response, 403

        response = jsonify({'error': 'Authentication required'})
        add_cors_headers_for_extension(response)
        return response, 401

    # Extract access token from Authorization header for calendar operations
    extension_token = None
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        extension_token = auth_header.split(' ')[1]

    event_type = _select_default_event_type(user)
    if not event_type:
        response = jsonify({'error': 'No active event types found'})
        add_cors_headers_for_extension(response)
        return response, 400

    tz = availability_service.get_timezone(user, event_type)
    start_date = datetime.now(tz).date()
    end_date = start_date + timedelta(days=13)

    try:
        availability_batch = availability_service.get_availability_for_range(
            user, event_type, start_date, end_date
        )
    except AvailabilityError as exc:
        if exc.code == 'google_unavailable':
            # This means the user's calendar refresh token is expired/invalid
            response = jsonify({
                'error': 'SETUP_REQUIRED',
                'message': 'Your calendar connection has expired. Please reconnect your Google Calendar.',
                'setup_url': url_for('onboarding_routes.onboarding', _external=True)
            })
            add_cors_headers_for_extension(response)
            return response, 403
            
        response = jsonify({'error': str(exc) or 'Unable to fetch availability'})
        add_cors_headers_for_extension(response)
        return response, 500

    all_slots = _flatten_slots(availability_batch)
    
    # Get number of days to show (default 5)
    days_param = request.args.get('days', 5)
    try:
        days_to_show = max(1, min(14, int(days_param)))
    except (TypeError, ValueError):
        days_to_show = 10
    
    # Filter slots to only those within the next N days
    cutoff_date = start_date + timedelta(days=days_to_show)
    visible_slots = [
        slot for slot in all_slots 
        if slot.start.astimezone(tz).date() < cutoff_date
    ]

    # Consolidate consecutive slots for better readability
    consolidated_slots = _consolidate_consecutive_slots(visible_slots)

    slots_payload = []
    lines = []
    for slot in consolidated_slots:
        display = _format_slot_display(slot, tz)
        slots_payload.append(
            {
                'start': slot.start.isoformat(),
                'end': slot.end.isoformat(),
                'display': display,
            }
        )
        lines.append(f"- {display}")

    if not consolidated_slots:
        response = jsonify(
            {
                'success': False,
                'slots': [],
                'text': 'No availability found in the next two weeks.',
            }
        )
        add_cors_headers_for_extension(response)
        return response, 200

    text_header = f"Here are some options for {event_type.title}:"
    text_body = "\n".join(lines)
    response = jsonify(
        {
            'success': True,
            'event_type': {
                'id': event_type.id,
                'title': event_type.title,
                'duration_minutes': event_type.duration_minutes,
            },
            'slots': slots_payload,
            'text': f"{text_header}\n{text_body}",
        }
    )
    add_cors_headers_for_extension(response)
    return response, 200


@app.route('/api/extension/booking_link', methods=['GET', 'OPTIONS'])
def extension_booking_link():
    """Return the user's booking link for the Chrome extension."""

    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        add_cors_headers_for_extension(response)
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return response

    user, email = _resolve_extension_user()
    if not user:
        if email:
            response = jsonify({
                'error': 'SETUP_REQUIRED',
                'message': 'Welcome! Please complete your setup.',
                'setup_url': url_for('onboarding_routes.onboarding', _external=True)
            })
            add_cors_headers_for_extension(response)
            return response, 403

        response = jsonify({'error': 'Authentication required'})
        add_cors_headers_for_extension(response)
        return response, 401

    if not user.handle:
        response = jsonify({'error': 'No public handle configured'})
        add_cors_headers_for_extension(response)
        return response, 400

    event_type = _select_default_event_type(user)
    if not event_type or not event_type.slug:
        response = jsonify({'error': 'No public event type available'})
        add_cors_headers_for_extension(response)
        return response, 400

    booking_link = url_for(
        'public_booking.event_type_page',
        handle=user.handle,
        slug=event_type.slug,
        _external=True,
    )

    response = jsonify(
        {
            'success': True,
            'booking_link': booking_link,
            'event_type': {
                'id': event_type.id,
                'slug': event_type.slug,
                'title': event_type.title,
            },
        }
    )
    add_cors_headers_for_extension(response)
    return response, 200


@app.route('/api/extension/contacts', methods=['POST', 'OPTIONS'])
def extension_save_contacts():
    """Accept contacts from the extension and store them in the CRM."""

    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        add_cors_headers_for_extension(response)
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return response

    user, email = _resolve_extension_user()
    if not user:
        if email:
            # For background contact sync, just fail silently/gracefully if not onboarded
            response = jsonify({'error': 'SETUP_REQUIRED'})
            add_cors_headers_for_extension(response)
            return response, 403

        response = jsonify({'error': 'Authentication required'})
        add_cors_headers_for_extension(response)
        return response, 401

    payload = request.get_json(silent=True) or {}
    raw_contacts = payload.get('contacts') or payload.get('emails') or []
    if isinstance(raw_contacts, dict):
        raw_contacts = [raw_contacts]
    if isinstance(raw_contacts, str):
        raw_contacts = [raw_contacts]

    processed = []
    created_count = 0
    for entry in raw_contacts:
        if isinstance(entry, str):
            email = entry
            name = None
        else:
            email = entry.get('email') if entry else None
            name = entry.get('name') if isinstance(entry, dict) else None
        if not email:
            continue
        normalized = email.strip().lower()
        if not normalized:
            continue
        existing = Contact.query.filter_by(user_id=user.id, email=normalized).first()
        contact = contact_service.ensure_contact(
            user,
            normalized,
            display_name=name,
            first_seen_source='chrome_extension',
            first_seen_at=datetime.utcnow(),
        )
        
        if contact:
            contact_service.record_interaction(
                contact,
                outgoing=True,
                occurred_at=datetime.utcnow()
            )

        created = existing is None and contact is not None
        if created:
            created_count += 1
        processed.append({'email': normalized, 'name': name, 'created': created})

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error saving contacts: {e}")
        response = jsonify({'error': 'Database error'})
        add_cors_headers_for_extension(response)
        return response, 500

    response = jsonify(
        {
            'success': True,
            'processed': len(processed),
            'created': created_count,
            'contacts': processed,
        }
    )
    add_cors_headers_for_extension(response)
    return response, 200

@app.route('/api/user/timezone', methods=['POST', 'OPTIONS'])
def update_user_timezone():
    """Update user's timezone (for future use)"""
    
    # Handle CORS preflight
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        add_cors_headers_for_extension(response)
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return response
    
    # Check authentication explicitly for API endpoint
    user, email = _resolve_extension_user()
    if not user:
        if email:
             # Valid token but user not found -> Redirect to onboarding
            response = jsonify({
                'error': 'SETUP_REQUIRED',
                'message': 'Welcome! Please complete your setup.',
                'setup_url': url_for('onboarding_routes.onboarding', _external=True)
            })
            add_cors_headers_for_extension(response)
            return response, 403

        response = jsonify({'error': 'Authentication required'})
        add_cors_headers_for_extension(response)
        return response, 401
    
    try:
        data = request.get_json()
        new_timezone = data.get('timezone', 'UTC')
        
        # Validate timezone string (basic validation)
        if not new_timezone or not isinstance(new_timezone, str):
            response = jsonify({'error': 'Invalid timezone format'})
            add_cors_headers_for_extension(response)
            return response, 400
        
        # Only update if timezone is different (optimization)
        if user.timezone != new_timezone:
            user.timezone = new_timezone
            db.session.commit()
            
            response_data = {
                'success': True,
                'timezone': new_timezone,
                'message': f'Timezone updated to {new_timezone}'
            }
        else:
            response_data = {
                'success': True,
                'timezone': user.timezone,
                'message': 'Timezone unchanged (already current)'
            }
        
        response = jsonify(response_data)
        add_cors_headers_for_extension(response)
        return response, 200
        
    except Exception as e:
        response = jsonify({'error': 'Failed to update timezone'})
        add_cors_headers_for_extension(response)
        return response, 500

@app.route('/api/extension/process', methods=['POST', 'OPTIONS'])
def extension_process_events():
    """
    Process text and/or attachments from Chrome extension.
    Reuses existing processing pipeline with cleaner API interface.
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        add_cors_headers_for_extension(response)
        # Also allow headers needed for file upload
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-User-Email'
        return response

    try:
        # Resolve user using shared helper
        user, email = _resolve_extension_user()
        if not user:
            if email:
                response = jsonify({
                    'error': 'SETUP_REQUIRED',
                    'code': 'SETUP_REQUIRED',
                    'message': 'Please complete setup',
                    'setup_url': url_for('onboarding_routes.onboarding', _external=True)
                })
                add_cors_headers_for_extension(response)
                return response, 403

            response = jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'})
            add_cors_headers_for_extension(response)
            return response, 401

        # Extract text input
        text_input = ''
        source_info = 'Chrome Extension'
        
        if request.content_type and request.content_type.startswith('application/json'):
            data = request.get_json() or {}
            text_input = data.get('text', '')
            source_info = data.get('source', 'Chrome Extension')
        else:
            text_input = request.form.get('stripped-text', '')
            source_info = request.form.get('Subject', 'Chrome Extension Text Input')

        if not text_input.strip():
            response = jsonify({'error': 'No text provided to process', 'code': 'NO_TEXT'})
            add_cors_headers_for_extension(response)
            return response, 400

        # Format text for processing (similar to email format)
        formatted_text = f"From: {user.email}\nSource: {source_info}\n\n{text_input}"

        # Process attachments if present (screenshots)
        attachments_data = []
        if request.files:
            for field_name, file_obj in request.files.items():
                if file_obj and file_obj.filename:
                    file_content = file_obj.read()
                    attachment_info = {
                        'name': file_obj.filename,
                        'content-type': file_obj.content_type or 'image/png',
                        'size': len(file_content),
                        'content': file_content
                    }
                    attachments_data.append(attachment_info)

        # Auto-sync if user has Google authentication
        auto_sync = user.google_id is not None
        
        # Import here to avoid circular imports
        from app.services.event_processing import process_text_to_events

        # Process using existing pipeline
        result = process_text_to_events(
            formatted_text,
            user,
            source_type="chrome_extension",
            auto_sync=auto_sync
        )

        # Process attachments if present
        total_attachment_events = 0
        total_attachment_synced = 0
        
        if attachments_data:
            from app.services.attachment_processor import attachment_processor
            
            text_input_record = result.get('text_input')
            if text_input_record:
                processed_attachments = attachment_processor.process_email_attachments(
                    text_input_record, attachments_data, auto_sync=True
                )
                
                # Count attachment events
                for attachment in processed_attachments:
                    if attachment and hasattr(attachment, 'extracted_events_count'):
                        attachment_events = attachment.extracted_events_count or 0
                        total_attachment_events += attachment_events
                        
                        # Count synced events from this attachment
                        from app.models import Event
                        attachment_synced_events = Event.query.filter_by(
                            user_id=user.id,
                            text_input_id=text_input_record.id,
                            is_synced=True
                        ).filter(
                            Event.extracted_at >= attachment.created_at
                        ).count()
                        total_attachment_synced += attachment_synced_events

        # Calculate totals
        text_events = len(result.get('events', []))
        text_synced = result.get('synced_count', 0)
        
        total_events = text_events + total_attachment_events
        total_synced = text_synced + total_attachment_synced

        # Return structured response
        response_data = {
            'status': 'success',
            'text_events_extracted': text_events,
            'attachment_events_extracted': total_attachment_events,
            'total_events_extracted': total_events,
            'total_events_synced': total_synced,
            'auto_sync_enabled': auto_sync,
            'attachments_processed': len(attachments_data),
            'user_id': user.id,
            'message': f'Successfully extracted {total_events} events' + 
                      (f', {total_synced} synced to calendar' if auto_sync else '')
        }

        response = jsonify(response_data)
        add_cors_headers_for_extension(response)
        return response, 200

    except Exception as e:
        # Log error but don't crash
        print(f"Chrome extension API error: {str(e)}")
        response = jsonify({
            'error': 'Processing failed',
            'code': 'PROCESSING_ERROR',
            'message': str(e)
        })
        add_cors_headers_for_extension(response)
        return response, 500


# ==============================================================================
# Email Tracking Endpoints
# ==============================================================================

@app.route('/api/tracking/pixel/<tracking_id>', methods=['GET'])
def tracking_pixel(tracking_id):
    """
    Serves tracking pixel and records open event.
    PUBLIC endpoint - no authentication required.
    """
    # Record event asynchronously (don't block pixel response)
    try:
        tracking_service.record_tracking_event(
            tracking_id=tracking_id,
            ip_address=request.headers.get('X-Forwarded-For', request.remote_addr),
            user_agent=request.headers.get('User-Agent')
        )
    except Exception as e:
        app.logger.error(f"Error recording tracking event: {e}")

    # Return 1x1 transparent GIF
    gif_bytes = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')
    return send_file(
        io.BytesIO(gif_bytes),
        mimetype='image/gif',
        max_age=0
    )


@app.route('/api/tracking/requests', methods=['POST', 'OPTIONS'])
def create_tracking_request():
    """
    Creates a new tracking request.
    Request body: {
        "tracking_id": "abc123...",
        "subject": "Meeting follow-up",
        "recipients": [{"email": "...", "name": "..."}],
        "cc_recipients": [...],
        "gmail_message_id": "...",
        "gmail_thread_id": "..."
    }
    """
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        add_cors_headers_for_extension(response)
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response

    user, email = _resolve_extension_user()

    if not user:
        response = jsonify({
            'error': 'Authentication required',
            'code': 'AUTH_REQUIRED'
        })
        add_cors_headers_for_extension(response)
        return response, 401

    try:
        data = request.get_json()

        tracking_request = tracking_service.create_tracking_request(
            user=user,
            tracking_id=data['tracking_id'],
            subject=data.get('subject'),
            recipients=data['recipients'],
            cc_recipients=data.get('cc_recipients'),
            bcc_recipients=data.get('bcc_recipients'),
            gmail_message_id=data.get('gmail_message_id'),
            gmail_thread_id=data.get('gmail_thread_id')
        )

        response = jsonify({
            'success': True,
            'tracking_request': tracking_request.to_dict()
        })
        add_cors_headers_for_extension(response)
        return response

    except Exception as e:
        app.logger.error(f"Error creating tracking request: {e}")
        response = jsonify({
            'error': 'Failed to create tracking request',
            'code': 'CREATE_FAILED',
            'message': str(e)
        })
        add_cors_headers_for_extension(response)
        return response, 500


@app.route('/api/tracking/requests', methods=['GET', 'OPTIONS'])
def get_tracking_requests():
    """
    Get last 50 tracking requests (no pagination, no filtering).
    Returns basic list with new_opens_count for badge notification.
    """
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        add_cors_headers_for_extension(response)
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response

    user, email = _resolve_extension_user()

    if not user:
        response = jsonify({
            'error': 'Authentication required',
            'code': 'AUTH_REQUIRED'
        })
        add_cors_headers_for_extension(response)
        return response, 401

    try:
        since = request.args.get('since')  # For polling - get events since last check

        # Get recent tracking requests
        # Import here to avoid circular dependency
        from sqlalchemy.orm import joinedload

        if since:
            # Parse the since timestamp
            try:
                since_dt = datetime.fromisoformat(since.replace('Z', ''))
                # Only get tracking requests with new opens since 'since' timestamp
                # This makes polling more efficient by only returning updated data
                # Eager load recipients to avoid N+1 queries (events use lazy='dynamic' so can't eager load)
                requests_query = TrackingRequest.query.options(
                    joinedload(TrackingRequest.recipients).joinedload(TrackingRecipient.contact)
                ).filter(
                    TrackingRequest.user_id == user.id,
                    TrackingRequest.is_active == True,
                    TrackingRequest.last_opened_at > since_dt
                ).order_by(TrackingRequest.sent_at.desc()).limit(50).all()

                app.logger.info(f"Fetching tracking requests with opens since {since_dt} - found {len(requests_query)} requests")
            except (ValueError, TypeError) as e:
                app.logger.warning(f"Invalid 'since' parameter: {since} - {e}")
                # Fall back to getting all recent requests
                requests_query = TrackingRequest.query.options(
                    joinedload(TrackingRequest.recipients).joinedload(TrackingRecipient.contact)
                ).filter_by(
                    user_id=user.id,
                    is_active=True
                ).order_by(TrackingRequest.sent_at.desc()).limit(50).all()
        else:
            # First load - get all recent requests (last 50, no time filter)
            requests_query = TrackingRequest.query.options(
                joinedload(TrackingRequest.recipients).joinedload(TrackingRecipient.contact)
            ).filter(
                TrackingRequest.user_id == user.id,
                TrackingRequest.is_active == True
            ).order_by(TrackingRequest.sent_at.desc()).limit(50).all()

            app.logger.info(f"First load - fetching last 50 tracking requests - found {len(requests_query)} requests")

        # Count new opens since user last viewed dashboard (for badge)
        new_opens_count = 0
        if user.tracking_last_viewed_at:
            # Count events since last viewed (using > to exclude exact timestamp)
            new_opens_count = db.session.query(db.func.count(TrackingEvent.id)).join(
                TrackingRequest
            ).filter(
                TrackingRequest.user_id == user.id,
                TrackingEvent.opened_at > user.tracking_last_viewed_at
            ).scalar() or 0
        else:
            # Never viewed dashboard - count all events
            new_opens_count = db.session.query(db.func.count(TrackingEvent.id)).join(
                TrackingRequest
            ).filter(
                TrackingRequest.user_id == user.id
            ).scalar() or 0

        # Include events data for popup UI (limit to first event for performance)
        response = jsonify({
            'success': True,
            'requests': [req.to_dict(include_events=True) for req in requests_query],
            'new_opens_count': new_opens_count,  # For badge notification
            'tracking_last_viewed_at': user.tracking_last_viewed_at.isoformat() + 'Z' if user.tracking_last_viewed_at else None
        })
        add_cors_headers_for_extension(response)
        return response

    except Exception as e:
        app.logger.error(f"Error fetching tracking requests: {e}")
        response = jsonify({
            'error': 'Failed to fetch tracking requests',
            'code': 'FETCH_FAILED',
            'message': str(e)
        })
        add_cors_headers_for_extension(response)
        return response, 500


@app.route('/api/tracking/mark-viewed', methods=['POST', 'OPTIONS'])
def mark_tracking_viewed():
    """
    Mark tracking dashboard as viewed (updates user.tracking_last_viewed_at).
    This clears the unread count.
    """
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        add_cors_headers_for_extension(response)
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response

    user, email = _resolve_extension_user()

    if not user:
        response = jsonify({
            'error': 'Authentication required',
            'code': 'AUTH_REQUIRED'
        })
        add_cors_headers_for_extension(response)
        return response, 401

    try:
        # Update tracking_last_viewed_at to now
        user.tracking_last_viewed_at = datetime.utcnow()
        db.session.commit()

        response = jsonify({
            'success': True,
            'tracking_last_viewed_at': user.tracking_last_viewed_at.isoformat() + 'Z'
        })
        add_cors_headers_for_extension(response)
        return response

    except Exception as e:
        app.logger.error(f"Error marking tracking as viewed: {e}")
        db.session.rollback()
        response = jsonify({
            'error': 'Failed to mark as viewed',
            'code': 'UPDATE_FAILED',
            'message': str(e)
        })
        add_cors_headers_for_extension(response)
        return response, 500


@app.route('/api/contacts/<int:contact_id>/engagement', methods=['GET', 'OPTIONS'])
def get_contact_engagement(contact_id):
    """Get email tracking engagement for a specific contact."""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        add_cors_headers_for_extension(response)
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response

    user, email = _resolve_extension_user()

    if not user:
        response = jsonify({
            'error': 'Authentication required',
            'code': 'AUTH_REQUIRED'
        })
        add_cors_headers_for_extension(response)
        return response, 401

    try:
        contact = Contact.query.filter_by(id=contact_id, user_id=user.id).first()

        if not contact:
            response = jsonify({
                'error': 'Contact not found',
                'code': 'NOT_FOUND'
            })
            add_cors_headers_for_extension(response)
            return response, 404

        # Get all tracked emails sent to this contact
        tracked_emails = db.session.query(TrackingRequest).join(
            TrackingRecipient
        ).filter(
            TrackingRecipient.contact_id == contact.id
        ).order_by(TrackingRequest.sent_at.desc()).limit(20).all()

        response = jsonify({
            'success': True,
            'contact': {
                'id': contact.id,
                'email': contact.email,
                'display_name': contact.display_name,
                'emails_received': contact.emails_received,
                'emails_opened': contact.emails_opened,
                'open_rate': contact.email_open_rate,
                'last_email_opened_at': contact.last_email_opened_at.isoformat() if contact.last_email_opened_at else None
            },
            'recent_emails': [
                {
                    'subject': req.subject,
                    'sent_at': req.sent_at.isoformat(),
                    'opened': req.first_opened_at is not None,
                    'open_count': req.open_count
                }
                for req in tracked_emails
            ]
        })
        add_cors_headers_for_extension(response)
        return response

    except Exception as e:
        app.logger.error(f"Error fetching contact engagement: {e}")
        response = jsonify({
            'error': 'Failed to fetch contact engagement',
            'code': 'FETCH_FAILED',
            'message': str(e)
        })
        add_cors_headers_for_extension(response)
        return response, 500
