from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    mobile = db.Column(db.String(32), nullable=False, default="")
    profile_photo_name = db.Column(db.String(255))
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="USER", index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    contractor = db.relationship("Contractor", back_populates="user", uselist=False)

    @property
    def is_active(self):
        return self.active

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Contractor(db.Model):
    __tablename__ = "contractors"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    business_name = db.Column(db.String(160), nullable=False, default="")
    business_type = db.Column(db.String(80), nullable=False, default="")
    experience_years = db.Column(db.Integer, nullable=False, default=0)
    address = db.Column(db.String(240), nullable=False, default="")
    city = db.Column(db.String(100), nullable=False, default="")
    pincode = db.Column(db.String(16), nullable=False, default="")
    skills = db.Column(db.Text, nullable=False, default="")
    verification_status = db.Column(db.String(20), nullable=False, default="PENDING", index=True)
    average_rating = db.Column(db.Float, nullable=False, default=0)
    schedule_version = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    user = db.relationship("User", back_populates="contractor")
    services = db.relationship("ContractorService", cascade="all, delete-orphan", back_populates="contractor")
    portfolio = db.relationship("PortfolioItem", cascade="all, delete-orphan", back_populates="contractor")


class ServiceCategory(db.Model):
    __tablename__ = "service_categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(110), unique=True, nullable=False)
    description = db.Column(db.String(300), nullable=False, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    services = db.relationship("Service", back_populates="category")


class Service(db.Model):
    __tablename__ = "services"
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("service_categories.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=False, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    category = db.relationship("ServiceCategory", back_populates="services")


class ContractorService(db.Model):
    __tablename__ = "contractor_services"
    id = db.Column(db.Integer, primary_key=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False, index=True)
    contractor = db.relationship("Contractor", back_populates="services")
    service = db.relationship("Service")
    __table_args__ = (db.UniqueConstraint("contractor_id", "service_id"),)


class ServiceRequest(db.Model):
    __tablename__ = "service_requests"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False, index=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractors.id"), index=True)
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(240), nullable=False)
    preferred_at = db.Column(db.DateTime(timezone=True))
    budget = db.Column(db.Numeric(12, 2))
    urgency = db.Column(db.String(20), nullable=False, default="NORMAL")
    requirements = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(24), nullable=False, default="PENDING", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    customer = db.relationship("User")
    service = db.relationship("Service")
    contractor = db.relationship("Contractor")
    job = db.relationship("Job", back_populates="request", uselist=False)
    photos = db.relationship("RequestPhoto", cascade="all, delete-orphan", back_populates="request")


class RequestPhoto(db.Model):
    __tablename__ = "request_photos"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    original_name = db.Column(db.String(255), nullable=False)
    request = db.relationship("ServiceRequest", back_populates="photos")


class ContractorResponse(db.Model):
    __tablename__ = "contractor_responses"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False)
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (db.UniqueConstraint("request_id", "contractor_id"),)


class Job(db.Model):
    __tablename__ = "jobs"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("service_requests.id", ondelete="CASCADE"), unique=True, nullable=False)
    scheduled_start = db.Column(db.DateTime(timezone=True))
    scheduled_end = db.Column(db.DateTime(timezone=True))
    agreed_amount = db.Column(db.Numeric(12, 2))
    payment_lock_version = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    request = db.relationship("ServiceRequest", back_populates="job")
    payments = db.relationship("Payment", back_populates="job")
    review = db.relationship("Review", back_populates="job", uselist=False)
    messages = db.relationship("JobMessage", cascade="all, delete-orphan", back_populates="job", order_by="JobMessage.sent_at")


class JobMessage(db.Model):
    __tablename__ = "job_messages"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    body = db.Column(db.String(4000), nullable=False)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    job = db.relationship("Job", back_populates="messages")
    sender = db.relationship("User")


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(120), unique=True)
    gateway_order_id = db.Column(db.String(120))
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    platform_fee = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    status = db.Column(db.String(24), nullable=False, default="PENDING", index=True)
    refund_status = db.Column(db.String(24), nullable=False, default="NONE")
    provider = db.Column(db.String(50), nullable=False, default="UNCONFIGURED")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    paid_at = db.Column(db.DateTime(timezone=True))
    job = db.relationship("Job", back_populates="payments")
    __table_args__ = (db.UniqueConstraint("gateway_order_id", name="uq_payments_gateway_order_id"),)


class Review(db.Model):
    __tablename__ = "reviews"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractors.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    service_quality = db.Column(db.Integer, nullable=False)
    communication = db.Column(db.Integer, nullable=False)
    punctuality = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    job = db.relationship("Job", back_populates="review")


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(60), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    read_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class Complaint(db.Model):
    __tablename__ = "complaints"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.String(80), nullable=False)
    details = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="OPEN", index=True)
    previous_job_status = db.Column(db.String(24), nullable=False, default="IN_PROGRESS")
    resolution = db.Column(db.Text, nullable=False, default="")
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at = db.Column(db.DateTime(timezone=True))
    job = db.relationship("Job")
    evidence = db.relationship("ComplaintEvidence", cascade="all, delete-orphan", back_populates="complaint")


class ComplaintEvidence(db.Model):
    __tablename__ = "complaint_evidence"
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    original_name = db.Column(db.String(255), nullable=False)
    complaint = db.relationship("Complaint", back_populates="evidence")


class ContractorDocument(db.Model):
    __tablename__ = "contractor_documents"
    id = db.Column(db.Integer, primary_key=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    original_name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="PENDING")
    review_note = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class PortfolioItem(db.Model):
    __tablename__ = "contractor_portfolio"
    id = db.Column(db.Integer, primary_key=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=False, default="")
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    contractor = db.relationship("Contractor", back_populates="portfolio")


class AvailabilityRule(db.Model):
    __tablename__ = "contractor_availability"
    id = db.Column(db.Integer, primary_key=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False, index=True)
    weekday = db.Column(db.Integer, nullable=False)
    starts_at = db.Column(db.String(5), nullable=False)
    ends_at = db.Column(db.String(5), nullable=False)
    __table_args__ = (db.UniqueConstraint("contractor_id", "weekday"),)


class TimeOff(db.Model):
    __tablename__ = "contractor_time_off"
    id = db.Column(db.Integer, primary_key=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False, index=True)
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    note = db.Column(db.String(300), nullable=False, default="")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(80), nullable=False)
    entity_type = db.Column(db.String(80), nullable=False)
    entity_id = db.Column(db.Integer)
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class PlatformSetting(db.Model):
    __tablename__ = "platform_settings"
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(500), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class LegacyBusiness(db.Model):
    __tablename__ = "businesses"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    category = db.Column(db.String, nullable=False)
    subcategory = db.Column(db.String, nullable=False)
    location = db.Column(db.String, nullable=False)
    description = db.Column(db.Text, nullable=False)
    buyer_types = db.Column(db.Text, nullable=False)
    products = db.Column(db.Text, nullable=False)
    services = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String, nullable=False)
    rating = db.Column(db.Float, nullable=False)
    available = db.Column(db.Integer, nullable=False)
    wholesale = db.Column(db.Integer, nullable=False)
    verified = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.String, nullable=False, server_default=db.text("CURRENT_TIMESTAMP"))


class LegacyProduct(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String, nullable=False)
    category = db.Column(db.String, nullable=False)
    unit = db.Column(db.String, nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=False)
    available = db.Column(db.Integer, nullable=False, default=1)


class LegacyRFQ(db.Model):
    __tablename__ = "rfqs"
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, nullable=False)
    buyer_name = db.Column(db.String, nullable=False)
    buyer_email = db.Column(db.String, nullable=False)
    requirement = db.Column(db.Text, nullable=False)
    status = db.Column(db.String, nullable=False, server_default=db.text("'PENDING'"))
    created_at = db.Column(db.String, nullable=False, server_default=db.text("CURRENT_TIMESTAMP"))
