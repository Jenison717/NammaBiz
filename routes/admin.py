import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import click
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user

from extensions import db
from models import AuditLog, Complaint, Contractor, ContractorDocument, Job, Notification, Payment, PlatformSetting, Review, Service, ServiceCategory, ServiceRequest, User
from services.auth_service import send_reset_email
from services.notification_service import job_notice
from services.verification_service import review_contractor
from utils.decorators import roles_required
from utils.helpers import audit
from utils.validators import valid_email, valid_password


admin = Blueprint("admin", __name__, url_prefix="/admin")


@admin.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated and current_user.role == "ADMIN":
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if user and user.active and user.role == "ADMIN" and user.check_password(request.form.get("password", "")):
            login_user(user)
            return redirect(url_for("admin.dashboard"))
        flash("Admin credentials were not accepted.", "error")
    return render_template("auth/login.html", admin_login=True)


@admin.get("/dashboard")
@roles_required("ADMIN")
def dashboard():
    stats = {
        "users": User.query.filter_by(role="USER").count(),
        "contractors": Contractor.query.count(),
        "active_contractors": Contractor.query.join(User).filter(Contractor.verification_status == "APPROVED", User.active.is_(True)).count(),
        "pending_verifications": Contractor.query.filter_by(verification_status="PENDING").count(),
        "active_jobs": ServiceRequest.query.filter(ServiceRequest.status.in_(["CONTRACTOR_ACCEPTED", "SCHEDULED", "IN_PROGRESS"])).count(),
        "completed_jobs": ServiceRequest.query.filter_by(status="COMPLETED").count(),
        "cancelled_jobs": ServiceRequest.query.filter_by(status="CANCELLED").count(),
        "revenue": db.session.query(db.func.coalesce(db.func.sum(Payment.platform_fee), 0)).filter(Payment.status == "SUCCESS").scalar(),
        "open_complaints": Complaint.query.filter(Complaint.status.in_(["OPEN", "UNDER_REVIEW"])).count(),
    }
    activity = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(12).all()
    return render_template("portal/admin_dashboard.html", stats=stats, activity=activity)


@admin.get("/users")
@roles_required("ADMIN")
def users():
    term = request.args.get("q", "").strip()[:100]
    query = User.query.filter(User.role != "ADMIN")
    if term:
        query = query.filter(db.or_(User.name.ilike(f"%{term}%"), User.email.ilike(f"%{term}%")))
    return render_template("portal/admin_users.html", users=query.order_by(User.created_at.desc()).all(), term=term)


@admin.get("/users/<int:user_id>")
@roles_required("ADMIN")
def user_detail(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    filters = [AuditLog.actor_id == user.id, db.and_(AuditLog.entity_type == "user", AuditLog.entity_id == user.id)]
    if user.contractor:
        filters.append(db.and_(AuditLog.entity_type == "contractor", AuditLog.entity_id == user.contractor.id))
    activity = AuditLog.query.filter(db.or_(*filters)).order_by(AuditLog.created_at.desc()).limit(100).all()
    return render_template("portal/admin_user_detail.html", account=user, activity=activity)


@admin.post("/users/<int:user_id>/status")
@roles_required("ADMIN")
def set_user_status(user_id):
    user = db.session.get(User, user_id)
    if not user or user.role == "ADMIN":
        abort(404)
    active = request.form.get("active") == "1"
    user.active = active
    audit("USER_REACTIVATED" if active else "USER_SUSPENDED", "user", user.id)
    db.session.commit()
    flash("Account status updated.", "success")
    return redirect(url_for("admin.users"))


@admin.get("/contractors")
@roles_required("ADMIN")
def contractors():
    term = request.args.get("q", "").strip()[:100]
    query = Contractor.query.join(User)
    if term:
        query = query.filter(db.or_(Contractor.business_name.ilike(f"%{term}%"), Contractor.city.ilike(f"%{term}%"), User.name.ilike(f"%{term}%"), User.email.ilike(f"%{term}%")))
    items = query.order_by(Contractor.created_at.desc()).all()
    return render_template("portal/admin_contractors.html", contractors=items, term=term)


@admin.get("/contractors/<int:contractor_id>/verification")
@roles_required("ADMIN")
def contractor_verification(contractor_id):
    from models import PortfolioItem

    contractor = db.session.get(Contractor, contractor_id)
    if not contractor:
        abort(404)
    documents = ContractorDocument.query.filter_by(contractor_id=contractor.id).all()
    portfolio = PortfolioItem.query.filter_by(contractor_id=contractor.id).all()
    return render_template("portal/admin_verification.html", contractor=contractor, documents=documents, portfolio=portfolio)


@admin.get("/documents/<int:document_id>")
@roles_required("ADMIN")
def document(document_id):
    from flask import current_app, send_from_directory

    item = db.session.get(ContractorDocument, document_id)
    if not item:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_ROOT"] / "documents", item.stored_name, as_attachment=True, download_name=item.original_name)


@admin.post("/contractors/<int:contractor_id>/review")
@roles_required("ADMIN")
def review_verification(contractor_id):
    contractor = db.session.get(Contractor, contractor_id)
    if not contractor:
        abort(404)
    try:
        review_contractor(contractor, request.form.get("decision", ""), request.form.get("note", ""), current_user.id)
        db.session.commit()
        flash("Verification decision recorded.", "success")
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "error")
    return redirect(url_for("admin.contractor_verification", contractor_id=contractor_id))


@admin.route("/categories", methods=["GET", "POST"])
@roles_required("ADMIN")
def categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not name or not slug:
            flash("Enter a category name.", "error")
        elif ServiceCategory.query.filter(db.or_(ServiceCategory.name == name, ServiceCategory.slug == slug)).first():
            flash("That category already exists.", "error")
        else:
            category = ServiceCategory(name=name, slug=slug, description=request.form.get("description", "")[:300])
            db.session.add(category)
            audit("SERVICE_CATEGORY_CREATED", "service_category", details={"name": name})
            db.session.commit()
            flash("Category added.", "success")
    return render_template("portal/admin_services.html", categories=ServiceCategory.query.order_by(ServiceCategory.name).all(), services=Service.query.order_by(Service.name).all())


@admin.post("/categories/<int:category_id>")
@roles_required("ADMIN")
def update_category(category_id):
    category = db.session.get(ServiceCategory, category_id)
    if not category:
        abort(404)
    name = request.form.get("name", "").strip()[:100]
    if name:
        category.name = name
        category.description = request.form.get("description", "")[:300]
    category.active = request.form.get("active") == "1"
    audit("SERVICE_CATEGORY_UPDATED", "service_category", category.id, {"active": category.active})
    db.session.commit()
    flash("Category updated.", "success")
    return redirect(url_for("admin.categories"))


@admin.post("/services")
@roles_required("ADMIN")
def create_service():
    name = request.form.get("name", "").strip()[:120]
    category = db.session.get(ServiceCategory, request.form.get("category_id", type=int))
    if not name or not category:
        flash("Choose a category and enter a service name.", "error")
    else:
        service = Service(category=category, name=name, description=request.form.get("description", "")[:500])
        db.session.add(service)
        audit("SERVICE_CREATED", "service", details={"name": name, "category_id": category.id})
        db.session.commit()
        flash("Service added.", "success")
    return redirect(url_for("admin.categories"))


@admin.post("/services/<int:service_id>")
@roles_required("ADMIN")
def update_service(service_id):
    service = db.session.get(Service, service_id)
    if not service:
        abort(404)
    name = request.form.get("name", "").strip()[:120]
    if name:
        service.name = name
        service.description = request.form.get("description", "")[:500]
        category_id = request.form.get("category_id", type=int)
        if category_id and db.session.get(ServiceCategory, category_id):
            service.category_id = category_id
    service.active = request.form.get("active") == "1"
    audit("SERVICE_UPDATED", "service", service.id, {"active": service.active})
    db.session.commit()
    flash("Service updated.", "success")
    return redirect(url_for("admin.categories"))


@admin.get("/jobs")
@roles_required("ADMIN")
def jobs():
    items = ServiceRequest.query.order_by(ServiceRequest.created_at.desc()).limit(500).all()
    return render_template("portal/admin_jobs.html", requests=items)


@admin.get("/payments")
@roles_required("ADMIN")
def payments():
    items = Payment.query.order_by(Payment.created_at.desc()).limit(500).all()
    return render_template("portal/admin_payments.html", payments=items)


@admin.get("/revenue")
@roles_required("ADMIN")
def revenue():
    settled = Payment.query.filter_by(status="SUCCESS").order_by(Payment.paid_at.desc()).all()
    monthly = {}
    for payment in settled:
        paid_at = payment.paid_at or payment.created_at
        key = paid_at.strftime("%Y-%m")
        totals = monthly.setdefault(key, {"gross": Decimal("0.00"), "fees": Decimal("0.00"), "count": 0})
        totals["gross"] += Decimal(payment.amount)
        totals["fees"] += Decimal(payment.platform_fee)
        totals["count"] += 1
    return render_template("portal/admin_revenue.html", monthly=sorted(monthly.items(), reverse=True), settled_count=len(settled))


@admin.get("/reviews")
@roles_required("ADMIN")
def reviews():
    items = Review.query.order_by(Review.created_at.desc()).limit(500).all()
    return render_template("portal/reviews.html", reviews=items, admin_view=True)


@admin.get("/complaints")
@roles_required("ADMIN")
def complaints():
    items = Complaint.query.order_by(Complaint.created_at.desc()).all()
    return render_template("portal/admin_complaints.html", complaints=items)


@admin.post("/complaints/<int:complaint_id>")
@roles_required("ADMIN")
def update_complaint(complaint_id):
    complaint = db.session.get(Complaint, complaint_id)
    if not complaint:
        abort(404)
    status = request.form.get("status", "").upper()
    resolution = request.form.get("resolution", "").strip()[:3000]
    allowed = {"OPEN": {"UNDER_REVIEW"}, "UNDER_REVIEW": {"RESOLVED", "REJECTED"}}
    if status not in allowed.get(complaint.status, set()) or (status in {"RESOLVED", "REJECTED"} and not resolution):
        flash("Choose a valid status and record a resolution for closed complaints.", "error")
    else:
        complaint.status = status
        complaint.resolution = resolution
        complaint.reviewed_by = current_user.id
        if status in {"RESOLVED", "REJECTED"}:
            complaint.resolved_at = datetime.now(timezone.utc)
            other_open = Complaint.query.filter(
                Complaint.job_id == complaint.job_id,
                Complaint.id != complaint.id,
                Complaint.status.in_(["OPEN", "UNDER_REVIEW"]),
            ).count()
            if not other_open and complaint.job.request.status == "DISPUTED":
                complaint.job.request.status = complaint.previous_job_status
        audit("COMPLAINT_UPDATED", "complaint", complaint.id, {"status": status})
        notify = Notification(user_id=complaint.reporter_id, kind="COMPLAINT_UPDATE", message=f"Complaint #{complaint.id} is now {status.lower().replace('_', ' ')}.")
        db.session.add(notify)
        db.session.commit()
        flash("Complaint updated.", "success")
    return redirect(url_for("admin.complaints"))


@admin.get("/notifications")
@roles_required("ADMIN")
def notifications():
    users = User.query.filter_by(active=True).order_by(User.name).all()
    return render_template("portal/admin_notifications.html", users=users)


@admin.post("/notifications")
@roles_required("ADMIN")
def send_notification():
    user_id = request.form.get("user_id", type=int)
    message = request.form.get("message", "").strip()[:500]
    recipient = db.session.get(User, user_id) if user_id else None
    if not message or len(message) < 3 or (user_id and (not recipient or not recipient.active)):
        flash("Choose an active recipient and enter a message.", "error")
    else:
        recipients = [recipient] if recipient else User.query.filter_by(active=True).all()
        db.session.add_all([Notification(user_id=item.id, kind="ADMIN_MESSAGE", message=message) for item in recipients])
        audit("ADMIN_NOTIFICATION_SENT", "notification", details={"recipient_count": len(recipients)})
        db.session.commit()
        flash(f"Notification sent to {len(recipients)} account(s).", "success")
    return redirect(url_for("admin.notifications"))


@admin.get("/reports")
@roles_required("ADMIN")
def reports():
    counts = {"requests": ServiceRequest.query.count(), "completed": ServiceRequest.query.filter_by(status="COMPLETED").count(), "users": User.query.filter_by(role="USER").count(), "contractors": Contractor.query.count(), "payments_successful": Payment.query.filter_by(status="SUCCESS").count()}
    return render_template("portal/admin_reports.html", counts=counts)


@admin.route("/settings", methods=["GET", "POST"])
@roles_required("ADMIN")
def settings():
    setting = db.session.get(PlatformSetting, "platform_fee_percent")
    if request.method == "POST":
        try:
            rate = Decimal(request.form.get("platform_fee_percent", ""))
            if not rate.is_finite() or rate < 0 or rate > 100:
                raise InvalidOperation
            setting = setting or PlatformSetting(key="platform_fee_percent", value="0")
            setting.value = str(rate)
            db.session.add(setting)
            audit("PLATFORM_SETTING_UPDATED", "platform_setting", details={"platform_fee_percent": str(rate)})
            db.session.commit()
            flash("Platform fee setting saved. It applies to new payment records only.", "success")
        except (InvalidOperation, ValueError):
            db.session.rollback()
            flash("Enter a fee percentage from 0 to 100.", "error")
    return render_template("portal/admin_settings.html", setting=setting)


def register_cli(app):
    @app.cli.command("create-admin")
    @click.argument("email")
    @click.option("--name", prompt=True)
    @click.password_option()
    def create_admin(email, name, password):
        email = email.strip().lower()
        if not valid_email(email) or not valid_password(password):
            raise click.ClickException("Use a valid email and a password between 10 and 128 characters.")
        if User.query.filter_by(email=email).first():
            raise click.ClickException("An account with that email already exists.")
        user = User(name=name.strip(), email=email, role="ADMIN")
        user.set_password(password)
        db.session.add(user)
        audit("ADMIN_CREATED", "user", details={"email": email})
        db.session.commit()
        click.echo("Admin account created.")
