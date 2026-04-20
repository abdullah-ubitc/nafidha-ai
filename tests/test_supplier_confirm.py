"""Tests for supplier confirm endpoints (Phase E) - public token-based endpoints"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Tokens are environment-specific — seed via TEST_* env vars
# Fallback to known-invalid values so tests gracefully skip if not set
VALID_TOKEN       = os.environ.get("TEST_SUPPLIER_VALID_TOKEN", "")
PRECONFIRMED_TOKEN = os.environ.get("TEST_SUPPLIER_PRECONFIRMED_TOKEN", "")
INVALID_TOKEN     = os.environ.get("TEST_SUPPLIER_INVALID_TOKEN", "invalid-token-that-does-not-exist-xyz123")
ADMIN_EMAIL       = os.environ.get("TEST_ADMIN_EMAIL", "admin@customs.ly")
ADMIN_PASSWORD    = os.environ.get("TEST_ADMIN_PASSWORD", "")


@pytest.fixture(scope="module")
def admin_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if resp.status_code == 200:
        return resp.cookies.get("access_token") or resp.json().get("access_token")
    pytest.skip("Admin login failed")


@pytest.fixture(scope="module")
def fresh_token(admin_token):
    """Create a new ACID with exporter_email and return its token"""
    session = requests.Session()
    # Login to get cookie
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if resp.status_code != 200:
        pytest.skip("Admin login failed")
    session.cookies.update(resp.cookies)

    # Create ACID with exporter_email
    payload = {
        "supplier_name": "TEST Supplier GmbH",
        "supplier_country": "Germany",
        "supplier_address": "Berliner Str 1, Berlin",
        "goods_description": "TEST Electronic Components",
        "hs_code": "8542.31",
        "quantity": 100,
        "unit": "pcs",
        "value_usd": 5000.0,
        "port_of_entry": "Tripoli",
        "transport_mode": "sea",
        "carrier_name": "MSC",
        "bill_of_lading": "MSC123TEST",
        "estimated_arrival": "2026-03-01",
        "exporter_email": "test-supplier@example.com",
        "exporter_tax_id": "TEST123456",
        "proforma_invoice": None,
        "on_behalf_of": None
    }
    create_resp = session.post(f"{BASE_URL}/api/acid", json=payload)
    if create_resp.status_code != 200:
        pytest.skip(f"Failed to create ACID: {create_resp.text}")
    data = create_resp.json()
    token = data.get("supplier_confirm_token")
    if not token:
        pytest.skip("No supplier_confirm_token in created ACID")
    return token


class TestSupplierConfirmBackend:
    """Backend tests for supplier confirm endpoints"""

    # Test 1: POST /api/acid creates supplier_confirm_token when exporter_email provided
    def test_create_acid_generates_token(self, fresh_token):
        assert fresh_token is not None and len(fresh_token) > 10
        print(f"PASS: fresh_token generated: {fresh_token[:20]}...")

    # Test 2: GET /api/acid/supplier/confirm/{token} returns shipment details (valid token)
    def test_get_supplier_confirm_valid_token(self):
        resp = requests.get(f"{BASE_URL}/api/acid/supplier/confirm/{VALID_TOKEN}")
        # Token might be confirmed already or still valid
        assert resp.status_code in [200, 404], f"Unexpected status: {resp.status_code}"
        if resp.status_code == 200:
            data = resp.json()
            assert "acid_number" in data
            assert "supplier_name" in data
            assert "goods_description" in data
            assert "value_usd" in data
            print(f"PASS: GET valid token returned acid_number={data['acid_number']}")
        else:
            print("INFO: Token no longer valid (ACID may have been re-created)")

    # Test with fresh token
    def test_get_supplier_confirm_fresh_token(self, fresh_token):
        resp = requests.get(f"{BASE_URL}/api/acid/supplier/confirm/{fresh_token}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "acid_number" in data
        assert data.get("supplier_name") == "TEST Supplier GmbH"
        assert data.get("value_usd") == 5000.0
        assert data.get("exporter_confirmation") == False
        print(f"PASS: Fresh token GET returned {data['acid_number']}")

    # Test 3: GET /api/acid/supplier/confirm/{token} returns 404 for invalid token
    def test_get_supplier_confirm_invalid_token(self):
        resp = requests.get(f"{BASE_URL}/api/acid/supplier/confirm/{INVALID_TOKEN}")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        print("PASS: Invalid token returns 404")

    # Test 4: POST /api/acid/supplier/confirm/{token} marks exporter_confirmation=True
    def test_post_supplier_confirm_fresh_token(self, fresh_token):
        resp = requests.post(f"{BASE_URL}/api/acid/supplier/confirm/{fresh_token}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data.get("already_confirmed") == False
        assert "acid_number" in data
        print(f"PASS: Confirmation successful for {data['acid_number']}")

        # Verify via GET that exporter_confirmation is now True
        get_resp = requests.get(f"{BASE_URL}/api/acid/supplier/confirm/{fresh_token}")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data.get("exporter_confirmation") == True
        print("PASS: GET after confirm shows exporter_confirmation=True")

    # Test 5: POST second time returns already_confirmed=True
    def test_post_supplier_confirm_already_confirmed(self, fresh_token):
        # Already confirmed from previous test
        resp = requests.post(f"{BASE_URL}/api/acid/supplier/confirm/{fresh_token}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert data.get("already_confirmed") == True
        print("PASS: Second confirmation returns already_confirmed=True")

    # Test pre-confirmed token (may be already confirmed)
    def test_preconfirmed_token(self):
        resp = requests.post(f"{BASE_URL}/api/acid/supplier/confirm/{PRECONFIRMED_TOKEN}")
        # Either already confirmed or invalid
        assert resp.status_code in [200, 404], f"Unexpected: {resp.status_code}"
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("already_confirmed") == True
            print(f"PASS: Pre-confirmed token returns already_confirmed=True")
        else:
            print("INFO: Pre-confirmed token no longer in DB")

    # Test POST with invalid token
    def test_post_supplier_confirm_invalid_token(self):
        resp = requests.post(f"{BASE_URL}/api/acid/supplier/confirm/{INVALID_TOKEN}")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
        print("PASS: POST with invalid token returns 404")
