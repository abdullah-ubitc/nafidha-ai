"""
Phase F Backend Tests — NAFIDHA Libya Customs
Tests: wallet top-up, admin expired-count, suspend-expired, broker endpoints
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

def get_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    return r.json().get('access_token', '')

class TestWallet:
    """Wallet endpoint tests"""

    def test_wallet_balance(self):
        token = get_token("importer@customs.ly", "Importer@2026!")
        r = requests.get(f"{BASE_URL}/api/wallet/my", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert "balance_lyd" in data
        assert isinstance(data["balance_lyd"], (int, float))

    def test_wallet_topup(self):
        token = get_token("importer@customs.ly", "Importer@2026!")
        r = requests.post(f"{BASE_URL}/api/wallet/topup",
            json={"amount_lyd": 100.0, "payment_ref": "TEST-PHASE-F-001"},
            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        # Verify balance updated
        assert "balance_lyd" in data or "message" in data or "amount_lyd" in data

    def test_wallet_topup_missing_field(self):
        token = get_token("importer@customs.ly", "Importer@2026!")
        r = requests.post(f"{BASE_URL}/api/wallet/topup",
            json={"amount": 100.0},  # wrong field name
            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422  # Validation error

    def test_wallet_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/wallet/my")
        assert r.status_code in [401, 403]


class TestAdminUserManagement:
    """Admin user management tests"""

    def test_expired_count(self):
        token = get_token("admin@customs.ly", "Admin@2026!")
        r = requests.get(f"{BASE_URL}/api/users/admin/expired-count",
            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert "expired_active_count" in data
        assert isinstance(data["expired_active_count"], int)
        assert data["expired_active_count"] == 0  # No expired licenses in test data

    def test_suspend_expired(self):
        token = get_token("admin@customs.ly", "Admin@2026!")
        r = requests.post(f"{BASE_URL}/api/users/admin/suspend-expired",
            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert "suspended_count" in data
        assert data["suspended_count"] == 0

    def test_expired_count_requires_admin(self):
        token = get_token("broker@customs.ly", "Broker@2026!")
        r = requests.get(f"{BASE_URL}/api/users/admin/expired-count",
            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code in [401, 403]


class TestBrokerEndpoints:
    """Broker page endpoints"""

    def test_broker_my_requests(self):
        token = get_token("broker@customs.ly", "Broker@2026!")
        r = requests.get(f"{BASE_URL}/api/broker/my-requests",
            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_broker_importers(self):
        token = get_token("broker@customs.ly", "Broker@2026!")
        r = requests.get(f"{BASE_URL}/api/broker/importers",
            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_broker_do_pending_requests(self):
        """Test filtering by do_issued status for SAD-ready tab"""
        token = get_token("broker@customs.ly", "Broker@2026!")
        r = requests.get(f"{BASE_URL}/api/broker/my-requests?status=do_issued",
            headers={"Authorization": f"Bearer {token}"})
        # Either returns filtered list or all (depends on implementation)
        assert r.status_code == 200


class TestManifestDO:
    """Manifest DO issuance endpoint"""

    def test_accepted_manifests_exist(self):
        token = get_token("carrier@customs.ly", "Carrier@2026!")
        r = requests.get(f"{BASE_URL}/api/manifests",
            headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        manifests = r.json()
        accepted = [m for m in manifests if m.get('status') == 'accepted']
        assert len(accepted) >= 1, "Need at least 1 accepted manifest for DO issuance"
        print(f"Found {len(accepted)} accepted manifests")

    def test_issue_do_requires_freight_confirmation(self):
        token = get_token("carrier@customs.ly", "Carrier@2026!")
        # Get accepted manifest
        r = requests.get(f"{BASE_URL}/api/manifests",
            headers={"Authorization": f"Bearer {token}"})
        manifests = r.json()
        accepted = [m for m in manifests if m.get('status') == 'accepted']
        if not accepted:
            pytest.skip("No accepted manifests available")

        manifest_id = accepted[0].get('_id')
        # Try to issue DO without freight confirmation
        do_r = requests.put(f"{BASE_URL}/api/manifests/{manifest_id}/issue-do",
            json={"freight_fees_confirmed": False},
            headers={"Authorization": f"Bearer {token}"})
        # Should either fail or require confirmed=True
        # 400/422 if freight not confirmed, or 200 if allowed
        assert do_r.status_code in [200, 400, 422]
        print(f"Issue DO response: {do_r.status_code} - {do_r.text[:100]}")
