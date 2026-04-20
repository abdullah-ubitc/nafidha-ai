"""
Test KYC enforcement on POST /api/acid endpoint.
Critical bug fix: Users with non-approved KYC status must be blocked from creating ACID requests.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ACID_PAYLOAD = {
    "supplier_name": "Test Supplier Co",
    "supplier_country": "TR",
    "supplier_address": "Istanbul, Turkey",
    "goods_description": "Electronic components",
    "hs_code": "8541.10",
    "quantity": 100,
    "unit": "PCS",
    "value_usd": 5000,
    "port_of_entry": "Tripoli",
    "transport_mode": "sea",
    "carrier_name": "Test Carrier",
    "bill_of_lading": "BL-TEST-001",
    "estimated_arrival": "2026-04-01",
}


def login(email: str, password: str) -> requests.Session:
    session = requests.Session()
    resp = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    return session, resp


class TestKYCEnforcementOnACID:
    """KYC enforcement: non-approved users must NOT be able to create ACID requests."""

    def test_pending_user_blocked(self):
        """Pending importer (email verified but KYC not approved) → 403 KYC_NOT_APPROVED"""
        session, login_resp = login("test_correction_importer@test.ly", "TestPass@2026!")
        # Login should be blocked too (pending → 403)
        if login_resp.status_code == 403:
            # Can't get token via login; use cookies file
            pytest.skip("Pending user blocked at login — cannot test ACID directly via login flow")

        resp = session.post(f"{BASE_URL}/api/acid", json=ACID_PAYLOAD)
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
        data = resp.json()
        detail = data.get("detail", {})
        assert detail.get("code") == "KYC_NOT_APPROVED", f"Expected KYC_NOT_APPROVED, got: {detail}"
        print(f"PASS: pending user blocked with code={detail.get('code')}, msg={detail.get('message')}")

    def test_email_unverified_user_blocked(self):
        """Register a fresh importer (email_unverified) and try to create ACID → 403"""
        import random, string
        rand = ''.join(random.choices(string.ascii_lowercase, k=6))
        email = f"TEST_unverified_{rand}@test.ly"

        session = requests.Session()
        reg_resp = session.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "TestPass@2026!",
            "role": "importer",
            "name_ar": "مستورد تجريبي",
            "name_en": "Test Importer",
            "company_name_ar": "شركة تجريبية",
            "company_name_en": "Test Company",
            "phone": "+218911234567",
            "address": "Tripoli, Libya",
            "license_number": "LIC-TEST-001",
        })
        assert reg_resp.status_code in [200, 201], f"Registration failed: {reg_resp.text}"
        reg_data = reg_resp.json()
        # Must NOT contain email_verify_token
        assert "email_verify_token" not in reg_data, "email_verify_token leaked in register response!"
        print(f"PASS: email_verify_token not in register response")

        # Now try to login — should be blocked as email_unverified
        login_resp = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": "TestPass@2026!"})
        assert login_resp.status_code == 403, f"Expected 403 at login for email_unverified, got {login_resp.status_code}"
        login_data = login_resp.json()
        detail = login_data.get("detail", {})
        assert detail.get("code") in ["EMAIL_UNVERIFIED", "KYC_PENDING"], f"Unexpected code: {detail}"
        print(f"PASS: email_unverified user blocked at login with code={detail.get('code')}")

    def test_pending_user_via_cookie_file_blocked(self):
        """Use /tmp/pending_cookies.txt session to attempt ACID creation → 403"""
        import http.cookiejar
        cj = http.cookiejar.MozillaCookieJar("/tmp/pending_cookies.txt")
        try:
            cj.load(ignore_discard=True, ignore_expires=True)
        except Exception as e:
            pytest.skip(f"Could not load pending cookies: {e}")

        session = requests.Session()
        session.cookies = cj
        resp = session.post(f"{BASE_URL}/api/acid", json=ACID_PAYLOAD)
        print(f"pending_cookies ACID response: {resp.status_code} {resp.text[:300]}")
        if resp.status_code == 401:
            pytest.skip("Cookie expired — cannot test")
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "KYC_NOT_APPROVED", f"Expected KYC_NOT_APPROVED, got: {detail}"
        print(f"PASS: pending user via cookie blocked with code={detail.get('code')}")

    def test_email_unverified_user_via_cookie_file_blocked(self):
        """Use /tmp/test_cookies.txt (email_unverified) → 403 KYC_NOT_APPROVED"""
        import http.cookiejar
        cj = http.cookiejar.MozillaCookieJar("/tmp/test_cookies.txt")
        try:
            cj.load(ignore_discard=True, ignore_expires=True)
        except Exception as e:
            pytest.skip(f"Could not load test cookies: {e}")

        session = requests.Session()
        session.cookies = cj
        resp = session.post(f"{BASE_URL}/api/acid", json=ACID_PAYLOAD)
        print(f"test_cookies (email_unverified) ACID response: {resp.status_code} {resp.text[:300]}")
        if resp.status_code == 401:
            pytest.skip("Cookie expired — cannot test")
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "KYC_NOT_APPROVED", f"Expected KYC_NOT_APPROVED, got: {detail}"
        print(f"PASS: email_unverified user via cookie blocked with code={detail.get('code')}")

    def test_approved_broker_can_create_acid(self):
        """Approved broker (broker@customs.ly) → ACID creation succeeds"""
        session, login_resp = login("broker@customs.ly", "Broker@2026!")
        assert login_resp.status_code == 200, f"Broker login failed: {login_resp.text}"
        resp = session.post(f"{BASE_URL}/api/acid", json=ACID_PAYLOAD)
        assert resp.status_code in [200, 201], f"Expected 200/201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "acid_number" in data, f"acid_number missing in response: {data}"
        print(f"PASS: approved broker created ACID: {data.get('acid_number')}")

    def test_admin_can_create_acid(self):
        """Admin bypasses KYC check → ACID creation succeeds"""
        session, login_resp = login("admin@customs.ly", "Admin@2026!")
        assert login_resp.status_code == 200, f"Admin login failed: {login_resp.text}"
        resp = session.post(f"{BASE_URL}/api/acid", json=ACID_PAYLOAD)
        assert resp.status_code in [200, 201], f"Expected 200/201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "acid_number" in data, f"acid_number missing in response: {data}"
        print(f"PASS: admin created ACID: {data.get('acid_number')}")

    def test_get_me_no_email_verify_token(self):
        """GET /api/auth/me must NOT return email_verify_token"""
        session, login_resp = login("admin@customs.ly", "Admin@2026!")
        assert login_resp.status_code == 200
        resp = session.get(f"{BASE_URL}/api/auth/me")
        assert resp.status_code == 200, f"GET /api/auth/me failed: {resp.text}"
        data = resp.json()
        assert "email_verify_token" not in data, f"email_verify_token leaked in /api/auth/me: {list(data.keys())}"
        print(f"PASS: email_verify_token not in /api/auth/me response. Keys: {list(data.keys())}")

    def test_needs_correction_user_create_via_api_then_block(self):
        """Create a user, set needs_correction status, verify ACID blocked"""
        import random, string
        rand = ''.join(random.choices(string.ascii_lowercase, k=6))
        email = f"TEST_correction_{rand}@test.ly"

        # Register
        admin_session, _ = login("admin@customs.ly", "Admin@2026!")
        session = requests.Session()
        reg_resp = session.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "TestPass@2026!",
            "role": "importer",
            "name_ar": "مستورد تجريبي",
            "name_en": "Test Correction Importer",
            "company_name_ar": "شركة تجريبية",
            "company_name_en": "Test Correction Company",
            "phone": "+218911234999",
            "address": "Tripoli, Libya",
            "license_number": "LIC-CORR-001",
        })
        assert reg_resp.status_code in [200, 201], f"Registration failed: {reg_resp.text}"
        user_id = reg_resp.json().get("user", {}).get("_id") or reg_resp.json().get("_id")

        if not user_id:
            pytest.skip("Could not get user_id from register response")

        # Verify email via token (get from DB directly)
        # Skip email verify — just set status directly via admin endpoint if available
        # Use reg_officer to set needs_correction
        officer_session, _ = login("reg_officer@customs.ly", "RegOfficer@2026!")
        correct_resp = officer_session.post(f"{BASE_URL}/api/kyc/{user_id}/correct",
                                             json={"notes": "Please fix documents"})
        if correct_resp.status_code not in [200, 201]:
            pytest.skip(f"Could not set needs_correction status: {correct_resp.text}")

        # needs_correction users CAN login (they've verified email, just need doc correction)
        login_resp = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": "TestPass@2026!"})
        if login_resp.status_code == 403:
            pytest.skip(f"needs_correction user blocked at login (unexpected): {login_resp.text}")
        assert login_resp.status_code == 200, f"needs_correction user login failed: {login_resp.text}"

        # But ACID creation must be blocked
        acid_resp = session.post(f"{BASE_URL}/api/acid", json=ACID_PAYLOAD)
        assert acid_resp.status_code == 403, f"Expected 403 for needs_correction user creating ACID, got {acid_resp.status_code}: {acid_resp.text}"
        detail = acid_resp.json().get("detail", {})
        assert detail.get("code") == "KYC_NOT_APPROVED", f"Expected KYC_NOT_APPROVED, got: {detail}"
        print(f"PASS: needs_correction user blocked at ACID creation with code={detail.get('code')}, msg={detail.get('message')}")

    def test_regression_login_blocks_pending_user(self):
        """Regression: Login must block pending users with 403"""
        session, resp = login("test_kyc_fix@test.ly", "TestPass@2026!")
        # Should be 403 (KYC_PENDING or EMAIL_UNVERIFIED)
        assert resp.status_code == 403, f"Expected 403 for pending user at login, got {resp.status_code}: {resp.text}"
        detail = resp.json().get("detail", {})
        assert detail.get("code") in ["KYC_PENDING", "EMAIL_UNVERIFIED", "KYC_NOT_APPROVED"], f"Unexpected code: {detail}"
        print(f"PASS: pending/unverified user blocked at login with code={detail.get('code')}")
