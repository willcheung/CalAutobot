from uuid import uuid4

from app import db
from app.models import User
from app.services import event_types as event_types_service


def test_create_event_type_generates_unique_slug(app_context):
    unique_email = f"tester-{uuid4().hex}@example.com"
    user = User(username=f"tester-{uuid4().hex}", email=unique_email, timezone="UTC")
    db.session.add(user)
    db.session.commit()

    first = event_types_service.create_event_type(user.id, "30 Minute Meeting", 30)
    second = event_types_service.create_event_type(user.id, "30 Minute Meeting", 45)

    assert first.slug == "30-minute-meeting"
    assert second.slug.startswith("30-minute-meeting-")

    fetched = event_types_service.list_event_types(user.id)
    assert len(fetched) == 2
