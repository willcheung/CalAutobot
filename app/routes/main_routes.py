import logging
import math
import os
import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import User, Event, UserEmail, CalWaitlist, Contact, ContactLabel
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_auth_requests
from app.services.google_calendar import (
    create_calendar_event,
    update_calendar_event,
    delete_calendar_event,
    check_user_has_calendar_scope,
)
from datetime import datetime
import sentry_sdk
from sqlalchemy import func, or_, and_
import pytz
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

# Import helper modules
from app.services.event_processing import process_text_to_events
from app.helpers.event_utils import (
    prepare_event_data_for_calendar,
    update_event_from_form,
    format_event_for_api,
    get_event_start_datetime,
    get_event_source_display,
    truncate_text,
    extract_meeting_link,
)
from app.helpers.domain_utils import (
    get_base_url,
    get_mailgun_forward_email,
    is_production,
    is_development,
)
from app.services.follow_up_service import send_due_followups
from app.services import availability as availability_service
from app.services.reminder_service import send_due_reminders

logger = logging.getLogger(__name__)

main_routes = Blueprint("main_routes", __name__)

def calendar_needs_connection():
    """Check if the current user needs to (re)connect their Google Calendar"""
    from flask_login import current_user
    
    if not current_user.is_authenticated:
        return False
    
    # No token at all
    if not current_user.google_token:
        return True
    
    # Has token but no refresh token - will eventually fail
    if not current_user.google_refresh_token:
        return True
    
    return False

@main_routes.app_context_processor
def inject_domain_utils():
    """Make domain utility functions available in templates"""
    return {
        'get_base_url': get_base_url,
        'get_mailgun_forward_email': get_mailgun_forward_email,
        'is_production': is_production,
        'is_development': is_development,
        'calendar_needs_connection': calendar_needs_connection
    }

@main_routes.route("/health")
def health_check():
    """Health check endpoint for deployment"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}, 200

@main_routes.route("/health/db")
def db_health_check():
    """Database health check endpoint"""
    try:
        # Test database connection
        result = db.session.execute(db.text('SELECT 1 as test')).fetchone()

        # Get some basic stats
        user_count = db.session.execute(db.text('SELECT COUNT(*) FROM "user"')).scalar()
        event_count = db.session.execute(db.text('SELECT COUNT(*) FROM event')).scalar()

        return {
            "status": "healthy", 
            "database": "connected",
            "test_query": result[0] if result else None,
            "user_count": user_count,
            "event_count": event_count,
            "timestamp": datetime.utcnow().isoformat()
        }, 200
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        return {
            "status": "unhealthy", 
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }, 500

@main_routes.route("/webhook/check-emails", methods=["GET", "POST"])
def webhook_check_emails():
    """Webhook endpoint for automated email checking via external cron services"""
    try:
        # Basic security: check for API key
        api_key = request.args.get('key') or request.headers.get('X-API-Key')
        expected_key = os.environ.get('WEBHOOK_API_KEY', 'calendar-ai-webhook-2024')
        
        if api_key != expected_key:
            logger.warning(f"❌ Unauthorized webhook access attempt from {request.remote_addr}")
            return {
                "status": "error",
                "message": "Unauthorized access"
            }, 401
        
        logger.info("🔄 Email check webhook triggered")
        
        # Import here to avoid circular dependencies
        from app.services.gmail_processor import check_new_emails
        from app.services.gmail_service import GmailOAuthError
        
        # Run the email check
        check_new_emails()
        
        logger.info("✅ Email check webhook completed successfully")
        return {
            "status": "success",
            "message": "Email check completed",
            "timestamp": datetime.utcnow().isoformat()
        }, 200
        
    except GmailOAuthError as e:
        logger.error(f"❌ Gmail OAuth authentication failed: {str(e)}")
        sentry_sdk.capture_exception(e)
        return {
            "status": "error",
            "message": f"Gmail authentication failed: {str(e)}",
            "error_type": "oauth_error",
            "timestamp": datetime.utcnow().isoformat()
        }, 503  # Service Unavailable - indicates service dependency (Gmail OAuth) is down
        
    except Exception as e:
        logger.error(f"❌ Email check webhook failed: {str(e)}")
        sentry_sdk.capture_exception(e)
        return {
            "status": "error",
            "message": f"Email check failed: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }, 500


@main_routes.route("/webhook/follow-ups", methods=["GET", "POST"])
def webhook_follow_ups():
    """Webhook endpoint for automated follow-up emails."""
    try:
        api_key = request.args.get('key') or request.headers.get('X-API-Key')
        expected_key = os.environ.get('WEBHOOK_API_KEY', 'calendar-ai-webhook-2024')

        if api_key != expected_key:
            logger.warning(f"❌ Unauthorized follow-up webhook access attempt from {request.remote_addr}")
            return {
                "status": "error",
                "message": "Unauthorized access"
            }, 401

        logger.info("🔄 Follow-up webhook triggered")
        result = send_due_followups()
        logger.info(
            "✅ Follow-up webhook completed (processed=%s, sent=%s)",
            result.get("processed"),
            result.get("sent"),
        )
        return {
            "status": "success",
            "processed": result.get("processed"),
            "sent": result.get("sent"),
            "timestamp": datetime.utcnow().isoformat()
        }, 200
    except Exception as exc:
        logger.error(f"❌ Follow-up webhook failed: {str(exc)}")
        sentry_sdk.capture_exception(exc)
        return {
            "status": "error",
            "message": f"Follow-up processing failed: {str(exc)}",
            "timestamp": datetime.utcnow().isoformat()
        }, 500


@main_routes.route("/webhook/reminders", methods=["GET", "POST"])
def webhook_reminders():
    """Webhook endpoint for upcoming meeting reminders."""
    try:
        api_key = request.args.get('key') or request.headers.get('X-API-Key')
        expected_key = os.environ.get('WEBHOOK_API_KEY', 'calendar-ai-webhook-2024')

        if api_key != expected_key:
            logger.warning(f"❌ Unauthorized reminder webhook access attempt from {request.remote_addr}")
            return {
                "status": "error",
                "message": "Unauthorized access"
            }, 401

        logger.info("🔄 Reminder webhook triggered")
        result = send_due_reminders()
        logger.info(
            "✅ Reminder webhook completed (processed=%s, sent=%s)",
            result.get("processed"),
            result.get("sent"),
        )
        return {
            "status": "success",
            "processed": result.get("processed"),
            "sent": result.get("sent"),
            "timestamp": datetime.utcnow().isoformat()
        }, 200
    except Exception as exc:
        logger.error(f"❌ Reminder webhook failed: {str(exc)}")
        sentry_sdk.capture_exception(exc)
        return {
            "status": "error",
            "message": f"Reminder processing failed: {str(exc)}",
            "timestamp": datetime.utcnow().isoformat()
        }, 500

def _verify_pubsub_request():
    """
    Validate the Pub/Sub push authentication token when configured.
    If no expected values are set, accept the request (useful for local testing).
    """
    expected_service_account = os.environ.get("GMAIL_PUSH_SERVICE_ACCOUNT_EMAIL")
    expected_audience = os.environ.get("GMAIL_PUSH_AUDIENCE")

    if not expected_service_account and not expected_audience:
        return True

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        logger.warning("Missing Bearer token on Gmail push request")
        return False

    token = auth_header.split(" ", 1)[1].strip()
    try:
        request_adapter = google_auth_requests.Request()
        token_info = google_id_token.verify_oauth2_token(
            token,
            request_adapter,
            audience=expected_audience if expected_audience else None
        )
    except Exception as exc:
        logger.warning("Failed to verify Gmail push token: %s", exc)
        return False

    if expected_service_account and token_info.get("email") != expected_service_account:
        logger.warning(
            "Gmail push token email mismatch (got %s, expected %s)",
            token_info.get("email"),
            expected_service_account,
        )
        return False

    return True

@main_routes.route("/webhook/gmail/push", methods=["GET", "POST"])
def gmail_push_webhook():
    """
    Pub/Sub push endpoint for Gmail history notifications.
    Respond quickly with 204 to acknowledge receipt.
    """
    try:
        if request.method == "GET":
            # Allow manual verification or uptime probes with a shared token.
            expected_token = os.environ.get("GMAIL_PUSH_VERIFICATION_TOKEN")
            if expected_token:
                provided = request.args.get("token")
                if provided != expected_token:
                    logger.warning("Gmail push verification token mismatch")
                    return {"status": "error", "message": "unauthorized"}, 403
            challenge = request.args.get("challenge", "")
            return (challenge or "", 200)

        if not _verify_pubsub_request():
            return {"status": "error", "message": "unauthorized"}, 403

        envelope = request.get_json(silent=True) or {}
        if not envelope.get("message"):
            logger.warning("Received Gmail push request without message payload")
            return ("", 204)

        from app.services.gmail_push_processor import (
            enqueue_history_message,
            handle_history_message,
        )

        try:
            if enqueue_history_message(envelope):
                return ("", 204)
        except Exception as exc:
            logger.exception(
                "Failed to enqueue Gmail push task; falling back to inline processing: %s",
                exc,
            )

        handle_history_message(envelope)
        return ("", 204)

    except Exception as exc:
        logger.exception("Gmail push webhook failed: %s", exc)
        return {
            "status": "error",
            "message": f"Gmail push processing failed: {str(exc)}",
        }, 500

@main_routes.route("/webhook/gmail/renew-watch", methods=["POST"])
def gmail_renew_watch_webhook():
    """
    Endpoint for external cron to ensure Gmail watch is active.
    Uses same API key guard as the legacy polling webhook.
    """
    try:
        api_key = request.args.get("key") or request.headers.get("X-API-Key")
        expected_key = os.environ.get("WEBHOOK_API_KEY", "calendar-ai-webhook-2024")
        if api_key != expected_key:
            logger.warning("Unauthorized Gmail watch renewal attempt from %s", request.remote_addr)
            return {"status": "error", "message": "Unauthorized access"}, 401

        topic_name = os.environ.get("GMAIL_PUSH_TOPIC")
        if not topic_name:
            return (
                {
                    "status": "error",
                    "message": "GMAIL_PUSH_TOPIC must be configured to renew watch",
                },
                500,
            )

        raw_label_ids = os.environ.get("GMAIL_PUSH_LABEL_IDS", "")
        label_ids = [label.strip() for label in raw_label_ids.split(",") if label.strip()]
        email_address = os.environ.get("GMAIL_PUSH_EMAIL_ADDRESS", "me")

        from app.services.gmail_push_processor import renew_watch_if_needed

        response = renew_watch_if_needed(
            topic_name=topic_name,
            label_ids=label_ids or None,
            email_address=email_address,
        )

        if response:
            history_id = response.get("historyId")
            expiration_ms = response.get("expiration")
            expiration_iso = None
            if expiration_ms:
                try:
                    expiration_iso = datetime.utcfromtimestamp(int(expiration_ms) / 1000.0).isoformat()
                except (TypeError, ValueError):
                    expiration_iso = None
            return {
                "status": "success",
                "message": "Gmail watch renewed",
                "historyId": history_id,
                "expiresAt": expiration_iso,
            }, 200

        return {
            "status": "success",
            "message": "Existing Gmail watch still valid",
        }, 200

    except Exception as exc:
        logger.exception("Gmail watch renewal failed: %s", exc)
        return {
            "status": "error",
            "message": f"Failed to renew Gmail watch: {str(exc)}",
        }, 500

@main_routes.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main_routes.bookings"))
    return render_template("index.html", show_landing_header=True)

@main_routes.route("/waitlist", methods=["POST"])
def join_waitlist():
    """Capture waitlist submissions for premium plans."""
    redirect_url = url_for("main_routes.index") + "#pricing"
    email = (request.form.get("waitlist_email") or "").strip()
    wants_json = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes["application/json"] >= request.accept_mimetypes["text/html"]
    )

    def respond(message, category="success", status=200):
        if wants_json:
            return jsonify({"status": category, "message": message}), status
        flash(message, category)
        return redirect(redirect_url)

    if not email:
        return respond("Please enter your email to join the waitlist.", "error", 400)

    email_normalized = email.lower()
    email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    if not re.match(email_pattern, email_normalized):
        return respond("Please enter a valid email address.", "error", 400)

    try:
        existing = CalWaitlist.query.filter(func.lower(CalWaitlist.email) == email_normalized).first()
        if existing:
            return respond("You're already on the waitlist! We'll be in touch soon.", "info", 200)

        waitlist_entry = CalWaitlist(email=email_normalized)
        db.session.add(waitlist_entry)
        db.session.commit()
        return respond("Thanks! We'll reach out when the Small Business plan opens up.", "success", 201)
    except IntegrityError:
        db.session.rollback()
        return respond("You're already on the waitlist! We'll be in touch soon.", "info", 200)
    except Exception as exc:
        db.session.rollback()
        logger.exception("Failed to save waitlist submission: %s", exc)
        return respond("Something went wrong. Please try again in a moment.", "error", 500)

@main_routes.route("/image-to-calendar")
def image_to_calendar():
    return render_template("image_to_calendar.html", show_landing_header=True)

@main_routes.route("/signup")
def signup():
    """Landing page that detects timezone and redirects to Google OAuth"""
    return render_template("signup_redirect.html")

@main_routes.route("/bookings")
@login_required
def bookings():
    status = request.args.get("status", "upcoming").lower()
    if status not in {"upcoming", "past", "cancelled"}:
        status = "upcoming"

    page = request.args.get("page", type=int, default=1)
    page = max(page, 1)
    per_page = 25

    now_utc = datetime.utcnow().replace(microsecond=0)
    user_tz = availability_service.get_timezone(current_user)
    now_local = now_utc.replace(tzinfo=pytz.UTC).astimezone(user_tz)
    now_date = now_local.date()
    now_time = now_local.time().replace(microsecond=0)
    base_query = Event.query.filter_by(user_id=current_user.id)

    upcoming_filter = or_(
        Event.start_date > now_date,
        and_(
            Event.start_date == now_date,
            or_(
                Event.start_time.is_(None),
                and_(Event.start_time.isnot(None), Event.start_time >= now_time),
            ),
        ),
    )

    past_filter = or_(
        Event.start_date < now_date,
        and_(
            Event.start_date == now_date,
            Event.start_time.isnot(None),
            Event.start_time < now_time,
        ),
    )

    # Build status-specific query with SQL filtering and sorting
    if status == "cancelled":
        query = base_query.filter(Event.status == "cancelled").order_by(
            Event.start_date.desc(), Event.start_time.desc(), Event.created_at.desc()
        )
    elif status == "past":
        query = base_query.filter(
            Event.status != "cancelled",
            past_filter,
        ).order_by(
            Event.start_date.desc(), Event.start_time.desc(), Event.created_at.desc()
        )
    else:  # upcoming
        query = base_query.filter(
            Event.status != "cancelled",
            upcoming_filter,
        ).order_by(
            Event.start_date.asc(), Event.start_time.asc(), Event.created_at.asc()
        )

    # Paginate at database level
    pagination_obj = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Build display events only for current page
    display_events = []
    for event in pagination_obj.items:
        start_dt = get_event_start_datetime(event)
        source_label, badge_class, source_key = get_event_source_display(event)
        full_description = (event.event_description or "").strip()
        description_preview, is_truncated = truncate_text(full_description, 200)
        meeting_link = extract_meeting_link(event)
        display_events.append(
            {
                "event": event,
                "start_dt": start_dt,
                "source_label": source_label,
                "badge_class": badge_class,
                "source_key": source_key,
                "description": full_description,
                "description_preview": description_preview,
                "is_truncated": is_truncated,
                "meeting_link": meeting_link,
            }
        )

    pagination = {
        "page": pagination_obj.page,
        "pages": pagination_obj.pages,
        "has_prev": pagination_obj.has_prev,
        "has_next": pagination_obj.has_next,
        "total": pagination_obj.total,
    }

    # Efficient COUNT queries for tab badges
    counts = {
        "upcoming": base_query.filter(
            Event.status != "cancelled",
            upcoming_filter,
        ).count(),
        "past": base_query.filter(
            Event.status != "cancelled",
            past_filter,
        ).count(),
        "cancelled": base_query.filter(Event.status == "cancelled").count(),
    }

    has_calendar_scope = check_user_has_calendar_scope(current_user)

    return render_template(
        "bookings.html",
        events=display_events,
        status=status,
        pagination=pagination,
        counts=counts,
        has_calendar_scope=has_calendar_scope,
    )


@main_routes.route("/contacts")
@login_required
def contacts_page():
    search_query = (request.args.get("q") or "").strip()
    label_filter = request.args.get("label", type=int)

    contacts_query = (
        Contact.query.options(selectinload(Contact.labels))
        .filter_by(user_id=current_user.id)
    )

    if search_query:
        term = f"%{search_query.lower()}%"
        contacts_query = contacts_query.filter(
            or_(
                func.lower(Contact.display_name).like(term),
                func.lower(Contact.email).like(term),
                func.lower(Contact.company).like(term),
                func.lower(Contact.job_title).like(term),
            )
        )

    if label_filter:
        contacts_query = contacts_query.join(Contact.labels).filter(ContactLabel.id == label_filter)

    contacts = (
        contacts_query.order_by(
            Contact.last_interaction_at.desc(),
            Contact.created_at.desc(),
        )
        .limit(200)
        .all()
    )

    labels = (
        ContactLabel.query.filter_by(user_id=current_user.id)
        .order_by(ContactLabel.name.asc())
        .all()
    )

    return render_template(
        "contacts/index.html",
        contacts=contacts,
        labels=labels,
        search_query=search_query,
        active_label_id=label_filter,
    )


@main_routes.route("/dashboard")
@login_required
def dashboard_redirect():
    """Legacy /dashboard endpoint redirecting to bookings"""
    return redirect(url_for("main_routes.bookings"), code=301)

@main_routes.route("/extract_events", methods=["POST"])
@login_required
def extract_events():
    try:
        text = request.form.get("text", "").strip()

        if not text:
            logger.warning(f"User {current_user.id} submitted empty text")
            flash("Please enter some text to extract events from.", "error")
            return redirect(url_for("main_routes.bookings"))

        # Process text to events using helper function
        result = process_text_to_events(text, current_user, source_type="manual", auto_sync=True)

        events_count = len(result['events'])
        synced_count = result['synced_count']

        if 'offline_extraction' in result and result['offline_extraction']:
            flash("AI service timed out. Extracting events offline. Results may be less accurate.", "warning")

        if events_count > 0:
            if synced_count > 0:
                flash(f"Successfully extracted {events_count} event(s) and synced {synced_count} to your Cal Event Extraction calendar!", "success")
            else:
                flash(f"Successfully extracted {events_count} event(s)! Events are ready for manual sync.", "success")
        else:
            flash("No valid events could be extracted from the text.", "warning")

    except ValueError as ve:
        logger.warning(f"Validation error for user {current_user.id}: {str(ve)}")
        flash(str(ve), "error")

    except Exception as e:
        logger.error(f"Event extraction failed for user {current_user.id}: {str(e)}")
        sentry_sdk.capture_exception(e)

        # Show user-friendly error message based on error type
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "429" in error_msg:
            flash("AI service is busy. Please wait a moment and try again.", "error")
        elif "authentication" in error_msg or "401" in error_msg:
            flash("AI service authentication issue. Please contact support.", "error")
        elif "network" in error_msg or "timeout" in error_msg:
            flash("Network connection issue. Please check your connection and try again.", "error")
        else:
            flash("Unable to extract events from the text. Please try rephrasing or shortening your text.", "error")

    return redirect(url_for("main_routes.bookings"))

@main_routes.route("/edit_event/<int:event_id>")
@login_required
def edit_event(event_id):
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()
    return render_template("event_form.html", event=event)

@main_routes.route("/update_event/<int:event_id>", methods=["POST"])
@login_required
def update_event(event_id):
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()

    try:
        # Update event using helper function
        update_event_from_form(event, request.form)

        # Update in Google Calendar if already synced
        if event.is_synced and event.google_event_id:
            try:
                event_data = prepare_event_data_for_calendar(event)

                if update_calendar_event(
                    current_user,
                    event.google_event_id,
                    event_data,
                    use_extraction_calendar=True,
                ):
                    flash("Event updated successfully in both database and Google Calendar!", "success")
                else:
                    flash("Event updated in database, but failed to update in Google Calendar.", "warning")
            except Exception as e:
                flash(f"Event updated in database, but Google Calendar update failed: {str(e)}", "warning")
        else:
            flash("Event updated successfully!", "success")

        db.session.commit()

    except Exception as e:
        logger.error(f"Error updating event {event_id} for user {current_user.id}: {str(e)}", exc_info=True)
        sentry_sdk.capture_exception(e)
        db.session.rollback()
        flash(f"Error updating event: {str(e)}", "error")

    return redirect(url_for("main_routes.bookings"))

@main_routes.route("/sync_to_calendar/<int:event_id>", methods=["POST"])
@login_required
def sync_to_calendar(event_id):
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()

    if event.is_synced:
        flash("Event is already synced to Google Calendar.", "info")
        return redirect(url_for("main_routes.bookings"))

    try:
        event_data = prepare_event_data_for_calendar(event)
        google_event_id = create_calendar_event(
            current_user,
            event_data,
            use_extraction_calendar=True,
        )

        event.google_event_id = google_event_id
        event.is_synced = True
        db.session.commit()

        flash("Event successfully added to Google Calendar!", "success")

    except Exception as e:
        logger.error(f"Error syncing event {event_id} to calendar for user {current_user.id}: {str(e)}", exc_info=True)
        sentry_sdk.capture_exception(e)
        flash(f"Error syncing to Google Calendar: {str(e)}", "error")

    return redirect(url_for("main_routes.bookings"))

def delete_event_internal(event, user, skip_google_calendar=False):
    """
    Internal function to delete an event from database and optionally Google Calendar.
    
    Args:
        event: Event object to delete
        user: User object who owns the event
        skip_google_calendar: If True, skip Google Calendar deletion (used for webhook deletions)
    
    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    try:
        # Delete from Google Calendar if synced and not skipping
        if not skip_google_calendar and event.is_synced and event.google_event_id:
            try:
                delete_calendar_event(
                    user,
                    event.google_event_id,
                    use_extraction_calendar=True,
                )
            except Exception as e:
                logger.warning(f"Failed to delete event {event.id} from Google Calendar: {str(e)}")
                # Continue with database deletion even if Google Calendar deletion fails

        # Delete from database
        db.session.delete(event)
        db.session.commit()
        
        logger.info(f"Successfully deleted event {event.id} ({event.event_name}) for user {user.id}")
        return True, None

    except Exception as e:
        logger.error(f"Error deleting event {event.id} for user {user.id}: {str(e)}", exc_info=True)
        sentry_sdk.capture_exception(e)
        db.session.rollback()
        return False, str(e)

@main_routes.route("/delete_event/<int:event_id>", methods=["POST"])
@login_required
def delete_event(event_id):
    event = Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()

    success, error_message = delete_event_internal(event, current_user, skip_google_calendar=False)
    
    if success:
        flash("Event deleted successfully!", "success")
    else:
        flash(f"Error deleting event: {error_message}", "error")

    return redirect(url_for("main_routes.bookings"))

@main_routes.route('/terms')
def terms():
    """Display Terms of Service page"""
    return render_template('terms.html')

@main_routes.route('/privacy')
def privacy():
    """Display Privacy Policy page"""
    return render_template('privacy.html')

@main_routes.route("/add_email", methods=["POST"])
@login_required
def add_email():
    """Add an additional email address to the user's account via AJAX"""
    try:
        # Check if it's an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        email = request.form.get("email", "").lower().strip()
        
        if not email:
            error_msg = "Please enter a valid email address."
            if is_ajax:
                return jsonify({"success": False, "error": error_msg}), 400
            flash(error_msg, "error")
            return redirect(url_for("main_routes.bookings"))
        
        # Validate email format
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            error_msg = "Please enter a valid email address format."
            if is_ajax:
                return jsonify({"success": False, "error": error_msg}), 400
            flash(error_msg, "error")
            return redirect(url_for("main_routes.bookings"))
        
        # Check if email is already the user's primary email
        if email == current_user.email:
            error_msg = "This is already your primary email address."
            if is_ajax:
                return jsonify({"success": False, "error": error_msg}), 400
            flash(error_msg, "warning")
            return redirect(url_for("main_routes.bookings"))
        
        # Optimized single query to check all email conflicts at once
        # Check if email already exists for this user OR any other user (primary or additional)
        existing_user_email = User.query.filter(User.email == email, User.extraction_calendar_id != None).first()
        existing_user_additional = UserEmail.query.filter_by(user_id=current_user.id, email=email).first()
        
        if existing_user_additional:
            error_msg = "This email is already added to your account."
            if is_ajax:
                return jsonify({"success": False, "error": error_msg}), 400
            flash(error_msg, "warning")
            return redirect(url_for("main_routes.bookings"))
        
        if existing_user_email:
            error_msg = "This email is already associated with another account."
            if is_ajax:
                return jsonify({"success": False, "error": error_msg}), 400
            flash(error_msg, "error")
            return redirect(url_for("main_routes.bookings"))
        
        # Add the email
        user_email = UserEmail(user_id=current_user.id, email=email)
        db.session.add(user_email)
        db.session.commit()
        
        success_msg = f"Email {email} added successfully! Emails sent to this address will now be processed for your calendar."
        
        if is_ajax:
            return jsonify({
                "success": True, 
                "message": success_msg,
                "email": {
                    "id": user_email.id,
                    "email": user_email.email,
                    "created_at": user_email.created_at.isoformat()
                }
            }), 200
            
        flash(success_msg, "success")
        
    except Exception as e:
        logger.error(f"Error adding email for user {current_user.id}: {str(e)}")
        sentry_sdk.capture_exception(e)
        db.session.rollback()
        error_msg = "Error adding email. Please try again."
        
        if is_ajax:
            return jsonify({"success": False, "error": error_msg}), 500
        flash(error_msg, "error")
    
    return redirect(url_for("main_routes.bookings"))

@main_routes.route("/remove_email/<int:email_id>", methods=["POST"])
@login_required
def remove_email(email_id):
    """Remove an additional email address from the user's account"""
    try:
        # Check if it's an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        user_email = UserEmail.query.filter_by(id=email_id, user_id=current_user.id).first_or_404()
        
        email_address = user_email.email
        db.session.delete(user_email)
        db.session.commit()
        
        success_msg = f"Email {email_address} removed successfully."
        
        if is_ajax:
            return jsonify({"success": True, "message": success_msg}), 200
            
        flash(success_msg, "success")
        
    except Exception as e:
        logger.error(f"Error removing email {email_id} for user {current_user.id}: {str(e)}")
        sentry_sdk.capture_exception(e)
        db.session.rollback()
        error_msg = "Error removing email. Please try again."
        
        if is_ajax:
            return jsonify({"success": False, "error": error_msg}), 500
        flash(error_msg, "error")
    
    return redirect(url_for("main_routes.bookings"))

@main_routes.route("/api/extract_events", methods=["POST"])
@login_required
def api_extract_events():
    """
    API endpoint for extracting events from text.
    Can be used by external services, webhooks, or programmatic access.
    """
    try:
        # Get JSON data from request
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        text = data.get("text", "").strip()
        if not text:
            return jsonify({"error": "Text field is required"}), 400

        source_type = data.get("source_type", "api")
        auto_sync = data.get("auto_sync", True)

        # Process text to events using helper function
        result = process_text_to_events(text, current_user, source_type=source_type, auto_sync=auto_sync)

        # Format response using helper function
        events_data = [format_event_for_api(event) for event in result['events']]

        response = {
            'success': True,
            'text_input_id': result['text_input'].id,
            'events_count': len(result['events']),
            'synced_count': result['synced_count'],
            'from_email': result['from_email'],
            'events': events_data
        }

        if 'offline_extraction' in result and result['offline_extraction']:
            response['offline_extraction'] = True

        return jsonify(response), 200

    except ValueError as ve:
        logger.warning(f"API validation error for user {current_user.id}: {str(ve)}")
        return jsonify({"error": str(ve)}), 400

    except Exception as e:
        logger.error(f"API event extraction failed for user {current_user.id}: {str(e)}")
        sentry_sdk.capture_exception(e)

        # Return appropriate error response
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "429" in error_msg:
            return jsonify({"error": "AI service is busy. Please try again later."}), 429
        elif "authentication" in error_msg or "401" in error_msg:
            return jsonify({"error": "AI service authentication failed."}), 503
        else:
            return jsonify({"error": "Failed to process text. Please try again."}), 500
