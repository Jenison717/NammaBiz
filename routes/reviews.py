from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from extensions import db
from models import Job, Review
from utils.decorators import roles_required


reviews = Blueprint("reviews", __name__, url_prefix="/reviews")


@reviews.get("/")
@roles_required("USER")
def index():
    eligible = Job.query.join(Job.request).filter(Job.request.has(user_id=current_user.id, status="COMPLETED"), ~Job.review.has()).all()
    return render_template("portal/review_form.html", jobs=eligible)


@reviews.post("/<int:job_id>")
@roles_required("USER")
def create(job_id):
    job = db.session.get(Job, job_id)
    if not job or job.request.user_id != current_user.id or job.request.status != "COMPLETED":
        abort(404)
    if job.review:
        flash("This job already has a review.", "error")
        return redirect(url_for("reviews.index"))
    try:
        rating = int(request.form.get("rating", ""))
        quality = int(request.form.get("service_quality", ""))
        communication = int(request.form.get("communication", ""))
        punctuality = int(request.form.get("punctuality", ""))
        if any(value < 1 or value > 5 for value in (rating, quality, communication, punctuality)):
            raise ValueError
    except ValueError:
        flash("Ratings must be from 1 to 5.", "error")
        return redirect(url_for("reviews.index"))
    review = Review(job=job, user_id=current_user.id, contractor_id=job.request.contractor_id, rating=rating, service_quality=quality, communication=communication, punctuality=punctuality, comment=request.form.get("comment", "").strip()[:2000])
    db.session.add(review)
    contractor = job.request.contractor
    contractor.average_rating = ((contractor.average_rating * Review.query.filter_by(contractor_id=contractor.id).count()) + rating) / (Review.query.filter_by(contractor_id=contractor.id).count() + 1)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("A review could not be saved for this job.", "error")
    else:
        flash("Review submitted.", "success")
    return redirect(url_for("reviews.index"))
