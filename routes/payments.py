import hashlib
import hmac
from decimal import Decimal

from flask import Blueprint, abort, current_app, jsonify, render_template, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from extensions import csrf, db
from models import Payment
from services.notification_service import job_notice
from services.payment_service import PaymentGatewayError, gateway_checkout_available, selected_provider, verify_gateway_payment
from utils.decorators import roles_required
from utils.helpers import audit, notify


payments = Blueprint("payments", __name__, url_prefix="/payments")


@payments.get("/<int:payment_id>")
@roles_required("USER", "CONTRACTOR", "ADMIN")
def detail(payment_id):
    payment = db.session.get(Payment, payment_id)
    if not payment:
        abort(404)
    request = payment.job.request
    allowed = current_user.role == "ADMIN" or request.user_id == current_user.id or bool(current_user.role == "CONTRACTOR" and current_user.contractor and request.contractor_id == current_user.contractor.id)
    if not allowed:
        abort(403)
    checkout_enabled = bool(
        current_user.role == "USER"
        and request.user_id == current_user.id
        and payment.status == "PENDING"
        and payment.gateway_order_id
        and gateway_checkout_available()
        and payment.provider == selected_provider()
    )
    return render_template(
        "portal/payment_detail.html",
        payment=payment,
        checkout_enabled=checkout_enabled,
        checkout_mode=current_app.config["PAYMENT_MODE"] if checkout_enabled else "disabled",
        razorpay_key_id=current_app.config["RAZORPAY_KEY_ID"] if checkout_enabled else "",
        amount_paise=int(Decimal(payment.amount) * 100),
    )


@payments.post("/<int:payment_id>/verify")
@roles_required("USER")
def verify_checkout(payment_id):
    payment = db.session.get(Payment, payment_id)
    if not payment or payment.job.request.user_id != current_user.id:
        abort(404)
    data = request.get_json(silent=True) or {}
    order_id = str(data.get("razorpay_order_id", ""))
    payment_id_from_gateway = str(data.get("razorpay_payment_id", ""))
    signature = str(data.get("razorpay_signature", ""))
    already_successful = payment.status == "SUCCESS" and payment.transaction_id == payment_id_from_gateway
    try:
        verify_gateway_payment(payment, order_id, payment_id_from_gateway, signature)
    except PaymentGatewayError:
        db.session.rollback()
        return jsonify({"verified": False, "message": "The gateway has not confirmed a captured payment."}), 400
    if not already_successful:
        job_notice(payment.job.request.contractor.user_id, f"Payment for job #{payment.job_id} was confirmed in Razorpay.")
        notify(current_user.id, "PAYMENT_COMPLETED", f"Payment for job #{payment.job_id} is confirmed.")
        audit("PAYMENT_CONFIRMED", "payment", payment.id, {"provider": payment.provider, "transaction_id": payment.transaction_id})
        db.session.commit()
    return jsonify({"verified": True, "status": payment.status, "transaction_id": payment.transaction_id})


@payments.post("/webhooks/razorpay")
@csrf.exempt
def razorpay_webhook():
    webhook_secret = current_app.config.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        abort(404)
    raw_body = request.get_data(cache=True)
    supplied_signature = request.headers.get("X-Razorpay-Signature", "")
    expected_signature = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, supplied_signature):
        abort(400)
    payload = request.get_json(silent=True) or {}
    if payload.get("event") != "payment.captured":
        return "", 200
    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = str(entity.get("order_id", ""))
    transaction_id = str(entity.get("id", ""))
    payment = Payment.query.filter_by(gateway_order_id=order_id).first()
    if not payment or not transaction_id or payment.status == "SUCCESS":
        return "", 200
    if payment.provider != selected_provider():
        abort(400)
    expected_amount = int(Decimal(payment.amount) * 100)
    if entity.get("status") != "captured" or entity.get("currency") != "INR" or entity.get("amount") != expected_amount:
        abort(400)
    payment.transaction_id = transaction_id
    payment.status = "SUCCESS"
    from models import utcnow
    payment.paid_at = utcnow()
    job_notice(payment.job.request.contractor.user_id, f"Payment for job #{payment.job_id} was confirmed in Razorpay.")
    notify(payment.job.request.user_id, "PAYMENT_COMPLETED", f"Payment for job #{payment.job_id} is confirmed.")
    audit("PAYMENT_CONFIRMED_WEBHOOK", "payment", payment.id, {"provider": payment.provider, "transaction_id": transaction_id})
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return "", 200
    return "", 200
