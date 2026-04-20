"""Phase A - New Roles Testing: carrier_agent, manifest_officer, acid_risk_officer, declaration_officer, release_officer"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

def login(email, password):
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed for {email}: {resp.text}"
    data = resp.json()
    return data.get("access_token") or data.get("token")

def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}

# --- Auth Tests ---
class TestPhaseALogin:
    def test_carrier_agent_login(self):
        token = login("carrier@customs.ly", "Carrier@2026!")
        assert token and len(token) > 10

    def test_manifest_officer_login(self):
        token = login("manifest@customs.ly", "Manifest@2026!")
        assert token and len(token) > 10

    def test_acid_risk_officer_login(self):
        token = login("acidrisk@customs.ly", "AcidRisk@2026!")
        assert token and len(token) > 10

    def test_declaration_officer_login(self):
        token = login("declaration@customs.ly", "Declaration@2026!")
        assert token and len(token) > 10

    def test_release_officer_login(self):
        token = login("release@customs.ly", "Release@2026!")
        assert token and len(token) > 10

    def test_admin_login(self):
        # The admin account is admin@customs.ly (ladmin@customs.ly does not exist)
        token = login("admin@customs.ly", "Admin@2026!")
        assert token and len(token) > 10


# --- Manifest APIs ---
class TestManifestAPI:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.carrier_token = login("carrier@customs.ly", "Carrier@2026!")
        self.manifest_token = login("manifest@customs.ly", "Manifest@2026!")

    def test_create_manifest(self):
        payload = {
            "transport_mode": "sea",
            "port_of_entry": "طرابلس",
            "arrival_date": "2026-06-01",
            "vessel_name": "TEST_VESSEL_001",
            "consignments": [{"description": "بضائع تجريبية", "weight": 1000, "packages": 10}]
        }
        resp = requests.post(f"{BASE_URL}/api/manifests", json=payload, headers=auth_headers(self.carrier_token))
        assert resp.status_code == 200, f"Create manifest failed: {resp.text}"
        data = resp.json()
        assert "manifest_number" in data
        assert data["manifest_number"].startswith("MNF/")
        # Format: MNF/YEAR/NNNNN
        parts = data["manifest_number"].split("/")
        assert len(parts) == 3
        self.manifest_id = data.get("id") or str(data.get("_id", ""))

    def test_manifest_number_format(self):
        payload = {
            "transport_mode": "air",
            "port_of_entry": "مصراتة",
            "arrival_date": "2026-06-01",
            "vessel_name": "TEST_AIR_001",
            "consignments": []
        }
        resp = requests.post(f"{BASE_URL}/api/manifests", json=payload, headers=auth_headers(self.carrier_token))
        assert resp.status_code == 200
        data = resp.json()
        mn = data["manifest_number"]
        parts = mn.split("/")
        assert parts[0] == "MNF"
        assert len(parts[1]) == 4  # year
        assert len(parts[2]) == 5  # 5-digit number

    def test_manifest_queue_returns_array(self):
        resp = requests.get(f"{BASE_URL}/api/manifests/queue", headers=auth_headers(self.manifest_token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_manifest_queue_contains_submitted(self):
        # Create one first
        payload = {
            "transport_mode": "road",
            "port_of_entry": "بنغازي",
            "arrival_date": "2026-06-01",
            "vessel_name": "TEST_TRUCK_001",
            "consignments": []
        }
        requests.post(f"{BASE_URL}/api/manifests", json=payload, headers=auth_headers(self.carrier_token))
        
        resp = requests.get(f"{BASE_URL}/api/manifests/queue", headers=auth_headers(self.manifest_token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Should have at least the one we just created
        assert len(data) >= 1

    def test_review_manifest_accept(self):
        # Create a manifest first
        payload = {
            "transport_mode": "sea",
            "port_of_entry": "طرابلس",
            "arrival_date": "2026-06-01",
            "vessel_name": "TEST_REVIEW_001",
            "consignments": []
        }
        create_resp = requests.post(f"{BASE_URL}/api/manifests", json=payload, headers=auth_headers(self.carrier_token))
        assert create_resp.status_code == 200
        manifest_id = create_resp.json().get("id") or create_resp.json().get("_id")
        
        # Review: accept
        review_resp = requests.put(
            f"{BASE_URL}/api/manifests/{manifest_id}/review",
            json={"action": "accept", "notes": "تم القبول"},
            headers=auth_headers(self.manifest_token)
        )
        assert review_resp.status_code == 200
        data = review_resp.json()
        assert data.get("new_status") == "accepted" or data.get("status") == "accepted"


# --- ACID Risk API ---
class TestAcidRiskAPI:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = login("acidrisk@customs.ly", "AcidRisk@2026!")

    def test_acid_risk_queue_returns_array(self):
        resp = requests.get(f"{BASE_URL}/api/acid-risk/queue", headers=auth_headers(self.token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_acid_risk_queue_structure(self):
        resp = requests.get(f"{BASE_URL}/api/acid-risk/queue", headers=auth_headers(self.token))
        assert resp.status_code == 200
        data = resp.json()
        if len(data) > 0:
            item = data[0]
            assert "id" in item or "_id" in item


# --- Declaration API ---
class TestDeclarationAPI:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = login("declaration@customs.ly", "Declaration@2026!")

    def test_declaration_queue_returns_array(self):
        resp = requests.get(f"{BASE_URL}/api/declaration/queue", headers=auth_headers(self.token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


# --- Release API ---
class TestReleaseAPI:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = login("release@customs.ly", "Release@2026!")

    def test_release_queue_returns_array(self):
        resp = requests.get(f"{BASE_URL}/api/release/queue", headers=auth_headers(self.token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_release_stats(self):
        resp = requests.get(f"{BASE_URL}/api/release/stats", headers=auth_headers(self.token))
        assert resp.status_code == 200
        data = resp.json()
        assert "pending_release" in data
        assert "released_today" in data
        assert "total_released" in data

    def test_release_stats_types(self):
        resp = requests.get(f"{BASE_URL}/api/release/stats", headers=auth_headers(self.token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["pending_release"], int)
        assert isinstance(data["released_today"], int)
        assert isinstance(data["total_released"], int)
