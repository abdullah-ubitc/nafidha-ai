"""
Carrier Multi-Modal Registration Tests — Iteration 46
Tests: carrier_agent registration, transport_modes, partial approval, auto-suspend on stat expiry
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

TS = int(time.time())
CARRIER_EMAIL = f"TEST_carrier_iter46_{TS}@test.ly"
CARRIER_PWD = "TestPass@2026!"

# Officer credentials
OFFICER_EMAIL = "reg_officer@customs.ly"
OFFICER_PWD = "RegOfficer@2026!"


@pytest.fixture(scope="module")
def officer_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": OFFICER_EMAIL, "password": OFFICER_PWD})
    assert r.status_code == 200, f"Officer login failed: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def officer_headers(officer_token):
    return {"Authorization": f"Bearer {officer_token}"}


# ── Test 1: Register carrier_agent with transport_modes ────────────────────────
def test_register_carrier_with_sea_air():
    """Backend POST /api/auth/register accepts carrier_agent with transport_modes=['sea','air']"""
    payload = {
        "email": CARRIER_EMAIL,
        "password": CARRIER_PWD,
        "role": "carrier_agent",
        "name_ar": "وكالة شحن الاختبار",
        "name_en": "Test Freight Agency",
        "entity_type": "company",
        "company_name_ar": "وكالة شحن الاختبار",
        "company_name_en": "Test Freight Agency",
        "commercial_registry_no": "CR-TEST-ITER46",
        "statistical_code": "SC-TEST-46",
        "statistical_expiry_date": "2027-01-01",  # Not expired
        "transport_modes": ["sea", "air"],
        "agency_name_ar": "وكالة شحن الاختبار",
        "agency_name_en": "Test Freight Agency",
        "agency_commercial_reg": "ACR-TEST-46",
        "marine_license_number": "MARINE-LIC-TEST",
        "marine_license_expiry": "2027-06-01",
        "air_operator_license": "AIR-OPS-TEST",
        "air_license_expiry": "2027-08-01",
        "rep_full_name_ar": "مختبر التسجيل",
        "rep_full_name_en": "Test Rep",
        "rep_id_type": "national_id",
        "rep_id_number": "ID-TEST-46",
        "rep_nationality": "ليبي",
        "rep_job_title": "owner",
        "rep_mobile": "218912345678",
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    assert r.status_code == 200, f"Registration failed: {r.text}"
    data = r.json()
    user = data["user"]
    assert user["role"] == "carrier_agent"
    assert user["registration_status"] == "email_unverified"
    assert "sea" in user["transport_modes"]
    assert "air" in user["transport_modes"]
    assert user["marine_license_number"] == "MARINE-LIC-TEST"
    assert user["air_operator_license"] == "AIR-OPS-TEST"
    print(f"PASS: Carrier registered with id={user['_id']}, transport_modes={user['transport_modes']}")
    return user["_id"]


# ── Test 2: Get user ID and verify email ────────────────────────────────────────
@pytest.fixture(scope="module")
def carrier_user_id():
    """Register carrier and get user_id"""
    email = f"TEST_carrier_partial_{TS}@test.ly"
    payload = {
        "email": email,
        "password": CARRIER_PWD,
        "role": "carrier_agent",
        "name_ar": "وكالة الاختبار الجزئي",
        "name_en": "Test Partial Freight Agency",
        "entity_type": "company",
        "company_name_ar": "وكالة الاختبار الجزئي",
        "company_name_en": "Test Partial Freight Agency",
        "commercial_registry_no": "CR-PARTIAL-46",
        "statistical_code": "SC-PARTIAL-46",
        "statistical_expiry_date": "2027-01-01",
        "transport_modes": ["sea", "air", "land"],
        "agency_name_ar": "وكالة الاختبار",
        "agency_name_en": "Test Agency",
        "agency_commercial_reg": "ACR-PARTIAL-46",
        "marine_license_number": "MARINE-PARTIAL",
        "marine_license_expiry": "2027-06-01",
        "air_operator_license": "AIR-PARTIAL",
        "air_license_expiry": "2027-08-01",
        "land_transport_license": "LAND-PARTIAL",
        "land_license_expiry": "2027-10-01",
        "rep_full_name_ar": "مفوض الاختبار",
        "rep_full_name_en": "Test Delegate",
        "rep_id_type": "national_id",
        "rep_id_number": "PARTIAL-ID-46",
        "rep_nationality": "ليبي",
        "rep_job_title": "owner",
        "rep_mobile": "218923456789",
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    assert r.status_code == 200
    user_id = r.json()["user"]["_id"]
    # Verify email to move to pending
    import re
    # Get verify token from DB via admin
    admin_r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    admin_token = admin_r.json()["access_token"]
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}
    user_r = requests.get(f"{BASE_URL}/api/kyc/registrations?status=email_unverified", headers=admin_hdrs)
    users = user_r.json()
    target = next((u for u in users if u["_id"] == user_id), None)
    if target:
        token = target.get("email_verify_token")
        if token:
            requests.get(f"{BASE_URL}/api/auth/verify-email/{token}")
    return user_id


@pytest.fixture(scope="module")
def locked_carrier_id(carrier_user_id, officer_headers):
    """Claim the carrier task so officer can approve"""
    # Claim the task
    r = requests.post(f"{BASE_URL}/api/workflow/claim",
                      json={"task_type": "kyc_review", "task_id": carrier_user_id},
                      headers=officer_headers)
    if r.status_code not in [200, 409]:
        print(f"Claim response: {r.status_code} {r.text}")
    return carrier_user_id


# ── Test 3: Partial approval ────────────────────────────────────────────────────
def test_partial_approval_sea_only(locked_carrier_id, officer_headers):
    """POST /api/kyc/{id}/approve with approved_modes=['sea'] rejected_modes=['air','land'] → partially_approved"""
    payload = {
        "approved_modes": ["sea"],
        "rejected_modes": ["air", "land"],
        "partial_rejection_reason": "الترخيص الجوي والبري غير مستوفين للمتطلبات"
    }
    r = requests.post(f"{BASE_URL}/api/kyc/{locked_carrier_id}/approve",
                      json=payload, headers=officer_headers)
    assert r.status_code == 200, f"Partial approval failed: {r.text}"
    data = r.json()
    assert data["status"] == "partially_approved", f"Expected partially_approved, got: {data['status']}"
    assert data["account_status"] == "active"
    print(f"PASS: Partial approval → status={data['status']}, account_status={data['account_status']}")


# ── Test 4: Auto-suspend on expired statistical card ───────────────────────────
def test_auto_suspend_on_expired_statistical(officer_headers):
    """Carrier with expired statistical_expiry_date gets account_status=suspended on approval"""
    email = f"TEST_carrier_suspended_{TS}@test.ly"
    # Register with expired stat date
    payload = {
        "email": email,
        "password": CARRIER_PWD,
        "role": "carrier_agent",
        "name_ar": "وكالة مجمَّدة",
        "name_en": "Suspended Test Agency",
        "entity_type": "company",
        "company_name_ar": "وكالة مجمَّدة",
        "company_name_en": "Suspended Test Agency",
        "commercial_registry_no": "CR-SUSP-46",
        "statistical_code": "SC-SUSP-46",
        "statistical_expiry_date": "2020-01-01",  # expired!
        "transport_modes": ["sea"],
        "agency_name_ar": "وكالة مجمَّدة",
        "agency_name_en": "Suspended Agency",
        "agency_commercial_reg": "ACR-SUSP-46",
        "marine_license_number": "MARINE-SUSP",
        "marine_license_expiry": "2027-01-01",
        "rep_full_name_ar": "مفوض مجمَّد",
        "rep_full_name_en": "Suspended Rep",
        "rep_id_type": "national_id",
        "rep_id_number": "SUSP-ID-46",
        "rep_nationality": "ليبي",
        "rep_job_title": "owner",
        "rep_mobile": "218934567890",
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    assert r.status_code == 200
    user_id = r.json()["user"]["_id"]

    # Verify email
    admin_r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    admin_token = admin_r.json()["access_token"]
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}
    user_r = requests.get(f"{BASE_URL}/api/kyc/registrations?status=email_unverified", headers=admin_hdrs)
    users = user_r.json()
    target = next((u for u in users if u["_id"] == user_id), None)
    if target:
        tok = target.get("email_verify_token")
        if tok:
            requests.get(f"{BASE_URL}/api/auth/verify-email/{tok}")

    # Claim
    requests.post(f"{BASE_URL}/api/workflow/claim",
                  json={"task_type": "kyc_review", "task_id": user_id},
                  headers=officer_headers)

    # Approve fully
    r2 = requests.post(f"{BASE_URL}/api/kyc/{user_id}/approve",
                       json={"approved_modes": ["sea"], "rejected_modes": []},
                       headers=officer_headers)
    assert r2.status_code == 200, f"Approval failed: {r2.text}"
    data = r2.json()
    assert data["account_status"] == "suspended", f"Expected suspended, got: {data['account_status']}"
    assert "تجميد" in data["message"] or "suspended" in data["message"].lower() or "تجميد" in data.get("message","")
    print(f"PASS: Auto-suspend on expired stat → account_status={data['account_status']}")


# ── Test 5: fully approved (all modes) ─────────────────────────────────────────
def test_full_approval_all_modes(officer_headers):
    """POST /api/kyc/{id}/approve with approved_modes=['sea','air'] rejected_modes=[] → approved"""
    email = f"TEST_carrier_full_approve_{TS}@test.ly"
    payload = {
        "email": email,
        "password": CARRIER_PWD,
        "role": "carrier_agent",
        "name_ar": "وكالة مقبولة كلياً",
        "name_en": "Fully Approved Agency",
        "entity_type": "company",
        "company_name_ar": "وكالة مقبولة كلياً",
        "company_name_en": "Fully Approved Agency",
        "commercial_registry_no": "CR-FULL-46",
        "statistical_code": "SC-FULL-46",
        "statistical_expiry_date": "2028-01-01",
        "transport_modes": ["sea", "air"],
        "agency_name_ar": "وكالة مقبولة",
        "agency_name_en": "Full Agency",
        "agency_commercial_reg": "ACR-FULL-46",
        "marine_license_number": "MARINE-FULL",
        "marine_license_expiry": "2028-06-01",
        "air_operator_license": "AIR-FULL",
        "air_license_expiry": "2028-08-01",
        "rep_full_name_ar": "مفوض مقبول",
        "rep_full_name_en": "Full Rep",
        "rep_id_type": "national_id",
        "rep_id_number": "FULL-ID-46",
        "rep_nationality": "ليبي",
        "rep_job_title": "owner",
        "rep_mobile": "218945678901",
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    assert r.status_code == 200
    user_id = r.json()["user"]["_id"]

    # Verify email
    admin_r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    admin_token = admin_r.json()["access_token"]
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}
    user_r = requests.get(f"{BASE_URL}/api/kyc/registrations?status=email_unverified", headers=admin_hdrs)
    users = user_r.json()
    target = next((u for u in users if u["_id"] == user_id), None)
    if target:
        tok = target.get("email_verify_token")
        if tok:
            requests.get(f"{BASE_URL}/api/auth/verify-email/{tok}")

    # Claim
    requests.post(f"{BASE_URL}/api/workflow/claim",
                  json={"task_type": "kyc_review", "task_id": user_id},
                  headers=officer_headers)

    # Approve fully (no rejected modes)
    r2 = requests.post(f"{BASE_URL}/api/kyc/{user_id}/approve",
                       json={"approved_modes": ["sea", "air"], "rejected_modes": []},
                       headers=officer_headers)
    assert r2.status_code == 200, f"Full approval failed: {r2.text}"
    data = r2.json()
    assert data["status"] == "approved", f"Expected approved, got: {data['status']}"
    assert data["account_status"] == "active"
    print(f"PASS: Full approval → status={data['status']}")


# ── Test 6: partially_approved user can login ────────────────────────────────
def test_partially_approved_user_can_login(locked_carrier_id):
    """partially_approved user should be able to log in"""
    # The locked_carrier_id fixture was partially approved in test_partial_approval_sea_only
    # We need to check their email
    admin_r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    admin_token = admin_r.json()["access_token"]
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}
    
    # Find the user by ID
    r = requests.get(f"{BASE_URL}/api/kyc/registrations?status=all", headers=admin_hdrs)
    users = r.json()
    target = next((u for u in users if u.get("_id") == locked_carrier_id), None)
    if not target:
        pytest.skip("Could not find partially approved user")
    
    # Partially approved users should be able to login (status != email_unverified or rejected)
    email = target["email"]
    lr = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": CARRIER_PWD})
    assert lr.status_code == 200, f"Login failed for partially_approved user: {lr.text}"
    print(f"PASS: Partially approved user can login")


# ── Test 7: workflow pool shows transport_modes in KYC task ──────────────────
def test_workflow_kyc_task_has_transport_modes(officer_headers):
    """GET /api/workflow/pool returns transport_modes for carrier kyc tasks"""
    r = requests.get(f"{BASE_URL}/api/workflow/pool", headers=officer_headers)
    assert r.status_code == 200
    # Check if any carrier tasks have transport_modes field
    tasks = r.json()
    carrier_tasks = [t for t in tasks if t.get("meta_role") == "carrier_agent"]
    if carrier_tasks:
        t = carrier_tasks[0]
        assert "transport_modes" in t, "transport_modes field missing from KYC task"
        print(f"PASS: carrier KYC task has transport_modes={t.get('transport_modes')}")
    else:
        print("INFO: No carrier tasks in pool currently")


# ── Test 8: partial approval requires at least 1 approved mode ───────────────
def test_partial_approval_requires_at_least_one_mode(officer_headers):
    """POST /api/kyc/{id}/approve with approved_modes=[] rejected_modes=['sea'] → 400"""
    # Register a quick carrier
    email = f"TEST_carrier_no_mode_{TS}@test.ly"
    payload = {
        "email": email, "password": CARRIER_PWD,
        "role": "carrier_agent",
        "name_ar": "وكالة بدون وسيط", "name_en": "No Mode Agency",
        "entity_type": "company",
        "company_name_ar": "وكالة بدون وسيط", "company_name_en": "No Mode Agency",
        "commercial_registry_no": "CR-NOMODE-46",
        "statistical_code": "SC-NOMODE", "statistical_expiry_date": "2028-01-01",
        "transport_modes": ["sea"],
        "agency_name_ar": "وكالة", "agency_name_en": "Agency",
        "agency_commercial_reg": "ACR-NOMODE",
        "marine_license_number": "MARINE-NOMODE", "marine_license_expiry": "2028-01-01",
        "rep_full_name_ar": "مفوض", "rep_full_name_en": "Rep",
        "rep_id_type": "national_id", "rep_id_number": "NOMODE-ID",
        "rep_nationality": "ليبي", "rep_job_title": "owner",
        "rep_mobile": "218956789012",
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    assert r.status_code == 200
    user_id = r.json()["user"]["_id"]

    # Verify + claim
    admin_r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    admin_token = admin_r.json()["access_token"]
    admin_hdrs = {"Authorization": f"Bearer {admin_token}"}
    user_r = requests.get(f"{BASE_URL}/api/kyc/registrations?status=email_unverified", headers=admin_hdrs)
    target = next((u for u in user_r.json() if u["_id"] == user_id), None)
    if target and target.get("email_verify_token"):
        requests.get(f"{BASE_URL}/api/auth/verify-email/{target['email_verify_token']}")

    requests.post(f"{BASE_URL}/api/workflow/claim",
                  json={"task_type": "kyc_review", "task_id": user_id},
                  headers=officer_headers)

    # Try to approve with no approved_modes
    r2 = requests.post(f"{BASE_URL}/api/kyc/{user_id}/approve",
                       json={"approved_modes": [], "rejected_modes": ["sea"]},
                       headers=officer_headers)
    assert r2.status_code == 400, f"Expected 400, got: {r2.status_code} {r2.text}"
    print(f"PASS: Empty approved_modes rejected with 400")
