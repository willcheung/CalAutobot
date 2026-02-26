import os
import logging
import threading
from datetime import datetime, timedelta

# Load environment variables from .env file (for local development)
# This will safely do nothing in production where .env file doesn't exist
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)

# create the app
app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)
# Security: Session secret must be set via environment variable
# No hardcoded fallback - app will fail to start if not configured
secret_key = os.environ.get("SESSION_SECRET")
if not secret_key:
    if os.environ.get("VERCEL_ENV") == "production":
        raise RuntimeError("SESSION_SECRET environment variable must be set in production")
    # Dev only: generate a random secret for this session
    import secrets
    secret_key = secrets.token_hex(32)
    logger.warning("Using generated SESSION_SECRET for development. Set SESSION_SECRET env var for production.")
app.secret_key = secret_key
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1,
                        x_host=1)  # needed for url_for to generate with https

# configure the database, relative to the app instance folder
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    logger.warning("No DATABASE_URL found, using SQLite fallback")

app.config["SQLALCHEMY_DATABASE_URI"] = database_url

try:
    database_backend = make_url(database_url).get_backend_name()
except Exception:
    database_backend = None

if database_backend == "sqlite":
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
    }
else:
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 280,
        "pool_pre_ping": True,
        "pool_timeout": 30,
        "pool_size": 5,
        "max_overflow": 10,
        "connect_args": {
            "connect_timeout": 30,
            "sslmode": "require",
            "application_name": "calendar_ai",
            "keepalives_idle": "600",
            "keepalives_interval": "30",
            "keepalives_count": "3",
            "options": "-c statement_timeout=30000"
        }
    }

# initialize the app with the extension, flask-sqlalchemy >= 3.0.x
db.init_app(app)


# Database health check function
def check_db_connection():
    """Check if database connection is healthy and attempt to reconnect if needed"""
    try:
        db.session.execute(db.text('SELECT 1'))
        return True
    except Exception as e:
        logger.warning(f"Database connection check failed: {str(e)}")
        try:
            db.session.rollback()
            db.session.close()
        except Exception:
            pass
        return False


# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'google_auth.login'


def renew_webhook_async(user_id):
    """Background task to renew Google Calendar webhook for a user."""
    try:
        # Create new app context and DB session for thread safety
        with app.app_context():
            from app.models import User
            from app.services.google_calendar import (
                setup_calendar_webhook_for_user,
                refresh_google_token,
            )
            
            # Fresh query in this thread's session
            user = User.query.get(user_id)
            if not user or not user.extraction_calendar_id:
                return
            
            # Refresh access token and renew webhook
            access_token = refresh_google_token(user)
            setup_calendar_webhook_for_user(
                user=user,
                access_token=access_token,
                calendar_id=user.extraction_calendar_id,
            )
            logger.info(f"✅ Renewed webhook for {user.email} in background")
            
    except Exception as e:
        logger.warning(f"Background webhook renewal failed for user {user_id}: {e}")


@login_manager.user_loader
def load_user(user_id):
    from app.models import User
    try:
        user = User.query.get(int(user_id))
        
        # Spawn background thread to renew webhook if needed
        if user and user.webhook_expiration:
            renew_threshold = datetime.utcnow() + timedelta(hours=12)
            if user.webhook_expiration <= renew_threshold:
                thread = threading.Thread(
                    target=renew_webhook_async,
                    args=(user.id,),
                    daemon=True
                )
                thread.start()
                logger.info(f"⏰ Spawned background webhook renewal for {user.email}")
        
        return user
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error loading user {user_id}: {str(e)}")
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except ImportError:
            pass
        return None


# Global error handlers
@app.errorhandler(404)
def not_found_error(error):
    logger.warning(f"404 error: {request.url}")
    return render_template('error.html',
                           error_code=404,
                           error_message="Page not found"), 404


@app.errorhandler(405)
def method_not_allowed_error(error):
    logger.error(f"❌ 405 Method Not Allowed: {request.method} {request.path}")
    logger.error(
        f"❌ Available methods: {list(error.valid_methods) if hasattr(error, 'valid_methods') else 'Unknown'}"
    )
    return jsonify({
        'error':
        'Method Not Allowed',
        'method':
        request.method,
        'path':
        request.path,
        'valid_methods':
        list(error.valid_methods) if hasattr(error, 'valid_methods') else []
    }), 405


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {str(error)}")
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(error)
    except ImportError:
        pass
    db.session.rollback()
    return render_template('error.html',
                           error_code=500,
                           error_message="Internal server error"), 500


@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {str(e)}", exc_info=True)
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(e)
    except ImportError:
        pass
    db.session.rollback()

    # Return JSON error for AJAX requests
    if request.is_json:
        return jsonify({
            'error':
            'An unexpected error occurred',
            'message':
            str(e) if app.debug else 'Please try again later'
        }), 500

    # Return HTML error page for regular requests
    return render_template('error.html',
                           error_code=500,
                           error_message="An unexpected error occurred"), 500


@app.route('/health')
def health_check():
    """Simple health check endpoint that responds immediately"""
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()}), 200


@app.before_request
def ensure_user_handle():
    if current_user.is_authenticated and not getattr(current_user, "handle", None):
        from app.services.users import assign_unique_handle

        assign_unique_handle(current_user)
        db.session.commit()


with app.app_context():
    # Make sure to import the models here or their tables won't be created
    from app import models  # noqa: F401

    # Import and register blueprints
    from app.routes.main_routes import main_routes
    from app.routes.google_auth import google_auth
    from app.routes.calendly_auth import calendly_auth
    from app.routes.calendly_webhooks import calendly_webhooks
    from app.routes.google_webhook import google_webhook
    from app.routes.settings import settings_routes
    from app.routes.event_types import event_types_routes
    from app.routes.availability import availability_routes
    from app.routes.public_booking import public_booking
    from app.routes.onboarding import onboarding_routes
    from app.routes.stripe_webhook import stripe_webhook
    from app.routes.newsletter import newsletter_bp

    # Register blueprints
    app.register_blueprint(main_routes)
    app.register_blueprint(google_auth)
    app.register_blueprint(calendly_auth)
    app.register_blueprint(calendly_webhooks)
    # Removed mailgun_webhook blueprint - migrated to Gmail API
    app.register_blueprint(google_webhook)
    app.register_blueprint(settings_routes)
    app.register_blueprint(event_types_routes)
    app.register_blueprint(availability_routes)
    app.register_blueprint(public_booking)
    app.register_blueprint(onboarding_routes)
    app.register_blueprint(stripe_webhook)
    app.register_blueprint(newsletter_bp, url_prefix='/newsletter')



    # Import extension support routes
    from app.routes import extension_support  # noqa: F401
    
    # Initialize Sentry for error tracking (lazy load after app is ready)
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.flask import FlaskIntegration
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
            
            sentry_sdk.init(
                dsn=sentry_dsn,
                traces_sample_rate=1,
                enable_logs=True,
                send_default_pii=True,
                environment=os.environ.get("FLASK_ENV", "production"),
                integrations=[
                    FlaskIntegration(),
                    SqlalchemyIntegration(),
                ]
            )
            logger.info("Sentry initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Sentry: {e}")
    
    # Create tables - skip only if explicitly disabled for faster startup
    # Set SKIP_DB_INIT=true to skip table creation (use only if tables already exist)
    if os.environ.get("SKIP_DB_INIT") != "true":
        try:
            db.create_all()
        except Exception as e:
            logger.warning(f"Database initialization warning: {e}")
