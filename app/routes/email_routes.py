"""
Email Summarization API Routes

Provides endpoints for email summaries and sender pattern tracking.
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app import db
from app.services.email_summarizer import (
    summarize_email,
    get_sender_patterns_by_category,
    get_high_priority_senders
)
from app.models import EmailSummary
import logging

logger = logging.getLogger(__name__)

email_bp = Blueprint('email', __name__, url_prefix='/api/email')


@email_bp.route('/summarize', methods=['POST'])
@login_required
def summarize():
    """
    Summarize an email text without saving to database.
    
    Request body:
    {
        "text": "email content...",
        "from_email": "optional@sender.com"
    }
    
    Returns:
    {
        "summary": "...",
        "category": "...",
        "priority_score": 5,
        "action_required": false,
        "action_description": null,
        "sender_email": "...",
        "sender_domain": "...",
        "sender_name": "..."
    }
    """
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'error': 'Text is required'}), 400
        
        text = data.get('text', '')
        from_email = data.get('from_email')
        
        if not text.strip():
            return jsonify({'error': 'Text cannot be empty'}), 400
        
        result = summarize_email(text, from_email)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error summarizing email: {str(e)}")
        return jsonify({'error': str(e)}), 500


@email_bp.route('/summaries', methods=['GET'])
@login_required
def get_summaries():
    """
    Get email summaries for the current user.
    
    Query params:
    - category: Filter by category
    - limit: Number of results (default 20, max 100)
    
    Returns:
    {
        "summaries": [...]
    }
    """
    try:
        category = request.args.get('category')
        limit = min(int(request.args.get('limit', 20)), 100)
        
        query = EmailSummary.query.filter_by(user_id=current_user.id)
        
        if category:
            query = query.filter_by(category=category)
        
        summaries = query.order_by(EmailSummary.created_at.desc()).limit(limit).all()
        
        return jsonify({
            'summaries': [s.to_dict() for s in summaries]
        })
        
    except Exception as e:
        logger.error(f"Error getting summaries: {str(e)}")
        return jsonify({'error': str(e)}), 500


@email_bp.route('/senders', methods=['GET'])
@login_required
def get_senders():
    """
    Get sender patterns for the current user.
    
    Query params:
    - category: Filter by category
    - min_priority: Minimum average priority score
    
    Returns:
    {
        "senders": [...]
    }
    """
    try:
        category = request.args.get('category')
        min_priority = request.args.get('min_priority')
        
        if min_priority:
            try:
                min_priority = float(min_priority)
                senders = get_high_priority_senders(current_user.id, min_priority)
            except ValueError:
                senders = get_sender_patterns_by_category(current_user.id, category)
        else:
            senders = get_sender_patterns_by_category(current_user.id, category)
        
        return jsonify({
            'senders': senders
        })
        
    except Exception as e:
        logger.error(f"Error getting senders: {str(e)}")
        return jsonify({'error': str(e)}), 500


@email_bp.route('/senders/categories', methods=['GET'])
@login_required
def get_sender_categories():
    """
    Get sender counts grouped by category.
    
    Returns:
    {
        "categories": {
            "newsletter": 5,
            "promotion": 10,
            "personal": 2,
            ...
        }
    }
    """
    try:
        from app.models import SenderPattern
        from sqlalchemy import func
        
        results = db.session.query(
            SenderPattern.category,
            func.count(SenderPattern.id).label('count')
        ).filter(
            SenderPattern.user_id == current_user.id,
            SenderPattern.category.isnot(None)
        ).group_by(SenderPattern.category).all()
        
        categories = {r.category: r.count for r in results}
        
        return jsonify({
            'categories': categories
        })
        
    except Exception as e:
        logger.error(f"Error getting sender categories: {str(e)}")
        return jsonify({'error': str(e)}), 500


@email_bp.route('/priority', methods=['GET'])
@login_required
def get_priority_emails():
    """
    Get high-priority emails that need action.
    
    Query params:
    - min_priority: Minimum priority score (default 7)
    - limit: Number of results (default 10)
    
    Returns:
    {
        "emails": [...]
    }
    """
    try:
        min_priority = int(request.args.get('min_priority', 7))
        limit = min(int(request.args.get('limit', 10)), 50)
        
        emails = EmailSummary.query.filter(
            EmailSummary.user_id == current_user.id,
            EmailSummary.priority_score >= min_priority
        ).order_by(
            EmailSummary.priority_score.desc(),
            EmailSummary.created_at.desc()
        ).limit(limit).all()
        
        return jsonify({
            'emails': [e.to_dict() for e in emails]
        })
        
    except Exception as e:
        logger.error(f"Error getting priority emails: {str(e)}")
        return jsonify({'error': str(e)}), 500
