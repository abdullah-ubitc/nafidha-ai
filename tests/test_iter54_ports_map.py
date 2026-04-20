"""
Iteration 54 — Ports Map & Language Toggle Tests
Tests: /api/ports/stats endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

@pytest.fixture(scope="module")
def admin_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@customs.ly",
        "password": "Admin@2026!"
    })
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    return resp.json().get("access_token") or resp.json().get("token")

@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}

class TestPortsStats:
    """Tests for GET /api/ports/stats"""

    def test_ports_stats_returns_200(self, admin_headers):
        resp = requests.get(f"{BASE_URL}/api/ports/stats", headers=admin_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_ports_stats_structure(self, admin_headers):
        resp = requests.get(f"{BASE_URL}/api/ports/stats", headers=admin_headers)
        data = resp.json()
        assert "ports" in data, "Missing 'ports' key"
        assert "summary" in data, "Missing 'summary' key"

    def test_ports_count_is_19(self, admin_headers):
        resp = requests.get(f"{BASE_URL}/api/ports/stats", headers=admin_headers)
        data = resp.json()
        ports = data["ports"]
        assert len(ports) == 19, f"Expected 19 ports, got {len(ports)}"

    def test_ports_have_required_fields(self, admin_headers):
        resp = requests.get(f"{BASE_URL}/api/ports/stats", headers=admin_headers)
        ports = resp.json()["ports"]
        required = ["value", "label_en", "mode", "region", "lon", "lat",
                    "acid_count", "land_pending", "land_escalated", "status"]
        for port in ports[:3]:  # Check first 3
            for field in required:
                assert field in port, f"Port '{port.get('value')}' missing field '{field}'"

    def test_summary_has_required_fields(self, admin_headers):
        resp = requests.get(f"{BASE_URL}/api/ports/stats", headers=admin_headers)
        summary = resp.json()["summary"]
        for field in ["total_active_acids", "total_land_pending", "total_land_escalated",
                      "alert_ports", "active_ports"]:
            assert field in summary, f"Summary missing '{field}'"

    def test_summary_total_active_acids(self, admin_headers):
        resp = requests.get(f"{BASE_URL}/api/ports/stats", headers=admin_headers)
        summary = resp.json()["summary"]
        # Just verify it's a non-negative integer
        assert isinstance(summary["total_active_acids"], int)
        assert summary["total_active_acids"] >= 0

    def test_musaid_port_exists(self, admin_headers):
        resp = requests.get(f"{BASE_URL}/api/ports/stats", headers=admin_headers)
        ports = resp.json()["ports"]
        musaid = [p for p in ports if p.get("is_musaid")]
        assert len(musaid) >= 1, "No port with is_musaid=True found"
        assert musaid[0]["value"] == "منفذ مساعد"

    def test_port_status_values_valid(self, admin_headers):
        resp = requests.get(f"{BASE_URL}/api/ports/stats", headers=admin_headers)
        ports = resp.json()["ports"]
        valid = {"idle", "active", "caution", "alert"}
        for p in ports:
            assert p["status"] in valid, f"Port '{p['value']}' has invalid status '{p['status']}'"

    def test_ports_stats_requires_auth(self):
        resp = requests.get(f"{BASE_URL}/api/ports/stats")
        assert resp.status_code in [401, 403], f"Expected auth required, got {resp.status_code}"
