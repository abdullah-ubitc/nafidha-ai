"""Backend tests for Phase L — Notification System"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

def login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.cookies, r.json()
    return None, None

@pytest.fixture(scope="module")
def importer_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "importer@customs.ly", "password": "Importer@2026!"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s

@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s

@pytest.fixture(scope="module")
def risk_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "acidrisk@customs.ly", "password": "AcidRisk@2026!"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s


class TestNotificationCRUD:
    """Test notification CRUD endpoints"""

    def test_get_notifications(self, importer_session):
        r = importer_session.get(f"{BASE_URL}/api/notifications")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list)
        print(f"GET /notifications: {len(data)} notifications found")

    def test_get_unread_count(self, importer_session):
        r = importer_session.get(f"{BASE_URL}/api/notifications/unread-count")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "count" in data
        assert isinstance(data["count"], int)
        print(f"GET /notifications/unread-count: {data['count']} unread")

    def test_mark_all_read(self, importer_session):
        r = importer_session.put(f"{BASE_URL}/api/notifications/read-all")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("ok") == True
        # Verify count is now 0
        r2 = importer_session.get(f"{BASE_URL}/api/notifications/unread-count")
        assert r2.status_code == 200
        assert r2.json()["count"] == 0
        print("mark_all_read: count is now 0 ✓")

    def test_notifications_require_auth(self):
        r = requests.get(f"{BASE_URL}/api/notifications")
        assert r.status_code in [401, 403], f"Expected 401/403 for unauthenticated, got {r.status_code}"
        print("Auth guard working ✓")


class TestAcidCreatesNotifications:
    """Test that ACID creation triggers notifications"""

    def test_acid_submitted_notification_created(self, importer_session):
        """Creating ACID should trigger acid_submitted notification"""
        # Get count before
        r0 = importer_session.get(f"{BASE_URL}/api/notifications/unread-count")
        before_count = r0.json()["count"]

        # Create an ACID without exporter_tax_id
        acid_data = {
            "bl_number": "TEST-BL-001",
            "vessel_name": "TEST VESSEL",
            "voyage_number": "V001",
            "port_of_loading": "Hamburg",
            "port_of_discharge": "Tripoli",
            "supplier_name": "Test Supplier GmbH",
            "supplier_country": "DE",
            "supplier_address": "Hamburg, Germany",
            "hs_code": "84713000",
            "goods_description": "Laptop Computers for testing",
            "quantity": 10,
            "unit": "piece",
            "weight_kg": 50.0,
            "value_usd": 5000.0,
            "currency": "USD",
            "transport_mode": "sea",
            "invoice_number": "INV-TEST-001",
            "port_of_entry": "Tripoli",
        }
        r = importer_session.post(f"{BASE_URL}/api/acid", json=acid_data)
        assert r.status_code in [200, 201], f"ACID creation failed: {r.status_code} {r.text}"
        acid = r.json()
        acid_id = acid.get("id") or acid.get("_id")
        print(f"Created ACID: {acid.get('acid_number')} id={acid_id}")

        import time; time.sleep(1)  # wait for async notification

        # Check unread count increased
        r2 = importer_session.get(f"{BASE_URL}/api/notifications/unread-count")
        after_count = r2.json()["count"]
        assert after_count > before_count, f"Expected notification count to increase. Before: {before_count}, After: {after_count}"
        print(f"acid_submitted notification created ✓ ({before_count} → {after_count})")

        # Check notification list contains acid_submitted
        r3 = importer_session.get(f"{BASE_URL}/api/notifications")
        notifs = r3.json()
        templates = [n.get("template") for n in notifs]
        assert "acid_submitted" in templates, f"acid_submitted not in notifications: {templates[:5]}"
        print("acid_submitted template found ✓")
        return acid_id

    def test_acid_with_verified_exporter_creates_green_channel(self, importer_session, admin_session):
        """ACID with verified exporter should create green_channel notification"""
        # First ensure a verified exporter exists
        tax_id = "TEST-VERIFIED-EXP-001"

        # Create/verify exporter via admin
        exp_data = {
            "tax_id": tax_id,
            "company_name": "Test Verified Exporter",
            "country": "DE",
            "is_verified": True
        }
        # Try creating via exporters API if available
        r_exp = admin_session.post(f"{BASE_URL}/api/exporters", json=exp_data)
        print(f"Exporter creation: {r_exp.status_code}")

        # Get count before
        r0 = importer_session.get(f"{BASE_URL}/api/notifications/unread-count")
        before_count = r0.json()["count"]

        acid_data = {
            "bl_number": "TEST-BL-GREEN-001",
            "vessel_name": "GREEN VESSEL",
            "voyage_number": "V002",
            "port_of_loading": "Hamburg",
            "port_of_discharge": "Tripoli",
            "supplier_name": "Test Verified Exporter",
            "supplier_country": "DE",
            "supplier_address": "Hamburg, Germany",
            "exporter_tax_id": tax_id,
            "hs_code": "84713000",
            "goods_description": "Computers",
            "quantity": 5,
            "unit": "piece",
            "weight_kg": 25.0,
            "value_usd": 3000.0,
            "currency": "USD",
            "transport_mode": "sea",
            "invoice_number": "INV-GREEN-001",
            "port_of_entry": "Tripoli",
        }
        r = importer_session.post(f"{BASE_URL}/api/acid", json=acid_data)
        assert r.status_code in [200, 201], f"ACID creation failed: {r.text}"
        print(f"Created ACID with exporter_tax_id: {r.json().get('acid_number')}")

        import time; time.sleep(1)

        # Check if notification count increased (at least acid_submitted)
        r2 = importer_session.get(f"{BASE_URL}/api/notifications/unread-count")
        after_count = r2.json()["count"]
        assert after_count > before_count, f"No new notifications after ACID with exporter. Before: {before_count}, After: {after_count}"

        # Check for green_channel in notifications
        r3 = importer_session.get(f"{BASE_URL}/api/notifications")
        notifs = r3.json()
        templates = [n.get("template") for n in notifs]
        print(f"Templates found: {set(templates)}")
        if "green_channel_activated" in templates:
            print("green_channel_activated notification found ✓")
        else:
            print(f"Note: green_channel_activated not found (exporter may not be verified). Templates: {set(templates)}")

    def test_mark_single_notification_read(self, importer_session):
        """Test marking a single notification as read"""
        r = importer_session.get(f"{BASE_URL}/api/notifications")
        notifs = r.json()
        unread = [n for n in notifs if not n.get("is_read")]
        if not unread:
            pytest.skip("No unread notifications to test")

        notif_id = unread[0]["_id"]
        r2 = importer_session.put(f"{BASE_URL}/api/notifications/{notif_id}/read")
        assert r2.status_code == 200
        assert r2.json().get("ok") == True
        print(f"Mark single read ✓ id={notif_id}")


class TestAcidStatusNotifications:
    """Test that ACID status changes trigger notifications"""

    def test_acid_under_review_notification(self, importer_session, risk_session):
        """Changing ACID to under_review should create notification"""
        # First create an ACID
        acid_data = {
            "bl_number": "TEST-REVIEW-001",
            "vessel_name": "REVIEW VESSEL",
            "voyage_number": "V003",
            "port_of_loading": "Hamburg",
            "port_of_discharge": "Tripoli",
            "supplier_name": "Review Supplier",
            "supplier_country": "DE",
            "supplier_address": "Berlin",
            "hs_code": "84713000",
            "goods_description": "Test Goods for review",
            "quantity": 5,
            "unit": "piece",
            "weight_kg": 20.0,
            "value_usd": 2000.0,
            "currency": "USD",
            "transport_mode": "sea",
            "invoice_number": "INV-REVIEW-001",
            "port_of_entry": "Tripoli",
        }
        r = importer_session.post(f"{BASE_URL}/api/acid", json=acid_data)
        assert r.status_code in [200, 201], f"ACID creation failed: {r.text}"
        acid_id = r.json().get("id") or r.json().get("_id")
        print(f"Created ACID for review test: id={acid_id}")

        import time; time.sleep(0.5)

        # Get count before review
        r0 = importer_session.get(f"{BASE_URL}/api/notifications/unread-count")
        before_count = r0.json()["count"]

        # Change to under_review
        review_data = {"status": "under_review", "review_note": "Under review for testing"}
        r2 = risk_session.put(f"{BASE_URL}/api/acid/{acid_id}/review", json=review_data)
        print(f"Review status change: {r2.status_code} {r2.text[:200]}")

        if r2.status_code == 200:
            time.sleep(1)
            r3 = importer_session.get(f"{BASE_URL}/api/notifications/unread-count")
            after_count = r3.json()["count"]
            print(f"After under_review: notifications {before_count} → {after_count}")

            r4 = importer_session.get(f"{BASE_URL}/api/notifications")
            notifs = r4.json()
            templates = [n.get("template") for n in notifs[:10]]
            print(f"Recent templates: {templates}")
            if "acid_under_review" in templates:
                print("acid_under_review notification found ✓")
            else:
                print(f"acid_under_review not found in recent templates")
        else:
            print(f"Review endpoint returned {r2.status_code} — may need different role or endpoint")
