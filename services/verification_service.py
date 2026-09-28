from datetime import datetime, timezone

from extensions import db
from models import AuditLog, Contractor, ContractorDocument
from services.notification_service import job_notice


def review_contractor(contractor, decision, note="", actor_id=None):
    decision = decision.upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("Verification decision must be APPROVED or REJECTED.")
    if decision == "APPROVED":
        submitted = {document.kind for document in ContractorDocument.query.filter_by(contractor_id=contractor.id).filter(ContractorDocument.status.in_(["PENDING", "APPROVED"]))}
        if not {"IDENTITY", "BUSINESS"}.issubset(submitted):
            raise ValueError("Identity and business documents must be submitted before approval.")
    contractor.verification_status = decision
    db.session.add(AuditLog(actor_id=actor_id, action=f"CONTRACTOR_{decision}", entity_type="contractor", entity_id=contractor.id, details={"note": note[:500]}))
    db.session.add(AuditLog(actor_id=actor_id, action="DOCUMENT_REVIEW", entity_type="contractor", entity_id=contractor.id, details={"document_status": decision, "note": note[:500]}))
    for document in ContractorDocument.query.filter_by(contractor_id=contractor.id, status="PENDING"):
        document.status = decision
        document.review_note = note[:500]
    job_notice(contractor.user_id, f"Your contractor verification was {decision.lower()}.")
