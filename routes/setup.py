from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_user
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import AuditLog, PlatformSetting, User
from utils.validators import valid_email, valid_password


setup = Blueprint("setup", __name__)


def _local_setup_allowed():
    return current_app.config.get("FLASK_ENV") != "production" and request.remote_addr in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def _already_configured():
    return PlatformSetting.query.filter_by(key="initial_admin_created").first() is not None or User.query.filter_by(role="ADMIN").first() is not None


@setup.route("/setup", methods=["GET", "POST"])
def first_run_setup():
    if not _local_setup_allowed():
        abort(404)
    if _already_configured():
        return redirect(url_for("admin.login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        try:
            fee = Decimal(request.form.get("platform_fee_percent", "0"))
            fee_valid = fee.is_finite() and Decimal("0") <= fee <= Decimal("100")
        except InvalidOperation:
            fee, fee_valid = Decimal("0"), False
        if not name or len(name) > 120 or not valid_email(email) or not valid_password(password) or not fee_valid:
            flash("Enter a name, valid email, password of at least 10 characters, and fee from 0 to 100.", "error")
            return render_template("setup/first_run.html")

        admin = User(name=name, email=email, role="ADMIN")
        admin.set_password(password)
        try:
            db.session.add(admin)
            db.session.flush()
            db.session.add_all([
                PlatformSetting(key="initial_admin_created", value=str(admin.id)),
                PlatformSetting(key="platform_fee_percent", value=str(fee)),
                AuditLog(action="INITIAL_SETUP_COMPLETED", entity_type="user", entity_id=admin.id, details={"platform_fee_percent": str(fee)}),
            ])
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Setup was completed in another session or that email is already in use. Sign in or choose another email.", "error")
            return redirect(url_for("setup.first_run_setup"))

        login_user(admin)
        flash("Initial setup is complete. You are signed in as the platform administrator.", "success")
        return redirect(url_for("admin.dashboard"))
    return render_template("setup/first_run.html")
