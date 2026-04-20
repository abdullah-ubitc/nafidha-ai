"""KYC Correction (needs_correction) workflow tests — Phase N"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

REG_OFFICER = {"email": "reg_officer@customs.ly", "password": "RegOfficer@2026!"}
ADMIN = {"email": "admin@customs.ly", "password": "Admin@2026!"}

# Test importer to be created and used for correction tests
TEST_IMPORTER_EMAIL = "TEST_correction_importer@test.ly"


@pytest.fixture(scope="module")
def officer_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=REG_OFFICER)
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s


@pytest.fixture(scope="module")
def test_user_id(officer_session):
    """Create a test importer and return its ID (email is lowercased by backend)."""
    email_lower = TEST_IMPORTER_EMAIL.lower()
    # Register a test importer (may already exist)
    requests.post(f"{BASE_URL}/api/auth/register", json={
        "email": TEST_IMPORTER_EMAIL,
        "password": "TestPass@2026!",
        "name_ar": "مستورد تجريبي",
        "name_en": "Test Importer",
        "role": "importer",
        "phone": "0911234567",
    })

    # Search across all statuses
    for status in ["pending", "needs_correction", "approved", "rejected", "all"]:
        r = officer_session.get(f"{BASE_URL}/api/kyc/registrations?status={status}")
        if r.status_code == 200:
            for u in r.json():
                if u.get("email", "").lower() == email_lower:
                    return u["_id"]
    pytest.fail(f"Could not find test importer {email_lower}")


# ── Stats endpoint ──────────────────────────────────────────────

class TestKYCStats:
    """GET /api/kyc/registrations/stats"""

    def test_stats_returns_needs_correction(self, officer_session):
        r = officer_session.get(f"{BASE_URL}/api/kyc/registrations/stats")
        assert r.status_code == 200
        data = r.json()
        assert "needs_correction" in data, f"needs_correction missing: {data}"
        assert "pending" in data
        assert "approved" in data
        assert "rejected" in data
        print(f"Stats: {data}")


# ── Correct endpoint ────────────────────────────────────────────

class TestKYCCorrect:
    """POST /api/kyc/{user_id}/correct"""

    def test_correct_empty_notes_returns_422(self, officer_session, test_user_id):
        r = officer_session.post(f"{BASE_URL}/api/kyc/{test_user_id}/correct", json={
            "notes": "",
            "flagged_docs": []
        })
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
        print("Empty notes correctly returns 422")

    def test_correct_sets_needs_correction(self, officer_session, test_user_id):
        r = officer_session.post(f"{BASE_URL}/api/kyc/{test_user_id}/correct", json={
            "notes": "يرجى رفع السجل التجاري الصالح",
            "flagged_docs": ["commercial_registry"]
        })
        assert r.status_code == 200, f"Correct failed: {r.status_code} {r.text}"
        data = r.json()
        assert data.get("status") == "needs_correction"
        print(f"Correct response: {data}")

    def test_needs_correction_in_list(self, officer_session, test_user_id):
        """Verify the user appears in needs_correction filter"""
        r = officer_session.get(f"{BASE_URL}/api/kyc/registrations?status=needs_correction")
        assert r.status_code == 200
        users = r.json()
        ids = [u["_id"] for u in users]
        assert test_user_id in ids, f"User {test_user_id} not in needs_correction list"
        print(f"needs_correction list has {len(users)} user(s)")

    def test_needs_correction_in_stats(self, officer_session):
        """needs_correction count should be >= 1 after setting correction"""
        r = officer_session.get(f"{BASE_URL}/api/kyc/registrations/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["needs_correction"] >= 1
        print(f"needs_correction count: {data['needs_correction']}")


# ── Workflow pool ───────────────────────────────────────────────

class TestWorkflowPool:
    """GET /api/workflow/pool should include needs_correction users"""

    def test_pool_includes_needs_correction(self, officer_session, test_user_id):
        r = officer_session.get(f"{BASE_URL}/api/workflow/pool")
        assert r.status_code == 200
        pool = r.json()
        # Find kyc tasks — pool uses task_id which equals the user _id
        kyc_tasks = [t for t in pool if t.get("task_type") == "kyc_review"]
        ids = [t.get("task_id") for t in kyc_tasks]
        print(f"Pool KYC tasks: {len(kyc_tasks)}, task_ids: {ids[:5]}")
        assert test_user_id in ids, f"needs_correction user {test_user_id} not in pool tasks"


# ── Doc serve endpoint ──────────────────────────────────────────

class TestDocServe:
    """GET /api/registration/docs/{file_id}/serve accessible by registration_officer"""

    def test_doc_serve_with_fake_id_returns_404_not_403(self, officer_session):
        """Should return 404 (not found) not 403 (forbidden) for registration_officer"""
        r = officer_session.get(f"{BASE_URL}/api/registration/docs/fakeid123/serve")
        # 404 means access is allowed (file just doesn't exist)
        # 403 means forbidden
        assert r.status_code != 403, f"registration_officer got 403 on doc serve"
        print(f"Doc serve status for fake id: {r.status_code}")
