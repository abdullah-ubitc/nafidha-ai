"""
Tests for KYC Resubmit feature:
- POST /api/kyc/resubmit endpoint
- needs_correction user can login and resubmit
- validation: non-needs_correction user gets 400
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://libya-customs-acis.preview.emergentagent.com").rstrip("/")

CORRECTION_USER = {"email": "test_correction_importer@test.ly", "password": "TestPass@2026!"}
REG_OFFICER     = {"email": "reg_officer@customs.ly", "password": "RegOfficer@2026!"}
ADMIN           = {"email": "admin@customs.ly", "password": "Admin@2026!"}


def login(session, email, password):
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    return r


class TestResubmitBackend:
    """Backend tests for /api/kyc/resubmit"""

    def test_correction_user_can_login(self):
        """needs_correction users must NOT be blocked by auth"""
        s = requests.Session()
        r = login(s, CORRECTION_USER["email"], CORRECTION_USER["password"])
        print(f"Login status: {r.status_code}, body: {r.text[:200]}")
        assert r.status_code == 200, f"Login failed: {r.text}"
        data = r.json()
        assert "token" in data or "access_token" in data or r.cookies.get("access_token")

    def test_correction_user_status_is_needs_correction(self):
        """User should have registration_status=needs_correction"""
        s = requests.Session()
        r = login(s, CORRECTION_USER["email"], CORRECTION_USER["password"])
        assert r.status_code == 200
        # Check /me or user data
        me_r = s.get(f"{BASE_URL}/api/auth/me")
        print(f"ME status: {me_r.status_code}, body: {me_r.text[:300]}")
        assert me_r.status_code == 200
        user = me_r.json()
        assert user.get("registration_status") == "needs_correction", f"Expected needs_correction, got: {user.get('registration_status')}"

    def test_correction_user_has_flagged_docs(self):
        """User should have flagged docs set"""
        s = requests.Session()
        login(s, CORRECTION_USER["email"], CORRECTION_USER["password"])
        me_r = s.get(f"{BASE_URL}/api/auth/me")
        assert me_r.status_code == 200
        user = me_r.json()
        flagged = user.get("correction_flagged_docs") or []
        print(f"Flagged docs: {flagged}")
        assert len(flagged) > 0, "Expected at least one flagged doc"

    def test_resubmit_success_for_needs_correction_user(self):
        """POST /api/kyc/resubmit → 200 with status=pending"""
        s = requests.Session()
        r = login(s, CORRECTION_USER["email"], CORRECTION_USER["password"])
        assert r.status_code == 200

        resubmit_r = s.post(f"{BASE_URL}/api/kyc/resubmit")
        print(f"Resubmit status: {resubmit_r.status_code}, body: {resubmit_r.text[:300]}")
        assert resubmit_r.status_code == 200
        data = resubmit_r.json()
        assert data.get("status") == "pending", f"Expected status=pending, got: {data}"
        assert "message" in data

    def test_resubmit_sets_is_resubmission_flag(self):
        """After resubmit, user should have is_resubmission=True via /me"""
        s = requests.Session()
        login(s, CORRECTION_USER["email"], CORRECTION_USER["password"])
        # First reset back to needs_correction via admin
        # (Might already be pending from previous test — check)
        me_r = s.get(f"{BASE_URL}/api/auth/me")
        user = me_r.json()
        print(f"Status after resubmit: {user.get('registration_status')}, is_resubmission: {user.get('is_resubmission')}")
        # Status should now be pending with is_resubmission=True
        if user.get("registration_status") == "pending":
            assert user.get("is_resubmission") is True

    def test_resubmit_blocked_for_pending_user(self):
        """POST /api/kyc/resubmit → 400 Arabic error for non-needs_correction user"""
        # Use reg_officer (approved/internal) — should not be allowed to resubmit
        s = requests.Session()
        r = login(s, REG_OFFICER["email"], REG_OFFICER["password"])
        assert r.status_code == 200
        resubmit_r = s.post(f"{BASE_URL}/api/kyc/resubmit")
        print(f"Officer resubmit status: {resubmit_r.status_code}, body: {resubmit_r.text[:300]}")
        assert resubmit_r.status_code == 400
        # Check Arabic error message
        detail = resubmit_r.json().get("detail", "")
        print(f"Error detail: {detail}")
        assert len(detail) > 0, "Expected Arabic error message"

    def test_resubmit_requires_auth(self):
        """POST /api/kyc/resubmit without auth → 401/403"""
        r = requests.post(f"{BASE_URL}/api/kyc/resubmit")
        print(f"Unauthenticated resubmit: {r.status_code}")
        assert r.status_code in [401, 403], f"Expected 401/403, got {r.status_code}"

    def test_reset_correction_user_for_next_test(self):
        """Reset correction user back to needs_correction via officer for re-testing"""
        # Login as officer
        s_officer = requests.Session()
        r = login(s_officer, REG_OFFICER["email"], REG_OFFICER["password"])
        assert r.status_code == 200

        # Get correction user's ID via admin
        s_admin = requests.Session()
        login(s_admin, ADMIN["email"], ADMIN["password"])
        users_r = s_admin.get(f"{BASE_URL}/api/kyc/pending-users")
        if users_r.status_code != 200:
            print(f"Could not list pending users: {users_r.status_code}")
            pytest.skip("Cannot get user list")

        users = users_r.json()
        correction_user = next((u for u in users if u.get("email") == CORRECTION_USER["email"]), None)
        if not correction_user:
            print("Correction user not found in pending list (may be in different pool)")
            return  # Not critical

        user_id = correction_user.get("id") or correction_user.get("_id")
        print(f"Resetting user {user_id} to needs_correction")
        reset_r = s_officer.post(
            f"{BASE_URL}/api/kyc/request-correction/{user_id}",
            json={"notes": "إعادة تعيين للاختبار", "flagged_docs": ["commercial_registry", "national_id"]}
        )
        print(f"Reset status: {reset_r.status_code}, body: {reset_r.text[:200]}")
        # Not asserting — best effort reset for next test run
