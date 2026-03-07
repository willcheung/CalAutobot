"""AI CEO Dashboard - Public metrics for CalAutobot"""
import logging
import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify
from sqlalchemy import func
from app import db
from app.models import User, Event, NewsletterSubscriber

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)

# Stripe integration for real revenue data
try:
    import stripe
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
    if not stripe.api_key:
        stripe = None
        logger.warning("STRIPE_SECRET_KEY not set - revenue will show $0")
except ImportError:
    stripe = None
    logger.warning("Stripe library not installed")


def get_stripe_revenue():
    """Fetch real revenue data from Stripe API"""
    if stripe is None:
        return {"total": 0, "mrr": 0, "last_30d": 0, "verified": False}
    
    try:
        # Get balance transactions for revenue calculation
        # Note: This is simplified - real MRR requires subscription tracking
        now = datetime.utcnow()
        thirty_days_ago = int((now - timedelta(days=30)).timestamp())
        
        # Fetch successful charges from last 30 days
        charges = stripe.Charge.list(
            limit=100,
            created={'gte': thirty_days_ago},
            expand=['data.balance_transaction']
        )
        
        last_30d = 0
        for charge in charges.auto_paging_iter():
            if charge.status == 'succeeded' and charge.paid:
                # Convert from cents to dollars
                last_30d += charge.amount / 100
        
        # For MRR, we'd need subscription data - for now use last 30d as proxy
        # In future, track actual subscriptions
        mrr = last_30d  # Simplified: assume last 30d revenue ≈ MRR for one-time products
        
        # Total revenue (all time) - fetch all successful charges
        all_charges = stripe.Charge.list(limit=100)
        total = 0
        for charge in all_charges.auto_paging_iter():
            if charge.status == 'succeeded' and charge.paid:
                total += charge.amount / 100
        
        return {
            "total": total,
            "mrr": mrr,
            "last_30d": last_30d,
            "verified": True  # Data came from Stripe API
        }
    except Exception as e:
        logger.error(f"Failed to fetch Stripe revenue: {e}")
        return {"total": 0, "mrr": 0, "last_30d": 0, "verified": False}


def get_x_followers():
    """Get X/Twitter follower count - stored in env or file"""
    # For now, read from a simple file that can be updated
    # In future, integrate with X API
    try:
        follower_file = "/root/.openclaw/workspace/.x_followers"
        if os.path.exists(follower_file):
            with open(follower_file, 'r') as f:
                data = f.read().strip()
                if data:
                    return int(data)
    except:
        pass
    return 2  # Default known value


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
        
        # Revenue (from Stripe API)
        revenue = get_stripe_revenue()
        
        # X/Twitter followers
        x_followers = get_x_followers()
        
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
            "x_twitter": {
                "followers": x_followers,
                "target": 1000
            },
            "revenue": revenue,
            "goals": {
                "users_30d": {"target": 100, "current": new_users_30d},
                "mrr_90d": {"target": 1000, "current": revenue["mrr"]},
                "revenue_1y": {"target": 1000000, "current": revenue["total"]},
                "x_followers": {"target": 1000, "current": x_followers}
            }
        })
        
    except Exception as e:
        logger.error(f"Dashboard metrics error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
