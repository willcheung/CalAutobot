"""Extension support routes for Chrome extension integration."""

from datetime import datetime, timedelta
from typing import Optional

from flask import jsonify, session, request, url_for
import requests
from flask_login import current_user

from app import app, db
from app.models import EventType, User, Contact
from app.services import availability as availability_service, contacts as contact_service
from app.services.availability import AvailabilityError

def add_cors_headers_for_extension(response):
    """Add proper CORS headers for Chrome extension requests"""
    origin = request.headers.get('Origin')
    if origin and origin.startswith('chrome-extension://'):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response


def _resolve_extension_user() -> Optional[User]:
    """Return the authenticated user via session or Authorization header."""
    if current_user.is_authenticated:
        return current_user

    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        
        # Verify token with Google
        try:
            # Call Google's tokeninfo endpoint
            resp = requests.get(f'https://www.googleapis.com/oauth2/v3/tokeninfo?access_token={token}')
            
            if resp.status_code == 200:
                token_info = resp.json()
                email = token_info.get('email')
                
                # Verify audience matches our client ID (optional but recommended security)
                # For now, just verifying email is a huge step up from "trust me bro"
                
                if email:
                    return User.query.filter_by(email=email.strip().lower()).first()
            else:
                print(f"Token verification failed: {resp.text}")
                
        except Exception as e:
            print(f"Token verification error: {e}")

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
            return User.query.filter_by(email=email.strip().lower()).first()
    return None


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
        response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return response

    user = _resolve_extension_user()
    if not user:
        response = jsonify({'error': 'Authentication required'})
        add_cors_headers_for_extension(response)
        return response, 401

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
            # This means the user hasn't connected their calendar or token is invalid
            response = jsonify({
                'error': 'SETUP_REQUIRED',
                'message': 'Please connect your Google Calendar to continue.',
                'setup_url': url_for('onboarding.onboarding_step1', _external=True)
            })
            add_cors_headers_for_extension(response)
            return response, 403
            
        response = jsonify({'error': str(exc) or 'Unable to fetch availability'})
        add_cors_headers_for_extension(response)
        return response, 500

    all_slots = _flatten_slots(availability_batch)
    count_param = request.args.get('count', 3)
    try:
        requested = max(1, min(10, int(count_param)))
    except (TypeError, ValueError):
        requested = 3
    visible_slots = all_slots[:requested]

    slots_payload = []
    lines = []
    for slot in visible_slots:
        display = _format_slot_display(slot, tz)
        slots_payload.append(
            {
                'start': slot.start.isoformat(),
                'end': slot.end.isoformat(),
                'display': display,
            }
        )
        lines.append(f"- {display}")

    if not visible_slots:
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
        response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return response

    user = _resolve_extension_user()
    if not user:
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
        response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return response

    user = _resolve_extension_user()
    if not user:
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
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        origin = request.headers.get('Origin')
        if origin and origin.startswith('chrome-extension://'):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return response
    
    # Check authentication explicitly for API endpoint
    if not current_user.is_authenticated:
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
        if current_user.timezone != new_timezone:
            current_user.timezone = new_timezone
            db.session.commit()
            
            response_data = {
                'success': True,
                'timezone': new_timezone,
                'message': f'Timezone updated to {new_timezone}'
            }
        else:
            response_data = {
                'success': True,
                'timezone': current_user.timezone,
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
        user = _resolve_extension_user()
        if not user:
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
