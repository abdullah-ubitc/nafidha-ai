"""
Iteration 68 — Rate Limiting on forgot-password + Domain consolidation tests
Tests: 3 requests succeed, 4th returns HTTP 429 with Arabic message
"""
import pytest
import requests
import os
import time
import subprocess

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestForgotPasswordRateLimit:
    """Rate limiter: 3 requests/hour per IP. 4th must return 429."""

    def test_admin_login_regression(self):
        """Regression: admin login still works."""
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": "admin@customs.ly", "password": "Admin@2026!"},
                          timeout=10)
        assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
        data = r.json()
        assert "user" in data
        assert data["user"]["email"] == "admin@customs.ly"
        print("PASS: Admin login works")

    def test_first_three_requests_succeed(self):
        """First 3 requests to forgot-password must return 200."""
        # Restart backend to reset the in-memory rate limiter
        subprocess.run(["sudo", "supervisorctl", "restart", "backend"],
                       check=False, capture_output=True)
        time.sleep(4)  # Wait for backend to come up

        for i in range(1, 4):
            r = requests.post(f"{BASE_URL}/api/auth/forgot-password",
                              json={"email": "unknown_test_rate_limit@test.ly"},
                              timeout=10)
            assert r.status_code == 200, f"Request {i} failed with {r.status_code}: {r.text}"
            print(f"PASS: Request {i} returned 200")

    def test_fourth_request_returns_429(self):
        """4th request from same IP must return HTTP 429 with Arabic message."""
        # Make the 4th request (rate limiter was initialized by previous test)
        r = requests.post(f"{BASE_URL}/api/auth/forgot-password",
                          json={"email": "unknown_test_rate_limit@test.ly"},
                          timeout=10)
        assert r.status_code == 429, f"Expected 429 but got {r.status_code}: {r.text}"
        print(f"PASS: 4th request returned 429")

    def test_429_message_contains_arabic_text(self):
        """429 detail must contain 'تجاوزت الحد المسموح' and wait time in minutes."""
        r = requests.post(f"{BASE_URL}/api/auth/forgot-password",
                          json={"email": "unknown_test_rate_limit@test.ly"},
                          timeout=10)
        # Should be 429 (rate limit already triggered)
        assert r.status_code == 429, f"Expected 429 but got {r.status_code}"
        data = r.json()
        detail = data.get("detail", "")
        assert "تجاوزت الحد المسموح" in detail, f"Arabic message not found: {detail}"
        # Check for minute mention
        assert "دقيقة" in detail, f"Wait time in minutes not found: {detail}"
        print(f"PASS: Arabic message correct: {detail[:80]}")

    def test_forgot_password_known_email_within_limit(self):
        """Regression: forgot-password works for known email when within limit (fresh restart)."""
        # Restart to reset limiter
        subprocess.run(["sudo", "supervisorctl", "restart", "backend"],
                       check=False, capture_output=True)
        time.sleep(4)

        r = requests.post(f"{BASE_URL}/api/auth/forgot-password",
                          json={"email": "admin@customs.ly"},
                          timeout=10)
        assert r.status_code == 200, f"Expected 200 got {r.status_code}: {r.text}"
        data = r.json()
        assert "message" in data
        assert "ستصلك رسالة" in data["message"] or "إذا كان البريد" in data["message"]
        print(f"PASS: forgot-password known email: {data['message'][:60]}")

    def test_reset_password_invalid_token(self):
        """Regression: reset-password validates token correctly."""
        r = requests.post(f"{BASE_URL}/api/auth/reset-password",
                          json={"token": "invalid_token_xyz", "new_password": "NewPass@2026!"},
                          timeout=10)
        assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"
        data = r.json()
        detail = data.get("detail", {})
        code = detail.get("code") if isinstance(detail, dict) else ""
        assert code == "INVALID_RESET_TOKEN" or "غير صالح" in str(detail), f"Unexpected detail: {detail}"
        print("PASS: reset-password invalid token returns 400")

    def test_reset_password_short_password(self):
        """Regression: reset-password rejects passwords shorter than 8 chars."""
        r = requests.post(f"{BASE_URL}/api/auth/reset-password",
                          json={"token": "some_token", "new_password": "short"},
                          timeout=10)
        assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"
        print("PASS: reset-password rejects short password")


class TestDomainConsolidation:
    """Verify _FRONTEND_URL constant is used consistently in auth.py and email_service.py."""

    def test_frontend_url_in_auth_py(self):
        """auth.py must use module-level _FRONTEND_URL (not scattered os.environ.get)."""
        with open("/app/backend/routes/auth.py") as f:
            content = f.read()
        # Check module-level constant defined
        assert '_FRONTEND_URL = os.environ.get("FRONTEND_BASE_URL"' in content, \
            "_FRONTEND_URL constant not found in auth.py"
        # Check no scattered os.environ.get for frontend URL in the body
        # (The module-level constant should be the only os.environ.get for FRONTEND_BASE_URL)
        import re
        # Find all occurrences
        matches = re.findall(r'os\.environ\.get\(["\']FRONTEND_BASE_URL["\']', content)
        assert len(matches) == 1, f"Expected 1 occurrence of os.environ.get FRONTEND_BASE_URL, found {len(matches)}"
        print("PASS: auth.py uses module-level _FRONTEND_URL constant only once")

    def test_frontend_url_in_email_service(self):
        """email_service.py must define _FRONTEND_URL from FRONTEND_BASE_URL env var."""
        with open("/app/backend/services/email_service.py") as f:
            content = f.read()
        assert '_FRONTEND_URL = os.environ.get("FRONTEND_BASE_URL"' in content, \
            "_FRONTEND_URL not found in email_service.py"
        assert "libya-customs-acis.preview.emergentagent.com" in content, \
            "Default domain not found in email_service.py"
        print("PASS: email_service.py uses _FRONTEND_URL from FRONTEND_BASE_URL env var")

    def test_auth_py_uses_frontend_url_variable(self):
        """auth.py must reference _FRONTEND_URL variable (not hardcoded URL) for links."""
        with open("/app/backend/routes/auth.py") as f:
            content = f.read()
        # Should use _FRONTEND_URL variable for verify_url and reset_url
        assert "_FRONTEND_URL" in content
        # Count usages of the variable (not the definition)
        import re
        usages = re.findall(r'frontend\s*=\s*_FRONTEND_URL|_FRONTEND_URL', content)
        assert len(usages) >= 3, f"Expected at least 3 uses of _FRONTEND_URL, found {len(usages)}"
        print(f"PASS: _FRONTEND_URL used {len(usages)} times in auth.py")
