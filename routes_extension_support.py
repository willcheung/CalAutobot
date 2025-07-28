"""
Extension support routes for Chrome extension integration
"""

from flask import jsonify, session
from flask_login import current_user
from app import app

@app.route('/api/user/info', methods=['GET'])
def get_user_info():
    """Get current user info for Chrome extension authentication check"""
    try:
        if current_user.is_authenticated:
            return jsonify({
                'id': current_user.id,
                'email': current_user.email,
                'username': current_user.username,
                'authenticated': True
            })
        else:
            return jsonify({'authenticated': False}), 401
    except Exception as e:
        return jsonify({'error': 'Failed to get user info', 'authenticated': False}), 500