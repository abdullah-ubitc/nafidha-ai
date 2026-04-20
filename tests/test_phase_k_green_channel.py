"""Phase K - Green Channel backend tests"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


def get_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.cookies.get("access_token") or r.json().get("access_token")
    return None


def auth_session(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s


@pytest.fixture(scope="module")
def importer_session():
    return auth_session("importer@customs.ly", "Importer@2026!")


@pytest.fixture(scope="module")
def admin_session():
    return auth_session("admin@customs.ly", "Admin@2026!")


@pytest.fixture(scope="module")
def risk_session():
    return auth_session("acidrisk@customs.ly", "AcidRisk@2026!")


ACID_PAYLOAD_GREEN = {
    "supplier_name": "Samsung Electronics GmbH",
    "supplier_country": "Germany",
    "supplier_address": "Berlin, Germany",
    "goods_description": "Electronic Components Test",
    "hs_code": "8542.31",
    "quantity": 100,
    "unit": "pcs",
    "value_usd": 5000,
    "port_of_entry": "ميناء طرابلس البحري",
    "transport_mode": "sea",
    "carrier_name": "Test Carrier",
    "bill_of_lading": "BL-TEST-001",
    "estimated_arrival": "2026-04-01",
    "exporter_tax_id": "DE123456789",
    "exporter_email": "samsung@test.com",
}

ACID_PAYLOAD_NO_GREEN = {
    "supplier_name": "Unknown Supplier",
    "supplier_country": "Italy",
    "supplier_address": "Rome, Italy",
    "goods_description": "Misc Goods",
    "hs_code": "9999.99",
    "quantity": 10,
    "unit": "pcs",
    "value_usd": 500,
    "port_of_entry": "ميناء مصراتة",
    "transport_mode": "sea",
    "carrier_name": "Carrier B",
    "bill_of_lading": "BL-TEST-002",
    "estimated_arrival": "2026-04-15",
    # No exporter_tax_id
}


class TestGreenChannelCreate:
    """Test ACID creation with green channel detection"""

    def test_create_acid_with_verified_exporter_is_green(self, importer_session):
        """POST /api/acid with DE123456789 (verified) → is_green_channel=True, priority_score=100"""
        r = importer_session.post(f"{BASE_URL}/api/acid", json=ACID_PAYLOAD_GREEN)
        assert r.status_code == 200, f"Failed: {r.text}"
        data = r.json()
        assert data.get("is_green_channel") is True, f"Expected is_green_channel=True, got {data.get('is_green_channel')}"
        assert data.get("priority_score") == 100, f"Expected priority_score=100, got {data.get('priority_score')}"
        # Store acid_id for later tests
        TestGreenChannelCreate.green_acid_id = data.get("_id") or data.get("id")
        TestGreenChannelCreate.green_acid_number = data.get("acid_number")
        print(f"✅ Green Channel ACID created: {data.get('acid_number')}, is_green_channel={data.get('is_green_channel')}, priority_score={data.get('priority_score')}")

    def test_create_acid_without_exporter_tax_id_not_green(self, importer_session):
        """POST /api/acid without exporter_tax_id → is_green_channel=False, priority_score=0"""
        r = importer_session.post(f"{BASE_URL}/api/acid", json=ACID_PAYLOAD_NO_GREEN)
        assert r.status_code == 200, f"Failed: {r.text}"
        data = r.json()
        assert data.get("is_green_channel") is False, f"Expected is_green_channel=False, got {data.get('is_green_channel')}"
        assert data.get("priority_score") == 0, f"Expected priority_score=0, got {data.get('priority_score')}"
        TestGreenChannelCreate.regular_acid_id = data.get("_id") or data.get("id")
        print(f"✅ Regular ACID created: {data.get('acid_number')}, is_green_channel={data.get('is_green_channel')}, priority_score={data.get('priority_score')}")


class TestAcidRiskQueue:
    """Test that green channel requests appear first in the queue"""

    def test_queue_green_first(self, risk_session):
        """GET /api/acid-risk/queue → green channel (priority_score=100) items first"""
        r = risk_session.get(f"{BASE_URL}/api/acid-risk/queue")
        assert r.status_code == 200, f"Failed: {r.text}"
        items = r.json()
        assert isinstance(items, list), "Expected list response"
        if len(items) > 1:
            # Verify ordering: items with higher priority_score come first
            scores = [item.get("priority_score", 0) for item in items]
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i+1], f"Queue not sorted: scores[{i}]={scores[i]} < scores[{i+1}]={scores[i+1]}"
            print(f"✅ Queue sorted correctly. Priority scores: {scores[:5]}")
        
        # Check green channel items are present
        green_items = [i for i in items if i.get("is_green_channel") is True]
        print(f"✅ Queue: {len(items)} total, {len(green_items)} green channel")


class TestExecutiveDashboard:
    """Test executive dashboard green channel metrics"""

    def test_dashboard_has_green_channel_key(self, admin_session):
        """GET /api/executive/dashboard → contains green_channel key"""
        r = admin_session.get(f"{BASE_URL}/api/executive/dashboard")
        assert r.status_code == 200, f"Failed: {r.text}"
        data = r.json()
        assert "green_channel" in data, f"Missing 'green_channel' key in response"
        gc = data["green_channel"]
        assert "total" in gc, "Missing total in green_channel"
        assert "pending" in gc, "Missing pending in green_channel"
        assert "approved" in gc, "Missing approved in green_channel"
        assert "active_ports" in gc, "Missing active_ports in green_channel"
        assert gc["total"] >= 1, f"Expected at least 1 green channel total, got {gc['total']}"
        print(f"✅ green_channel: total={gc['total']}, pending={gc['pending']}, approved={gc['approved']}, ports={gc['active_ports']}")

    def test_dashboard_green_channel_avg_hours(self, admin_session):
        """Executive dashboard has clearance time comparison fields"""
        r = admin_session.get(f"{BASE_URL}/api/executive/dashboard")
        assert r.status_code == 200
        gc = r.json()["green_channel"]
        assert "avg_clearance_hours_green" in gc
        assert "avg_clearance_hours_regular" in gc
        print(f"✅ Clearance hours: green={gc['avg_clearance_hours_green']}, regular={gc['avg_clearance_hours_regular']}")


class TestClearanceTimestamps:
    """Test clearance_started_at and clearance_completed_at recording"""

    def test_review_action_sets_clearance_started_at(self, risk_session):
        """PUT /api/acid/{id}/review with action=review → sets clearance_started_at"""
        acid_id = getattr(TestGreenChannelCreate, 'green_acid_id', None)
        if not acid_id:
            pytest.skip("No green acid_id from create test")
        r = risk_session.put(f"{BASE_URL}/api/acid/{acid_id}/review",
                             json={"action": "review", "notes": "بدء مراجعة القناة الخضراء"})
        assert r.status_code == 200, f"Failed: {r.text}"
        data = r.json()
        assert data.get("new_status") == "under_review"
        
        # Verify clearance_started_at was set
        acid_r = risk_session.get(f"{BASE_URL}/api/acid/{acid_id}")
        assert acid_r.status_code == 200
        acid = acid_r.json()
        assert acid.get("clearance_started_at") is not None, "clearance_started_at should be set after review action"
        print(f"✅ clearance_started_at set: {acid.get('clearance_started_at')}")

    def test_approve_action_sets_clearance_completed_at(self, risk_session):
        """PUT /api/acid/{id}/review with action=approve → sets clearance_completed_at"""
        acid_id = getattr(TestGreenChannelCreate, 'green_acid_id', None)
        if not acid_id:
            pytest.skip("No green acid_id from create test")
        r = risk_session.put(f"{BASE_URL}/api/acid/{acid_id}/review",
                             json={"action": "approve", "notes": "اعتماد القناة الخضراء"})
        assert r.status_code == 200, f"Failed: {r.text}"
        data = r.json()
        assert data.get("new_status") == "approved"
        
        # Verify clearance_completed_at was set
        acid_r = risk_session.get(f"{BASE_URL}/api/acid/{acid_id}")
        assert acid_r.status_code == 200
        acid = acid_r.json()
        assert acid.get("clearance_completed_at") is not None, "clearance_completed_at should be set after approve action"
        print(f"✅ clearance_completed_at set: {acid.get('clearance_completed_at')}")
