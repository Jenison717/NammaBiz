from extensions import db
from models import AuditLog
from services.notification_service import job_notice


def review_contractor(contractor, decision, note="", actor_id=None):
    decision = decision.upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("Verification decision must be APPROVED or REJECTED.")
    contractor.verification_status = decision
    db.session.add(AuditLog(actor_id=actor_id, action=f"CONTRACTOR_{decision}", entity_type="contractor", entity_id=contractor.id, details={"note": note[:500]}))
    job_notice(contractor.user_id, f"Your contractor verification was {decision.lower()}.")
