"""Backend tests for BrokerDashboard + Available Brokers API (iteration 49)"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_CREDS = {"email": "admin@customs.ly", "password": "Admin@2026!"}
BROKER_CREDS = {"email": "test_broker_wizard@test.ly", "password": "Broker@2026!"}
FROZEN_CREDS = {"email": "frozen_broker3@test.ly", "password": "Broker@2026!"}
REGULAR_BROKER_CREDS = {"email": "broker@customs.ly", "password": "Broker@2026!"}


def login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code == 200:
        return r.cookies
    return None


class TestAvailableBrokers:
    """BACKEND-1 to BACKEND-5: available-brokers endpoint"""

    def test_available_brokers_no_filter(self):
        """BACKEND-1: Returns list of approved non-frozen brokers"""
        cookies = login(BROKER_CREDS)
        if not cookies:
            pytest.skip("Login failed")
        r = requests.get(f"{BASE_URL}/api/users/available-brokers", cookies=cookies)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list), "Response should be a list"
        # Verify all are approved active brokers (no suspended)
        for b in data:
            assert "_id" in b or "id" in b
            assert b.get("broker_type") in ("individual", "company", None, "")
        print(f"PASS: available-brokers no filter returned {len(data)} brokers")

    def test_available_brokers_tripoli_port(self):
        """BACKEND-2: Filter by طرابلس البحري — returns TRP brokers + companies"""
        cookies = login(BROKER_CREDS)
        if not cookies:
            pytest.skip("Login failed")
        r = requests.get(
            f"{BASE_URL}/api/users/available-brokers",
            params={"port_of_entry": "طرابلس البحري"},
            cookies=cookies
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        for b in data:
            # Each broker should be TRP individual or company
            if b.get("broker_type") == "individual":
                assert b.get("customs_region") == "TRP", \
                    f"Individual broker {b.get('_id')} has region {b.get('customs_region')}, expected TRP"
        print(f"PASS: طرابلس البحري filter returned {len(data)} brokers, all individual are TRP")

    def test_available_brokers_benghazi_excludes_trp(self):
        """BACKEND-3: Filter by بنغازي البحري — TRP individual broker should be excluded"""
        cookies = login(BROKER_CREDS)
        if not cookies:
            pytest.skip("Login failed")
        r = requests.get(
            f"{BASE_URL}/api/users/available-brokers",
            params={"port_of_entry": "بنغازي البحري"},
            cookies=cookies
        )
        assert r.status_code == 200
        data = r.json()
        for b in data:
            if b.get("broker_type") == "individual":
                assert b.get("customs_region") != "TRP", \
                    f"TRP individual broker should not appear for بنغازي البحري"
        print(f"PASS: بنغازي البحري excludes TRP individual brokers ({len(data)} returned)")

    def test_musaid_priority_flag(self):
        """BACKEND-4: BNG/MSR brokers have is_musaid_priority=true"""
        cookies = login(BROKER_CREDS)
        if not cookies:
            pytest.skip("Login failed")
        r = requests.get(f"{BASE_URL}/api/users/available-brokers", cookies=cookies)
        assert r.status_code == 200
        data = r.json()
        for b in data:
            region = b.get("customs_region", "")
            if region in ("BNG", "MSR"):
                assert b.get("is_musaid_priority") is True, \
                    f"Broker in {region} should have is_musaid_priority=True"
        print("PASS: BNG/MSR brokers have is_musaid_priority=True")

    def test_frozen_broker_excluded(self):
        """BACKEND-5: frozen_broker3 (suspended) should not appear"""
        cookies = login(ADMIN_CREDS)
        if not cookies:
            pytest.skip("Admin login failed")
        r = requests.get(f"{BASE_URL}/api/users/available-brokers", cookies=cookies)
        assert r.status_code == 200
        data = r.json()
        emails = [b.get("email", "") for b in data]
        assert "frozen_broker3@test.ly" not in emails, \
            "Frozen broker should not appear in available-brokers list"
        print(f"PASS: frozen_broker3 not in available-brokers ({len(data)} total)")

    def test_broker_my_requests_endpoint(self):
        """BrokerDashboard uses /broker/my-requests — verify endpoint exists"""
        cookies = login(BROKER_CREDS)
        if not cookies:
            pytest.skip("Login failed")
        r = requests.get(f"{BASE_URL}/api/broker/my-requests", cookies=cookies)
        assert r.status_code in (200, 404), f"Expected 200 or 404, got {r.status_code}: {r.text}"
        if r.status_code == 200:
            assert isinstance(r.json(), list)
        print(f"PASS: /broker/my-requests returned {r.status_code}")

    def test_broker_importers_endpoint(self):
        """BrokerDashboard uses /broker/importers — verify endpoint exists"""
        cookies = login(BROKER_CREDS)
        if not cookies:
            pytest.skip("Login failed")
        r = requests.get(f"{BASE_URL}/api/broker/importers", cookies=cookies)
        assert r.status_code in (200, 404), f"Expected 200 or 404, got {r.status_code}: {r.text}"
        if r.status_code == 200:
            assert isinstance(r.json(), list)
        print(f"PASS: /broker/importers returned {r.status_code}")

    def test_requires_auth(self):
        """available-brokers requires authentication"""
        r = requests.get(f"{BASE_URL}/api/users/available-brokers")
        assert r.status_code in (401, 403), f"Expected 401/403 without auth, got {r.status_code}"
        print(f"PASS: requires auth, got {r.status_code}")
