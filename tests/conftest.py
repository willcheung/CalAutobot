import os
import pathlib

import pytest

# Disable Sentry during tests to prevent test errors from being logged to production
os.environ.pop("SENTRY_DSN", None)

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


@pytest.fixture()
def client(test_app):
    """Return a test client for the Flask app."""
    return test_app.test_client()


@pytest.fixture()
def app_context(test_app):
    """Provide an application context for database-bound tests."""
    with test_app.app_context():
        yield
