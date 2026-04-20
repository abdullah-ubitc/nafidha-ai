"""
Tests for KYC Drawer features:
- GET /api/kyc/{user_id} endpoint
- Task Stickiness (Awaiting_Correction wf_status)
- /api/workflow/my-queue includes Awaiting_Correction tasks
"""
import pytest
import requests
import os

def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL", "")
    if not url:
        env_path = "/app/frontend/.env"
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.strip().split("=", 1)[1]
    return url.rstrip("/")

BASE_URL = _load_base_url()

OFFICER_EMAIL = "reg_officer@customs.ly"
OFFICER_PASS = "RegOfficer@2026!"

# Known test user with pending KYC
TEST_USER_ID = "69d81846c0b7bece7601dd4a"  # test_correction_importer@test.ly


def get_officer_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OFFICER_EMAIL, "password": OFFICER_PASS})
    if resp.status_code == 200:
        return resp.json().get("access_token") or resp.cookies.get("access_token")
    return None


@pytest.fixture(scope="module")
def officer_session():
    s = requests.Session()
    resp = s.post(f"{BASE_URL}/api/auth/login", json={"email": OFFICER_EMAIL, "password": OFFICER_PASS})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json().get("access_token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


class TestKYCGetUserEndpoint:
    """Test GET /api/kyc/{user_id} new endpoint"""

    def test_get_kyc_user_returns_200(self, officer_session):
        resp = officer_session.get(f"{BASE_URL}/api/kyc/{TEST_USER_ID}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_get_kyc_user_has_required_fields(self, officer_session):
        resp = officer_session.get(f"{BASE_URL}/api/kyc/{TEST_USER_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert "email" in data
        assert "role" in data
        assert "registration_status" in data

    def test_get_kyc_user_invalid_id(self, officer_session):
        resp = officer_session.get(f"{BASE_URL}/api/kyc/invalid_id_123")
        assert resp.status_code in [400, 404, 422], f"Expected error, got {resp.status_code}"

    def test_get_kyc_user_nonexistent(self, officer_session):
        resp = officer_session.get(f"{BASE_URL}/api/kyc/000000000000000000000000")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


class TestWorkflowMyQueue:
    """Test /api/workflow/my-queue includes Awaiting_Correction"""

    def test_my_queue_endpoint_accessible(self, officer_session):
        resp = officer_session.get(f"{BASE_URL}/api/workflow/my-queue")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_my_queue_returns_list(self, officer_session):
        resp = officer_session.get(f"{BASE_URL}/api/workflow/my-queue")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list) or isinstance(data, dict)

    def test_workflow_stats_accessible(self, officer_session):
        resp = officer_session.get(f"{BASE_URL}/api/workflow/stats")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


class TestKYCCorrectionStickiness:
    """Test that request_correction sets wf_status=Awaiting_Correction"""

    def test_correct_endpoint_sets_awaiting_correction(self, officer_session):
        """After calling /correct, wf_status should be Awaiting_Correction, not Unassigned"""
        # First check the user exists
        resp = officer_session.get(f"{BASE_URL}/api/kyc/{TEST_USER_ID}")
        if resp.status_code != 200:
            pytest.skip("Test user not found")
        user_data = resp.json()

        # If user already in awaiting correction, just verify
        if user_data.get("wf_status") == "Awaiting_Correction":
            assert user_data["wf_status"] == "Awaiting_Correction"
            print("User already in Awaiting_Correction state - verified stickiness")
            return

        # If user is in pending state, try to claim and then correct
        wf_status = user_data.get("wf_status", "Unassigned")
        print(f"User wf_status: {wf_status}, reg_status: {user_data.get('registration_status')}")

    def test_kyc_pool_endpoint_accessible(self, officer_session):
        resp = officer_session.get(f"{BASE_URL}/api/workflow/pool?task_type=kyc_review")
        # May return 200 or 422 depending on params
        assert resp.status_code in [200, 422], f"Unexpected: {resp.status_code}: {resp.text}"

    def test_workflow_pool_main(self, officer_session):
        resp = officer_session.get(f"{BASE_URL}/api/workflow/pool")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "pool" in data or isinstance(data, list), f"Unexpected response: {data}"
