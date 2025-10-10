#!/usr/bin/env python3
"""
Migration: create gmail_push_state table.

Run with: python tools/migrations/20240910_add_gmail_push_state.py

Creates the table if it is missing and exits cleanly if it already exists.
"""

import logging
import sys

sys.path.append(".")

from app import app, db  # noqa: E402
from app.models import GmailPushState  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    with app.app_context():
        logger.info("Creating gmail_push_state table if missing")
        GmailPushState.__table__.create(bind=db.engine, checkfirst=True)
        logger.info("Done")


if __name__ == "__main__":
    main()
