from datetime import datetime, timezone

from flask import Blueprint, abort, redirect, url_for
from flask_login import current_user

from extensions import db
from models import Notification
from utils.decorators import roles_required


notifications = Blueprint("notifications", __name__, url_prefix="/notifications")


@notifications.get("/")
@roles_required("USER", "CONTRACTOR", "ADMIN")
def index():
    from flask import render_template

    items = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(200).all()
    return render_template("portal/notifications.html", notifications=items)


@notifications.post("/<int:notification_id>/read")
@roles_required("USER", "CONTRACTOR", "ADMIN")
def mark_read(notification_id):
    item = db.session.get(Notification, notification_id)
    if not item or item.user_id != current_user.id:
        abort(404)
    item.read_at = item.read_at or datetime.now(timezone.utc)
    db.session.commit()
    return redirect(url_for("notifications.index"))
