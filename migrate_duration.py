#!/usr/bin/env python3
"""
Migration script to add duration_minutes column and populate existing events.
"""

import os
import sys
import logging
from app import app, db
from models import Event
from helpers.event_utils import calculate_event_duration_minutes

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_duration():
    """Add duration_minutes column and populate for existing events."""
    with app.app_context():
        try:
            # Create the table with the new column (if needed)
            db.create_all()
            logger.info("Database tables created/updated")
            
            # Check if events exist
            total_events = Event.query.count()
            logger.info(f"Found {total_events} total events in database")
            
            if total_events == 0:
                logger.info("No events found - migration complete")
                return
            
            # Count events without duration
            events_without_duration = Event.query.filter(Event.duration_minutes.is_(None)).count()
            logger.info(f"Found {events_without_duration} events without duration")
            
            if events_without_duration == 0:
                logger.info("All events already have duration calculated - migration complete")
                return
            
            # Process events in batches
            batch_size = 100
            updated_count = 0
            failed_count = 0
            
            offset = 0
            while True:
                events_batch = Event.query.filter(Event.duration_minutes.is_(None)).limit(batch_size).offset(offset).all()
                
                if not events_batch:
                    break
                
                for event in events_batch:
                    try:
                        # Calculate duration
                        duration = calculate_event_duration_minutes(event)
                        event.duration_minutes = duration
                        
                        if duration is not None:
                            logger.info(f"Event {event.id} '{event.event_name}': {duration} minutes")
                            updated_count += 1
                        else:
                            logger.info(f"Event {event.id} '{event.event_name}': No duration (all-day or insufficient data)")
                            updated_count += 1
                            
                    except Exception as e:
                        logger.error(f"Failed to calculate duration for event {event.id}: {str(e)}")
                        failed_count += 1
                
                # Commit batch
                try:
                    db.session.commit()
                    logger.info(f"Committed batch of {len(events_batch)} events")
                except Exception as e:
                    logger.error(f"Failed to commit batch: {str(e)}")
                    db.session.rollback()
                    failed_count += len(events_batch)
                
                offset += batch_size
            
            logger.info(f"Migration complete: {updated_count} events updated, {failed_count} failed")
            
        except Exception as e:
            logger.error(f"Migration failed: {str(e)}")
            db.session.rollback()
            raise

if __name__ == "__main__":
    migrate_duration()