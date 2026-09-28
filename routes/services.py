from flask import Blueprint, abort, current_app, render_template, request, send_from_directory
from flask_login import current_user

from extensions import db
from models import Contractor, PortfolioItem, Service, ServiceCategory, User
from services.matching_service import matching_contractors


services = Blueprint("services", __name__)


@services.get("/services")
def browse_services():
    term = request.args.get("q", "").strip()[:100]
    category_id = request.args.get("category", type=int)
    city = request.args.get("city", "").strip()[:100]
    query = Service.query.join(ServiceCategory).filter(Service.active.is_(True), ServiceCategory.active.is_(True))
    if term:
        query = query.filter(Service.name.ilike(f"%{term}%"))
    if category_id:
        query = query.filter(Service.category_id == category_id)
    categories = ServiceCategory.query.filter_by(active=True).order_by(ServiceCategory.name).all()
    listings = []
    for service in query.order_by(Service.name).all():
        listings.append((service, matching_contractors(service.id, city)))
    return render_template("marketplace/services.html", listings=listings, categories=categories, term=term, city=city, category_id=category_id)


@services.get("/contractors/<int:contractor_id>")
def contractor_detail(contractor_id):
    profile = Contractor.query.filter_by(id=contractor_id, verification_status="APPROVED").first()
    if not profile or not profile.user.active:
        abort(404)
    portfolio = PortfolioItem.query.filter_by(contractor_id=profile.id).order_by(PortfolioItem.created_at.desc()).all()
    return render_template("marketplace/contractor_detail.html", profile=profile, portfolio=portfolio)


@services.get("/contractor-portfolio/<int:item_id>")
def contractor_portfolio(item_id):
    item = PortfolioItem.query.get_or_404(item_id)
    if item.contractor.verification_status != "APPROVED" or not item.contractor.user.active:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_ROOT"] / "portfolios", item.stored_name, as_attachment=False)


@services.get("/profile-photos/<int:user_id>")
def profile_photo(user_id):
    user = db.session.get(User, user_id)
    if not user or not user.profile_photo_name:
        abort(404)
    owner = current_user.is_authenticated and current_user.id == user.id
    approved_provider = bool(user.role == "CONTRACTOR" and user.contractor and user.contractor.verification_status == "APPROVED" and user.active)
    admin = current_user.is_authenticated and current_user.role == "ADMIN"
    if not (owner or approved_provider or admin):
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_ROOT"] / "profiles", user.profile_photo_name, as_attachment=False)
