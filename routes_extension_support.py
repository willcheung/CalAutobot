"""
Extension support routes for Chrome extension integration
"""

from flask import jsonify, session, request
from flask_login import current_user, login_required
from app import app, db

def add_cors_headers_for_extension(response):
    """Add proper CORS headers for Chrome extension requests"""
    origin = request.headers.get('Origin')
    if origin and origin.startswith('chrome-extension://'):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

@app.route('/api/user/info', methods=['GET', 'OPTIONS'])
def get_user_info():
    """Get current user info for Chrome extension authentication check"""
    
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        origin = request.headers.get('Origin')
        if origin and origin.startswith('chrome-extension://'):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return response
    
    try:
        response_data = {'authenticated': False}
        status_code = 200
        
        if current_user.is_authenticated:
            response_data = {
                'id': current_user.id,
                'email': current_user.email,
                'username': current_user.username,
                'timezone': current_user.timezone,
                'authenticated': True
            }
        
        response = jsonify(response_data)
        add_cors_headers_for_extension(response)
        return response, status_code
        
    except Exception as e:
        response = jsonify({'error': 'Failed to get user info', 'authenticated': False})
        add_cors_headers_for_extension(response)
        return response, 500

@app.route('/api/user/timezone', methods=['POST', 'OPTIONS'])
def update_user_timezone():
    """Update user's timezone (for future use)"""
    
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        origin = request.headers.get('Origin')
        if origin and origin.startswith('chrome-extension://'):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return response
    
    # Check authentication explicitly for API endpoint
    if not current_user.is_authenticated:
        response = jsonify({'error': 'Authentication required'})
        add_cors_headers_for_extension(response)
        return response, 401
    
    try:
        data = request.get_json()
        new_timezone = data.get('timezone', 'UTC')
        
        # Validate timezone string (basic validation)
        if not new_timezone or not isinstance(new_timezone, str):
            response = jsonify({'error': 'Invalid timezone format'})
            add_cors_headers_for_extension(response)
            return response, 400
        
        # Only update if timezone is different (optimization)
        if current_user.timezone != new_timezone:
            current_user.timezone = new_timezone
            db.session.commit()
            
            response_data = {
                'success': True,
                'timezone': new_timezone,
                'message': f'Timezone updated to {new_timezone}'
            }
        else:
            response_data = {
                'success': True,
                'timezone': current_user.timezone,
                'message': 'Timezone unchanged (already current)'
            }
        
        response = jsonify(response_data)
        add_cors_headers_for_extension(response)
        return response, 200
        
    except Exception as e:
        response = jsonify({'error': 'Failed to update timezone'})
        add_cors_headers_for_extension(response)
        return response, 500