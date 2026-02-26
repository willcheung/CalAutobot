"""Newsletter subscription routes for Cal's Daily Briefing"""
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for
from app import db
from app.models import NewsletterSubscriber
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

newsletter_bp = Blueprint("newsletter", __name__)


@newsletter_bp.route("/subscribe", methods=["POST"])
def subscribe():
    """Handle newsletter subscription - API endpoint"""
    data = request.get_json() if request.is_json else request.form
    
    email = data.get("email", "").strip().lower()
    name = data.get("name", "").strip() if data.get("name") else None
    source = data.get("source", "website")
    
    if not email:
        if request.is_json:
            return jsonify({"success": False, "error": "Email is required"}), 400
        flash("Email is required", "error")
        return redirect(request.referrer or url_for("main_routes.index"))
    
    # Basic email validation
    if "@" not in email or "." not in email.split("@")[-1]:
        if request.is_json:
            return jsonify({"success": False, "error": "Invalid email address"}), 400
        flash("Invalid email address", "error")
        return redirect(request.referrer or url_for("main_routes.index"))
    
    try:
        # Check if already subscribed
        existing = NewsletterSubscriber.query.filter_by(email=email).first()
        
        if existing:
            if existing.is_active:
                msg = "You're already subscribed to Cal's Daily Briefing!"
                if request.is_json:
                    return jsonify({"success": True, "message": msg})
                flash(msg, "info")
                return redirect(request.referrer or url_for("main_routes.index"))
            else:
                # Reactivate unsubscribed user
                existing.is_active = True
                existing.unsubscribed_at = None
                if name:
                    existing.name = name
                db.session.commit()
                msg = "Welcome back! You've been resubscribed to Cal's Daily Briefing."
                if request.is_json:
                    return jsonify({"success": True, "message": msg})
                flash(msg, "success")
                return redirect(request.referrer or url_for("main_routes.index"))
        
        # Create new subscriber
        subscriber = NewsletterSubscriber(
            email=email,
            name=name,
            source=source,
            is_active=True
        )
        db.session.add(subscriber)
        db.session.commit()
        
        logger.info(f"New newsletter subscriber: {email} (source: {source})")
        
        msg = "You're subscribed! Check your inbox for Cal's next Daily Briefing."
        if request.is_json:
            return jsonify({"success": True, "message": msg, "subscriber_id": subscriber.id})
        flash(msg, "success")
        return redirect(request.referrer or url_for("main_routes.index"))
        
    except IntegrityError:
        db.session.rollback()
        msg = "You're already subscribed!"
        if request.is_json:
            return jsonify({"success": True, "message": msg})
        flash(msg, "info")
        return redirect(request.referrer or url_for("main_routes.index"))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Newsletter subscription error: {e}")
        if request.is_json:
            return jsonify({"success": False, "error": "Something went wrong. Please try again."}), 500
        flash("Something went wrong. Please try again.", "error")
        return redirect(request.referrer or url_for("main_routes.index"))


@newsletter_bp.route("/unsubscribe", methods=["GET", "POST"])
def unsubscribe():
    """Handle newsletter unsubscription"""
    if request.method == "GET":
        email = request.args.get("email", "").strip().lower()
    else:
        data = request.get_json() if request.is_json else request.form
        email = data.get("email", "").strip().lower()
    
    if not email:
        if request.is_json:
            return jsonify({"success": False, "error": "Email is required"}), 400
        return render_template("newsletter/unsubscribe.html", error="Email is required")
    
    subscriber = NewsletterSubscriber.query.filter_by(email=email).first()
    
    if not subscriber or not subscriber.is_active:
        msg = "You're not currently subscribed."
        if request.is_json:
            return jsonify({"success": True, "message": msg})
        return render_template("newsletter/unsubscribe.html", message=msg)
    
    subscriber.is_active = False
    subscriber.unsubscribed_at = datetime.utcnow()
    db.session.commit()
    
    logger.info(f"Newsletter unsubscribe: {email}")
    
    msg = "You've been unsubscribed from Cal's Daily Briefing."
    if request.is_json:
        return jsonify({"success": True, "message": msg})
    return render_template("newsletter/unsubscribe.html", message=msg)


@newsletter_bp.route("/subscribers/count")
def subscriber_count():
    """Get the current subscriber count - public API"""
    count = NewsletterSubscriber.query.filter_by(is_active=True).count()
    return jsonify({"count": count})


@newsletter_bp.route("/briefing", methods=["GET"])
def briefing_page():
    """Landing page for Cal's Daily Briefing subscription"""
    count = NewsletterSubscriber.query.filter_by(is_active=True).count()
    return render_template("newsletter/briefing.html", subscriber_count=count)
