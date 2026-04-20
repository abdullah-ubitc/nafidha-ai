"""Tests for Dynamic Configuration / KYC Settings feature"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

REG_OFFICER = {"email": "reg_officer@customs.ly", "password": "RegOfficer@2026!"}
ADMIN_CREDS  = {"email": "admin@customs.ly",     "password": "Admin@2026!"}


@pytest.fixture(scope="module")
def officer_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=REG_OFFICER)
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json().get("access_token") or r.cookies.get("access_token")


@pytest.fixture(scope="module")
def officer_headers(officer_token):
    if officer_token:
        return {"Authorization": f"Bearer {officer_token}"}
    return {}


@pytest.fixture(scope="module")
def officer_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=REG_OFFICER)
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s


# ── GET /kyc/settings ────────────────────────────────────────────────────────

class TestGetSettings:
    def test_get_returns_200(self, officer_session):
        r = officer_session.get(f"{BASE_URL}/api/kyc/settings")
        assert r.status_code == 200, r.text

    def test_get_has_license_expiry_warn_days(self, officer_session):
        r = officer_session.get(f"{BASE_URL}/api/kyc/settings")
        data = r.json()
        assert "license_expiry_warn_days" in data
        assert isinstance(data["license_expiry_warn_days"], int)

    def test_get_has_default_from_env(self, officer_session):
        r = officer_session.get(f"{BASE_URL}/api/kyc/settings")
        data = r.json()
        assert "default_from_env" in data
        assert data["default_from_env"] == 30


# ── POST /kyc/settings ───────────────────────────────────────────────────────

class TestPostSettings:
    def test_post_saves_value_45(self, officer_session):
        r = officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 45})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("license_expiry_warn_days") == 45
        assert "message" in data

    def test_get_after_post_returns_45(self, officer_session):
        officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 45})
        r = officer_session.get(f"{BASE_URL}/api/kyc/settings")
        assert r.json()["license_expiry_warn_days"] == 45

    def test_get_after_post_has_updated_by_name(self, officer_session):
        officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 45})
        r = officer_session.get(f"{BASE_URL}/api/kyc/settings")
        data = r.json()
        assert data.get("updated_by_name"), "updated_by_name should be populated"


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_value_0_returns_422(self, officer_session):
        r = officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 0})
        assert r.status_code == 422, r.text

    def test_value_366_returns_422(self, officer_session):
        r = officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 366})
        assert r.status_code == 422, r.text

    def test_value_365_is_valid(self, officer_session):
        r = officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 365})
        assert r.status_code == 200, r.text

    def test_value_1_is_valid(self, officer_session):
        r = officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 1})
        assert r.status_code == 200, r.text


# ── CRON uses DB value ────────────────────────────────────────────────────────

class TestCRONUsesDBValue:
    def test_trigger_uses_45_day_window(self, officer_session):
        # Set to 45 first
        officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 45})
        # Trigger CRON
        r = officer_session.post(f"{BASE_URL}/api/kyc/scheduler/trigger")
        assert r.status_code == 200, r.text
        data = r.json()
        # days_window is nested inside 'details'
        days_window = data.get("days_window") or (data.get("details") or {}).get("days_window")
        assert days_window == 45, f"Expected days_window=45, got {data}"


# ── Audit Log ─────────────────────────────────────────────────────────────────

class TestAuditLog:
    def test_audit_log_entry_created(self, officer_session):
        officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 45})
        # Audit logs require admin role
        admin_session = requests.Session()
        r = admin_session.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
        assert r.status_code == 200
        r = admin_session.get(f"{BASE_URL}/api/audit/logs?limit=100")
        assert r.status_code == 200, r.text
        logs = r.json()
        if isinstance(logs, dict):
            logs = logs.get("logs") or logs.get("items") or []
        actions = [l.get("action") for l in logs]
        assert "kyc_settings_updated" in actions, f"No kyc_settings_updated in audit log: {actions}"


# ── Persistence (save 60, reload) ─────────────────────────────────────────────

class TestPersistence:
    def test_save_60_and_persist(self, officer_session):
        officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 60})
        r = officer_session.get(f"{BASE_URL}/api/kyc/settings")
        assert r.json()["license_expiry_warn_days"] == 60

    def test_reset_to_30_after_tests(self, officer_session):
        """Reset to default after tests"""
        r = officer_session.post(f"{BASE_URL}/api/kyc/settings", json={"license_expiry_warn_days": 30})
        assert r.status_code == 200
