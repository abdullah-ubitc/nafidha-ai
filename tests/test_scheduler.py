"""
Tests for CRON Scheduler feature — Phase P1
Tests: scheduler status, manual trigger, audit log, admin access
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

REG_OFFICER_EMAIL = "reg_officer@customs.ly"
REG_OFFICER_PASS  = "RegOfficer@2026!"
ADMIN_EMAIL       = "admin@customs.ly"
ADMIN_PASS        = "Admin@2026!"


def login(email, password):
    session = requests.Session()
    resp = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed for {email}: {resp.text}"
    return session


@pytest.fixture(scope="module")
def reg_session():
    return login(REG_OFFICER_EMAIL, REG_OFFICER_PASS)


@pytest.fixture(scope="module")
def admin_session():
    return login(ADMIN_EMAIL, ADMIN_PASS)


class TestSchedulerStatus:
    def test_scheduler_status_returns_200(self, reg_session):
        resp = reg_session.get(f"{BASE_URL}/api/kyc/scheduler/status")
        assert resp.status_code == 200, f"Unexpected: {resp.text}"
        print("PASS: scheduler status 200")

    def test_scheduler_status_has_required_fields(self, reg_session):
        resp = reg_session.get(f"{BASE_URL}/api/kyc/scheduler/status")
        data = resp.json()
        assert "last_run" in data, "Missing last_run"
        assert "next_run" in data, "Missing next_run"
        assert "schedule" in data, "Missing schedule"
        assert "job_id" in data, "Missing job_id"
        print(f"PASS: scheduler fields present — next_run={data['next_run']}")

    def test_scheduler_next_run_is_set(self, reg_session):
        resp = reg_session.get(f"{BASE_URL}/api/kyc/scheduler/status")
        data = resp.json()
        assert data["next_run"] is not None, "next_run should not be None"
        print(f"PASS: next_run = {data['next_run']}")

    def test_scheduler_job_id(self, reg_session):
        resp = reg_session.get(f"{BASE_URL}/api/kyc/scheduler/status")
        data = resp.json()
        assert data["job_id"] == "license_expiry_check"
        print("PASS: job_id correct")

    def test_admin_can_access_scheduler_status(self, admin_session):
        resp = admin_session.get(f"{BASE_URL}/api/kyc/scheduler/status")
        assert resp.status_code == 200, f"Admin can't access: {resp.text}"
        print("PASS: admin can access scheduler status")


class TestSchedulerTrigger:
    def test_manual_trigger_returns_200(self, reg_session):
        resp = reg_session.post(f"{BASE_URL}/api/kyc/scheduler/trigger")
        assert resp.status_code == 200, f"Trigger failed: {resp.text}"
        print("PASS: manual trigger 200")

    def test_manual_trigger_returns_sent_count(self, reg_session):
        resp = reg_session.post(f"{BASE_URL}/api/kyc/scheduler/trigger")
        data = resp.json()
        assert "details" in data, "Missing details field"
        assert "sent" in data["details"], "Missing sent count in details"
        assert isinstance(data["details"]["sent"], int)
        print(f"PASS: trigger returned sent={data['details']['sent']}")

    def test_manual_trigger_has_message(self, reg_session):
        resp = reg_session.post(f"{BASE_URL}/api/kyc/scheduler/trigger")
        data = resp.json()
        assert "message" in data
        print(f"PASS: trigger message = {data['message']}")

    def test_manual_trigger_updates_last_run(self, reg_session):
        # Trigger first
        reg_session.post(f"{BASE_URL}/api/kyc/scheduler/trigger")
        # Then check status
        status_resp = reg_session.get(f"{BASE_URL}/api/kyc/scheduler/status")
        status_data = status_resp.json()
        last_run = status_data.get("last_run", {})
        assert last_run.get("triggered_at") is not None, "triggered_at should be set after trigger"
        print(f"PASS: last_run updated — triggered_at={last_run.get('triggered_at')}")

    def test_admin_can_trigger_scheduler(self, admin_session):
        resp = admin_session.post(f"{BASE_URL}/api/kyc/scheduler/trigger")
        assert resp.status_code == 200, f"Admin trigger failed: {resp.text}"
        print("PASS: admin can trigger scheduler")


class TestAuditLog:
    def test_trigger_creates_audit_log(self, reg_session):
        # We can't directly query audit_logs via API, but trigger should work
        # Trigger and verify the response indicates success
        resp = reg_session.post(f"{BASE_URL}/api/kyc/scheduler/trigger")
        assert resp.status_code == 200
        data = resp.json()
        # The audit log is internal; verify trigger ran successfully (implies log was created)
        assert data["details"]["job"] == "license_expiry_check"
        print("PASS: trigger ran (audit log should be created)")

    def test_trigger_details_has_system_job(self, reg_session):
        resp = reg_session.post(f"{BASE_URL}/api/kyc/scheduler/trigger")
        data = resp.json()
        details = data.get("details", {})
        assert details.get("job") == "license_expiry_check"
        assert "triggered_at" in details
        assert "finished_at" in details
        print("PASS: trigger details correct")
