"""Phase 6 backend tests: Public Tracking, JL38 PDF, regression"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


def get_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json().get("access_token") or r.json().get("token")
    return None


class TestPublicTracking:
    """GET /api/public/track/{acid_number} — no auth required"""

    def test_track_known_acid(self):
        """Track a known gate_released ACID"""
        r = requests.get(f"{BASE_URL}/api/public/track/ACID/2026/00001")
        # Try alternate format if first fails
        if r.status_code == 404:
            # try URL encoded
            r = requests.get(f"{BASE_URL}/api/public/track/ACID%2F2026%2F00001")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "acid_number" in data
        assert "status" in data
        assert "timeline_stages" in data
        stages = data["timeline_stages"]
        assert len(stages) >= 4, f"Expected at least 4 stages, got {len(stages)}"
        print(f"ACID: {data['acid_number']}, Status: {data['status']}, Stages: {len(stages)}")

    def test_track_returns_jl38_for_released(self):
        """Gate released ACIDs should return jl38_number"""
        r = requests.get(f"{BASE_URL}/api/public/track/ACID/2026/00001")
        if r.status_code == 404:
            r = requests.get(f"{BASE_URL}/api/public/track/ACID%2F2026%2F00001")
        if r.status_code != 200:
            pytest.skip("ACID/2026/00001 not accessible")
        data = r.json()
        if data.get("status") == "gate_released":
            assert data.get("jl38_number") is not None, "jl38_number should be present for gate_released"
            print(f"JL38 number: {data['jl38_number']}")
        else:
            print(f"ACID status is {data['status']}, not gate_released - skipping jl38 check")

    def test_track_not_found_returns_404(self):
        """Non-existent ACID returns 404"""
        r = requests.get(f"{BASE_URL}/api/public/track/ACID/9999/99999")
        assert r.status_code == 404, f"Expected 404, got {r.status_code}"

    def test_track_no_auth_required(self):
        """Endpoint works without Authorization header"""
        s = requests.Session()
        # No auth header set
        r = s.get(f"{BASE_URL}/api/public/track/ACID/2026/00001")
        if r.status_code == 404:
            r = s.get(f"{BASE_URL}/api/public/track/ACID%2F2026%2F00001")
        assert r.status_code in [200, 404], f"Unexpected status: {r.status_code}"
        print(f"No-auth track test status: {r.status_code}")

    def test_track_find_any_gate_released(self):
        """Find any gate_released ACID and verify response shape"""
        token = get_token("admin@customs.ly", "Admin@2026!")
        if not token:
            pytest.skip("Admin login failed")
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{BASE_URL}/api/acid?status=gate_released", headers=headers)
        if r.status_code != 200:
            pytest.skip("Cannot fetch acid requests")
        items = r.json()
        if not items:
            pytest.skip("No gate_released ACIDs found")
        acid_number = items[0].get("acid_number")
        import urllib.parse
        track_r = requests.get(f"{BASE_URL}/api/public/track/{urllib.parse.quote(acid_number, safe='')}")
        assert track_r.status_code == 200, f"Track failed for {acid_number}: {track_r.text}"
        data = track_r.json()
        assert data["status"] == "gate_released"
        assert data["jl38_number"] is not None
        print(f"Found gate_released ACID: {acid_number}, JL38: {data['jl38_number']}")


class TestJL38PDF:
    """GET /api/acid/{id}/jl38-pdf — requires auth"""

    def test_jl38_pdf_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/acid/some_id/jl38-pdf")
        assert r.status_code in [401, 403, 422], f"Expected auth error, got {r.status_code}"

    def test_jl38_pdf_download_for_released(self):
        """Gate officer can download JL38 PDF for a released ACID"""
        token = get_token("gate@customs.ly", "Gate@2026!")
        if not token:
            pytest.skip("Gate login failed")
        headers = {"Authorization": f"Bearer {token}"}
        # Get gate released ACIDs
        r = requests.get(f"{BASE_URL}/api/gate/queue", headers=headers)
        # Queue may be empty (all released), try admin list
        admin_token = get_token("admin@customs.ly", "Admin@2026!")
        if not admin_token:
            pytest.skip("Admin login failed")
        ah = {"Authorization": f"Bearer {admin_token}"}
        ar = requests.get(f"{BASE_URL}/api/acid?status=gate_released", headers=ah)
        if ar.status_code != 200 or not ar.json():
            pytest.skip("No gate_released ACIDs available")
        acid_id = str(ar.json()[0].get("_id") or ar.json()[0].get("id"))
        pdf_r = requests.get(f"{BASE_URL}/api/acid/{acid_id}/jl38-pdf", headers=headers)
        assert pdf_r.status_code == 200, f"PDF download failed: {pdf_r.text}"
        assert pdf_r.headers.get("content-type", "").startswith("application/pdf")
        assert len(pdf_r.content) > 1000, "PDF seems too small"
        print(f"PDF downloaded: {len(pdf_r.content)} bytes")

    def test_jl38_pdf_not_available_for_non_released(self):
        """400 if ACID doesn't have jl38_number yet"""
        token = get_token("admin@customs.ly", "Admin@2026!")
        if not token:
            pytest.skip("Admin login failed")
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{BASE_URL}/api/acid?status=submitted", headers=headers)
        if r.status_code != 200 or not r.json():
            pytest.skip("No submitted ACIDs")
        acid_id = str(r.json()[0].get("_id") or r.json()[0].get("id"))
        pdf_r = requests.get(f"{BASE_URL}/api/acid/{acid_id}/jl38-pdf", headers=headers)
        assert pdf_r.status_code == 400, f"Expected 400, got {pdf_r.status_code}"
        print(f"Correctly blocked non-released ACID")


class TestRegression:
    """Regression: core flows still work"""

    def test_admin_login(self):
        token = get_token("admin@customs.ly", "Admin@2026!")
        assert token is not None, "Admin login failed"

    def test_importer_login(self):
        token = get_token("importer@test.ly", "Test@2024!")
        assert token is not None, "Importer login failed"

    def test_gate_login(self):
        token = get_token("gate@customs.ly", "Gate@2026!")
        assert token is not None, "Gate login failed"

    def test_admin_requests_load(self):
        token = get_token("admin@customs.ly", "Admin@2026!")
        assert token
        r = requests.get(f"{BASE_URL}/api/acid", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        print(f"Admin requests: {len(r.json())} items")

    def test_gate_queue_accessible(self):
        token = get_token("gate@customs.ly", "Gate@2026!")
        assert token
        r = requests.get(f"{BASE_URL}/api/gate/queue", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    def test_release_blocked_if_not_treasury_paid(self):
        """Gate release should return 400 for non-treasury_paid ACID"""
        token = get_token("gate@customs.ly", "Gate@2026!")
        assert token
        headers = {"Authorization": f"Bearer {token}"}
        # Get an approved (not treasury_paid) ACID
        admin_token = get_token("admin@customs.ly", "Admin@2026!")
        ah = {"Authorization": f"Bearer {admin_token}"}
        r = requests.get(f"{BASE_URL}/api/acid?status=approved", headers=ah)
        if r.status_code != 200 or not r.json():
            pytest.skip("No approved ACIDs")
        acid_id = str(r.json()[0].get("_id") or r.json()[0].get("id"))
        release_r = requests.post(f"{BASE_URL}/api/acid/{acid_id}/gate-release", 
                                   json={"notes": "test"}, headers=headers)
        assert release_r.status_code in [400, 403], f"Expected 400/403 for non-treasury_paid, got {release_r.status_code}"
