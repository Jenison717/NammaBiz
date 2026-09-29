import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import create_app
from extensions import db
from models import AvailabilityRule, Contractor, ContractorService, Complaint, Job, JobMessage, Payment, PlatformSetting, Review, Service, ServiceCategory, ServiceRequest, User
from services.payment_service import PaymentGatewayError, _razorpay_client


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "workflow.sqlite3")
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def make_user(self, name, email, role):
        account = User(name=name, email=email, role=role)
        account.set_password("long-test-password")
        db.session.add(account)
        db.session.flush()
        return account

    def login(self, email):
        return self.client.post("/auth/login", data={"email": email, "password": "long-test-password"}, follow_redirects=True)

    def test_admin_routes_render_and_can_edit_service_catalog(self):
        with self.app.app_context():
            admin = self.make_user("Admin", "admin@example.test", "ADMIN")
            provider_user = self.make_user("Provider", "reviewed-provider@example.test", "CONTRACTOR")
            incomplete_user = self.make_user("Incomplete Provider", "incomplete-provider@example.test", "CONTRACTOR")
            provider = Contractor(user=provider_user, business_name="Pending Provider")
            incomplete_provider = Contractor(user=incomplete_user, business_name="Incomplete Provider")
            db.session.add_all([provider, incomplete_provider])
            db.session.flush()
            db.session.commit()
            provider_id = provider.id
            incomplete_provider_id = incomplete_provider.id
        response = self.client.post("/admin/login", data={"email": "admin@example.test", "password": "long-test-password"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        review_page = self.client.get(f"/admin/contractors/{incomplete_provider_id}/verification")
        self.assertEqual(review_page.status_code, 200)
        self.assertIn(b"Review the contractor profile", review_page.data)
        self.assertIn(b"Record decision", review_page.data)
        self.assertIn(b'value="APPROVED"', review_page.data)
        response = self.client.post(f"/admin/contractors/{incomplete_provider_id}/review", data={"decision": "APPROVED"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(Contractor, incomplete_provider_id).verification_status, "APPROVED")
        paths = ["/admin/users", "/admin/contractors", "/admin/categories", "/admin/jobs", "/admin/payments", "/admin/revenue", "/admin/reviews", "/admin/complaints", "/admin/notifications", "/admin/reports", "/admin/settings"]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        response = self.client.post(f"/admin/contractors/{provider_id}/review", data={"decision": "APPROVED", "note": "Documents checked"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(Contractor, provider_id).verification_status, "APPROVED")
        response = self.client.post("/admin/categories", data={"name": "Testing", "description": "Test services"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            category = ServiceCategory.query.filter_by(name="Testing").one()
            category_id = category.id
        response = self.client.post("/admin/services", data={"category_id": str(category_id), "name": "Fixture service", "description": "Editable service"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            service = Service.query.filter_by(name="Fixture service").one()
            self.assertTrue(service.active)
            service_id = service.id
        response = self.client.post(f"/admin/services/{service_id}", data={"name": "Fixture service", "category_id": str(category_id)}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertFalse(db.session.get(Service, service_id).active)

    def test_job_lifecycle_payment_review_and_complaint_resolution(self):
        with self.app.app_context():
            service = Service.query.first()
            customer = self.make_user("Customer", "customer@example.test", "USER")
            provider_user = self.make_user("Provider", "provider@example.test", "CONTRACTOR")
            self.make_user("Admin", "admin@example.test", "ADMIN")
            provider = Contractor(user=provider_user, business_name="Verified Repairs", city="Madurai", verification_status="APPROVED")
            provider.services = [ContractorService(service=service)]
            request = ServiceRequest(customer=customer, service=service, description="Repair a leaking kitchen pipe.", location="Madurai")
            second_request = ServiceRequest(customer=customer, service=service, description="Inspect a second kitchen pipe.", location="Madurai")
            db.session.add_all([provider, request, second_request])
            fee = PlatformSetting(key="platform_fee_percent", value="10")
            db.session.add(fee)
            db.session.commit()
            request_id, second_request_id, job_id = request.id, second_request.id, None
            contractor_id, customer_id = provider.id, customer.id

        self.login("provider@example.test")
        response = self.client.post(f"/contractor/requests/{request_id}/accept", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/contractor/requests/{second_request_id}/accept", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            item = db.session.get(ServiceRequest, request_id)
            self.assertEqual(item.status, "CONTRACTOR_ACCEPTED")
            job_id = item.job.id
            starts = (datetime.now() + timedelta(days=7)).replace(hour=10, minute=0, second=0, microsecond=0)
            db.session.add(AvailabilityRule(contractor_id=contractor_id, weekday=starts.weekday(), starts_at="09:00", ends_at="17:00"))
            db.session.commit()
        response = self.client.post(f"/contractor/jobs/{request_id}/schedule", data={"starts_at": starts.isoformat()}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/contractor/jobs/{second_request_id}/schedule", data={"starts_at": starts.isoformat()}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(ServiceRequest, second_request_id).status, "CONTRACTOR_ACCEPTED")
        response = self.client.post(f"/contractor/jobs/{request_id}/status", data={"status": "IN_PROGRESS"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/contractor/jobs/{request_id}/status", data={"status": "COMPLETED", "amount": "1000"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(ServiceRequest, request_id).status, "COMPLETED")
            self.assertEqual(db.session.get(Job, job_id).agreed_amount, 1000)

        self.client.post("/auth/logout")
        self.login("customer@example.test")
        detail = self.client.get(f"/user/requests/{request_id}")
        self.assertIn(f"/user/jobs/{job_id}/payment".encode(), detail.data)
        response = self.client.post(f"/user/jobs/{job_id}/payment", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            payment = Payment.query.filter_by(job_id=job_id).one()
            self.assertEqual(payment.status, "PENDING")
            self.assertEqual(float(payment.platform_fee), 100.0)
            payment_id = payment.id
        detail = self.client.get(f"/user/requests/{request_id}")
        self.assertIn(b"Payment record: Pending", detail.data)
        self.assertEqual(self.client.get(f"/payments/{payment_id}").status_code, 200)
        response = self.client.post(f"/reviews/{job_id}", data={"rating": "5", "service_quality": "5", "communication": "4", "punctuality": "5", "comment": "Good work"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/reviews/{job_id}", data={"rating": "4", "service_quality": "4", "communication": "4", "punctuality": "4"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(Review.query.filter_by(job_id=job_id).count(), 1)
        response = self.client.post(f"/jobs/{request_id}/messages", data={"body": "Thanks for completing the repair."}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(JobMessage.query.filter_by(job_id=job_id).one().body, "Thanks for completing the repair.")
        response = self.client.post(f"/jobs/{request_id}/complaints", data={"reason": "POOR_SERVICE", "details": "Please review this completed job."}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            complaint = Complaint.query.filter_by(job_id=job_id).one()
            self.assertEqual(db.session.get(ServiceRequest, request_id).status, "DISPUTED")
            complaint_id = complaint.id
        self.client.post("/auth/logout")
        self.client.post("/admin/login", data={"email": "admin@example.test", "password": "long-test-password"})
        response = self.client.post(f"/admin/complaints/{complaint_id}", data={"status": "UNDER_REVIEW", "resolution": "Investigating"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(f"/admin/complaints/{complaint_id}", data={"status": "RESOLVED", "resolution": "Reviewed and resolved."}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(ServiceRequest, request_id).status, "COMPLETED")
            self.assertEqual(db.session.get(Complaint, complaint_id).status, "RESOLVED")

    def test_razorpay_test_checkout_verifies_signature_and_capture_before_success(self):
        with self.app.app_context():
            service = Service.query.first()
            customer = self.make_user("Sandbox Customer", "sandbox-customer@example.test", "USER")
            provider_user = self.make_user("Sandbox Provider", "sandbox-provider@example.test", "CONTRACTOR")
            provider = Contractor(user=provider_user, business_name="Sandbox Provider", verification_status="APPROVED")
            service_request = ServiceRequest(customer=customer, service=service, contractor=provider, description="Completed demo work", location="Madurai", status="COMPLETED")
            job = Job(request=service_request, agreed_amount=Decimal("123.45"))
            payment = Payment(job=job, amount=Decimal("123.45"), platform_fee=Decimal("0.00"), status="PENDING")
            db.session.add_all([provider, service_request, job, payment])
            db.session.commit()
            job_id, payment_id = job.id, payment.id

        self.app.config.update({
            "PAYMENT_MODE": "razorpay_test",
            "RAZORPAY_KEY_ID": "rzp_test_demo_key",
            "RAZORPAY_KEY_SECRET": "test-secret-only-in-test",
        })
        self.login("sandbox-customer@example.test")
        gateway = MagicMock()
        gateway.order.create.return_value = {"id": "order_demo_123", "status": "created"}
        gateway.payment.fetch.return_value = {"id": "pay_demo_456", "order_id": "order_demo_123", "status": "captured", "amount": 12345, "currency": "INR"}
        with patch("services.payment_service._razorpay_client", return_value=gateway):
            response = self.client.post(f"/user/jobs/{job_id}/payment", follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"RAZORPAY TEST MODE", response.data)
            self.assertIn(b"order_demo_123", response.data)
            self.client.post(f"/user/jobs/{job_id}/payment", follow_redirects=True)
            self.assertEqual(gateway.order.create.call_count, 1)
            self.app.config["PAYMENT_MODE"] = "razorpay_live"
            response = self.client.post(f"/payments/{payment_id}/verify", json={
                "razorpay_order_id": "order_demo_123",
                "razorpay_payment_id": "pay_demo_456",
                "razorpay_signature": "signature-from-test-mode",
            })
            self.assertEqual(response.status_code, 400)
            self.app.config["PAYMENT_MODE"] = "razorpay_test"
            gateway.utility.verify_payment_signature.side_effect = ValueError("Invalid signature")
            response = self.client.post(f"/payments/{payment_id}/verify", json={
                "razorpay_order_id": "order_demo_123",
                "razorpay_payment_id": "pay_demo_456",
                "razorpay_signature": "forged",
            })
            self.assertEqual(response.status_code, 400)
            with self.app.app_context():
                self.assertEqual(db.session.get(Payment, payment_id).status, "PENDING")
                self.assertIsNone(db.session.get(Payment, payment_id).transaction_id)
            gateway.utility.verify_payment_signature.side_effect = None
            response = self.client.post(f"/payments/{payment_id}/verify", json={
                "razorpay_order_id": "order_demo_123",
                "razorpay_payment_id": "pay_demo_456",
                "razorpay_signature": "valid-test-signature",
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json["verified"])
        with self.app.app_context():
            payment = db.session.get(Payment, payment_id)
            self.assertEqual(payment.status, "SUCCESS")
            self.assertEqual(payment.transaction_id, "pay_demo_456")
            self.assertEqual(payment.gateway_order_id, "order_demo_123")

    def test_razorpay_client_rejects_key_mode_mismatch(self):
        self.app.config.update({
            "PAYMENT_MODE": "razorpay_test",
            "RAZORPAY_KEY_ID": "rzp_live_wrong_mode",
            "RAZORPAY_KEY_SECRET": "test-secret-only-in-test",
        })
        with self.app.app_context():
            with self.assertRaises(PaymentGatewayError):
                _razorpay_client()
            self.app.config["RAZORPAY_KEY_ID"] = "rzp_test_valid_prefix"
            client = _razorpay_client()
            self.assertTrue(hasattr(client, "order"))

    def test_razorpay_webhook_requires_hmac_and_captured_order_details(self):
        with self.app.app_context():
            service = Service.query.first()
            customer = self.make_user("Webhook Customer", "webhook-customer@example.test", "USER")
            provider_user = self.make_user("Webhook Provider", "webhook-provider@example.test", "CONTRACTOR")
            provider = Contractor(user=provider_user, business_name="Webhook Provider", verification_status="APPROVED")
            service_request = ServiceRequest(customer=customer, service=service, contractor=provider, description="Completed webhook job", location="Madurai", status="COMPLETED")
            job = Job(request=service_request, agreed_amount=Decimal("50.00"))
            payment = Payment(job=job, amount=Decimal("50.00"), platform_fee=Decimal("2.50"), status="PENDING", gateway_order_id="order_webhook_123", provider="RAZORPAY_TEST")
            db.session.add_all([provider, service_request, job, payment])
            db.session.commit()
            payment_id = payment.id
        self.app.config.update({"RAZORPAY_WEBHOOK_SECRET": "webhook-secret-only-in-test", "PAYMENT_MODE": "razorpay_test"})
        payload = {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_webhook_456", "order_id": "order_webhook_123", "status": "captured", "amount": 5000, "currency": "INR"}}},
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(b"webhook-secret-only-in-test", body, hashlib.sha256).hexdigest()
        response = self.client.post("/payments/webhooks/razorpay", data=body, headers={"X-Razorpay-Signature": "invalid"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.get(Payment, payment_id).status, "PENDING")
        response = self.client.post("/payments/webhooks/razorpay", data=body, headers={"X-Razorpay-Signature": signature}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            payment = db.session.get(Payment, payment_id)
            self.assertEqual(payment.status, "SUCCESS")
            self.assertEqual(payment.transaction_id, "pay_webhook_456")


if __name__ == "__main__":
    unittest.main()
