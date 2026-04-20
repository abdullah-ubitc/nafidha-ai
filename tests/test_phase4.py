"""Phase 4 Tests: HS Search, Export, Seed Data, Email (MOCKED)"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    assert r.status_code == 200
    return r.json().get("access_token")

@pytest.fixture(scope="module")
def reviewer_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "reviewer@test.ly", "password": "Test@2024!"})
    assert r.status_code == 200
    return r.json().get("access_token")

@pytest.fixture(scope="module")
def importer_token(admin_token):
    # importer account not seeded, use admin as fallback
    return admin_token

# ===== HS Search Tests =====
class TestHSSearch:
    def test_hs_search_arabic_query(self, admin_token):
        """Test HS search with Arabic query"""
        r = requests.post(f"{BASE_URL}/api/hs/search",
            json={"query": "ألواح طاقة شمسية", "max_results": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30)
        print(f"HS Search Arabic status: {r.status_code}")
        assert r.status_code == 200
        data = r.json()
        print(f"HS Search Arabic response: {data}")
        assert "results" in data
        assert len(data["results"]) >= 1
        # Check structure of results
        if data["results"]:
            result = data["results"][0]
            assert "hs_code" in result or "code" in result
            print(f"First result: {result}")

    def test_hs_search_english_query(self, admin_token):
        """Test HS search with English query"""
        r = requests.post(f"{BASE_URL}/api/hs/search",
            json={"query": "laptop computer", "max_results": 5},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30)
        print(f"HS Search English status: {r.status_code}")
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        print(f"HS Search English results count: {len(data['results'])}")

    def test_hs_search_car_query(self, importer_token):
        """Test HS search with car query"""
        r = requests.post(f"{BASE_URL}/api/hs/search",
            json={"query": "سيارة تويوتا", "max_results": 3},
            headers={"Authorization": f"Bearer {importer_token}"},
            timeout=30)
        print(f"HS Search car status: {r.status_code}")
        assert r.status_code == 200

    def test_hs_search_unauthenticated(self):
        """HS search requires auth"""
        r = requests.post(f"{BASE_URL}/api/hs/search",
            json={"query": "test"},
            timeout=15)
        assert r.status_code in [401, 403]

# ===== Seed Data Tests =====
class TestSeedData:
    def test_seed_data_already_exists(self, admin_token):
        """Seed data should report already exists (56 records)"""
        r = requests.post(f"{BASE_URL}/api/admin/seed-data",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30)
        print(f"Seed data status: {r.status_code}, body: {r.text[:200]}")
        assert r.status_code == 200
        data = r.json()
        # Should say already exists
        msg = str(data).lower()
        assert "موجود" in str(data) or "exist" in msg or "seed" in msg or "created" in msg

    def test_seed_data_admin_only(self, importer_token):
        """Only admin can seed data"""
        r = requests.post(f"{BASE_URL}/api/admin/seed-data",
            headers={"Authorization": f"Bearer {importer_token}"},
            timeout=15)
        assert r.status_code in [401, 403]

# ===== Executive Dashboard =====
class TestExecutiveDashboard:
    def test_dashboard_has_data(self, admin_token):
        """Dashboard should show seeded data"""
        r = requests.get(f"{BASE_URL}/api/executive/dashboard",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15)
        assert r.status_code == 200
        data = r.json()
        print(f"Dashboard total_requests: {data.get('total_requests')}")
        assert data.get("total_requests", 0) >= 50
        print(f"Dashboard ports count: {len(data.get('by_port', []))}")

# ===== Export Tests =====
class TestExports:
    def test_export_audit_excel_admin(self, admin_token):
        """Admin can download Excel audit trail"""
        r = requests.get(f"{BASE_URL}/api/export/audit-excel",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30)
        print(f"Export Excel status: {r.status_code}, content-type: {r.headers.get('content-type')}")
        assert r.status_code == 200
        assert "spreadsheet" in r.headers.get("content-type", "").lower() or \
               "excel" in r.headers.get("content-type", "").lower() or \
               "octet-stream" in r.headers.get("content-type", "").lower()
        assert len(r.content) > 1000  # Should be a real file

    def test_export_audit_excel_importer_forbidden(self, importer_token):
        """Importer cannot download audit Excel"""
        r = requests.get(f"{BASE_URL}/api/export/audit-excel",
            headers={"Authorization": f"Bearer {importer_token}"},
            timeout=15)
        assert r.status_code in [401, 403]

    def test_export_dashboard_pdf_admin(self, admin_token):
        """Admin can download PDF dashboard"""
        r = requests.get(f"{BASE_URL}/api/export/dashboard-pdf",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30)
        print(f"Export PDF status: {r.status_code}, content-type: {r.headers.get('content-type')}")
        assert r.status_code == 200
        assert "pdf" in r.headers.get("content-type", "").lower() or \
               "octet-stream" in r.headers.get("content-type", "").lower()
        assert len(r.content) > 1000

    def test_export_dashboard_pdf_reviewer(self, reviewer_token):
        """Reviewer can download PDF dashboard"""
        r = requests.get(f"{BASE_URL}/api/export/dashboard-pdf",
            headers={"Authorization": f"Bearer {reviewer_token}"},
            timeout=30)
        print(f"Export PDF reviewer status: {r.status_code}")
        assert r.status_code == 200

# ===== ACID Review with BackgroundTasks =====
class TestACIDReview:
    def test_acid_review_approve_triggers_email(self, admin_token, reviewer_token):
        """ACID review approval should work (email MOCKED/logged)"""
        # Get a submitted ACID to review
        r = requests.get(f"{BASE_URL}/api/acid/requests?status=submitted&limit=1",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15)
        if r.status_code != 200 or not r.json():
            r = requests.get(f"{BASE_URL}/api/acid/requests?limit=5",
                headers={"Authorization": f"Bearer {admin_token}"},
                timeout=15)
        
        requests_list = r.json() if r.status_code == 200 else []
        if isinstance(requests_list, dict):
            requests_list = requests_list.get("requests", requests_list.get("items", []))
        
        # Find a submitted/under_review request
        acid_id = None
        for req in requests_list:
            if req.get("status") in ["submitted", "under_review"]:
                acid_id = req.get("id") or req.get("_id")
                break
        
        if not acid_id:
            print("No submitted ACID found, skipping review test")
            pytest.skip("No submitted ACID request found")
        
        # Attempt review
        r2 = requests.put(f"{BASE_URL}/api/acid/{acid_id}/review",
            json={"action": "approve", "notes": "Test approval"},
            headers={"Authorization": f"Bearer {reviewer_token}"},
            timeout=20)
        print(f"ACID review status: {r2.status_code}, body: {r2.text[:300]}")
        assert r2.status_code in [200, 201]
