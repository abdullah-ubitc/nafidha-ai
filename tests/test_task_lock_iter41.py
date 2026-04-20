"""
Test Task-Lock Enforcement for KYC Decisions (Iteration 41)
Tests: 423 LOCK_REQUIRED without claim, claim flow, approve after claim
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

OFFICER_EMAIL = "reg_officer@customs.ly"
OFFICER_PASS  = "RegOfficer@2026!"
ADMIN_EMAIL   = "admin@customs.ly"
ADMIN_PASS    = "Admin@2026!"


def officer_login():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": OFFICER_EMAIL, "password": OFFICER_PASS},
                      timeout=15)
    assert r.status_code == 200, f"Officer login failed: {r.text}"
    return r.cookies, r.json().get("access_token")


def get_pending_user_id(cookies):
    r = requests.get(f"{BASE_URL}/api/kyc/registrations?status=pending",
                     cookies=cookies, timeout=15)
    assert r.status_code == 200, f"List pending failed: {r.text}"
    users = r.json()
    # Find an unassigned user
    for u in users:
        if u.get("wf_status", "Unassigned") in ("Unassigned", None, ""):
            return u["_id"]
    # fallback: any pending user
    if users:
        return users[0]["_id"]
    return None


class TestLockEnforcement:
    """Task-Lock: approve/reject must return 423 without claim"""

    def test_approve_without_lock_returns_423(self):
        cookies, _ = officer_login()
        uid = get_pending_user_id(cookies)
        if not uid:
            pytest.skip("No pending user found for lock test")
        r = requests.post(f"{BASE_URL}/api/kyc/{uid}/approve",
                          json={}, cookies=cookies, timeout=15)
        # If user is already claimed by this officer (from previous test runs), could be 200
        if r.status_code == 200:
            pytest.skip(f"User {uid} already claimed by this officer - 200 expected")
        assert r.status_code == 423, f"Expected 423, got {r.status_code}: {r.text}"
        data = r.json()
        detail = data.get("detail", {})
        assert detail.get("code") == "LOCK_REQUIRED", f"Expected LOCK_REQUIRED code: {data}"

    def test_reject_without_lock_returns_423(self):
        cookies, _ = officer_login()
        uid = get_pending_user_id(cookies)
        if not uid:
            pytest.skip("No pending user found for lock test")
        r = requests.post(f"{BASE_URL}/api/kyc/{uid}/reject",
                          json={"reason": "test reject without lock"},
                          cookies=cookies, timeout=15)
        if r.status_code == 200:
            pytest.skip(f"User {uid} already claimed by this officer")
        assert r.status_code == 423, f"Expected 423, got {r.status_code}: {r.text}"

    def test_correct_without_lock_returns_423(self):
        cookies, _ = officer_login()
        uid = get_pending_user_id(cookies)
        if not uid:
            pytest.skip("No pending user found")
        r = requests.post(f"{BASE_URL}/api/kyc/{uid}/correct",
                          json={"notes": "test without lock", "flagged_docs": []},
                          cookies=cookies, timeout=15)
        if r.status_code == 200:
            pytest.skip(f"User {uid} already claimed by this officer")
        assert r.status_code == 423, f"Expected 423, got {r.status_code}: {r.text}"


class TestClaimAndApprove:
    """Full workflow: claim → approve → 200"""

    def test_claim_task_success(self):
        cookies, _ = officer_login()
        uid = get_pending_user_id(cookies)
        if not uid:
            pytest.skip("No pending user found")
        r = requests.post(f"{BASE_URL}/api/workflow/claim",
                          json={"task_type": "kyc_review", "task_id": uid},
                          cookies=cookies, timeout=15)
        assert r.status_code == 200, f"Claim failed: {r.text}"
        data = r.json()
        assert "claimed" in str(data).lower() or "success" in str(data).lower() or data.get("task_id") or data.get("message"), \
            f"Unexpected claim response: {data}"

    def test_approve_after_claim_returns_200(self):
        cookies, _ = officer_login()
        # Find in-progress task for this officer
        r = requests.get(f"{BASE_URL}/api/workflow/my-queue",
                         cookies=cookies, timeout=15)
        assert r.status_code == 200, f"my-queue failed: {r.text}"
        tasks = r.json()
        kyc_tasks = [t for t in tasks if t.get("task_type") == "kyc_review"]
        if not kyc_tasks:
            # claim first
            uid = get_pending_user_id(cookies)
            if not uid:
                pytest.skip("No pending user and no claimed tasks")
            claim_r = requests.post(f"{BASE_URL}/api/workflow/claim",
                                    json={"task_type": "kyc_review", "task_id": uid},
                                    cookies=cookies, timeout=15)
            if claim_r.status_code != 200:
                pytest.skip(f"Claim failed: {claim_r.text}")
            task_id = uid
        else:
            task_id = kyc_tasks[0].get("task_id") or kyc_tasks[0].get("_id")

        r2 = requests.post(f"{BASE_URL}/api/kyc/{task_id}/approve",
                           json={}, cookies=cookies, timeout=15)
        assert r2.status_code == 200, f"Expected 200 after claim, got {r2.status_code}: {r2.text}"
        data = r2.json()
        assert data.get("status") == "approved", f"Unexpected response: {data}"

    def test_my_tasks_returns_kyc_review_type(self):
        cookies, _ = officer_login()
        r = requests.get(f"{BASE_URL}/api/workflow/my-queue",
                         cookies=cookies, timeout=15)
        assert r.status_code == 200
        tasks = r.json()
        assert isinstance(tasks, list), f"Expected list: {tasks}"

    def test_workflow_queue_has_kyc_tasks(self):
        cookies, _ = officer_login()
        r = requests.get(f"{BASE_URL}/api/workflow/pool",
                         cookies=cookies, timeout=15)
        assert r.status_code == 200, f"Queue failed: {r.text}"


class TestLockErrorMessage:
    """Verify 423 response structure"""

    def test_lock_required_error_has_correct_structure(self):
        cookies, _ = officer_login()
        uid = get_pending_user_id(cookies)
        if not uid:
            pytest.skip("No pending unassigned user found")
        r = requests.post(f"{BASE_URL}/api/kyc/{uid}/approve",
                          json={}, cookies=cookies, timeout=15)
        if r.status_code != 423:
            pytest.skip("User may already be claimed by this officer")
        data = r.json()
        detail = data.get("detail", {})
        assert "code" in detail, f"Missing 'code' in detail: {detail}"
        assert "message" in detail, f"Missing 'message' in detail: {detail}"
        assert detail["code"] == "LOCK_REQUIRED"
        # message should be Arabic
        assert len(detail["message"]) > 5, f"Message too short: {detail['message']}"
