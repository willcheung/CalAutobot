from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import EventType
from app.services import event_types as event_type_service

event_types_routes = Blueprint("event_types_routes", __name__)


@event_types_routes.route("/event-types", methods=["GET", "POST"])
@login_required
def list_event_types():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        try:
            duration = int(request.form.get("duration_minutes", "30") or 30)
        except ValueError:
            duration = 30
        description = request.form.get("description", "")
        is_public = bool(request.form.get("is_public"))

        if not title:
            flash("Title is required", "danger")
        else:
            event_type_service.create_event_type(
                current_user.id,
                title,
                duration,
                description,
                is_public=is_public,
            )
            flash("Event type created", "success")
        return redirect(url_for("event_types_routes.list_event_types"))

    items = event_type_service.list_event_types(current_user.id)
    return render_template("event_types/index.html", event_types=items)


@event_types_routes.route("/event-types/<int:event_type_id>/edit", methods=["GET", "POST"])
@login_required
def edit_event_type(event_type_id):
    event_type = EventType.query.filter_by(id=event_type_id, user_id=current_user.id).first_or_404()

    if request.method == "POST":
        title = request.form.get("title", event_type.title)
        try:
            duration = int(request.form.get("duration_minutes", event_type.duration_minutes))
        except ValueError:
            duration = event_type.duration_minutes
        description = request.form.get("description", "")
        is_public = bool(request.form.get("is_public"))
        event_type_service.update_event_type(event_type, title, duration, description, is_public)
        flash("Event type updated", "success")
        return redirect(url_for("event_types_routes.list_event_types"))

    return render_template("event_types/edit.html", event_type=event_type)


@event_types_routes.route("/event-types/<int:event_type_id>/toggle", methods=["POST"])
@login_required
def toggle_event_type(event_type_id):
    event_type = EventType.query.filter_by(id=event_type_id, user_id=current_user.id).first_or_404()
    is_active = request.form.get("is_active") == "true"
    event_type_service.set_event_type_active(event_type, is_active)
    flash("Event type updated", "success")
    return redirect(url_for("event_types_routes.list_event_types"))


@event_types_routes.route("/event-types/<int:event_type_id>/delete", methods=["POST"])
@login_required
def delete_event_type(event_type_id):
    event_type = EventType.query.filter_by(id=event_type_id, user_id=current_user.id).first_or_404()
    event_type_service.delete_event_type(event_type)
    flash("Event type deleted", "success")
    return redirect(url_for("event_types_routes.list_event_types"))
