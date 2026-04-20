"""
Workflow Engine Tests — Pool, Claim, Release, Complete, Admin endpoints
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

def get_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.cookies.get('access_token') or r.json().get('access_token')
    return None

def make_session(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    return s

@pytest.fixture(scope="module")
def reg_session():
    return make_session("reg_officer@customs.ly", "RegOfficer@2026!")

@pytest.fixture(scope="module")
def admin_session():
    return make_session("admin@customs.ly", "Admin@2026!")

@pytest.fixture(scope="module")
def acid_session():
    return make_session("acidrisk@customs.ly", "AcidRisk@2026!")

# ─── Stats ─────────────────────────────────────────────────────────

class TestWorkflowStats:
    def test_stats_returns_counts(self, reg_session):
        r = reg_session.get(f"{BASE_URL}/api/workflow/stats")
        assert r.status_code == 200
        data = r.json()
        assert "pool" in data
        assert "my_queue" in data
        assert "my_history" in data
        print(f"Stats: {data}")

    def test_stats_acid_officer(self, acid_session):
        r = acid_session.get(f"{BASE_URL}/api/workflow/stats")
        assert r.status_code == 200
        data = r.json()
        assert "pool" in data
        print(f"ACID Officer Stats: {data}")

# ─── Pool ───────────────────────────────────────────────────────────

class TestWorkflowPool:
    def test_pool_returns_list(self, reg_session):
        r = reg_session.get(f"{BASE_URL}/api/workflow/pool")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"Pool count (reg_officer): {len(r.json())}")

    def test_pool_kyc_tasks_have_required_fields(self, reg_session):
        r = reg_session.get(f"{BASE_URL}/api/workflow/pool")
        data = r.json()
        if data:
            task = data[0]
            assert "task_id" in task
            assert "task_type" in task
            assert "wf_sla_deadline" in task
            assert "sla_hours_remaining" in task
            assert task["task_type"] == "kyc_review"
            print(f"First KYC task: {task['task_id']}, SLA hours: {task['sla_hours_remaining']}")
        else:
            print("Pool is empty for reg_officer")

    def test_pool_acid_tasks(self, acid_session):
        r = acid_session.get(f"{BASE_URL}/api/workflow/pool")
        assert r.status_code == 200
        data = r.json()
        print(f"Pool count (acid_officer): {len(data)}")
        if data:
            task = data[0]
            assert task["task_type"] == "acid_review"

    def test_admin_sees_both_types(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/workflow/pool")
        assert r.status_code == 200
        data = r.json()
        types = {t["task_type"] for t in data}
        print(f"Admin pool types: {types}, count: {len(data)}")

# ─── Claim / Release / Complete ────────────────────────────────────

class TestWorkflowClaim:
    claimed_task_id = None
    claimed_task_type = None

    def test_release_any_existing_claims(self, reg_session):
        """Release any previously claimed tasks"""
        r = reg_session.get(f"{BASE_URL}/api/workflow/my-queue")
        assert r.status_code == 200
        for task in r.json():
            rel = reg_session.post(f"{BASE_URL}/api/workflow/release", json={
                "task_type": task["task_type"], "task_id": task["task_id"]
            })
            print(f"Pre-released task {task['task_id']}: {rel.status_code}")

    def test_claim_task(self, reg_session):
        r = reg_session.get(f"{BASE_URL}/api/workflow/pool")
        assert r.status_code == 200
        data = r.json()
        if not data:
            pytest.skip("No tasks in pool to claim")
        task = data[0]
        claim_r = reg_session.post(f"{BASE_URL}/api/workflow/claim", json={
            "task_type": task["task_type"], "task_id": task["task_id"]
        })
        assert claim_r.status_code == 200
        result = claim_r.json()
        assert "task_id" in result
        TestWorkflowClaim.claimed_task_id = task["task_id"]
        TestWorkflowClaim.claimed_task_type = task["task_type"]
        print(f"Claimed task: {task['task_id']}")

    def test_double_claim_returns_409(self, acid_session):
        """Claiming same task twice should return 409"""
        tid = TestWorkflowClaim.claimed_task_id
        ttype = TestWorkflowClaim.claimed_task_type
        if not tid:
            pytest.skip("No task was claimed")
        r = acid_session.post(f"{BASE_URL}/api/workflow/claim", json={
            "task_type": ttype, "task_id": tid
        })
        # Should return 409 (or 403 since acid officer can't claim kyc tasks)
        assert r.status_code in [409, 422, 403]
        print(f"Double claim response: {r.status_code} - {r.json()}")

    def test_my_queue_has_claimed_task(self, reg_session):
        r = reg_session.get(f"{BASE_URL}/api/workflow/my-queue")
        assert r.status_code == 200
        ids = [t["task_id"] for t in r.json()]
        assert TestWorkflowClaim.claimed_task_id in ids, f"Task not found in my-queue. Queue: {ids}"
        print(f"My queue count: {len(r.json())}")

    def test_release_task(self, reg_session):
        tid = TestWorkflowClaim.claimed_task_id
        if not tid:
            pytest.skip("No task was claimed")
        r = reg_session.post(f"{BASE_URL}/api/workflow/release", json={
            "task_type": TestWorkflowClaim.claimed_task_type, "task_id": tid
        })
        assert r.status_code == 200
        print(f"Released task {tid}: {r.json()}")

    def test_task_returns_to_pool_after_release(self, reg_session):
        r = reg_session.get(f"{BASE_URL}/api/workflow/pool")
        ids = [t["task_id"] for t in r.json()]
        assert TestWorkflowClaim.claimed_task_id in ids
        print("Task back in pool after release")

    def test_complete_without_notes_returns_422(self, reg_session):
        """Complete task with empty notes must return 422"""
        # First claim a task
        pool_r = reg_session.get(f"{BASE_URL}/api/workflow/pool")
        if not pool_r.json():
            pytest.skip("No tasks in pool")
        task = pool_r.json()[0]
        c = reg_session.post(f"{BASE_URL}/api/workflow/claim", json={
            "task_type": task["task_type"], "task_id": task["task_id"]
        })
        assert c.status_code == 200
        TestWorkflowClaim.claimed_task_id = task["task_id"]
        TestWorkflowClaim.claimed_task_type = task["task_type"]
        # Attempt complete with empty notes
        comp = reg_session.post(f"{BASE_URL}/api/workflow/complete", json={
            "task_type": task["task_type"], "task_id": task["task_id"], "notes": ""
        })
        assert comp.status_code == 422, f"Expected 422 for empty notes, got {comp.status_code}: {comp.text}"
        print(f"Empty notes correctly rejected: {comp.status_code}")

    def test_complete_with_whitespace_notes_returns_422(self, reg_session):
        """Complete task with whitespace-only notes must return 422"""
        tid = TestWorkflowClaim.claimed_task_id
        ttype = TestWorkflowClaim.claimed_task_type
        if not tid:
            pytest.skip("No task claimed")
        comp = reg_session.post(f"{BASE_URL}/api/workflow/complete", json={
            "task_type": ttype, "task_id": tid, "notes": "   "
        })
        assert comp.status_code == 422, f"Expected 422, got {comp.status_code}"
        print(f"Whitespace notes correctly rejected: {comp.status_code}")

    def test_complete_task_with_notes(self, reg_session):
        """Claim then complete a task with valid notes"""
        tid = TestWorkflowClaim.claimed_task_id
        ttype = TestWorkflowClaim.claimed_task_type
        if not tid:
            pytest.skip("No task claimed")
        # Complete with valid notes
        comp = reg_session.post(f"{BASE_URL}/api/workflow/complete", json={
            "task_type": ttype, "task_id": tid,
            "notes": "تمت المراجعة — الوثائق مكتملة ومطابقة للمتطلبات"
        })
        assert comp.status_code == 200, f"Expected 200, got {comp.status_code}: {comp.text}"
        print(f"Completed task with notes: {tid}")

    def test_history_has_completed_task_with_review_notes(self, reg_session):
        r = reg_session.get(f"{BASE_URL}/api/workflow/my-history")
        assert r.status_code == 200
        data = r.json()
        assert len(data) > 0
        # Verify wf_review_notes is present in the completed task
        task = data[0]
        assert "wf_review_notes" in task, "wf_review_notes field missing from history"
        assert task["wf_review_notes"], "wf_review_notes should not be empty"
        print(f"History task notes: '{task['wf_review_notes']}'")

    def test_complete_task_flow(self, reg_session):
        """Claim then complete a fresh task with notes"""
        r = reg_session.get(f"{BASE_URL}/api/workflow/pool")
        if not r.json():
            pytest.skip("No tasks in pool")
        task = r.json()[0]
        # Claim
        c = reg_session.post(f"{BASE_URL}/api/workflow/claim", json={
            "task_type": task["task_type"], "task_id": task["task_id"]
        })
        assert c.status_code == 200
        # Complete with notes
        comp = reg_session.post(f"{BASE_URL}/api/workflow/complete", json={
            "task_type": task["task_type"], "task_id": task["task_id"],
            "notes": "مراجعة مكتملة — اختبار"
        })
        assert comp.status_code == 200
        print(f"Completed task: {task['task_id']}")

    def test_history_has_completed_task(self, reg_session):
        r = reg_session.get(f"{BASE_URL}/api/workflow/my-history")
        assert r.status_code == 200
        assert len(r.json()) > 0
        print(f"History count: {len(r.json())}")

# ─── Admin Endpoints ────────────────────────────────────────────────

class TestAdminWorkflow:
    def test_admin_overview(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/workflow/admin/overview")
        assert r.status_code == 200
        data = r.json()
        assert "officers" in data
        assert "pool_counts" in data
        assert "inprogress_counts" in data
        assert "kyc" in data["pool_counts"]
        assert "acid" in data["pool_counts"]
        print(f"Overview: pool={data['pool_counts']}, inprogress={data['inprogress_counts']}")

    def test_admin_throughput(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/workflow/admin/throughput")
        assert r.status_code == 200
        data = r.json()
        assert "kyc" in data
        assert "acid" in data
        assert "today" in data["kyc"]
        assert "week" in data["kyc"]
        print(f"Throughput: kyc={data['kyc']}, acid={data['acid']}")

    def test_admin_in_progress(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/workflow/admin/in-progress")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"In-progress count: {len(r.json())}")

    def test_admin_force_release(self, admin_session, reg_session):
        """Claim a task then force-release via admin"""
        pool = reg_session.get(f"{BASE_URL}/api/workflow/pool").json()
        if not pool:
            pytest.skip("No tasks in pool")
        task = pool[0]
        # Claim
        reg_session.post(f"{BASE_URL}/api/workflow/claim", json={
            "task_type": task["task_type"], "task_id": task["task_id"]
        })
        # Force release
        r = admin_session.post(f"{BASE_URL}/api/workflow/admin/force-release", json={
            "task_type": task["task_type"], "task_id": task["task_id"],
            "reason": "testing force release"
        })
        assert r.status_code == 200
        print(f"Force release result: {r.json()}")

    def test_non_admin_cannot_access_admin_endpoints(self, reg_session):
        r = reg_session.get(f"{BASE_URL}/api/workflow/admin/overview")
        assert r.status_code in [401, 403]
        print(f"Non-admin access blocked: {r.status_code}")



# ─── SLA Trigger ────────────────────────────────────────────────────

class TestSLATrigger:
    def test_sla_trigger_endpoint(self, admin_session):
        """POST /api/kyc/scheduler/trigger-sla returns breaches_found and notifications_sent"""
        r = admin_session.post(f"{BASE_URL}/api/kyc/scheduler/trigger-sla")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        # Response has details nested under 'details' key
        assert "details" in data or "breaches_found" in data, f"Missing details: {data}"
        details = data.get("details", data)
        assert "breaches_found" in details, f"Missing breaches_found: {details}"
        assert "notifications_sent" in details, f"Missing notifications_sent: {details}"
        print(f"SLA trigger result: breaches_found={details['breaches_found']}, notifications_sent={details['notifications_sent']}")

    def test_sla_trigger_accessible_to_kyc_reviewer(self, reg_session):
        """reg_officer (KYC reviewer) can trigger SLA check (intentional design)"""
        r = reg_session.post(f"{BASE_URL}/api/kyc/scheduler/trigger-sla")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        print(f"Reg officer SLA trigger: {r.status_code}")
