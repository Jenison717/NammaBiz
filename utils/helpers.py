from flask import current_app
from flask_login import current_user

from extensions import db
from models import AuditLog, Notification


def notify(user_id, kind, message):
    db.session.add(Notification(user_id=user_id, kind=kind, message=message[:500]))


def audit(action, entity_type, entity_id=None, details=None):
    actor_id = current_user.id if current_user.is_authenticated else None
    db.session.add(AuditLog(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, details=details or {}))


def save_upload(file_storage, directory, allowed_extensions):
    from uuid import uuid4
    from werkzeug.utils import secure_filename

    original = secure_filename(file_storage.filename or "")
    extension = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if not original or extension not in allowed_extensions:
        raise ValueError("Choose a supported file type.")
    target_dir = current_app.config["UPLOAD_ROOT"] / directory
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid4().hex}.{extension}"
    file_storage.save(target_dir / stored)
    return original, stored
