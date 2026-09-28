from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, update

from extensions import db
from models import Job, Notification, Payment, Review, Service, ServiceCategory, ServiceRequest
from services.matching_service import matching_contractors
from services.notification_service import request_notice
from utils.decorators import roles_required
from utils.helpers import audit, save_upload
from utils.validators import positive_amount


user = Blueprint("user", __name__, url_prefix="/user")


@user.get("/dashboard")
@roles_required("USER")
def dashboard():
    requests = ServiceRequest.query.filter_by(user_id=current_user.id).order_by(ServiceRequest.created_at.desc()).all()
    active_count = sum(item.status in {"CONTRACTOR_ACCEPTED", "SCHEDULED", "IN_PROGRESS"} for item in requests)
    pending_count = sum(item.status == "PENDING" for item in requests)
    completed_count = sum(item.status == "COMPLETED" for item in requests)
    spending = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).join(Job).join(ServiceRequest).filter(
        ServiceRequest.user_id == current_user.id, Payment.status == "SUCCESS"
    ).scalar()
    notices = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(5).all()
    recommendations = []
    for item in requests[:3]:
        recommendations.extend(matching_contractors(item.service_id, item.location))
    return render_template("portal/dashboard.html", role="USER", requests=requests[:8], active_count=active_count, pending_count=pending_count, completed_count=completed_count, spending=spending, notices=notices, recommendations=recommendations[:4])


@user.route("/profile", methods=["GET", "POST"])
@roles_required("USER")
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        photo = request.files.get("profile_photo")
        if not name or len(name) > 120 or len(mobile) > 32 or (photo and photo.filename and photo.mimetype not in {"image/jpeg", "image/png", "image/webp"}):
            flash("Enter a name and a valid mobile number.", "error")
        else:
            try:
                current_user.name, current_user.mobile = name, mobile
                if photo and photo.filename:
                    _, current_user.profile_photo_name = save_upload(photo, "profiles", {"jpg", "jpeg", "png", "webp"})
                db.session.commit()
                flash("Profile updated.", "success")
            except (OSError, ValueError):
                db.session.rollback()
                flash("Profile photo could not be saved.", "error")
    return render_template("portal/profile.html")


@user.route("/requests/new", methods=["GET", "POST"])
@roles_required("USER")
def create_request():
    services = Service.query.join(ServiceCategory).filter(Service.active.is_(True), ServiceCategory.active.is_(True)).order_by(Service.name).all()
    selected_service_id = request.args.get("service", type=int)
    if request.method == "POST":
        service_id = request.form.get("service_id", type=int)
        service = db.session.get(Service, service_id) if service_id else None
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        requirements = request.form.get("requirements", "").strip()
        urgency = request.form.get("urgency", "NORMAL").upper()
        budget = positive_amount(request.form.get("budget", ""), optional=True)
        preferred_text = request.form.get("preferred_at", "").strip()
        try:
            preferred_at = datetime.fromisoformat(preferred_text) if preferred_text else None
        except ValueError:
            preferred_at = None
        photos = [item for item in request.files.getlist("photos") if item and item.filename]
        valid_photos = all(item.mimetype in {"image/jpeg", "image/png", "image/webp"} for item in photos)
        if not service or not service.active or not description or len(description) > 5000 or not location or len(location) > 240 or urgency not in {"LOW", "NORMAL", "URGENT"} or (request.form.get("budget", "").strip() and budget is None) or (preferred_text and preferred_at is None) or len(photos) > 4 or not valid_photos:
            flash("Check the service request details and supported image files.", "error")
        else:
            service_request = ServiceRequest(
                customer=current_user,
                service=service,
                description=description,
                location=location,
                requirements=requirements[:3000],
                urgency=urgency,
                budget=budget,
                preferred_at=preferred_at,
            )
            db.session.add(service_request)
            db.session.flush()
            try:
                for photo in photos:
                    original, stored = save_upload(photo, "requests", {"jpg", "jpeg", "png", "webp"})
                    from models import RequestPhoto
                    db.session.add(RequestPhoto(request=service_request, stored_name=stored, original_name=original))
                for contractor in matching_contractors(service.id, location):
                    from services.notification_service import job_notice
                    job_notice(contractor.user_id, f"A new service request #{service_request.id} matches your services.")
                request_notice(current_user.id, service_request.id)
                db.session.commit()
            except (OSError, ValueError):
                db.session.rollback()
                current_app.logger.exception("Unable to store service request attachments")
                flash("The request could not be saved. Check the image files and try again.", "error")
            else:
                flash("Your request is available to verified matching contractors.", "success")
                return redirect(url_for("user.requests"))
    return render_template("portal/create_request.html", services=services, selected_service_id=selected_service_id)


@user.get("/requests")
@roles_required("USER")
def requests():
    items = ServiceRequest.query.filter_by(user_id=current_user.id).order_by(ServiceRequest.created_at.desc()).all()
    return render_template("portal/requests.html", requests=items)


@user.get("/requests/<int:request_id>")
@roles_required("USER", "CONTRACTOR", "ADMIN")
def request_detail(request_id):
    item = db.session.get(ServiceRequest, request_id)
    if not item:
        abort(404)
    owns = current_user.id == item.user_id
    assigned = current_user.role == "CONTRACTOR" and current_user.contractor and current_user.contractor.id == item.contractor_id
    if not (owns or assigned or current_user.role == "ADMIN"):
        abort(403)
    return render_template("portal/request_detail.html", item=item)


@user.post("/requests/<int:request_id>/cancel")
@roles_required("USER")
def cancel_request(request_id):
    item = db.session.get(ServiceRequest, request_id)
    if not item or item.user_id != current_user.id:
        abort(404)
    if item.status not in {"PENDING", "CONTRACTOR_ACCEPTED"}:
        flash("This request can no longer be cancelled here.", "error")
    else:
        item.status = "CANCELLED"
        audit("SERVICE_REQUEST_CANCELLED", "service_request", item.id)
        if item.contractor:
            from services.notification_service import job_notice
            job_notice(item.contractor.user_id, f"Request #{item.id} was cancelled by the customer.")
        db.session.commit()
        flash("Request cancelled.", "success")
    return redirect(url_for("user.request_detail", request_id=request_id))


@user.get("/payments")
@roles_required("USER")
def payments():
    items = Payment.query.join(Job).join(ServiceRequest).filter(ServiceRequest.user_id == current_user.id).order_by(Payment.created_at.desc()).all()
    return render_template("portal/payments.html", payments=items)


@user.post("/jobs/<int:job_id>/payment")
@roles_required("USER")
def create_payment(job_id):
    from services.payment_service import PaymentGatewayError, create_gateway_order, create_pending_payment, gateway_checkout_available

    job = db.session.get(Job, job_id)
    if not job or job.request.user_id != current_user.id:
        abort(404)
    if job.request.status != "COMPLETED" or not job.agreed_amount:
        flash("A payment can only be prepared for a completed job with an agreed amount.", "error")
    else:
        db.session.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(payment_lock_version=Job.payment_lock_version + 1)
        )
        completed_payment = Payment.query.filter_by(job_id=job.id, status="SUCCESS").first()
        if completed_payment:
            db.session.rollback()
            return redirect(url_for("payments.detail", payment_id=completed_payment.id))
        payment = Payment.query.filter_by(job_id=job.id, status="PENDING").order_by(Payment.created_at.desc()).first()
        if not payment:
            payment = create_pending_payment(job, Decimal(job.agreed_amount))
            db.session.commit()
        if gateway_checkout_available():
            try:
                if not payment.gateway_order_id:
                    create_gateway_order(payment)
            except PaymentGatewayError as error:
                db.session.commit()
                current_app.logger.warning("Payment order setup failed: %s", error)
                flash("Sandbox checkout could not be started. The payment remains pending; check the gateway configuration and retry.", "error")
            else:
                db.session.commit()
                return redirect(url_for("payments.detail", payment_id=payment.id))
        else:
            db.session.commit()
            flash("A pending payment record was created. Configure Razorpay test credentials to open sandbox checkout.", "success")
        return redirect(url_for("payments.detail", payment_id=payment.id))
    return redirect(url_for("user.payments"))


@user.get("/reviews")
@roles_required("USER")
def reviews():
    items = Review.query.filter_by(user_id=current_user.id).order_by(Review.created_at.desc()).all()
    return render_template("portal/reviews.html", reviews=items)
