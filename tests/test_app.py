import io
import json
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from app import create_app


class NammaBizTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "test.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def request(self, path, method="GET", payload=b"", content_type=""):
        environ = {}
        setup_testing_defaults(environ)
        environ.update({"PATH_INFO": path, "REQUEST_METHOD": method, "wsgi.input": io.BytesIO(payload), "CONTENT_LENGTH": str(len(payload)), "CONTENT_TYPE": content_type})
        captured = {}
        body = b"".join(self.app(environ, lambda status, headers: captured.update(status=status, headers=dict(headers))))
        return captured, body

    def test_home_and_api_list_seeded_businesses(self):
        response, body = self.request("/")
        self.assertEqual(response["status"], "200 OK")
        self.assertIn(b"Bharath Steels", body)
        response, body = self.request("/api/businesses")
        self.assertEqual(response["status"], "200 OK")
        self.assertGreaterEqual(len(json.loads(body)), 8)

    def test_search_and_rfq_flow(self):
        self.assertEqual(self.app.search("welding", available=True)[0]["name"], "Vaigai Fabrications")
        payload = b"business_id=1&buyer_name=Ravi&buyer_email=ravi%40example.com&requirement=Need+TMT+bars"
        response, _ = self.request("/rfq", "POST", payload, "application/x-www-form-urlencoded")
        self.assertEqual(response["status"], "302 Found")
        self.assertEqual(len(self.app.rows("SELECT * FROM rfqs")), 1)

    def test_rfq_requires_valid_contact_and_detail(self):
        payload = b"business_id=1&buyer_name=Ravi&buyer_email=invalid&requirement=Need+steel"
        response, _ = self.request("/rfq", "POST", payload, "application/x-www-form-urlencoded")
        self.assertEqual(response["status"], "302 Found")
        self.assertEqual(len(self.app.rows("SELECT * FROM rfqs")), 0)

    def test_rfq_api_reports_validation_results_accurately(self):
        response, body = self.request("/api/rfqs", "POST", b'{"business_id":999,"buyer_name":"Ravi","buyer_email":"ravi@example.com","requirement":"Need enough detail for a quote"}', "application/json")
        self.assertEqual(response["status"], "400 Bad Request")
        self.assertFalse(json.loads(body)["created"])
        response, body = self.request("/api/rfqs", "POST", b'{"business_id":1,"buyer_name":"Ravi","buyer_email":"ravi@example.com","requirement":"Need enough detail for a quote"}', "application/json")
        self.assertEqual(response["status"], "201 Created")
        self.assertTrue(json.loads(body)["created"])

    def test_estimator_calculates_construction_and_fabrication_ranges(self):
        construction = self.app.estimate("construction", {"area": ["1200"], "quality": ["standard"]})
        fabrication = self.app.estimate("fabrication", {"width": ["12"], "height": ["7"], "kind": ["gate"]})
        self.assertEqual((construction["low"], construction["high"]), (2520000, 3000000))
        self.assertEqual((fabrication["low"], fabrication["high"]), (54600, 79800))


if __name__ == "__main__":
    unittest.main()
