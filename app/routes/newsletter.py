"""Newsletter subscription routes."""

import logging
from flask import Blueprint, request, jsonify, render_template

logger = logging.getLogger(__name__)

newsletter_bp = Blueprint('newsletter', __name__)


@newsletter_bp.route('/subscribe', methods=['POST'])
def subscribe():
    """Handle newsletter subscription."""
    data = request.get_json() or {}
    email = data.get('email')
    
    if not email:
        return jsonify({'error': 'Email required'}), 400
    
    # TODO: Integrate with email provider (beehiiv, etc.)
    logger.info(f"Newsletter subscription: {email}")
    
    return jsonify({'success': True, 'message': 'Subscribed successfully'})
