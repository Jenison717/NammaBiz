from flask import Blueprint, abort, current_app, flash, redirect, request, send_from_directory, url_for
from flask_login import current_user

from extensions import db
from models import Complaint, ComplaintEvidence, JobMessage, RequestPhoto, ServiceRequest
from services.notification_service import job_notice
from utils.decorators import roles_required
from utils.helpers import save_upload


jobs = Blueprint("jobs", __name__, url_prefix="/jobs")


def _can_view(item):
    if current_user.role == "ADMIN":
        return True
    if item.user_id == current_user.id:
        return True
    return bool(current_user.role == "CONTRACTOR" and current_user.contractor and item.contractor_id == current_user.contractor.id)


@jobs.post("/<int:request_id>/messages")
@roles_required("USER", "CONTRACTOR")
def send_message(request_id):
    item = db.session.get(ServiceRequest, request_id)
    if not item or not item.job:
        abort(404)
    if current_user.role == "USER":
        participant = item.user_id == current_user.id
        recipient_id = item.contractor.user_id if item.contractor else None
    else:
        participant = bool(current_user.contractor and item.contractor_id == current_user.contractor.id)
        recipient_id = item.user_id
    body = request.form.get("body", "").strip()
    if not participant:
        abort(403)
    if not body or len(body) > 4000:
        flash("Messages must contain between 1 and 4000 characters.", "error")
    else:
        db.session.add(JobMessage(job=item.job, sender_id=current_user.id, body=body))
        if recipient_id:
            job_notice(recipient_id, f"New message about request #{item.id}.")
        db.session.commit()
    if current_user.role == "CONTRACTOR":
        return redirect(url_for("contractor.job_detail", request_id=request_id))
    return redirect(url_for("user.request_detail", request_id=request_id))


@jobs.post("/<int:request_id>/complaints")
@roles_required("USER", "CONTRACTOR")
def create_complaint(request_id):
    item = db.session.get(ServiceRequest, request_id)
    if not item:
        abort(404)
    if current_user.role == "USER":
        participant = item.user_id == current_user.id
    else:
        participant = bool(item.contractor_id and current_user.contractor and item.contractor_id == current_user.contractor.id)
    if not participant or not item.job or item.status in {"PENDING", "CANCELLED", "REJECTED"}:
        abort(403)
    reason = request.form.get("reason", "OTHER").upper()
    details = request.form.get("details", "").strip()
    evidence = [file for file in request.files.getlist("evidence") if file and file.filename]
    valid_files = all(file.mimetype in {"application/pdf", "image/jpeg", "image/png", "image/webp"} for file in evidence)
    if reason not in {"POOR_SERVICE", "INCOMPLETE_WORK", "PAYMENT_PROBLEM", "CONTRACTOR_ISSUE", "CUSTOMER_ISSUE", "OTHER"} or not details or len(details) > 5000 or len(evidence) > 3 or not valid_files:
        flash("Check the complaint details and attached evidence.", "error")
    else:
        previous_status = item.status
        if item.status == "DISPUTED":
            open_complaint = Complaint.query.filter(
                Complaint.job_id == item.job.id,
                Complaint.status.in_(["OPEN", "UNDER_REVIEW"]),
            ).order_by(Complaint.created_at.asc()).first()
            previous_status = open_complaint.previous_job_status if open_complaint else "IN_PROGRESS"
        complaint = Complaint(job_id=item.job.id, reporter_id=current_user.id, reason=reason, details=details, previous_job_status=previous_status)
        item.status = "DISPUTED"
        db.session.add(complaint)
        db.session.flush()
        try:
            for file in evidence:
                original, stored = save_upload(file, "documents", {"pdf", "jpg", "jpeg", "png", "webp"})
                db.session.add(ComplaintEvidence(complaint=complaint, original_name=original, stored_name=stored))
            other_user_id = item.contractor.user_id if current_user.role == "USER" else item.user_id
            job_notice(other_user_id, f"A complaint was opened for request #{item.id}.")
            db.session.commit()
            flash("Complaint submitted for admin review.", "success")
        except (OSError, ValueError):
            db.session.rollback()
            current_app.logger.exception("Unable to store complaint evidence")
            flash("The complaint could not be saved.", "error")
    return redirect(url_for("user.request_detail", request_id=request_id))


@jobs.get("/request-photos/<int:photo_id>")
@roles_required("USER", "CONTRACTOR", "ADMIN")
def request_photo(photo_id):
    photo = db.session.get(RequestPhoto, photo_id)
    if not photo or not _can_view(photo.request):
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_ROOT"] / "requests", photo.stored_name, as_attachment=True, download_name=photo.original_name)


@jobs.get("/complaint-evidence/<int:evidence_id>")
@roles_required("USER", "CONTRACTOR", "ADMIN")
def complaint_evidence(evidence_id):
    evidence = db.session.get(ComplaintEvidence, evidence_id)
    if not evidence or not _can_view(evidence.complaint.job.request):
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_ROOT"] / "documents", evidence.stored_name, as_attachment=True, download_name=evidence.original_name)
