from urllib.parse import urlsplit

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import AuditLog, Contractor, ContractorService, Service, User
from services.auth_service import make_reset_token, read_reset_token, send_reset_email
from services.notification_service import registration_notice
from utils.helpers import save_upload
from utils.validators import valid_email, valid_password


auth = Blueprint("auth", __name__, url_prefix="/auth")


def _destination(user):
    return {"USER": "/user/dashboard", "CONTRACTOR": "/contractor/dashboard", "ADMIN": "/admin/dashboard"}.get(user.role, "/")


def _safe_next(value):
    if not value:
        return None
    parsed = urlsplit(value or "")
    if not parsed.netloc and not parsed.scheme and value.startswith("/") and not value.startswith("//"):
        return value
    return None


@auth.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(_destination(current_user))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        mobile = request.form.get("mobile", "").strip()
        password = request.form.get("password", "")
        photo = request.files.get("profile_photo")
        if not name or len(name) > 120 or not valid_email(email) or not valid_password(password) or (photo and photo.filename and photo.mimetype not in {"image/jpeg", "image/png", "image/webp"}):
            flash("Enter your name, a valid email, and a password of at least 10 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(name=name, email=email, mobile=mobile, role="USER")
            user.set_password(password)
            try:
                db.session.add(user)
                db.session.flush()
                if photo and photo.filename:
                    _, user.profile_photo_name = save_upload(photo, "profiles", {"jpg", "jpeg", "png", "webp"})
                registration_notice(user)
                db.session.commit()
            except (IntegrityError, OSError, ValueError):
                db.session.rollback()
                flash("An account with that email already exists.", "error")
            else:
                login_user(user)
                return redirect(_destination(user))
    return render_template("auth/register.html", contractor=False)


@auth.route("/register/contractor", methods=["GET", "POST"])
def register_contractor():
    if current_user.is_authenticated:
        return redirect(_destination(current_user))
    services = Service.query.filter_by(active=True).order_by(Service.name).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        photo = request.files.get("profile_photo")
        business_name = request.form.get("business_name", "").strip()
        selected_ids = {int(value) for value in request.form.getlist("services") if value.isdigit()}
        try:
            experience_years = int(request.form.get("experience_years", 0) or 0)
        except ValueError:
            experience_years = -1
        selected = Service.query.filter(Service.id.in_(selected_ids), Service.active.is_(True)).all() if selected_ids else []
        if not name or not valid_email(email) or not valid_password(password) or not business_name or not selected or not 0 <= experience_years <= 80 or (photo and photo.filename and photo.mimetype not in {"image/jpeg", "image/png", "image/webp"}):
            flash("Complete your details, choose at least one service, and use a password of at least 10 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(name=name, email=email, mobile=request.form.get("mobile", "").strip(), role="CONTRACTOR")
            user.set_password(password)
            contractor = Contractor(
                user=user,
                business_name=business_name,
                business_type=request.form.get("business_type", "").strip(),
                experience_years=experience_years,
                address=request.form.get("address", "").strip(),
                city=request.form.get("city", "").strip(),
                pincode=request.form.get("pincode", "").strip(),
                skills=request.form.get("skills", "").strip(),
            )
            contractor.services = [ContractorService(service=service) for service in selected]
            try:
                db.session.add(user)
                db.session.flush()
                if photo and photo.filename:
                    _, user.profile_photo_name = save_upload(photo, "profiles", {"jpg", "jpeg", "png", "webp"})
                registration_notice(user)
                db.session.add(AuditLog(action="CONTRACTOR_REGISTERED", entity_type="contractor", details={"verification_status": "PENDING"}))
                db.session.commit()
            except (IntegrityError, OSError, ValueError):
                db.session.rollback()
                flash("Could not create the account. Check the experience field and try again.", "error")
            else:
                login_user(user)
                flash("Your profile is pending admin verification. You cannot receive normal requests until approved.", "success")
                return redirect(_destination(user))
    return render_template("auth/register.html", contractor=True, services=services)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_destination(current_user))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.active and user.check_password(password):
            login_user(user, remember=request.form.get("remember") == "1")
            return redirect(_safe_next(request.args.get("next")) or _destination(user))
        flash("Email or password was not accepted.", "error")
    return render_template("auth/login.html")


@auth.post("/logout")
def logout():
    logout_user()
    flash("You have signed out.", "success")
    return redirect(url_for("auth.login"))


@auth.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email, active=True).first() if valid_email(email) else None
        if user:
            token = make_reset_token(user)
            link = url_for("auth.reset_password", token=token, _external=True)
            try:
                send_reset_email(user.email, link)
            except (OSError, RuntimeError):
                current_app.logger.exception("Password reset email could not be sent")
        flash("If the account is eligible, reset instructions will be sent to its email address.", "success")
        return redirect(url_for("auth.forgot_password"))
    return render_template("auth/forgot.html")


@auth.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    email = read_reset_token(token)
    user = User.query.filter_by(email=email, active=True).first() if email else None
    if not user:
        flash("That password reset link is invalid or expired.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if not valid_password(password):
            flash("Use a password between 10 and 128 characters.", "error")
        else:
            user.set_password(password)
            db.session.commit()
            flash("Your password has been reset. Sign in with the new password.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", token=token)
