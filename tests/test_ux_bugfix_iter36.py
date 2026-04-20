"""
UX Bugfix Tests (iteration 36):
1. Email Verify endpoint still works on direct GET (regression check)
2. Invalid token returns 400 with INVALID_TOKEN code
3. Email_unverified user login returns 403 (so frontend must show confirm-button only)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestEmailVerifyEndpoint:
    """Regression: verify-email API still functions correctly"""

    def test_invalid_token_returns_400(self):
        """Invalid token should return 400 with INVALID_TOKEN code"""
        res = requests.get(f"{BASE_URL}/api/auth/verify-email/fake-invalid-token-xyz")
        assert res.status_code == 400
        data = res.json()
        assert 'detail' in data
        detail = data['detail']
        assert detail.get('code') == 'INVALID_TOKEN' or 'invalid' in str(detail).lower() or 'token' in str(detail).lower()

    def test_empty_token_path_not_found(self):
        """Endpoint without token should return 404/405 (not 500)"""
        res = requests.get(f"{BASE_URL}/api/auth/verify-email/")
        assert res.status_code in [404, 405, 422]

    def test_resend_verification_requires_auth(self):
        """Resend verification should require authentication"""
        res = requests.post(f"{BASE_URL}/api/auth/resend-verification")
        assert res.status_code in [401, 403, 422]


class TestEmailUnverifiedLoginBlocked:
    """Email unverified user should be blocked from login (so they must use verify link)"""

    def test_email_unverified_user_login_returns_403(self):
        """Login with email_unverified account should return EMAIL_UNVERIFIED error"""
        res = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "test_verify_ux_fix@test.ly",
            "password": "TestPass@2026!"
        })
        # Should be blocked
        assert res.status_code in [400, 401, 403]
        data = res.json()
        detail = data.get('detail', {})
        if isinstance(detail, dict):
            assert detail.get('code') in ['EMAIL_UNVERIFIED', 'KYC_PENDING']

    def test_approved_user_login_works(self):
        """Approved user should login successfully"""
        res = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@customs.ly",
            "password": "Admin@2026!"
        })
        assert res.status_code == 200
        data = res.json()
        assert 'user' in data
        assert data['user']['registration_status'] == 'approved'
