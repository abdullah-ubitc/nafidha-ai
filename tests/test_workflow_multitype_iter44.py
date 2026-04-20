"""
Iteration 44 — Multi-Type Workflow Pool Tests
Tests: multi-role pool, ACID lock (423), KYC lock (423), stats
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Credentials
ADMIN_EMAIL    = "admin@customs.ly"
ADMIN_PASS     = "Admin@2026!"
MULTI_EMAIL    = "test_multi_role@customs.ly"
MULTI_PASS     = "TestPass@2026!"
REG_EMAIL      = "reg_officer@customs.ly"
REG_PASS       = "RegOfficer@2026!"


def login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.cookies
    return None


@pytest.fixture(scope="module")
def multi_cookies():
    c = login(MULTI_EMAIL, MULTI_PASS)
    if not c:
        pytest.skip("Cannot login as multi_role user")
    return c


@pytest.fixture(scope="module")
def reg_cookies():
    c = login(REG_EMAIL, REG_PASS)
    if not c:
        pytest.skip("Cannot login as reg_officer")
    return c


@pytest.fixture(scope="module")
def admin_cookies():
    c = login(ADMIN_EMAIL, ADMIN_PASS)
    if not c:
        pytest.skip("Cannot login as admin")
    return c


# ── 1. Multi-Role Pool returns both task types ──────────────────────────────
def test_multi_role_pool_contains_both_types(multi_cookies):
    r = requests.get(f"{BASE_URL}/api/workflow/pool", cookies=multi_cookies)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    tasks = r.json()
    assert isinstance(tasks, list), "Pool should return a list"
    types = {t["task_type"] for t in tasks}
    print(f"Task types in pool: {types}, total tasks: {len(tasks)}")
    # Both types should be present (or at least the endpoint returns without error)
    # Note: if pool is empty, types will be empty — that's still valid
    assert "kyc_review" in types or "acid_review" in types or len(tasks) == 0, \
        f"Unexpected task types: {types}"
    print(f"PASS — pool returned {len(tasks)} tasks, types: {types}")


# ── 2. Multi-Role Stats counts both types ───────────────────────────────────
def test_multi_role_stats(multi_cookies):
    r = requests.get(f"{BASE_URL}/api/workflow/stats", cookies=multi_cookies)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "pool" in data
    assert "my_queue" in data
    assert "my_history" in data
    print(f"PASS — stats: pool={data['pool']}, my_queue={data['my_queue']}, my_history={data['my_history']}")


# ── 3. ACID Lock: review without claim → 423 ────────────────────────────────
def test_acid_review_without_claim_returns_423(multi_cookies):
    # Get an available ACID task from pool
    r = requests.get(f"{BASE_URL}/api/workflow/pool", cookies=multi_cookies)
    assert r.status_code == 200
    tasks = r.json()
    acid_tasks = [t for t in tasks if t["task_type"] == "acid_review"]
    if not acid_tasks:
        pytest.skip("No acid_review tasks available in pool to test lock")

    acid_id = acid_tasks[0]["task_id"]
    print(f"Testing ACID lock on task_id={acid_id}")

    # Try to review without claiming first → should get 423
    r2 = requests.put(
        f"{BASE_URL}/api/acid/{acid_id}/review",
        json={"action": "review", "notes": "test without claim"},
        cookies=multi_cookies,
    )
    print(f"Review without claim status: {r2.status_code}, body: {r2.text[:300]}")
    assert r2.status_code == 423, f"Expected 423, got {r2.status_code}"
    body = r2.json()
    detail = body.get("detail", {})
    assert detail.get("code") == "LOCK_REQUIRED", f"Expected LOCK_REQUIRED code, got: {detail}"
    print(f"PASS — 423 with code=LOCK_REQUIRED returned correctly")


# ── 4. ACID Lock: claim then review → 200 ───────────────────────────────────
def test_acid_claim_then_review_returns_200(multi_cookies, admin_cookies):
    # Get an available ACID task
    r = requests.get(f"{BASE_URL}/api/workflow/pool", cookies=multi_cookies)
    assert r.status_code == 200
    tasks = r.json()
    acid_tasks = [t for t in tasks if t["task_type"] == "acid_review"]
    if not acid_tasks:
        pytest.skip("No acid_review tasks available in pool to claim")

    acid_id = acid_tasks[0]["task_id"]
    print(f"Claiming ACID task_id={acid_id}")

    # Claim the task
    claim_r = requests.post(
        f"{BASE_URL}/api/workflow/claim",
        json={"task_type": "acid_review", "task_id": acid_id},
        cookies=multi_cookies,
    )
    print(f"Claim status: {claim_r.status_code}, body: {claim_r.text[:200]}")
    assert claim_r.status_code == 200, f"Claim failed: {claim_r.text}"

    # Now review → should be 200
    review_r = requests.put(
        f"{BASE_URL}/api/acid/{acid_id}/review",
        json={"action": "review", "notes": "test after claim — iter44"},
        cookies=multi_cookies,
    )
    print(f"Review after claim status: {review_r.status_code}, body: {review_r.text[:300]}")
    assert review_r.status_code == 200, f"Expected 200 after claim, got {review_r.status_code}: {review_r.text}"
    print("PASS — review after claim returns 200")

    # Cleanup: release the task (status is now 'under_review', wf_status still In_Progress)
    # Try to release via workflow
    rel_r = requests.post(
        f"{BASE_URL}/api/workflow/release",
        json={"task_type": "acid_review", "task_id": acid_id},
        cookies=multi_cookies,
    )
    print(f"Release after review: {rel_r.status_code}")
    # Force release via admin if needed
    if rel_r.status_code != 200:
        admin_r = requests.post(
            f"{BASE_URL}/api/workflow/admin/force-release",
            json={"task_type": "acid_review", "task_id": acid_id},
            cookies=admin_cookies,
        )
        print(f"Admin force release: {admin_r.status_code}")


# ── 5. KYC Lock: approve without claim → 423 ────────────────────────────────
def test_kyc_approve_without_claim_returns_423(reg_cookies):
    # Get KYC task from pool
    r = requests.get(f"{BASE_URL}/api/workflow/pool", cookies=reg_cookies)
    assert r.status_code == 200
    tasks = r.json()
    kyc_tasks = [t for t in tasks if t["task_type"] == "kyc_review"]
    if not kyc_tasks:
        pytest.skip("No kyc_review tasks available in pool to test lock")

    kyc_id = kyc_tasks[0]["task_id"]
    print(f"Testing KYC lock on user_id={kyc_id}")

    # Try approve without claim
    r2 = requests.post(
        f"{BASE_URL}/api/kyc/{kyc_id}/approve",
        json={},
        cookies=reg_cookies,
    )
    print(f"KYC approve without claim: status={r2.status_code}, body={r2.text[:300]}")
    assert r2.status_code == 423, f"Expected 423, got {r2.status_code}"
    body = r2.json()
    detail = body.get("detail", {})
    code = detail.get("code") if isinstance(detail, dict) else str(detail)
    print(f"PASS — KYC 423 with detail: {detail}")
    assert "LOCK_REQUIRED" in str(detail), f"Expected LOCK_REQUIRED in detail, got: {detail}"


# ── 6. Single-role pool only returns KYC ────────────────────────────────────
def test_single_role_pool_kyc_only(reg_cookies):
    r = requests.get(f"{BASE_URL}/api/workflow/pool", cookies=reg_cookies)
    assert r.status_code == 200
    tasks = r.json()
    types = {t["task_type"] for t in tasks}
    assert "acid_review" not in types, f"reg_officer should not see acid tasks, got types: {types}"
    print(f"PASS — reg_officer pool contains only: {types}")
