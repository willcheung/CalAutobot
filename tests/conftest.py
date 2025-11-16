import os
import pathlib

import pytest

# Disable Sentry during tests to prevent test errors from being logged to production
os.environ.pop("SENTRY_DSN", None)

# Allow OAuth over HTTP during tests (oauthlib requires HTTPS by default)
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# Ensure the application boots against a local SQLite database during import-time setup.
DEFAULT_TEST_DB = pathlib.Path("pytest_bootstrap.db")
os.environ["DATABASE_URL"] = f"sqlite:///{DEFAULT_TEST_DB}"

from app import app as flask_app, db  # noqa: E402


@pytest.fixture(scope="session")
def test_app(tmp_path_factory):
    """Create a Flask app instance backed by an isolated SQLite database."""
    db_path = tmp_path_factory.mktemp("data") / "test.db"
    database_url = f"sqlite:///{db_path}"
    os.environ["DATABASE_URL"] = database_url

    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=database_url,
    )

    with flask_app.app_context():
        db.engine.dispose()
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture(autouse=True, scope="function")
def reset_db(test_app):
    """Automatically clear database state between tests to prevent constraint violations."""
    # Run test
    yield
    
    # Clean up after test - just truncate all tables to reset state
    with test_app.app_context():
        try:
            # Fast cleanup: just delete all rows from all tables
            meta = db.metadata
            for table in reversed(meta.sorted_tables):
                db.session.execute(table.delete())
            db.session.commit()
        except Exception:
            db.session.rollback()
        finally:
            db.session.remove()


@pytest.fixture()
def client(test_app):
    """Return a test client for the Flask app."""
    return test_app.test_client()


@pytest.fixture()
def app_context(test_app):
    """Provide an application context for database-bound tests."""
    with test_app.app_context():
        yield
