"""
Backend tests for License Expiry Tracking (Phase M)
Tests: expiring-licenses, expiring-licenses/stats, notify-expiring, notify-expiry
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

REG_OFFICER = {"email": "reg_officer@customs.ly", "password": "RegOfficer@2026!"}
ADMIN = {"email": "admin@customs.ly", "password": "Admin@2026!"}


@pytest.fixture(scope="module")
def reg_officer_session():
    """Authenticated session as registration_officer"""
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=REG_OFFICER)
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s


@pytest.fixture(scope="module")
def approved_user_with_expiry(reg_officer_session):
    """
    Create a new importer via registration, approve with expiry date 25 days from now.
    Returns the user_id.
    """
    expiry_date = (datetime.utcnow() + timedelta(days=25)).strftime("%Y-%m-%d")
    email = f"expiry_test_{int(datetime.utcnow().timestamp())}@test.ly"

    # Register new importer
    s = requests.Session()
    reg_data = {
        "email": email,
        "password": "Test@1234!",
        "name_ar": "مستورد اختبار الانتهاء",
        "name_en": "Expiry Test Importer",
        "role": "importer",
        "phone": "+218911111111",
        "company_name_ar": "شركة الاختبار",
    }
    r = s.post(f"{BASE_URL}/api/auth/register", json=reg_data)
    assert r.status_code in [200, 201], f"Register failed: {r.text}"
    user_id = r.json().get("user", {}).get("_id") or r.json().get("_id")

    # Get pending users to find the user_id
    r2 = reg_officer_session.get(f"{BASE_URL}/api/kyc/registrations?status=pending")
    assert r2.status_code == 200
    pending = r2.json()
    found = next((u for u in pending if u["email"] == email), None)
    if not found:
        pytest.skip(f"Could not find registered user {email} in pending list")

    user_id = found["_id"]

    # Approve with expiry date
    r3 = reg_officer_session.post(f"{BASE_URL}/api/kyc/{user_id}/approve", json={
        "license_expiry_date": expiry_date
    })
    assert r3.status_code == 200, f"Approve failed: {r3.text}"

    return {"user_id": user_id, "email": email, "expiry_date": expiry_date}


class TestExpiryStats:
    """Tests for /api/kyc/expiring-licenses/stats"""

    def test_stats_returns_200(self, reg_officer_session):
        r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses/stats")
        assert r.status_code == 200

    def test_stats_has_required_fields(self, reg_officer_session):
        r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses/stats")
        data = r.json()
        assert "expiring_soon_30d" in data
        assert "already_expired" in data
        assert isinstance(data["expiring_soon_30d"], int)
        assert isinstance(data["already_expired"], int)

    def test_stats_unauthenticated_blocked(self):
        r = requests.get(f"{BASE_URL}/api/kyc/expiring-licenses/stats")
        assert r.status_code in [401, 403]

    def test_stats_reflect_approved_user_with_expiry(self, reg_officer_session, approved_user_with_expiry):
        """After approving user with expiry in 25 days, stats should show >=1 expiring soon"""
        r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses/stats")
        data = r.json()
        assert data["expiring_soon_30d"] >= 1


class TestExpiringLicenses:
    """Tests for GET /api/kyc/expiring-licenses"""

    def test_default_days_30_returns_200(self, reg_officer_session):
        r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses?days=30")
        assert r.status_code == 200

    def test_returns_list(self, reg_officer_session):
        r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses?days=30")
        data = r.json()
        assert isinstance(data, list)

    def test_days_remaining_field_present(self, reg_officer_session, approved_user_with_expiry):
        r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses?days=30")
        data = r.json()
        assert len(data) >= 1
        for u in data:
            assert "days_remaining" in u, "days_remaining field missing"
            assert isinstance(u["days_remaining"], int)

    def test_approved_user_appears_in_list(self, reg_officer_session, approved_user_with_expiry):
        r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses?days=30")
        emails = [u["email"] for u in r.json()]
        assert approved_user_with_expiry["email"] in emails

    def test_different_day_filters(self, reg_officer_session):
        for days in [15, 30, 60, 90]:
            r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses?days={days}")
            assert r.status_code == 200, f"days={days} failed"

    def test_include_expired_param(self, reg_officer_session):
        r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses?days=30&include_expired=true")
        assert r.status_code == 200

    def test_invalid_days_rejected(self, reg_officer_session):
        r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses?days=0")
        assert r.status_code == 422


class TestNotifyExpiring:
    """Tests for POST /api/kyc/notify-expiring"""

    def test_bulk_notify_returns_200(self, reg_officer_session, approved_user_with_expiry):
        r = reg_officer_session.post(f"{BASE_URL}/api/kyc/notify-expiring?days=30")
        assert r.status_code == 200

    def test_bulk_notify_response_has_sent_count(self, reg_officer_session, approved_user_with_expiry):
        r = reg_officer_session.post(f"{BASE_URL}/api/kyc/notify-expiring?days=30")
        data = r.json()
        assert "sent" in data
        assert isinstance(data["sent"], int)
        assert data["sent"] >= 1

    def test_bulk_notify_has_message(self, reg_officer_session, approved_user_with_expiry):
        r = reg_officer_session.post(f"{BASE_URL}/api/kyc/notify-expiring?days=30")
        data = r.json()
        assert "message" in data

    def test_bulk_notify_unauthenticated_blocked(self):
        r = requests.post(f"{BASE_URL}/api/kyc/notify-expiring?days=30")
        assert r.status_code in [401, 403]


class TestNotifySingle:
    """Tests for POST /api/kyc/{id}/notify-expiry"""

    def test_single_notify_returns_200(self, reg_officer_session, approved_user_with_expiry):
        user_id = approved_user_with_expiry["user_id"]
        r = reg_officer_session.post(f"{BASE_URL}/api/kyc/{user_id}/notify-expiry")
        assert r.status_code == 200

    def test_single_notify_response_has_days_remaining(self, reg_officer_session, approved_user_with_expiry):
        user_id = approved_user_with_expiry["user_id"]
        r = reg_officer_session.post(f"{BASE_URL}/api/kyc/{user_id}/notify-expiry")
        data = r.json()
        assert "days_remaining" in data
        assert isinstance(data["days_remaining"], int)

    def test_single_notify_invalid_id(self, reg_officer_session):
        r = reg_officer_session.post(f"{BASE_URL}/api/kyc/invalidid123/notify-expiry")
        assert r.status_code == 400

    def test_single_notify_nonexistent_user(self, reg_officer_session):
        r = reg_officer_session.post(f"{BASE_URL}/api/kyc/000000000000000000000000/notify-expiry")
        assert r.status_code == 404


class TestApproveWithExpiry:
    """Tests for approve endpoint with license_expiry_date"""

    def test_approved_user_can_login(self, approved_user_with_expiry):
        """Approved user should be able to login"""
        r = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": approved_user_with_expiry["email"],
            "password": "Test@1234!"
        })
        assert r.status_code == 200, f"Approved user login failed: {r.text}"

    def test_approved_user_has_expiry_date(self, reg_officer_session, approved_user_with_expiry):
        """Approved user appears in expiring list with correct expiry"""
        r = reg_officer_session.get(f"{BASE_URL}/api/kyc/expiring-licenses?days=30")
        data = r.json()
        user = next((u for u in data if u["email"] == approved_user_with_expiry["email"]), None)
        assert user is not None
        assert user["license_expiry_date"] == approved_user_with_expiry["expiry_date"]
        assert 20 <= user["days_remaining"] <= 26  # ~25 days remaining


class TestAdminAccess:
    """Admin should also access KYC endpoints"""

    def test_admin_can_get_expiry_stats(self):
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN)
        assert r.status_code == 200
        r2 = s.get(f"{BASE_URL}/api/kyc/expiring-licenses/stats")
        assert r2.status_code == 200
