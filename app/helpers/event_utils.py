
from datetime import datetime, timedelta, timezone
from app.helpers.text_processing import sanitize_text_for_db
import dateutil.parser
import logging

logger = logging.getLogger(__name__)

def prepare_event_data_for_calendar(event):
    """
    Prepare event data for Google Calendar API.
    
    Args:
        event (Event): Event object from database
        
    Returns:
        dict: Event data formatted for Google Calendar
    """
    event_data = {
        'event_name': event.event_name,
        'event_description': event.event_description,
        'location': event.location
    }

    # Use datetime fields if available, otherwise fall back to separate date/time
    if event.start_datetime and event.end_datetime:
        event_data['start_datetime'] = event.start_datetime
        event_data['end_datetime'] = event.end_datetime
    else:
        # Fallback to separate date/time fields
        if event.start_date:
            event_data['start_date'] = event.start_date.strftime('%Y-%m-%d')
        if event.start_time:
            event_data['start_time'] = event.start_time.strftime('%H:%M')
        if event.end_date:
            event_data['end_date'] = event.end_date.strftime('%Y-%m-%d')
        if event.end_time:
            event_data['end_time'] = event.end_time.strftime('%H:%M')

    return event_data

def calculate_event_duration_minutes(event):
    """
    Calculate event duration in minutes from start and end times.
    
    Args:
        event (Event): Event object with start/end datetime or date/time fields
        
    Returns:
        int or None: Duration in minutes, or None if cannot be calculated
    """
    try:
        # Method 1: Use RFC3339 datetime strings if available
        if event.start_datetime and event.end_datetime:
            start_dt = dateutil.parser.parse(event.start_datetime)
            end_dt = dateutil.parser.parse(event.end_datetime)
            duration = end_dt - start_dt
            return int(duration.total_seconds() / 60)
        
        # Method 2: Use separate date/time fields
        if event.start_date and event.end_date:
            # Create datetime objects from date and time
            start_dt = datetime.combine(event.start_date, event.start_time or datetime.min.time())
            
            # For end datetime, use end_date and end_time if available
            if event.end_time:
                end_dt = datetime.combine(event.end_date, event.end_time)
            else:
                # If no end time specified, assume same day event with 1 hour duration
                if event.start_time:
                    # Add 1 hour to start time
                    end_dt = start_dt + timedelta(hours=1)
                else:
                    # If no start time either, assume all-day event (return None or 0)
                    if event.end_date != event.start_date:
                        # Multi-day event - calculate days * 24 hours
                        duration = event.end_date - event.start_date
                        return int(duration.days * 24 * 60)  # Convert days to minutes
                    else:
                        # Single all-day event, return None (cannot calculate meaningful minutes)
                        return None
            
            duration = end_dt - start_dt
            return int(duration.total_seconds() / 60)
            
    except Exception as e:
        logger.warning(f"Could not calculate duration for event {event.id}: {str(e)}")
        return None

    return None

def get_event_start_datetime(event):
    """
    Return a timezone-naive UTC datetime representing the event start.
    """
    try:
        if event.start_datetime:
            dt = dateutil.parser.isoparse(event.start_datetime)
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
    except (ValueError, TypeError) as exc:
        logger.debug("Failed to parse start_datetime for event %s: %s", getattr(event, "id", None), exc)

    if event.start_date:
        base_time = event.start_time or datetime.min.time()
        return datetime.combine(event.start_date, base_time)

    return event.created_at or datetime.utcnow()

def infer_event_source(event):
    """
    Determine the source of an event using stored metadata and fallbacks.
    """
    source = (event.source or "unknown").lower()
    if source != "unknown":
        return source

    if getattr(event, "text_input_id", None):
        return "extracted"
    if getattr(event, "public_token", None):
        return "public_booking"
    return "unknown"

SOURCE_DISPLAY = {
    "extracted": {"label": "Extracted Event", "badge_class": "badge bg-info"},
    "public_booking": {"label": "Public Booking", "badge_class": "badge bg-primary"},
    "ai_booking": {"label": "AI Booking", "badge_class": "badge bg-success"},
    "unknown": {"label": "Manual Entry", "badge_class": "badge bg-secondary"},
    "manual": {"label": "Manual Entry", "badge_class": "badge bg-secondary"},
}

def get_event_source_display(event):
    """
    Return (label, css_class) tuple describing the event source for UI badges.
    """
    source_key = infer_event_source(event)
    meta = SOURCE_DISPLAY.get(source_key, SOURCE_DISPLAY["unknown"])
    return meta["label"], meta["badge_class"], source_key

def update_event_from_form(event, form_data):
    """
    Update event object with form data.
    
    Args:
        event (Event): Event object to update
        form_data (dict): Form data from request
    """
    # Update event fields with sanitization
    event_name = form_data.get("event_name", "").strip() or "Untitled Event"
    event_description = form_data.get("event_description", "").strip()
    location = form_data.get("location", "").strip()

    event.event_name = sanitize_text_for_db(event_name)
    event.event_description = sanitize_text_for_db(event_description)
    event.location = sanitize_text_for_db(location)

    # Parse dates and times
    start_date_str = form_data.get("start_date")
    if start_date_str:
        event.start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()

    start_time_str = form_data.get("start_time")
    if start_time_str:
        event.start_time = datetime.strptime(start_time_str, '%H:%M').time()
    else:
        event.start_time = None

    end_date_str = form_data.get("end_date")
    if end_date_str:
        event.end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        event.end_date = event.start_date

    end_time_str = form_data.get("end_time")
    if end_time_str:
        event.end_time = datetime.strptime(end_time_str, '%H:%M').time()
    else:
        event.end_time = None

    event.updated_at = datetime.utcnow()
    
    # Calculate and update duration in minutes
    event.duration_minutes = calculate_event_duration_minutes(event)

def format_event_for_api(event):
    """
    Format event object for API response.
    
    Args:
        event (Event): Event object from database
        
    Returns:
        dict: Event data formatted for API response
    """
    return {
        'id': event.id,
        'event_name': event.event_name,
        'event_description': event.event_description,
        'start_date': event.start_date.strftime('%Y-%m-%d') if event.start_date else None,
        'start_time': event.start_time.strftime('%H:%M') if event.start_time else None,
        'end_date': event.end_date.strftime('%Y-%m-%d') if event.end_date else None,
        'end_time': event.end_time.strftime('%H:%M') if event.end_time else None,
        'start_datetime': event.start_datetime,
        'end_datetime': event.end_datetime,
        'location': event.location,
        'duration_minutes': event.duration_minutes,
        'is_synced': event.is_synced,
        'google_event_id': event.google_event_id
    }
