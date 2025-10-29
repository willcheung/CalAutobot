import json
import os
import logging
from datetime import datetime, date
import re

# the well-rounded OpenAI model is "gpt-4.1-mini".
# do not change this unless explicitly requested by the user
from openai import OpenAI
import sentry_sdk

from app.helpers.datetime_utils import ensure_timezone

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "your-openai-api-key")
openai = OpenAI(api_key=OPENAI_API_KEY)

# Centralized prompt template - single place to edit the extraction prompt
EVENT_EXTRACTION_SYS_PROMPT = """You are an expert at extracting structured calendar events from unstructured text, documents, and images.  Always respond with a valid JSON object. No extra commentary, no explanations.  

Output Schema:
Return a single JSON object with a top-level key "events" containing a list of event objects.  
Each event object must include the following keys (use null if unavailable):  
- "event_name" (string, include traveler name(s) if a flight; append one relevant emoji)  
- "event_description" (string, multi-line human-readable summary with key details)  
- "start_date" (YYYY-MM-DD or null)  
- "start_time" (HH:MM:SS or null)  
- "start_datetime" (RFC3339 combined datetime in **{user_timezone}** timezone or null)  
- "end_date" (YYYY-MM-DD or null)  
- "end_time" (HH:MM:SS or null)  
- "end_datetime" (RFC3339 combined datetime in **{user_timezone}** timezone or null)  
- "location" (string or null)  
- "emoji" (string, one relevant emoji)

If no events are found, return:  
{"events": []}
"""

EVENT_EXTRACTION_PROMPT = """
Extraction rules:
- If text is non-English, retain original language as much as possible. 
- Sometimes the text is content of an email or forwarded email. If it is, use the body of the email for event extraction. If there's an image or document, extract events from the content of the image or document.
- Extract clear "event_name" and add one relevant emoji. 
- Build "event_description" that summarizes this calendar event. Include details like booking codes, confirmation numbers, and other important details for the event. Make description easily human readable with new lines and bullet points.
- Resolve "start_datetime" and "end_datetime" into RFC3339.
- Extract "location" if available.
- Expand recurring events into individual objects.
- Remove duplicates.
- Use user's {user_timezone} timezone.
- Resolve relative dates (e.g., “tomorrow”, “next Monday”) using email sent date if available, else assume current date = {current_date}.

Flight Itineraries:
- Treat each flight leg as an event.
- Use {user_timezone} timezone for traveler’s perspective.
- Extract traveler names; include in "event_name".
- Identify departure/arrival airports (IATA code and city).
- Use their correct IANA timezones (with DST rules) for departure/arrival times.
- "start_datetime" = departure local time converted to traveler’s timezone.
- "end_datetime" = arrival local time converted to traveler’s timezone.
- Always ensure end_datetime > start_datetime.
- "location" = departure airport.
- "event_description" must include:
-- Airline + flight number
-- Departure + arrival airports and times
-- Duration, cabin, aircraft, seat info (if given)
-- Passenger(s) names
-- Confirmation/booking codes
-- Other details (distance, travel agent contact, etc.)
-- Format description with bullet points or new lines.

Input: '''{text}'''"""


def extract_events_from_text(text,
                             current_date=None,
                             user_timezone="UTC",
                             image_data=None):
    """
    Extract events from text using OpenAI API synchronously.

    Args:
        text (str): The input text containing event information
        current_date (str): Current date in YYYY-MM-DD format for resolving relative dates
        user_timezone (str): User's timezone for proper time handling
        image_data (str): Base64 encoded image data for multimodal processing

    Returns:
        tuple: (list of extracted events, from_email, is_offline, openai_status, openai_error)
    """
    if current_date is None:
        tz = ensure_timezone(user_timezone)
        current_date_str = datetime.now(tz).strftime("%Y-%m-%d")
    elif isinstance(current_date, (datetime, date)):
        current_date_str = current_date.strftime("%Y-%m-%d")
    else:
        current_date_str = str(current_date)

    # Check if text appears to be an email and extract from address
    from_email = None
    email_match = re.search(r'From:\s*([^\s<]+@[^\s>]+)', text, re.IGNORECASE)
    if email_match:
        from_email = email_match.group(1)
        logger.info(f"Extracted from email: {from_email}")

    # Build the prompt using the centralized template
    sys_prompt = EVENT_EXTRACTION_SYS_PROMPT
    prompt = EVENT_EXTRACTION_PROMPT.format(user_timezone=user_timezone,
                                            current_date=current_date_str,
                                            text=text)

    try:
        logger.info(f"Extracting events from text of length {len(text)}")

        # Prepare messages for OpenAI API call
        messages = [{"role": "system", "content": sys_prompt}]

        # Add user message with optional image
        if image_data:
            # For multimodal processing with image
            user_message = {
                "role":
                "user",
                "content": [{
                    "type": "text",
                    "text": prompt
                }, {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_data}"
                    }
                }]
            }
            model = "gpt-4.1-mini"
        else:
            # For text-only processing
            user_message = {"role": "user", "content": prompt}
            model = "gpt-4.1-mini"

        messages.append(user_message)

        # Make synchronous OpenAI API call with shorter timeout to prevent worker timeouts
        response = openai.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            timeout=90.0)

        content = response.choices[0].message.content
        if not content:
            raise Exception("Empty response from AI service")

        result = json.loads(content)
        events = result.get("events", [])

        # If text is from email, append from email to event description
        if from_email:
            for event in events:
                if event.get("event_description"):
                    event[
                        "event_description"] = f"{event['event_description']} \n\n(from {from_email})"

        # Add CalAutobot.com branding to all event descriptions
        for event in events:
            if event.get("event_description"):
                event["event_description"] = f"{event['event_description']}\n\n- Created by CalAutobot.com"
            else:
                event["event_description"] = "- Created by CalAutobot.com"

        # Add emojis to event names using OpenAI-generated emoji
        for event in events:
            if event.get("event_name"):
                event["event_name"] = add_emoji_to_event_name(
                    event["event_name"], event.get("emoji"))

        logger.info(
            f"Successfully extracted {len(events)} events via OpenAI API")
        return events, from_email, False, "success", None

    except Exception as e:
        error_msg = str(e)
        logger.error(f"OpenAI API error: {error_msg}")
        sentry_sdk.capture_exception(e)

        # Re-raise the exception to be handled by the calling function
        raise Exception(f"Failed to extract events: {error_msg}")


def validate_and_clean_event(event_data):
    """
    Validate and clean extracted event data.

    Args:
        event_data (dict): Raw event data from extraction

    Returns:
        dict: Cleaned and validated event data
    """

    # Helper function to safely strip strings
    def safe_strip(value, default=''):
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip() or default
        return str(value).strip() or default

    cleaned = {
        'event_name': safe_strip(event_data.get('event_name'),
                                 'Untitled Event'),
        'event_description': safe_strip(event_data.get('event_description'),
                                        ''),
        'start_date': event_data.get('start_date'),
        'start_time': event_data.get('start_time'),
        'end_date': event_data.get('end_date'),
        'end_time': event_data.get('end_time'),
        'location': safe_strip(event_data.get('location'), '')
    }

    # Validate dates
    try:
        if cleaned['start_date']:
            datetime.strptime(cleaned['start_date'], '%Y-%m-%d')
        if cleaned['end_date']:
            datetime.strptime(cleaned['end_date'], '%Y-%m-%d')
    except ValueError as e:
        logger.error(
            f"❌ Date validation failed for event '{cleaned.get('event_name', 'Unknown')}': start_date='{cleaned.get('start_date')}', end_date='{cleaned.get('end_date')}'"
        )
        raise ValueError(f"Invalid date format: {str(e)}")

    # Validate and normalize times
    def normalize_time(time_str):
        if not time_str:
            return None

        time_str = str(time_str).strip()
        if not time_str:
            return None

        # Try multiple time formats
        time_formats = [
            '%H:%M',  # 14:30
            '%I:%M %p',  # 2:30 PM
            '%I:%M%p',  # 2:30PM
            '%H:%M:%S',  # 14:30:00
            '%I:%M:%S %p'  # 2:30:00 PM
        ]

        for fmt in time_formats:
            try:
                parsed_time = datetime.strptime(time_str, fmt)
                return parsed_time.strftime(
                    '%H:%M')  # Always return in 24-hour format
            except ValueError:
                continue

        # If no format matches, log the problematic value and raise error
        logger.error(
            f"Unable to parse time format: '{time_str}' - tried formats: {time_formats}"
        )
        raise ValueError(f"Unable to parse time format: {time_str}")

    try:
        cleaned['start_time'] = normalize_time(cleaned['start_time'])
        cleaned['end_time'] = normalize_time(cleaned['end_time'])
    except ValueError as e:
        logger.error(
            f"❌ Time validation failed for event '{cleaned.get('event_name', 'Unknown')}': start_time='{event_data.get('start_time')}', end_time='{event_data.get('end_time')}'"
        )
        raise ValueError(f"Invalid time format: {str(e)}")

    # Validate RFC3339 datetime strings if present
    def validate_rfc3339_datetime(dt_str):
        if not dt_str:
            return None
        try:
            # Basic validation - ensure it looks like an RFC3339 datetime
            if 'T' in str(dt_str) and ('+' in str(dt_str)
                                       or '-' in str(dt_str)[-6:]):
                return str(dt_str).strip()
            return None
        except Exception:
            return None

    # Validate datetime fields
    cleaned['start_datetime'] = validate_rfc3339_datetime(
        cleaned.get('start_datetime'))
    cleaned['end_datetime'] = validate_rfc3339_datetime(
        cleaned.get('end_datetime'))

    # If end_date is not specified, use start_date
    if cleaned['start_date'] and not cleaned['end_date']:
        cleaned['end_date'] = cleaned['start_date']

    return cleaned


def add_emoji_to_event_name(event_name, emoji=None):
    """
    Add emoji to event name if provided by OpenAI and not already present.

    Args:
        event_name (str): Original event name
        emoji (str): Emoji generated by OpenAI

    Returns:
        str: Event name with emoji prefix if applicable
    """
    if not event_name:
        return event_name

    # If no emoji provided, use default calendar emoji
    if not emoji:
        emoji = "📅"

    # Check if event name already contains an emoji
    # Simple check for common emoji ranges
    import re
    emoji_pattern = re.compile(
        r'[\U0001F600-\U0001F64F]|[\U0001F300-\U0001F5FF]|[\U0001F680-\U0001F6FF]|[\U0001F1E0-\U0001F1FF]|[\U00002600-\U000027BF]|[\U0001F900-\U0001F9FF]'
    )

    if emoji_pattern.search(event_name):
        return event_name

    # Add emoji prefix
    return f"{emoji} {event_name}"
