"""KYC System Tests — Phase KYC
Tests for: pending user login block, KYC approval/rejection, stats, reg_officer login
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

REG_OFFICER = {"email": "reg_officer@customs.ly", "password": "RegOfficer@2026!"}
ADMIN = {"email": "admin@customs.ly", "password": "Admin@2026!"}
BROKER = {"email": "broker@customs.ly", "password": "Broker@2026!"}

TEST_IMPORTER_EMAIL = f"testimp_{int(time.time())}@test.ly"
TEST_IMPORTER_PASS = "Test@2026!"


@pytest.fixture(scope="module")
def officer_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=REG_OFFICER)
    assert r.status_code == 200, f"Officer login failed: {r.text}"
    return r.cookies.get("access_token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def officer_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=REG_OFFICER)
    assert r.status_code == 200, f"Officer login failed: {r.text}"
    return s


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN)
    assert r.status_code == 200
    return s


@pytest.fixture(scope="module")
def pending_user_id(officer_session):
    """Register a fresh importer, return their user_id"""
    r = requests.post(f"{BASE_URL}/api/auth/register", json={
        "email": TEST_IMPORTER_EMAIL,
        "password": TEST_IMPORTER_PASS,
        "name_ar": "مستورد تجريبي",
        "name_en": "Test Importer",
        "role": "importer",
        "phone": "0912345678",
        "company_name_ar": "شركة الاختبار",
        "company_name_en": "Test Co",
    })
    assert r.status_code in [200, 201], f"Registration failed: {r.text}"
    data = r.json()
    uid = data.get("user", {}).get("_id") or data.get("user", {}).get("id") or data.get("id")
    assert uid, f"No user id returned: {data}"
    return uid


class TestAuth:
    """Auth-related KYC tests"""

    def test_reg_officer_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=REG_OFFICER)
        assert r.status_code == 200
        data = r.json()
        assert "user" in data
        assert data["user"]["role"] == "registration_officer"

    def test_admin_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "admin"

    def test_broker_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=BROKER)
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["registration_status"] == "approved"

    def test_pending_user_blocked_from_login(self, pending_user_id):
        """After registration, importer should be blocked (pending)"""
        r = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_IMPORTER_EMAIL,
            "password": TEST_IMPORTER_PASS,
        })
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
        data = r.json()
        detail = data.get("detail", "")
        # detail may be a dict with "code" key
        if isinstance(detail, dict):
            code = detail.get("code", "")
            msg = detail.get("message", "")
            assert code == "KYC_PENDING" or "pending" in msg.lower() or "مراجعة" in msg, \
                f"Expected KYC_PENDING error, got: {detail}"
        else:
            assert "KYC_PENDING" in str(detail) or "pending" in str(detail).lower(), \
                f"Expected KYC_PENDING error, got: {detail}"


class TestKYCEndpoints:
    """KYC management endpoint tests"""

    def test_stats_as_officer(self, officer_session):
        r = officer_session.get(f"{BASE_URL}/api/kyc/registrations/stats")
        assert r.status_code == 200
        data = r.json()
        assert "pending" in data
        assert "approved" in data
        assert "rejected" in data
        assert isinstance(data["pending"], int)

    def test_stats_as_admin(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/kyc/registrations/stats")
        assert r.status_code == 200

    def test_stats_unauthorized(self):
        r = requests.get(f"{BASE_URL}/api/kyc/registrations/stats")
        assert r.status_code in [401, 403]

    def test_list_pending_registrations(self, officer_session, pending_user_id):
        r = officer_session.get(f"{BASE_URL}/api/kyc/registrations?status=pending")
        assert r.status_code == 200
        users = r.json()
        assert isinstance(users, list)
        ids = [u["_id"] for u in users]
        assert pending_user_id in ids, f"Pending user {pending_user_id} not in list"

    def test_list_pending_unauthorized(self):
        r = requests.get(f"{BASE_URL}/api/kyc/registrations?status=pending")
        assert r.status_code in [401, 403]

    def test_approve_user(self, officer_session, pending_user_id):
        r = officer_session.post(f"{BASE_URL}/api/kyc/{pending_user_id}/approve", json={
            "license_expiry_date": "2027-12-31"
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "approved"

    def test_approved_user_can_login(self):
        """After approval, the importer should be able to login"""
        r = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_IMPORTER_EMAIL,
            "password": TEST_IMPORTER_PASS,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["registration_status"] == "approved"


class TestKYCRejectFlow:
    """Test reject flow with a second fresh importer"""

    def test_reject_user(self, officer_session):
        # Register fresh user
        email = f"testreject_{int(time.time())}@test.ly"
        r = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "Test@2026!",
            "name_ar": "مرفوض تجريبي",
            "name_en": "Test Reject",
            "role": "customs_broker",
            "phone": "0912345679",
        })
        assert r.status_code in [200, 201]
        resp_data = r.json()
        user_uid = resp_data.get("user", {}).get("_id") or resp_data.get("user", {}).get("id") or resp_data.get("id")
        assert user_uid, f"No uid from register: {resp_data}"

        # Reject the user
        r2 = officer_session.post(f"{BASE_URL}/api/kyc/{user_uid}/reject", json={
            "reason": "وثائق غير مكتملة - اختبار"
        })
        assert r2.status_code == 200
        assert r2.json().get("status") == "rejected"

        # Rejected user should also be blocked
        r3 = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": "Test@2026!"})
        assert r3.status_code == 403
        detail = r3.json().get("detail", "")
        if isinstance(detail, dict):
            code = detail.get("code", "")
            assert "KYC_REJECTED" in code or "rejected" in code.lower(), f"Expected KYC_REJECTED, got: {detail}"
        else:
            assert "KYC_REJECTED" in str(detail) or "rejected" in str(detail).lower(), f"Expected KYC_REJECTED, got: {detail}"

    def test_approve_without_expiry(self, officer_session):
        """Approve should work without license_expiry_date"""
        email = f"testnoexp_{int(time.time())}@test.ly"
        r = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": email,
            "password": "Test@2026!",
            "name_ar": "مستورد بدون تاريخ",
            "name_en": "No Expiry",
            "role": "importer",
        })
        assert r.status_code in [200, 201]
        resp_data2 = r.json()
        noexp_uid = resp_data2.get("user", {}).get("_id") or resp_data2.get("user", {}).get("id") or resp_data2.get("id")
        r2 = officer_session.post(f"{BASE_URL}/api/kyc/{noexp_uid}/approve", json={})
        assert r2.status_code == 200
