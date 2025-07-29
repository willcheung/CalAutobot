"""
Extension support routes for Chrome extension integration
"""

from flask import jsonify, session, request
from flask_login import current_user
from app import app

@app.route('/api/user/info', methods=['GET', 'OPTIONS'])
def get_user_info():
    """Get current user info for Chrome extension authentication check"""
    
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response
    
    try:
        response_data = {'authenticated': False}
        status_code = 200
        
        if current_user.is_authenticated:
            response_data = {
                'id': current_user.id,
                'email': current_user.email,
                'username': current_user.username,
                'authenticated': True
            }
        
        response = jsonify(response_data)
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, status_code
        
    except Exception as e:
        response = jsonify({'error': 'Failed to get user info', 'authenticated': False})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 500