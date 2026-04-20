"""Phase G Backend Tests — Executive Dashboard new fields, auto-suspend, self-suspension guard"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

def get_admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    if r.status_code == 200:
        return r.cookies.get("access_token") or r.json().get("token")
    return None

def get_importer_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "importer@customs.ly", "password": "Importer@2026!"})
    if r.status_code == 200:
        return r.cookies.get("access_token") or r.json().get("token")
    return None

def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return s

def importer_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "importer@customs.ly", "password": "Importer@2026!"})
    assert r.status_code == 200, f"Importer login failed: {r.text}"
    return s

# GOLDEN-1: Executive dashboard returns new Phase G fields
class TestExecutiveDashboard:
    def test_exec_dashboard_returns_200(self):
        s = admin_session()
        r = s.get(f"{BASE_URL}/api/executive/dashboard")
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"

    def test_exec_dashboard_has_platform_revenue_fields(self):
        s = admin_session()
        r = s.get(f"{BASE_URL}/api/executive/dashboard")
        assert r.status_code == 200
        data = r.json()
        summary = data.get("summary", data)
        assert "total_platform_revenue_lyd" in summary, f"Missing total_platform_revenue_lyd. Keys: {list(summary.keys())[:10]}"
        assert "platform_subscription_lyd" in summary, "Missing platform_subscription_lyd"
        assert "suspended_accounts_count" in summary, "Missing suspended_accounts_count"
        assert "active_entities_count" in summary, "Missing active_entities_count"
        assert "early_bird_subscriptions" in summary, "Missing early_bird_subscriptions"

    def test_exec_dashboard_fields_are_numbers(self):
        s = admin_session()
        r = s.get(f"{BASE_URL}/api/executive/dashboard")
        data = r.json()
        summary = data.get("summary", data)
        assert isinstance(summary["total_platform_revenue_lyd"], (int, float))
        assert isinstance(summary["suspended_accounts_count"], (int, float))
        assert isinstance(summary["active_entities_count"], (int, float))
        assert isinstance(summary["early_bird_subscriptions"], (int, float))

    def test_exec_dashboard_existing_fields(self):
        s = admin_session()
        r = s.get(f"{BASE_URL}/api/executive/dashboard")
        data = r.json()
        summary = data.get("summary", data)
        assert "total_requests" in summary
        assert "approval_rate_pct" in summary


# GOLDEN-2: Auto-suspend endpoint
class TestAutoSuspend:
    def test_suspend_expired_returns_200(self):
        s = admin_session()
        r = s.post(f"{BASE_URL}/api/users/admin/suspend-expired")
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"

    def test_suspend_expired_response_structure(self):
        s = admin_session()
        r = s.post(f"{BASE_URL}/api/users/admin/suspend-expired")
        assert r.status_code == 200
        data = r.json()
        assert "suspended_count" in data
        assert isinstance(data["suspended_count"], int)
        assert "message" in data

    def test_self_suspension_blocked(self):
        """Admin cannot suspend their own account"""
        s = admin_session()
        # Get admin's own user ID
        me_r = s.get(f"{BASE_URL}/api/auth/me")
        assert me_r.status_code == 200
        admin_id = me_r.json().get("id") or me_r.json().get("_id") or me_r.json().get("user_id")
        if not admin_id:
            pytest.skip("Could not get admin ID")
        r = s.put(f"{BASE_URL}/api/users/{admin_id}/status", json={"is_active": False})
        assert r.status_code == 400, f"Expected 400 for self-suspension, got {r.status_code}"


# Wallet top-up (GOLDEN-3)
class TestWalletTopup:
    def test_wallet_topup_as_importer(self):
        s = importer_session()
        r = s.post(f"{BASE_URL}/api/wallet/topup", json={"amount_lyd": 200, "payment_ref": "GOLDEN-TEST-001"})
        assert r.status_code in [200, 201], f"Got {r.status_code}: {r.text}"

    def test_wallet_balance_readable(self):
        s = importer_session()
        r = s.get(f"{BASE_URL}/api/wallet/my")
        assert r.status_code == 200
        data = r.json()
        assert "balance" in data or "balance_lyd" in data
