from sqlalchemy import select

from models import Contractor, ContractorResponse, ContractorService, Service, ServiceCategory, ServiceRequest


def matching_contractors(service_id, city=""):
    query = Contractor.query.join(ContractorService).join(Service).join(ServiceCategory).filter(
        ContractorService.service_id == service_id,
        Service.active.is_(True),
        ServiceCategory.active.is_(True),
        Contractor.verification_status == "APPROVED",
        Contractor.user.has(active=True),
    )
    if city:
        query = query.filter(Contractor.city.ilike(f"%{city.strip()}%"))
    return query.order_by(Contractor.average_rating.desc(), Contractor.id.asc()).all()


def available_requests_for(contractor):
    service_ids = [item.service_id for item in contractor.services if item.service.active and item.service.category.active]
    rejected = select(ContractorResponse.id).where(
        ContractorResponse.request_id == ServiceRequest.id,
        ContractorResponse.contractor_id == contractor.id,
        ContractorResponse.status == "REJECTED",
    ).exists()
    return ServiceRequest.query.filter(
        ServiceRequest.status == "PENDING",
        ServiceRequest.service_id.in_(service_ids),
        ~rejected,
    ).order_by(ServiceRequest.created_at.asc()).all()
