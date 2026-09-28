from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import update

from extensions import db
from models import AvailabilityRule, Contractor, ContractorResponse, ContractorService, Job, ServiceRequest, TimeOff
from services.notification_service import job_notice
from utils.helpers import notify


class WorkflowError(ValueError):
    pass


def accept_request(request_id, contractor):
    service_ids = [item.service_id for item in contractor.services if item.service.active and item.service.category.active]
    if contractor.verification_status != "APPROVED" or not service_ids:
        raise WorkflowError("Only approved contractors offering this service can accept requests.")
    result = db.session.execute(
        update(ServiceRequest)
        .where(
            ServiceRequest.id == request_id,
            ServiceRequest.status == "PENDING",
            ServiceRequest.contractor_id.is_(None),
            ServiceRequest.service_id.in_(service_ids),
        )
        .values(contractor_id=contractor.id, status="CONTRACTOR_ACCEPTED")
    )
    if result.rowcount != 1:
        raise WorkflowError("This request is no longer available.")
    request = db.session.get(ServiceRequest, request_id)
    db.session.add(ContractorResponse(request_id=request.id, contractor_id=contractor.id, status="ACCEPTED"))
    db.session.add(Job(request_id=request.id))
    job_notice(request.user_id, f"A contractor accepted request #{request.id}.")
    db.session.commit()
    return request


def reject_request(request_id, contractor):
    request = db.session.get(ServiceRequest, request_id)
    service_ids = [item.service_id for item in contractor.services if item.service.active and item.service.category.active]
    if contractor.verification_status != "APPROVED" or not request or request.status != "PENDING" or request.service_id not in service_ids:
        raise WorkflowError("This request cannot be rejected from this account.")
    existing = ContractorResponse.query.filter_by(request_id=request.id, contractor_id=contractor.id).first()
    if existing:
        raise WorkflowError("You already responded to this request.")
    db.session.add(ContractorResponse(request_id=request.id, contractor_id=contractor.id, status="REJECTED"))
    db.session.commit()


def schedule_job(request, contractor, starts_at):
    if request.contractor_id != contractor.id or request.status != "CONTRACTOR_ACCEPTED" or not request.job:
        raise WorkflowError("Only an accepted job can be scheduled.")
    lock = db.session.execute(
        update(Contractor)
        .where(Contractor.id == contractor.id)
        .values(schedule_version=Contractor.schedule_version + 1)
    )
    if lock.rowcount != 1:
        raise WorkflowError("The contractor schedule could not be locked.")
    rule = AvailabilityRule.query.filter_by(contractor_id=contractor.id, weekday=starts_at.weekday()).first()
    if not rule or not (rule.starts_at <= starts_at.strftime("%H:%M") and (starts_at + timedelta(hours=2)).strftime("%H:%M") <= rule.ends_at):
        raise WorkflowError("The requested start time is outside your published working hours.")
    ends_at = starts_at + timedelta(hours=2)
    if TimeOff.query.filter(
        TimeOff.contractor_id == contractor.id,
        TimeOff.starts_at < ends_at,
        TimeOff.ends_at > starts_at,
    ).first():
        raise WorkflowError("This time overlaps with your leave.")
    conflict = Job.query.join(ServiceRequest).filter(
        ServiceRequest.contractor_id == contractor.id,
        ServiceRequest.id != request.id,
        ServiceRequest.status == "SCHEDULED",
        Job.scheduled_start < ends_at,
        Job.scheduled_end > starts_at,
    ).first()
    if conflict:
        raise WorkflowError("This time overlaps with another booking.")
    result = db.session.execute(
        update(ServiceRequest)
        .where(ServiceRequest.id == request.id, ServiceRequest.contractor_id == contractor.id, ServiceRequest.status == "CONTRACTOR_ACCEPTED")
        .values(status="SCHEDULED")
    )
    if result.rowcount != 1:
        raise WorkflowError("This job has already changed and cannot be scheduled now.")
    request.status = "SCHEDULED"
    request.job.scheduled_start = starts_at
    request.job.scheduled_end = ends_at
    job_notice(request.user_id, f"Request #{request.id} is scheduled for {starts_at:%Y-%m-%d %H:%M}.")
    db.session.commit()


def transition_job(request, contractor, next_status, agreed_amount=None):
    allowed = {"IN_PROGRESS": "SCHEDULED", "COMPLETED": "IN_PROGRESS"}
    prior_status = allowed.get(next_status)
    if request.contractor_id != contractor.id or not prior_status:
        raise WorkflowError("That job status transition is not allowed.")
    if next_status == "COMPLETED":
        if agreed_amount is None or Decimal(agreed_amount) <= 0:
            raise WorkflowError("Enter the final agreed amount before completing the job.")
        request.job.agreed_amount = agreed_amount
    result = db.session.execute(
        update(ServiceRequest)
        .where(ServiceRequest.id == request.id, ServiceRequest.contractor_id == contractor.id, ServiceRequest.status == prior_status)
        .values(status=next_status)
    )
    if result.rowcount != 1:
        raise WorkflowError("This job status changed before your update could be saved.")
    request.status = next_status
    job_notice(request.user_id, f"Request #{request.id} is now {next_status.lower().replace('_', ' ')}.")
    if next_status == "COMPLETED":
        notify(request.user_id, "REVIEW_REMINDER", f"You can now review the contractor for request #{request.id}.")
    db.session.commit()
