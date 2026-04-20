"""Phase J - Exporter Management Suite: verify/unverify/stats/list endpoints"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_CREDS = {"email": "admin@customs.ly", "password": "Admin@2026!"}
TAX_ID = "DE123456789"


def get_admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
    if r.status_code == 200:
        return r.cookies.get("access_token") or r.json().get("token")
    return None


def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return s


# ─── Public Stats (no auth) ───────────────────────────────────────────────────

class TestPublicStats:
    def test_public_stats_no_auth(self):
        r = requests.get(f"{BASE_URL}/api/exporters/public/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total_exporters" in data
        assert "verified_exporters" in data
        assert "unique_countries" in data
        assert data["total_exporters"] >= 0
        assert data["verified_exporters"] >= 0
        assert data["unique_countries"] >= 0
        print(f"Stats: total={data['total_exporters']}, verified={data['verified_exporters']}, countries={data['unique_countries']}")

    def test_verified_lte_total(self):
        r = requests.get(f"{BASE_URL}/api/exporters/public/stats")
        data = r.json()
        assert data["verified_exporters"] <= data["total_exporters"]


# ─── Admin List Exporters ─────────────────────────────────────────────────────

class TestAdminListExporters:
    def test_list_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/exporters")
        assert r.status_code in [401, 403]

    def test_admin_can_list(self):
        s = admin_session()
        r = s.get(f"{BASE_URL}/api/exporters")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "exporters" in data
        assert isinstance(data["exporters"], list)
        print(f"Admin list: total={data['total']}, returned={len(data['exporters'])}")

    def test_filter_verified(self):
        s = admin_session()
        r = s.get(f"{BASE_URL}/api/exporters", params={"verified": True})
        assert r.status_code == 200
        data = r.json()
        for exp in data["exporters"]:
            assert exp["is_verified"] is True

    def test_filter_unverified(self):
        s = admin_session()
        r = s.get(f"{BASE_URL}/api/exporters", params={"verified": False})
        assert r.status_code == 200
        data = r.json()
        for exp in data["exporters"]:
            assert exp["is_verified"] is False

    def test_search_filter(self):
        s = admin_session()
        r = s.get(f"{BASE_URL}/api/exporters", params={"q": "Samsung"})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1


# ─── Verify / Unverify ────────────────────────────────────────────────────────

class TestVerifyUnverify:
    def test_verify_requires_admin(self):
        r = requests.patch(f"{BASE_URL}/api/exporters/{TAX_ID}/verify")
        assert r.status_code in [401, 403]

    def test_verify_exporter(self):
        s = admin_session()
        r = s.patch(f"{BASE_URL}/api/exporters/{TAX_ID}/verify", json={"notes": "Test verification"})
        assert r.status_code == 200
        data = r.json()
        assert data["is_verified"] is True
        print(f"Verified: {data}")

    def test_exporter_is_now_verified(self):
        s = admin_session()
        r = s.get(f"{BASE_URL}/api/exporters/{TAX_ID}")
        assert r.status_code == 200
        assert r.json()["is_verified"] is True

    def test_unverify_exporter(self):
        s = admin_session()
        r = s.patch(f"{BASE_URL}/api/exporters/{TAX_ID}/unverify")
        assert r.status_code == 200
        data = r.json()
        assert data["is_verified"] is False
        print(f"Unverified: {data}")

    def test_exporter_is_now_unverified(self):
        s = admin_session()
        r = s.get(f"{BASE_URL}/api/exporters/{TAX_ID}")
        assert r.status_code == 200
        assert r.json()["is_verified"] is False

    def test_verify_nonexistent(self):
        s = admin_session()
        r = s.patch(f"{BASE_URL}/api/exporters/INVALID_TAX_XYZ/verify", json={})
        assert r.status_code == 404

    def test_verify_with_notes_persisted(self):
        s = admin_session()
        notes = "TEST_Verified via automated test"
        s.patch(f"{BASE_URL}/api/exporters/{TAX_ID}/verify", json={"notes": notes})
        r = s.get(f"{BASE_URL}/api/exporters/{TAX_ID}")
        data = r.json()
        assert data["verification_notes"] == notes
        # cleanup
        s.patch(f"{BASE_URL}/api/exporters/{TAX_ID}/unverify")
