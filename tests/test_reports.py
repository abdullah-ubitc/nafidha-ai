"""
test_reports.py — Backend tests for Sovereign Reporting Engine
Tests: weekly-performance PDF endpoint, auth/authz, scheduler status, workflow regression
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_CREDS = {"email": "admin@customs.ly", "password": "Admin@2026!"}
REG_OFFICER_CREDS = {"email": "reg_officer@customs.ly", "password": "RegOfficer@2026!"}


@pytest.fixture(scope="module")
def admin_token():
    res = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
    assert res.status_code == 200, f"Admin login failed: {res.text}"
    return res.json().get("access_token") or res.json().get("token")


@pytest.fixture(scope="module")
def reg_officer_token():
    res = requests.post(f"{BASE_URL}/api/auth/login", json=REG_OFFICER_CREDS)
    assert res.status_code == 200, f"Reg officer login failed: {res.text}"
    return res.json().get("access_token") or res.json().get("token")


class TestWeeklyReport:
    """Tests for GET /api/reports/weekly-performance"""

    # Test 1: Current week PDF > 10KB
    def test_weekly_report_current_week_size(self, admin_token):
        res = requests.get(
            f"{BASE_URL}/api/reports/weekly-performance?week_offset=0",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text[:200]}"
        assert len(res.content) > 10_000, f"PDF too small: {len(res.content)} bytes"
        print(f"PASS: Current week PDF size = {len(res.content)} bytes")

    # Test 2: Last week PDF
    def test_weekly_report_last_week(self, admin_token):
        res = requests.get(
            f"{BASE_URL}/api/reports/weekly-performance?week_offset=1",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text[:200]}"
        assert len(res.content) > 10_000, f"PDF too small: {len(res.content)} bytes"
        print(f"PASS: Last week PDF size = {len(res.content)} bytes")

    # Test 3: No auth → 401
    def test_weekly_report_no_auth_returns_401(self):
        res = requests.get(f"{BASE_URL}/api/reports/weekly-performance?week_offset=0")
        assert res.status_code == 401, f"Expected 401, got {res.status_code}"
        print("PASS: No auth → 401")

    # Test 4: registration_officer → 403
    def test_weekly_report_reg_officer_returns_403(self, reg_officer_token):
        res = requests.get(
            f"{BASE_URL}/api/reports/weekly-performance?week_offset=0",
            headers={"Authorization": f"Bearer {reg_officer_token}"}
        )
        assert res.status_code == 403, f"Expected 403 for reg_officer, got {res.status_code}"
        print("PASS: registration_officer → 403")

    # Test 5: PDF starts with %PDF
    def test_weekly_report_valid_pdf_header(self, admin_token):
        res = requests.get(
            f"{BASE_URL}/api/reports/weekly-performance?week_offset=0",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res.status_code == 200
        assert res.content[:4] == b'%PDF', f"Invalid PDF header: {res.content[:10]}"
        print("PASS: PDF starts with %PDF")

    # Test: Content-Type is application/pdf
    def test_weekly_report_content_type(self, admin_token):
        res = requests.get(
            f"{BASE_URL}/api/reports/weekly-performance?week_offset=0",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res.status_code == 200
        assert "application/pdf" in res.headers.get("content-type", ""), f"Wrong content-type: {res.headers.get('content-type')}"
        print("PASS: Content-Type is application/pdf")


class TestSchedulerStatus:
    """Test 8: POST /api/kyc/scheduler/status has weekly_report job info"""

    def test_scheduler_status_has_weekly_report(self, admin_token):
        res = requests.get(
            f"{BASE_URL}/api/kyc/scheduler/status",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text[:300]}"
        data = res.json()
        # Check for weekly report job or sla_next_run field
        data_str = str(data).lower()
        has_weekly = "weekly" in data_str or "sla_next_run" in data_str or "weekly_report" in data_str
        assert has_weekly, f"No weekly report info in scheduler status: {data}"
        print(f"PASS: Scheduler status contains weekly report info")


class TestWorkflowRegression:
    """Tests 9-10: Workflow endpoints still work"""

    def test_workflow_pool_still_works(self, admin_token):
        res = requests.get(
            f"{BASE_URL}/api/workflow/pool",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res.status_code == 200, f"GET /api/workflow/pool failed: {res.status_code}"
        assert isinstance(res.json(), list), "Expected list response"
        print(f"PASS: workflow/pool returns {len(res.json())} tasks")

    def test_workflow_stats_still_works(self, admin_token):
        res = requests.get(
            f"{BASE_URL}/api/workflow/stats",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert res.status_code == 200, f"GET /api/workflow/stats failed: {res.status_code}"
        data = res.json()
        assert isinstance(data, dict), f"Expected dict, got {type(data)}"
        print(f"PASS: workflow/stats returns: {list(data.keys())}")
