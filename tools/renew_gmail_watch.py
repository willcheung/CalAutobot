#!/usr/bin/env python3
"""
Renew the Gmail push watch if it is missing or near expiration.

Environment variables:
  - GMAIL_PUSH_TOPIC (required): Full Pub/Sub topic name.
  - GMAIL_PUSH_LABEL_IDS (optional): Comma-separated label IDs.
  - GMAIL_PUSH_EMAIL_ADDRESS (optional): Mailbox email; defaults to 'me'.
"""

import logging
import os
import sys
from datetime import datetime

sys.path.append(".")

from app import app  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def main():
    topic_name = os.environ.get("GMAIL_PUSH_TOPIC")
    if not topic_name:
        logger.error("GMAIL_PUSH_TOPIC environment variable is required")
        sys.exit(1)

    raw_labels = os.environ.get("GMAIL_PUSH_LABEL_IDS", "")
    label_ids = [label.strip() for label in raw_labels.split(",") if label.strip()]
    email_address = os.environ.get("GMAIL_PUSH_EMAIL_ADDRESS", "me")

    logger.info("Ensuring Gmail watch is active for %s", email_address)
    logger.info("Using topic %s", topic_name)
    if label_ids:
        logger.info("Label IDs: %s", label_ids)

    with app.app_context():
        from app.services.gmail_push_processor import renew_watch_if_needed

        response = renew_watch_if_needed(
            topic_name=topic_name,
            label_ids=label_ids or None,
            email_address=email_address,
        )

        if response:
            history_id = response.get("historyId")
            expiration_ms = response.get("expiration")
            expiration = None
            if expiration_ms:
                try:
                    expiration = datetime.utcfromtimestamp(int(expiration_ms) / 1000.0)
                except (TypeError, ValueError):
                    expiration = None
            logger.info(
                "Gmail watch renewed (historyId=%s, expires=%s)",
                history_id,
                expiration.isoformat() if expiration else "unknown",
            )
        else:
            logger.info("Existing Gmail watch is still valid; no renewal performed")


if __name__ == "__main__":
    main()
