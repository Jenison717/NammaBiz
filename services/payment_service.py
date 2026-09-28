from abc import ABC, abstractmethod
from decimal import Decimal

from flask import current_app

from extensions import db
from models import Payment, PlatformSetting, utcnow


class PaymentGatewayError(RuntimeError):
    pass


def selected_provider():
    return {"razorpay_test": "RAZORPAY_TEST", "razorpay_live": "RAZORPAY_LIVE"}.get(
        current_app.config.get("PAYMENT_MODE", "disabled")
    )


class PaymentGateway(ABC):
    @abstractmethod
    def create_checkout(self, payment):
        """Return provider checkout data; implementations must not mark payment successful."""


class UnconfiguredGateway(PaymentGateway):
    def create_checkout(self, payment):
        raise RuntimeError("No payment gateway is configured.")


def gateway_checkout_available():
    mode = current_app.config.get("PAYMENT_MODE", "disabled")
    key_id = current_app.config.get("RAZORPAY_KEY_ID", "")
    key_secret = current_app.config.get("RAZORPAY_KEY_SECRET", "")
    if mode == "disabled" or not key_id or not key_secret:
        return False
    expected_prefix = {"razorpay_test": "rzp_test_", "razorpay_live": "rzp_live_"}.get(mode)
    return bool(expected_prefix and key_id.startswith(expected_prefix))


def _razorpay_client():
    mode = current_app.config.get("PAYMENT_MODE", "disabled")
    key_id = current_app.config.get("RAZORPAY_KEY_ID", "")
    key_secret = current_app.config.get("RAZORPAY_KEY_SECRET", "")
    expected_prefix = {"razorpay_test": "rzp_test_", "razorpay_live": "rzp_live_"}.get(mode)
    if not expected_prefix or not key_id or not key_secret or not key_id.startswith(expected_prefix):
        raise PaymentGatewayError("Razorpay is not configured for the selected payment mode.")
    try:
        import razorpay
    except ImportError as error:
        raise PaymentGatewayError("The Razorpay SDK is not installed.") from error
    return razorpay.Client(auth=(key_id, key_secret))


def create_pending_payment(job, amount, platform_fee=None):
    if platform_fee is None:
        setting = db.session.get(PlatformSetting, "platform_fee_percent")
        rate = Decimal(setting.value) if setting else Decimal("0")
        platform_fee = (Decimal(amount) * rate / Decimal("100")).quantize(Decimal("0.01"))
    payment = Payment(job=job, amount=amount, platform_fee=platform_fee, status="PENDING")
    db.session.add(payment)
    db.session.flush()
    return payment


def create_gateway_order(payment):
    client = _razorpay_client()
    amount_paise = int((Decimal(payment.amount) * 100).quantize(Decimal("1")))
    try:
        order = client.order.create(data={
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"nmbz-{payment.id}",
            "notes": {"nammabiz_payment_id": str(payment.id), "job_id": str(payment.job_id)},
        })
    except Exception as error:
        raise PaymentGatewayError("Razorpay could not create a checkout order.") from error
    if not order or not order.get("id") or order.get("status") != "created":
        raise PaymentGatewayError("Razorpay returned an invalid checkout order.")
    payment.gateway_order_id = order["id"]
    payment.provider = "RAZORPAY_TEST" if current_app.config["PAYMENT_MODE"] == "razorpay_test" else "RAZORPAY_LIVE"
    return order


def verify_gateway_payment(payment, order_id, payment_id, signature):
    if payment.provider != selected_provider():
        raise PaymentGatewayError("This payment belongs to a different gateway mode.")
    if payment.status == "SUCCESS" and payment.transaction_id == payment_id:
        return True
    if payment.status != "PENDING" or not payment.gateway_order_id or order_id != payment.gateway_order_id:
        raise PaymentGatewayError("The payment does not match a pending NammaBiz order.")
    client = _razorpay_client()
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
        captured = client.payment.fetch(payment_id)
    except Exception as error:
        raise PaymentGatewayError("Razorpay could not verify this payment.") from error
    expected_amount = int((Decimal(payment.amount) * 100).quantize(Decimal("1")))
    if (
        captured.get("id") != payment_id
        or captured.get("order_id") != order_id
        or captured.get("status") != "captured"
        or captured.get("amount") != expected_amount
        or captured.get("currency") != "INR"
    ):
        raise PaymentGatewayError("Razorpay has not confirmed that this payment was captured.")
    payment.transaction_id = payment_id
    payment.status = "SUCCESS"
    payment.paid_at = utcnow()
    db.session.commit()
    return True
