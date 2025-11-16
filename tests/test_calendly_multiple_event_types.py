"""
Tests for Calendly multiple event types handling.
Tests event type selection logic when user has multiple event types.
"""

import pytest
from datetime import datetime

from app import db
from app.models import User, EventType


@pytest.fixture
def user_with_mixed_event_types(test_app):
    """Create a user with both Calendly and non-Calendly event types."""
    with test_app.app_context():
        user = User(
            username="MixedUser",
            email="mixed@example.com",
            google_id="mixed123",
            calendly_access_token="test_access_token",
            calendly_user_uri="https://api.calendly.com/users/USER123",
            calendly_connected_at=datetime.utcnow(),
        )
        db.session.add(user)
        db.session.commit()

        # Create Calendly event types
        calendly_30 = EventType(
            user_id=user.id,
            slug="cal-30min",
            title="Calendly 30 Min",
            duration_minutes=30,
            calendly_event_type_uri="https://api.calendly.com/event_types/CAL30",
            is_calendly_managed=True,
            is_active=True,
        )
        calendly_60 = EventType(
            user_id=user.id,
            slug="cal-60min",
            title="Calendly 60 Min",
            duration_minutes=60,
            calendly_event_type_uri="https://api.calendly.com/event_types/CAL60",
            is_calendly_managed=True,
            is_active=True,
        )

        # Create non-Calendly event types (Google Calendar only)
        gcal_30 = EventType(
            user_id=user.id,
            slug="gcal-30min",
            title="Google Cal 30 Min",
            duration_minutes=30,
            is_calendly_managed=False,
            is_active=True,
        )
        gcal_45 = EventType(
            user_id=user.id,
            slug="gcal-45min",
            title="Google Cal 45 Min",
            duration_minutes=45,
            is_calendly_managed=False,
            is_active=True,
        )

        db.session.add_all([calendly_30, calendly_60, gcal_30, gcal_45])
        db.session.commit()

        yield user

        # Cleanup
        EventType.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()


@pytest.fixture
def user_with_duplicate_durations(test_app):
    """Create a user with both Calendly and Google Cal event types at same duration."""
    with test_app.app_context():
        user = User(
            username="DupUser",
            email="dup@example.com",
            google_id="dup123",
            calendly_access_token="test_access_token",
            calendly_user_uri="https://api.calendly.com/users/USER456",
            calendly_connected_at=datetime.utcnow(),
        )
        db.session.add(user)
        db.session.commit()

        # Create two 30-minute event types - one Calendly, one not
        # Calendly one created AFTER Google Cal one (higher ID)
        gcal_30 = EventType(
            user_id=user.id,
            slug="gcal-30",
            title="Google 30 Min",
            duration_minutes=30,
            is_calendly_managed=False,
            is_active=True,
        )
        db.session.add(gcal_30)
        db.session.commit()

        calendly_30 = EventType(
            user_id=user.id,
            slug="cal-30",
            title="Calendly 30 Min",
            duration_minutes=30,
            calendly_event_type_uri="https://api.calendly.com/event_types/CAL30",
            is_calendly_managed=True,
            is_active=True,
        )
        db.session.add(calendly_30)
        db.session.commit()

        yield user

        # Cleanup
        EventType.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()


class TestCalendlyMultipleEventTypes:
    """Test suite for multiple event type selection logic."""

    def test_calendly_event_type_prioritized_over_google_cal(
        self, test_app, user_with_duplicate_durations
    ):
        """Test that Calendly event types are prioritized over Google Cal for same duration."""
        with test_app.app_context():
            # Query for 30-minute event type with prioritization
            event_type = (
                EventType.query.filter_by(
                    user_id=user_with_duplicate_durations.id,
                    duration_minutes=30,
                    is_active=True,
                )
                .order_by(EventType.is_calendly_managed.desc(), EventType.id.asc())
                .first()
            )

            # Should return Calendly event type, not Google Cal
            assert event_type is not None
            assert event_type.is_calendly_managed is True
            assert event_type.title == "Calendly 30 Min"

    def test_default_event_type_prefers_calendly(
        self, test_app, user_with_mixed_event_types
    ):
        """Test that default event type selection prefers Calendly when available."""
        with test_app.app_context():
            # Simulate default event type selection (shortest Calendly event)
            default_event_type = (
                EventType.query.filter_by(
                    user_id=user_with_mixed_event_types.id,
                    is_active=True,
                )
                .filter(EventType.calendly_event_type_uri.isnot(None))
                .order_by(EventType.duration_minutes.asc(), EventType.id.asc())
                .first()
            )

            assert default_event_type is not None
            assert default_event_type.is_calendly_managed is True
            assert default_event_type.duration_minutes == 30
            assert default_event_type.title == "Calendly 30 Min"

    def test_all_event_types_grouped_by_duration(
        self, test_app, user_with_mixed_event_types
    ):
        """Test that event types can be grouped by duration correctly."""
        with test_app.app_context():
            all_event_types = (
                EventType.query.filter_by(
                    user_id=user_with_mixed_event_types.id,
                    is_active=True,
                )
                .order_by(EventType.duration_minutes.asc(), EventType.id.asc())
                .all()
            )

            # Group by duration
            by_duration = {}
            for et in all_event_types:
                duration = et.duration_minutes
                if duration not in by_duration:
                    by_duration[duration] = []
                by_duration[duration].append(et)

            # Verify grouping
            assert 30 in by_duration
            assert 45 in by_duration
            assert 60 in by_duration

            # 30 minutes should have both Calendly and Google Cal
            assert len(by_duration[30]) == 2
            types_30 = sorted(by_duration[30], key=lambda x: x.is_calendly_managed, reverse=True)
            assert types_30[0].is_calendly_managed is True  # Calendly first
            assert types_30[1].is_calendly_managed is False  # Google Cal second

    def test_inactive_event_types_excluded(self, test_app, user_with_mixed_event_types):
        """Test that inactive event types are excluded from selection."""
        with test_app.app_context():
            # Mark one event type as inactive
            inactive_et = EventType.query.filter_by(
                user_id=user_with_mixed_event_types.id,
                slug="cal-30min",
            ).first()
            inactive_et.is_active = False
            db.session.commit()

            # Query active event types
            active_event_types = EventType.query.filter_by(
                user_id=user_with_mixed_event_types.id,
                is_active=True,
            ).all()

            # Should not include inactive one
            slugs = [et.slug for et in active_event_types]
            assert "cal-30min" not in slugs
            assert "cal-60min" in slugs

            # Reset
            inactive_et.is_active = True
            db.session.commit()

    def test_calendly_event_types_have_uri(self, test_app, user_with_mixed_event_types):
        """Test that all Calendly-managed event types have URIs."""
        with test_app.app_context():
            calendly_types = EventType.query.filter_by(
                user_id=user_with_mixed_event_types.id,
                is_calendly_managed=True,
                is_active=True,
            ).all()

            # All should have URIs
            for et in calendly_types:
                assert et.calendly_event_type_uri is not None
                assert "api.calendly.com/event_types/" in et.calendly_event_type_uri

    def test_google_cal_event_types_no_uri(self, test_app, user_with_mixed_event_types):
        """Test that Google Calendar event types don't have Calendly URIs."""
        with test_app.app_context():
            gcal_types = EventType.query.filter_by(
                user_id=user_with_mixed_event_types.id,
                is_calendly_managed=False,
                is_active=True,
            ).all()

            # None should have Calendly URIs
            for et in gcal_types:
                assert et.calendly_event_type_uri is None

    def test_event_type_selection_for_specific_duration(
        self, test_app, user_with_mixed_event_types
    ):
        """Test selecting event type for a specific requested duration."""
        with test_app.app_context():
            # Request 45-minute meeting
            requested_duration = 45

            event_type = (
                EventType.query.filter_by(
                    user_id=user_with_mixed_event_types.id,
                    duration_minutes=requested_duration,
                    is_active=True,
                )
                .order_by(EventType.is_calendly_managed.desc(), EventType.id.asc())
                .first()
            )

            assert event_type is not None
            assert event_type.duration_minutes == 45
            # This one is Google Cal only (no Calendly 45-min event type)
            assert event_type.is_calendly_managed is False

    def test_no_conflict_when_only_calendly_types(self, test_app):
        """Test that there's no conflict when user only has Calendly event types."""
        with test_app.app_context():
            user = User(
                username="CalOnlyUser",
                email="calonly@example.com",
                google_id="calonly123",
                calendly_access_token="test_token",
            )
            db.session.add(user)
            db.session.commit()

            # Create only Calendly event types
            for duration in [15, 30, 60]:
                et = EventType(
                    user_id=user.id,
                    slug=f"cal-{duration}",
                    title=f"Cal {duration} Min",
                    duration_minutes=duration,
                    calendly_event_type_uri=f"https://api.calendly.com/event_types/CAL{duration}",
                    is_calendly_managed=True,
                    is_active=True,
                )
                db.session.add(et)
            db.session.commit()

            # Get all durations
            all_types = EventType.query.filter_by(user_id=user.id, is_active=True).all()
            durations = set(et.duration_minutes for et in all_types)

            # All should be unique
            assert len(durations) == 3
            assert 15 in durations
            assert 30 in durations
            assert 60 in durations

            # All should be Calendly-managed
            for et in all_types:
                assert et.is_calendly_managed is True

            # Cleanup
            EventType.query.filter_by(user_id=user.id).delete()
            db.session.delete(user)
            db.session.commit()

    def test_no_conflict_when_only_google_cal_types(self, test_app):
        """Test that there's no conflict when user only has Google Cal event types."""
        with test_app.app_context():
            user = User(
                username="GCalOnlyUser",
                email="gcalonly@example.com",
                google_id="gcalonly123",
            )
            db.session.add(user)
            db.session.commit()

            # Create only Google Cal event types
            for duration in [20, 40]:
                et = EventType(
                    user_id=user.id,
                    slug=f"gcal-{duration}",
                    title=f"GCal {duration} Min",
                    duration_minutes=duration,
                    is_calendly_managed=False,
                    is_active=True,
                )
                db.session.add(et)
            db.session.commit()

            # Get all types
            all_types = EventType.query.filter_by(user_id=user.id, is_active=True).all()

            # All should be Google Cal only
            for et in all_types:
                assert et.is_calendly_managed is False
                assert et.calendly_event_type_uri is None

            # Cleanup
            EventType.query.filter_by(user_id=user.id).delete()
            db.session.delete(user)
            db.session.commit()

    def test_conflicts_identified_correctly(self, test_app, user_with_duplicate_durations):
        """Test that we can identify duration conflicts between Calendly and Google Cal."""
        with test_app.app_context():
            # Get all event types
            all_types = EventType.query.filter_by(
                user_id=user_with_duplicate_durations.id,
                is_active=True,
            ).all()

            # Separate by type
            calendly_types = [et for et in all_types if et.is_calendly_managed]
            gcal_types = [et for et in all_types if not et.is_calendly_managed]

            # Get durations for each
            calendly_durations = set(et.duration_minutes for et in calendly_types)
            gcal_durations = set(et.duration_minutes for et in gcal_types)

            # Find conflicts
            conflicts = calendly_durations & gcal_durations

            # Should have conflict at 30 minutes
            assert 30 in conflicts
            assert len(conflicts) == 1

    def test_ordering_by_calendly_managed_desc(self, test_app, user_with_duplicate_durations):
        """Test that ordering by is_calendly_managed DESC works correctly."""
        with test_app.app_context():
            # Get 30-minute event types ordered by is_calendly_managed DESC
            types_30 = (
                EventType.query.filter_by(
                    user_id=user_with_duplicate_durations.id,
                    duration_minutes=30,
                    is_active=True,
                )
                .order_by(EventType.is_calendly_managed.desc(), EventType.id.asc())
                .all()
            )

            # Should return Calendly first, then Google Cal
            assert len(types_30) == 2
            assert types_30[0].is_calendly_managed is True
            assert types_30[1].is_calendly_managed is False
