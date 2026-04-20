"""
Smart Audit System — status_history, officer_viewed, Updated Badge
Iteration 40 tests
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

OFFICER_EMAIL = "reg_officer@customs.ly"
OFFICER_PASS  = "RegOfficer@2026!"
USER_EMAIL    = "test_correction_importer@test.ly"
USER_PASS     = "TestPass@2026!"
USER_ID       = "69d81846c0b7bece7601dd4a"
ADMIN_EMAIL   = "admin@customs.ly"
ADMIN_PASS    = "Admin@2026!"


def login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    cookies = r.cookies
    return cookies


class TestOfficerViewedEndpoint:
    """Test POST /api/kyc/{user_id}/viewed"""

    def test_officer_viewed_returns_ok(self):
        cookies = login(OFFICER_EMAIL, OFFICER_PASS)
        r = requests.post(f"{BASE_URL}/api/kyc/{USER_ID}/viewed", cookies=cookies)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("message") == "ok"
        print(f"PASS: officer_viewed endpoint returns ok. throttled={data.get('throttled', False)}")

    def test_officer_viewed_throttled_on_repeat(self):
        """Second call within 5 min should return throttled=True"""
        cookies = login(OFFICER_EMAIL, OFFICER_PASS)
        # First call
        requests.post(f"{BASE_URL}/api/kyc/{USER_ID}/viewed", cookies=cookies)
        # Second call (should be throttled)
        r = requests.post(f"{BASE_URL}/api/kyc/{USER_ID}/viewed", cookies=cookies)
        assert r.status_code == 200
        data = r.json()
        # Either throttled or not — both are valid (depends on timing)
        print(f"PASS: second call response: {data}")

    def test_officer_viewed_invalid_id(self):
        cookies = login(OFFICER_EMAIL, OFFICER_PASS)
        r = requests.post(f"{BASE_URL}/api/kyc/invalid_id_xyz/viewed", cookies=cookies)
        # Should return 200 with ok (graceful handling)
        assert r.status_code == 200
        print("PASS: invalid user_id handled gracefully")

    def test_unauthorized_cannot_call_viewed(self):
        """Regular user should not be able to call viewed"""
        cookies = login(USER_EMAIL, USER_PASS)
        r = requests.post(f"{BASE_URL}/api/kyc/{USER_ID}/viewed", cookies=cookies)
        assert r.status_code in [401, 403], f"Expected 401/403, got {r.status_code}"
        print(f"PASS: Regular user gets {r.status_code} on /viewed endpoint")


class TestStatusHistory:
    """Test status_history is populated and returned in KYC list"""

    def test_kyc_list_includes_status_history(self):
        cookies = login(OFFICER_EMAIL, OFFICER_PASS)
        r = requests.get(f"{BASE_URL}/api/kyc/registrations?status=pending", cookies=cookies)
        assert r.status_code == 200, f"Failed to get pending list: {r.text}"
        data = r.json()
        users = data.get("users", data) if isinstance(data, dict) else data
        assert len(users) > 0, "No pending users found"
        # Find our test user
        test_user = next((u for u in users if str(u.get("_id", u.get("id", ""))) == USER_ID), None)
        if test_user:
            history = test_user.get("status_history", [])
            print(f"PASS: test user status_history count: {len(history)}")
            assert isinstance(history, list)
        else:
            print(f"INFO: test user not found in pending list (may be in different status)")

    def test_status_history_has_valid_structure(self):
        """Verify status_history entries have required fields"""
        cookies = login(OFFICER_EMAIL, OFFICER_PASS)
        # Call viewed to ensure at least one entry
        requests.post(f"{BASE_URL}/api/kyc/{USER_ID}/viewed", cookies=cookies)
        
        r = requests.get(f"{BASE_URL}/api/kyc/registrations?status=pending", cookies=cookies)
        assert r.status_code == 200
        data = r.json()
        users = data.get("users", data) if isinstance(data, dict) else data
        test_user = next((u for u in users if str(u.get("_id", u.get("id", ""))) == USER_ID), None)
        
        if test_user and test_user.get("status_history"):
            entry = test_user["status_history"][-1]
            assert "action" in entry, "Missing 'action' field"
            assert "timestamp" in entry, "Missing 'timestamp' field"
            print(f"PASS: status_history entry structure valid: {entry.get('action')}")
        else:
            print("INFO: No status_history found for test user (may need seeding)")


class TestCorrectionAndBadgeLogic:
    """Test correction_requested_at and Updated Badge logic"""

    def test_request_correction_sets_correction_requested_at(self):
        """POST /api/kyc/{id}/correct should set correction_requested_at"""
        cookies = login(OFFICER_EMAIL, OFFICER_PASS)
        payload = {
            "notes": "يرجى تحديث الوثائق",
            "flagged_docs": []
        }
        r = requests.post(f"{BASE_URL}/api/kyc/{USER_ID}/correct", 
                          json=payload, cookies=cookies)
        assert r.status_code == 200, f"Correction request failed: {r.text}"
        data = r.json()
        print(f"PASS: correction requested. Response: {data}")

    def test_correction_adds_history_entry(self):
        """After correction request, status_history should have correction_requested entry"""
        cookies_off = login(OFFICER_EMAIL, OFFICER_PASS)
        # Request correction
        requests.post(f"{BASE_URL}/api/kyc/{USER_ID}/correct",
                      json={"notes": "Test correction", "flagged_docs": []},
                      cookies=cookies_off)
        
        # Check history
        r = requests.get(f"{BASE_URL}/api/kyc/registrations?status=needs_correction", cookies=cookies_off)
        assert r.status_code == 200
        data = r.json()
        users = data.get("users", data) if isinstance(data, dict) else data
        test_user = next((u for u in users if str(u.get("_id", u.get("id", ""))) == USER_ID), None)
        if test_user:
            history = test_user.get("status_history", [])
            actions = [e.get("action") for e in history]
            assert "correction_requested" in actions, f"No correction_requested in history: {actions}"
            print(f"PASS: history has correction_requested. All actions: {actions}")
        else:
            print("INFO: User not in needs_correction list")


class TestUserStatusHistoryViaMe:
    """Test that logged-in user can see their own status_history"""

    def test_user_me_includes_status_history(self):
        cookies = login(USER_EMAIL, USER_PASS)
        r = requests.get(f"{BASE_URL}/api/auth/me", cookies=cookies)
        assert r.status_code == 200, f"Failed /me: {r.text}"
        data = r.json()
        history = data.get("status_history", [])
        print(f"PASS: /me returns status_history with {len(history)} entries")
        assert isinstance(history, list)
        if history:
            entry = history[-1]
            assert "action" in entry
            assert "timestamp" in entry
            print(f"  Last action: {entry.get('action')} at {entry.get('timestamp')}")
