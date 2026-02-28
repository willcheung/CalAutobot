"""AI CEO Dashboard - Public metrics for CalAutobot"""
import logging
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify
from sqlalchemy import func
from app import db
from app.models import User, Event, NewsletterSubscriber

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def public_dashboard():
    """Public AI CEO Dashboard - Cal's metrics in real-time"""
    return render_template("dashboard/index.html")


@dashboard_bp.route("/api/metrics")
def get_metrics():
    """API endpoint for dashboard metrics"""
    try:
        # User metrics
        total_users = User.query.count()
        
        # Users created in last 30 days
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        new_users_30d = User.query.filter(User.created_at >= thirty_days_ago).count()
        
        # Users created in last 7 days
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        new_users_7d = User.query.filter(User.created_at >= seven_days_ago).count()
        
        # Event metrics
        total_events = Event.query.count()
        
        # Events created in last 30 days
        events_30d = Event.query.filter(Event.created_at >= thirty_days_ago).count()
        
        # Events by status
        scheduled_events = Event.query.filter_by(status='scheduled').count()
        completed_events = Event.query.filter_by(status='completed').count()
        cancelled_events = Event.query.filter_by(status='cancelled').count()
        
        # Newsletter subscribers
        active_subscribers = NewsletterSubscriber.query.filter_by(is_active=True).count()
        
        # Users with Google Calendar connected
        users_with_google = User.query.filter(User.google_token.isnot(None)).count()
        
        # Users with Calendly connected
        users_with_calendly = User.query.filter(User.calendly_access_token.isnot(None)).count()
        
        # Daily signups for the last 14 days
        daily_signups = []
        for i in range(13, -1, -1):
            day_start = datetime.utcnow() - timedelta(days=i)
            day_end = day_start + timedelta(days=1)
            count = User.query.filter(
                User.created_at >= day_start,
                User.created_at < day_end
            ).count()
            daily_signups.append({
                "date": day_start.strftime("%Y-%m-%d"),
                "count": count
            })
        
        # Daily events for the last 14 days
        daily_events = []
        for i in range(13, -1, -1):
            day_start = datetime.utcnow() - timedelta(days=i)
            day_end = day_start + timedelta(days=1)
            count = Event.query.filter(
                Event.created_at >= day_start,
                Event.created_at < day_end
            ).count()
            daily_events.append({
                "date": day_start.strftime("%Y-%m-%d"),
                "count": count
            })
        
        # Revenue (placeholder - integrate with Stripe)
        revenue = {
            "total": 0,
            "mrr": 0,
            "last_30d": 0
        }
        
        return jsonify({
            "success": True,
            "timestamp": datetime.utcnow().isoformat(),
            "users": {
                "total": total_users,
                "new_30d": new_users_30d,
                "new_7d": new_users_7d,
                "with_google": users_with_google,
                "with_calendly": users_with_calendly,
                "daily_signups": daily_signups
            },
            "events": {
                "total": total_events,
                "last_30d": events_30d,
                "scheduled": scheduled_events,
                "completed": completed_events,
                "cancelled": cancelled_events,
                "daily_events": daily_events
            },
            "newsletter": {
                "subscribers": active_subscribers
            },
            "revenue": revenue,
            "goals": {
                "users_30d": {"target": 100, "current": new_users_30d},
                "mrr_90d": {"target": 1000, "current": revenue["mrr"]},
                "revenue_1y": {"target": 1000000, "current": revenue["total"]}
            }
        })
        
    except Exception as e:
        logger.error(f"Dashboard metrics error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
