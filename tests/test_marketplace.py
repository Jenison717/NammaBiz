import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from config import Config
from extensions import db
from models import Contractor, ContractorService, PlatformSetting, Service, ServiceRequest, User
from scripts.import_legacy_sqlite import import_legacy_records


class MarketplaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "marketplace.sqlite3")
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def register_customer(self):
        return self.client.post("/auth/register", data={
            "name": "Test Customer",
            "email": "customer@example.test",
            "mobile": "9000000000",
            "password": "long-test-password",
        }, follow_redirects=True)

    def test_first_run_setup_creates_one_admin_and_platform_fee_once(self):
        response = self.client.get("/setup")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/setup", self.client.get("/auth/login").data)
        response = self.client.post("/setup", data={
            "name": "Initial Admin",
            "email": "initial-admin@example.test",
            "password": "initial-admin-password",
            "platform_fee_percent": "7.5",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Marketplace overview", response.data)
        self.assertNotIn(b"href=\"/setup\"", response.data)
        with self.app.app_context():
            admin = User.query.filter_by(email="initial-admin@example.test").one()
            self.assertEqual(admin.role, "ADMIN")
            self.assertTrue(admin.check_password("initial-admin-password"))
            self.assertEqual(User.query.filter_by(role="ADMIN").count(), 1)
            self.assertEqual(db.session.get(PlatformSetting, "platform_fee_percent").value, "7.5")
        self.assertEqual(self.client.get("/setup").status_code, 302)
        self.client.post("/auth/logout")
        self.assertNotIn(b"href=\"/setup\"", self.client.get("/auth/login").data)

    def test_first_run_setup_is_hidden_from_production_and_remote_clients(self):
        response = self.client.get("/setup", environ_overrides={"REMOTE_ADDR": "10.0.0.8"})
        self.assertEqual(response.status_code, 404)
        self.app.config["FLASK_ENV"] = "production"
        try:
            self.assertEqual(self.client.get("/setup").status_code, 404)
        finally:
            self.app.config["FLASK_ENV"] = "development"

    def test_customer_registration_hashes_password_and_blocks_other_roles(self):
        response = self.register_customer()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome, Test Customer", response.data)
        dashboard = self.client.get("/user/dashboard")
        self.assertIn(b"/user/requests", dashboard.data)
        self.assertIn(b"/user/payments", dashboard.data)
        self.assertIn(b"/user/reviews", dashboard.data)
        homepage = self.client.get("/")
        self.assertIn(b"/user/dashboard", homepage.data)
        self.assertIn(b"/auth/logout", homepage.data)
        with self.app.app_context():
            user = User.query.filter_by(email="customer@example.test").one()
            self.assertNotEqual(user.password_hash, "long-test-password")
            self.assertTrue(user.check_password("long-test-password"))
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 403)
        self.assertEqual(self.client.get("/contractor/dashboard").status_code, 403)

    def test_user_can_create_a_service_request(self):
        self.register_customer()
        with self.app.app_context():
            service_id = Service.query.first().id
        response = self.client.post("/user/requests/new", data={
            "service_id": str(service_id),
            "description": "Repair a leaking kitchen pipe and check the valve.",
            "location": "Anna Nagar, Madurai",
            "budget": "2500",
            "urgency": "NORMAL",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"General construction", response.data)
        with self.app.app_context():
            self.assertEqual(ServiceRequest.query.count(), 1)
            self.assertEqual(ServiceRequest.query.one().status, "PENDING")

    def test_contractor_profile_links_to_a_preselected_service_request(self):
        self.register_customer()
        with self.app.app_context():
            service = Service.query.first()
            provider_user = User(name="Approved Provider", email="approved@example.test", role="CONTRACTOR")
            provider_user.set_password("long-test-password")
            provider = Contractor(user=provider_user, business_name="Approved Repairs", verification_status="APPROVED")
            provider.services = [ContractorService(service=service)]
            db.session.add(provider)
            db.session.commit()
            provider_id, service_id = provider.id, service.id
        response = self.client.get(f"/contractors/{provider_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/user/requests/new?service={service_id}".encode(), response.data)
        form = self.client.get(f"/user/requests/new?service={service_id}")
        self.assertEqual(form.status_code, 200)
        self.assertIn(b"selected", form.data)

    def test_contractor_registration_is_pending_and_cannot_accept_jobs(self):
        with self.app.app_context():
            service_id = Service.query.first().id
        response = self.client.post("/auth/register/contractor", data={
            "name": "Test Contractor",
            "email": "contractor@example.test",
            "mobile": "9000000001",
            "password": "long-test-password",
            "business_name": "Test Services",
            "business_type": "Repair",
            "experience_years": "4",
            "city": "Madurai",
            "services": [str(service_id)],
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"pending admin verification", response.data)
        dashboard = self.client.get("/contractor/dashboard")
        self.assertIn(b"/contractor/earnings", dashboard.data)
        self.assertIn(b"/contractor/schedule", dashboard.data)
        self.assertIn(b"/notifications/", dashboard.data)
        with self.app.app_context():
            contractor = User.query.filter_by(email="contractor@example.test").one().contractor
            self.assertEqual(contractor.verification_status, "PENDING")
            customer = User(name="Request Owner", email="owner@example.test", role="USER")
            customer.set_password("long-test-password")
            request = ServiceRequest(customer=customer, service_id=service_id, description="Need repair work", location="Madurai")
            db.session.add_all([customer, request])
            db.session.commit()
            request_id = request.id
        response = self.client.post(f"/contractor/requests/{request_id}/accept", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 403)
        self.assertEqual(self.client.get("/user/dashboard").status_code, 403)
        with self.app.app_context():
            self.assertEqual(db.session.get(ServiceRequest, request_id).status, "PENDING")

    def test_csrf_is_required_when_enabled(self):
        self.app.config["WTF_CSRF_ENABLED"] = True
        response = self.client.post("/auth/register", data={
            "name": "No Token",
            "email": "no-token@example.test",
            "password": "long-test-password",
        })
        self.assertEqual(response.status_code, 400)

    def test_password_reset_link_expires_and_cannot_be_reused_after_reset(self):
        self.register_customer()
        self.client.post("/auth/logout")
        self.client.post("/auth/forgot", data={"email": "customer@example.test"})
        reset_url = self.app.extensions["mail_outbox"][0]["url"]
        token = reset_url.rsplit("/", 1)[1]
        response = self.client.post(f"/auth/reset/{token}", data={"password": "new-long-password"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(f"/auth/reset/{token}").status_code, 302)
        self.client.post("/auth/logout")
        response = self.client.post("/auth/login", data={"email": "customer@example.test", "password": "new-long-password"})
        self.assertEqual(response.status_code, 302)

    def test_legacy_importer_refuses_to_overwrite_destination_data(self):
        source = Path(self.temp.name) / "source.sqlite3"
        connection = sqlite3.connect(source)
        try:
            connection.execute("CREATE TABLE businesses (id INTEGER)")
            connection.execute("CREATE TABLE products (id INTEGER)")
            connection.execute("CREATE TABLE rfqs (id INTEGER)")
        finally:
            connection.close()
        with patch("scripts.import_legacy_sqlite.create_app", return_value=self.app):
            with self.assertRaisesRegex(ValueError, "must be empty"):
                import_legacy_records(source)
        with self.app.app_context():
            self.assertEqual(self.app.rows("SELECT COUNT(*) AS total FROM businesses")[0]["total"], 8)

    def test_legacy_importer_preserves_ids_and_rows_in_an_empty_destination(self):
        source = Path(self.temp.name) / "source-with-records.sqlite3"
        connection = sqlite3.connect(source)
        try:
            connection.executescript("""
                CREATE TABLE businesses (id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, subcategory TEXT NOT NULL, location TEXT NOT NULL, description TEXT NOT NULL, buyer_types TEXT NOT NULL, products TEXT NOT NULL, services TEXT NOT NULL, phone TEXT NOT NULL, rating REAL NOT NULL, available INTEGER NOT NULL, wholesale INTEGER NOT NULL, verified INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE products (id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL, unit TEXT NOT NULL, price REAL NOT NULL, description TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE rfqs (id INTEGER PRIMARY KEY, business_id INTEGER NOT NULL, buyer_name TEXT NOT NULL, buyer_email TEXT NOT NULL, requirement TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                INSERT INTO businesses VALUES (42,'Preserved Supplier','Electrical','Electrical trade','Madurai','Existing listing','Builders','Cables','Delivery','000',4.5,1,0,1,CURRENT_TIMESTAMP);
                INSERT INTO products VALUES (71,42,'Copper cable','Electrical','coil',100,'Existing product',1);
                INSERT INTO rfqs VALUES (93,42,'Buyer','buyer@example.test','Existing requirement','PENDING',CURRENT_TIMESTAMP);
            """)
        finally:
            connection.close()
        target_path = Path(self.temp.name) / "empty-target.sqlite3"
        sample_seed = Config.SEED_SAMPLE_DATA
        Config.SEED_SAMPLE_DATA = False
        try:
            target_app = create_app(target_path)
        finally:
            Config.SEED_SAMPLE_DATA = sample_seed
        with patch("scripts.import_legacy_sqlite.create_app", return_value=target_app):
            counts = import_legacy_records(source)
        self.assertEqual(counts, {"businesses": 1, "products": 1, "rfqs": 1})
        with target_app.app_context():
            self.assertEqual(target_app.rows("SELECT id,name FROM businesses")[0]["id"], 42)
            self.assertEqual(target_app.rows("SELECT id FROM products")[0]["id"], 71)
            self.assertEqual(target_app.rows("SELECT id FROM rfqs")[0]["id"], 93)


if __name__ == "__main__":
    unittest.main()
