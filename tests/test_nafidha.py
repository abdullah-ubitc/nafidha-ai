"""Backend tests for Libya Customs NAFIDHA Platform"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s

@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    token = r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s

# Auth tests
class TestAuth:
    def test_admin_login(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
        assert r.status_code == 200
        data = r.json()
        assert "user" in data
        assert data["user"]["role"] == "admin"
        assert "access_token" in data

    def test_invalid_login(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "wrong"})
        assert r.status_code == 401

    def test_register_importer(self, api):
        r = api.post(f"{BASE_URL}/api/auth/register", json={
            "email": "TEST_importer@test.ly",
            "password": "Test@1234!",
            "role": "importer",
            "name_ar": "مستورد اختبار",
            "name_en": "Test Importer",
            "entity_type": "individual",
            "phone": "0911234567",
            "city": "Tripoli"
        })
        assert r.status_code in [200, 201, 400]  # 400 if already exists
        if r.status_code in [200, 201]:
            data = r.json()
            assert "user" in data
            assert data["user"]["role"] == "importer"

    def test_login_importer(self, api):
        # register first if needed
        api.post(f"{BASE_URL}/api/auth/register", json={
            "email": "TEST_importer2@test.ly",
            "password": "Test@1234!",
            "role": "importer",
            "name_ar": "مستورد اختبار",
            "name_en": "Test Importer 2"
        })
        r = api.post(f"{BASE_URL}/api/auth/login", json={"email": "TEST_importer2@test.ly", "password": "Test@1234!"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_get_me(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == "admin@customs.ly"
        assert data["role"] == "admin"

# Dashboard tests
class TestDashboard:
    def test_admin_stats(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/dashboard/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total_users" in data
        assert "total_requests" in data

# ACID tests
class TestAcid:
    @pytest.fixture(scope="class")
    def importer_session(self):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        # Ensure user exists
        s.post(f"{BASE_URL}/api/auth/register", json={
            "email": "TEST_acid_user@test.ly",
            "password": "Test@1234!",
            "role": "importer",
            "name_ar": "مستورد ACID",
            "name_en": "ACID Test Importer"
        })
        r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "TEST_acid_user@test.ly", "password": "Test@1234!"})
        token = r.json().get("access_token")
        s.headers.update({"Authorization": f"Bearer {token}"})
        return s

    def test_create_acid(self, importer_session):
        r = importer_session.post(f"{BASE_URL}/api/acid", json={
            "supplier_name": "Test Supplier GmbH",
            "supplier_country": "DE",
            "goods_description": "Electronic components",
            "hs_code": "8471",
            "quantity": 100,
            "unit": "pcs",
            "value_usd": 5000,
            "port_of_entry": "Tripoli Port",
            "transport_mode": "sea"
        })
        assert r.status_code == 200
        data = r.json()
        assert "acid_number" in data
        acid_number = data["acid_number"]
        assert acid_number.startswith("ACID/2026/")
        # Store for later
        TestAcid.acid_number = acid_number
        TestAcid.acid_id = data["_id"]

    def test_list_acid(self, importer_session):
        r = importer_session.get(f"{BASE_URL}/api/acid")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_track_shipment(self, importer_session):
        if not hasattr(TestAcid, 'acid_number'):
            pytest.skip("ACID number not available")
        r = importer_session.get(f"{BASE_URL}/api/shipments/track/{TestAcid.acid_number}")
        assert r.status_code == 200
        data = r.json()
        assert data["acid_number"] == TestAcid.acid_number

    def test_review_acid(self, admin_session):
        if not hasattr(TestAcid, 'acid_id'):
            pytest.skip("ACID id not available")
        r = admin_session.put(f"{BASE_URL}/api/acid/{TestAcid.acid_id}/review", json={
            "action": "approve",
            "notes": "Approved by test"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["new_status"] == "approved"

# Fees tests
class TestFees:
    def test_calculate_fees(self, api):
        r = api.post(f"{BASE_URL}/api/fees/calculate", json={
            "value_usd": 10000,
            "hs_code": "8471",
            "quantity": 1
        })
        assert r.status_code == 200
        data = r.json()
        assert "customs_duty_usd" in data
        assert "total_usd" in data
        assert "vat_usd" in data
        assert data["value_usd"] == 10000
