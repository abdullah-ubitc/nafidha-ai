"""
Iteration 67 — Password Reset Flow Tests
Tests: /api/auth/forgot-password, /api/auth/reset-password
"""
import pytest
import requests
import os
import pymongo
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', '')
DB_NAME = os.environ.get('DB_NAME', '')

# Known test user
KNOWN_EMAIL = "admin@customs.ly"
UNKNOWN_EMAIL = "nonexistent_xyz999@test.ly"


@pytest.fixture(scope="module")
def db():
    client = pymongo.MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


class TestForgotPassword:
    """POST /api/auth/forgot-password"""

    def test_forgot_password_unknown_email_returns_success(self):
        """No user enumeration — always returns 200 with same message"""
        resp = requests.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": UNKNOWN_EMAIL})
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert "مُسجَّلاً" in data["message"] or "مسجلاً" in data["message"] or "ستصلك" in data["message"]
        print(f"PASS: Unknown email returns 200 — {data['message']}")

    def test_forgot_password_known_email_returns_success(self):
        """Known email also returns same success message"""
        resp = requests.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": KNOWN_EMAIL})
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        print(f"PASS: Known email returns 200 — {data['message']}")

    def test_forgot_password_stores_token_in_db(self, db):
        """After calling forgot-password with known user, token is stored in DB"""
        requests.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": KNOWN_EMAIL})
        time.sleep(0.5)  # allow DB write
        user = db.users.find_one({"email": KNOWN_EMAIL})
        assert user is not None
        assert "reset_password_token" in user, "reset_password_token not found in DB"
        assert "reset_password_expires" in user
        assert len(user["reset_password_token"]) > 10
        print(f"PASS: reset_password_token stored in DB: {user['reset_password_token'][:10]}...")

    def test_forgot_password_empty_email_returns_400(self):
        """Empty email returns 400"""
        resp = requests.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": ""})
        assert resp.status_code == 400
        print("PASS: Empty email returns 400")


class TestResetPassword:
    """POST /api/auth/reset-password"""

    def test_reset_password_invalid_token_returns_400(self):
        """Invalid token returns 400 with Arabic error"""
        resp = requests.post(f"{BASE_URL}/api/auth/reset-password", json={
            "token": "invalid_token_xyz",
            "new_password": "Admin@2026!"
        })
        assert resp.status_code == 400
        data = resp.json()
        detail = data.get("detail", {})
        # detail may be string or dict
        if isinstance(detail, dict):
            assert detail.get("code") == "INVALID_RESET_TOKEN"
            msg = detail.get("message", "")
        else:
            msg = detail
        assert "غير صالح" in msg or "رابط" in msg
        print(f"PASS: Invalid token returns 400 — {msg}")

    def test_reset_password_short_password_returns_400(self):
        """Password < 8 chars returns 400"""
        resp = requests.post(f"{BASE_URL}/api/auth/reset-password", json={
            "token": "some_token",
            "new_password": "abc"
        })
        assert resp.status_code == 400
        data = resp.json()
        detail = data.get("detail", "")
        assert "8" in str(detail) or "أحرف" in str(detail)
        print(f"PASS: Short password returns 400 — {detail}")

    def test_reset_password_full_flow(self, db):
        """Full flow: forgot-password → get token from DB → reset-password → login"""
        # Step 1: request reset
        resp = requests.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": KNOWN_EMAIL})
        assert resp.status_code == 200
        time.sleep(0.5)

        # Step 2: get token from DB
        user = db.users.find_one({"email": KNOWN_EMAIL})
        token = user.get("reset_password_token")
        assert token, "No reset token in DB"

        # Step 3: reset password — use the original admin password from env
        new_password = os.environ.get("TEST_ADMIN_PASSWORD", "")
        if not new_password:
            pytest.skip("TEST_ADMIN_PASSWORD env var not set — skipping reset flow")
        resp2 = requests.post(f"{BASE_URL}/api/auth/reset-password", json={
            "token": token,
            "new_password": new_password
        })
        assert resp2.status_code == 200
        data = resp2.json()
        assert "message" in data
        assert "تم" in data["message"] or "تغيير" in data["message"]
        print(f"PASS: Password reset success — {data['message']}")

        # Step 4: token should be cleared from DB
        time.sleep(0.3)
        user_after = db.users.find_one({"email": KNOWN_EMAIL})
        assert "reset_password_token" not in user_after, "Token not cleared after reset"
        print("PASS: Token cleared from DB after reset")

        # Step 5: login with new password
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": KNOWN_EMAIL,
            "password": new_password
        })
        assert login_resp.status_code == 200
        print("PASS: Login with new password works")


class TestRegressionAdmin:
    """Regression: Admin login still works"""

    def test_admin_login(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@customs.ly",
            "password": "Admin@2026!"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("role") == "admin" or "admin" in str(data)
        print("PASS: Admin login works")
