from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from extensions import db
from models import AvailabilityRule, Job, Notification, Payment, PortfolioItem, Review, ServiceRequest, TimeOff
from services.job_service import WorkflowError, accept_request, reject_request, schedule_job, transition_job
from services.matching_service import available_requests_for
from utils.decorators import roles_required
from utils.helpers import save_upload
from utils.validators import positive_amount


contractor = Blueprint("contractor", __name__, url_prefix="/contractor")


def _profile():
    profile = current_user.contractor
    if not profile:
        abort(403)
    return profile


@contractor.get("/dashboard")
@roles_required("CONTRACTOR")
def dashboard():
    profile = _profile()
    jobs = Job.query.join(ServiceRequest).filter(ServiceRequest.contractor_id == profile.id).order_by(ServiceRequest.created_at.desc()).all()
    completed = [job for job in jobs if job.request.status == "COMPLETED"]
    earnings = db.session.query(func.coalesce(func.sum(Payment.amount - Payment.platform_fee), 0)).join(Job).join(ServiceRequest).filter(
        ServiceRequest.contractor_id == profile.id, Payment.status == "SUCCESS"
    ).scalar()
    notices = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(5).all()
    today = datetime.now().date()
    accepted_count = sum(job.request.status == "CONTRACTOR_ACCEPTED" for job in jobs)
    today_count = sum(bool(job.scheduled_start and job.scheduled_start.date() == today) for job in jobs)
    unread_count = Notification.query.filter_by(user_id=current_user.id, read_at=None).count()
    return render_template("portal/dashboard.html", role="CONTRACTOR", requests=jobs[:8], incoming=available_requests_for(profile)[:5], completed_count=len(completed), accepted_count=accepted_count, today_count=today_count, unread_count=unread_count, earnings=earnings, notices=notices, contractor_profile=profile)


@contractor.route("/profile", methods=["GET", "POST"])
@roles_required("CONTRACTOR")
def profile():
    profile = _profile()
    if request.method == "POST":
        photo = request.files.get("profile_photo")
        if photo and photo.filename and photo.mimetype not in {"image/jpeg", "image/png", "image/webp"}:
            flash("Choose a JPEG, PNG, or WebP profile photo.", "error")
            return redirect(url_for("contractor.profile"))
        profile.business_name = request.form.get("business_name", "").strip()[:160]
        profile.business_type = request.form.get("business_type", "").strip()[:80]
        profile.experience_years = max(0, min(request.form.get("experience_years", type=int) or 0, 80))
        profile.address = request.form.get("address", "").strip()[:240]
        profile.city = request.form.get("city", "").strip()[:100]
        profile.pincode = request.form.get("pincode", "").strip()[:16]
        profile.skills = request.form.get("skills", "").strip()[:3000]
        try:
            if photo and photo.filename:
                _, current_user.profile_photo_name = save_upload(photo, "profiles", {"jpg", "jpeg", "png", "webp"})
            db.session.commit()
            flash("Contractor profile updated.", "success")
        except (OSError, ValueError):
            db.session.rollback()
            flash("Profile photo could not be saved.", "error")
    return render_template("portal/contractor_profile.html", profile=profile)


@contractor.get("/verification")
@roles_required("CONTRACTOR")
def verification():
    return render_template("portal/verification.html", profile=_profile())


@contractor.get("/requests")
@roles_required("CONTRACTOR")
def requests():
    profile = _profile()
    return render_template("portal/contractor_requests.html", requests=available_requests_for(profile), approved=profile.verification_status == "APPROVED")


@contractor.get("/requests/<int:request_id>")
@roles_required("CONTRACTOR")
def request_detail(request_id):
    profile = _profile()
    item = db.session.get(ServiceRequest, request_id)
    matching_service = any(service.service_id == item.service_id for service in profile.services) if item else False
    assigned = bool(item and item.contractor_id == profile.id)
    available = bool(item and item.status == "PENDING" and profile.verification_status == "APPROVED" and matching_service and item in available_requests_for(profile))
    if not item or not (assigned or available):
        abort(404)
    return render_template("portal/request_detail.html", item=item, contractor_view=True)


@contractor.post("/requests/<int:request_id>/<action>")
@roles_required("CONTRACTOR")
def respond(request_id, action):
    profile = _profile()
    try:
        if action == "accept":
            accept_request(request_id, profile)
            flash("Request accepted. Set a time from your job details.", "success")
        elif action == "reject":
            reject_request(request_id, profile)
            flash("Request declined. It remains available to other matching contractors.", "success")
        else:
            abort(404)
    except WorkflowError as error:
        db.session.rollback()
        flash(str(error), "error")
    return redirect(url_for("contractor.requests"))


@contractor.get("/jobs/<int:request_id>")
@roles_required("CONTRACTOR")
def job_detail(request_id):
    profile = _profile()
    item = db.session.get(ServiceRequest, request_id)
    if not item or item.contractor_id != profile.id:
        abort(404)
    return render_template("portal/request_detail.html", item=item, contractor_view=True)


@contractor.post("/jobs/<int:request_id>/schedule")
@roles_required("CONTRACTOR")
def schedule(request_id):
    profile = _profile()
    item = db.session.get(ServiceRequest, request_id)
    try:
        starts_at = datetime.fromisoformat(request.form.get("starts_at", ""))
        if not item:
            abort(404)
        schedule_job(item, profile, starts_at)
        flash("Job scheduled.", "success")
    except ValueError as error:
        db.session.rollback()
        flash(str(error) or "Enter a valid date and time.", "error")
    return redirect(url_for("contractor.job_detail", request_id=request_id))


@contractor.post("/jobs/<int:request_id>/status")
@roles_required("CONTRACTOR")
def update_job_status(request_id):
    profile = _profile()
    item = db.session.get(ServiceRequest, request_id)
    if not item:
        abort(404)
    next_status = request.form.get("status", "").upper()
    amount = positive_amount(request.form.get("amount", ""), optional=True) if next_status == "COMPLETED" else None
    try:
        transition_job(item, profile, next_status, amount)
        flash(f"Job marked {next_status.lower().replace('_', ' ')}.", "success")
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "error")
    return redirect(url_for("contractor.job_detail", request_id=request_id))


@contractor.route("/schedule", methods=["GET", "POST"])
@roles_required("CONTRACTOR")
def schedule_settings():
    profile = _profile()
    if request.method == "POST":
        rules = []
        valid = True
        for weekday in range(7):
            start = request.form.get(f"start_{weekday}", "")
            end = request.form.get(f"end_{weekday}", "")
            if not start and not end:
                continue
            try:
                start_time, end_time = datetime.strptime(start, "%H:%M"), datetime.strptime(end, "%H:%M")
                if start_time >= end_time:
                    valid = False
                    break
                rules.append(AvailabilityRule(contractor_id=profile.id, weekday=weekday, starts_at=start, ends_at=end))
            except ValueError:
                valid = False
                break
        if not valid:
            flash("Enter valid start and end times for each available day.", "error")
        else:
            AvailabilityRule.query.filter_by(contractor_id=profile.id).delete()
            db.session.add_all(rules)
            db.session.commit()
            flash("Weekly availability saved.", "success")
    rules = {rule.weekday: rule for rule in AvailabilityRule.query.filter_by(contractor_id=profile.id).all()}
    time_off = TimeOff.query.filter_by(contractor_id=profile.id).order_by(TimeOff.starts_at).all()
    return render_template("portal/schedule.html", rules=rules, time_off=time_off)


@contractor.post("/schedule/time-off")
@roles_required("CONTRACTOR")
def add_time_off():
    profile = _profile()
    try:
        starts = datetime.fromisoformat(request.form.get("starts_at", ""))
        ends = datetime.fromisoformat(request.form.get("ends_at", ""))
        if starts >= ends:
            raise ValueError
        db.session.add(TimeOff(contractor_id=profile.id, starts_at=starts, ends_at=ends, note=request.form.get("note", "")[:300]))
        db.session.commit()
        flash("Unavailable time added.", "success")
    except ValueError:
        db.session.rollback()
        flash("Enter a valid unavailable date range.", "error")
    return redirect(url_for("contractor.schedule_settings"))


@contractor.get("/earnings")
@roles_required("CONTRACTOR")
def earnings():
    profile = _profile()
    payments = Payment.query.join(Job).join(ServiceRequest).filter(ServiceRequest.contractor_id == profile.id).order_by(Payment.created_at.desc()).all()
    confirmed = [item for item in payments if item.status == "SUCCESS"]
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    def net(items):
        return sum((Decimal(item.amount) - Decimal(item.platform_fee) for item in items), Decimal("0.00"))

    def payment_date(item):
        value = item.paid_at or item.created_at
        return value.date() if value else today

    paid = net(confirmed)
    today_total = net([item for item in confirmed if payment_date(item) == today])
    weekly_total = net([item for item in confirmed if payment_date(item) >= week_start])
    monthly_total = net([item for item in confirmed if payment_date(item) >= month_start])
    fees = sum((Decimal(item.platform_fee) for item in payments if item.status == "SUCCESS"), Decimal("0.00"))
    pending = net([item for item in payments if item.status == "PENDING"])
    completed = ServiceRequest.query.filter_by(contractor_id=profile.id, status="COMPLETED").count()
    return render_template("portal/earnings.html", payments=payments, paid=paid, today_total=today_total, weekly_total=weekly_total, monthly_total=monthly_total, fees=fees, pending=pending, completed=completed)


@contractor.route("/portfolio", methods=["GET", "POST"])
@roles_required("CONTRACTOR")
def portfolio():
    profile = _profile()
    if request.method == "POST":
        image = request.files.get("image")
        title = request.form.get("title", "").strip()[:120]
        if not image or image.mimetype not in {"image/jpeg", "image/png", "image/webp"} or not title:
            flash("Add a title and a JPEG, PNG, or WebP portfolio image.", "error")
        else:
            try:
                original, stored = save_upload(image, "portfolios", {"jpg", "jpeg", "png", "webp"})
                db.session.add(PortfolioItem(contractor_id=profile.id, title=title, description=request.form.get("description", "")[:500], stored_name=stored))
                db.session.commit()
                flash("Portfolio item saved.", "success")
            except (OSError, ValueError):
                db.session.rollback()
                flash("Portfolio image could not be stored.", "error")
    items = PortfolioItem.query.filter_by(contractor_id=profile.id).order_by(PortfolioItem.created_at.desc()).all()
    return render_template("portal/portfolio.html", items=items)


@contractor.get("/reviews")
@roles_required("CONTRACTOR")
def reviews():
    items = Review.query.filter_by(contractor_id=_profile().id).order_by(Review.created_at.desc()).all()
    return render_template("portal/reviews.html", reviews=items)
