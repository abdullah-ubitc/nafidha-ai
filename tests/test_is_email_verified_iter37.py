"""
Iteration 37: Test is_email_verified field in GET /api/auth/me
QA Mission: Verify 30-second wait keeps status=email_unverified, is_email_verified=false
"""
import pytest
import requests
import time
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def registered_importer():
    """Register a fresh importer, return user data + token"""
    import random
    email = f"test_iter37_{random.randint(1000,9999)}@test.ly"
    payload = {
        "email": email,
        "password": "Test@1234!",
        "full_name": "Test Importer Iter37",
        "name_ar": "مستورد تجريبي",
        "name_en": "Test Importer Iter37",
        "role": "importer",
        "company_name": "Test Co",
        "phone": "0911234567"
    }
    resp = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    assert resp.status_code in (200, 201), f"Registration failed: {resp.text}"
    data = resp.json()
    token = data.get("access_token")
    user = data.get("user")
    return {"token": token, "user": user, "email": email}


def get_me(token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{BASE_URL}/api/auth/me", headers=headers)
    return resp


# ── Test 1: is_email_verified field exists in /me response ────────────
def test_is_email_verified_field_exists(registered_importer):
    token = registered_importer["token"]
    resp = get_me(token)
    assert resp.status_code == 200, f"/me failed: {resp.text}"
    data = resp.json()
    assert "is_email_verified" in data, "is_email_verified field missing from /me response"
    print(f"PASS: is_email_verified field present = {data['is_email_verified']}")


# ── Test 2: is_email_verified is false immediately after registration ──
def test_is_email_verified_false_after_registration(registered_importer):
    token = registered_importer["token"]
    resp = get_me(token)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_email_verified"] == False, \
        f"Expected is_email_verified=False, got {data['is_email_verified']}"
    print(f"PASS: is_email_verified=False immediately after registration")


# ── Test 3: registration_status is email_unverified after registration ─
def test_registration_status_email_unverified_after_registration(registered_importer):
    token = registered_importer["token"]
    resp = get_me(token)
    assert resp.status_code == 200
    data = resp.json()
    assert data["registration_status"] == "email_unverified", \
        f"Expected email_unverified, got {data['registration_status']}"
    print(f"PASS: registration_status=email_unverified after registration")


# ── Test 4: QA MISSION — 30s wait, status must NOT change ─────────────
def test_30_second_wait_status_remains_email_unverified(registered_importer):
    token = registered_importer["token"]
    
    # Check immediately
    resp_before = get_me(token)
    assert resp_before.status_code == 200
    data_before = resp_before.json()
    assert data_before["registration_status"] == "email_unverified"
    assert data_before["is_email_verified"] == False
    print(f"T=0s: status={data_before['registration_status']}, is_email_verified={data_before['is_email_verified']}")
    
    # Wait 30 seconds
    print("Waiting 30 seconds...")
    time.sleep(30)
    
    # Check after 30s
    resp_after = get_me(token)
    assert resp_after.status_code == 200
    data_after = resp_after.json()
    
    assert data_after["registration_status"] == "email_unverified", \
        f"FAIL: Status changed after 30s! Got: {data_after['registration_status']}"
    assert data_after["is_email_verified"] == False, \
        f"FAIL: is_email_verified changed after 30s! Got: {data_after['is_email_verified']}"
    
    print(f"T=30s: status={data_after['registration_status']}, is_email_verified={data_after['is_email_verified']}")
    print("PASS: Status remained email_unverified for 30 seconds")


# ── Test 5: Regression — approved broker login + /me ──────────────────
def test_approved_broker_me_response():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "broker@customs.ly",
        "password": "Broker@2026!"
    })
    assert resp.status_code == 200, f"Broker login failed: {resp.text}"
    # get token from cookie or body
    token = resp.json().get("access_token")
    cookies = resp.cookies
    
    if token:
        me_resp = requests.get(f"{BASE_URL}/api/auth/me",
                               headers={"Authorization": f"Bearer {token}"})
    else:
        me_resp = requests.get(f"{BASE_URL}/api/auth/me", cookies=cookies)
    
    assert me_resp.status_code == 200, f"/me for broker failed: {me_resp.text}"
    data = me_resp.json()
    assert "is_email_verified" in data, "is_email_verified missing for broker"
    assert data["registration_status"] == "approved", \
        f"Expected approved, got {data['registration_status']}"
    print(f"PASS: Broker /me: is_email_verified={data['is_email_verified']}, status={data['registration_status']}")


# ── Test 6: email_verified_at field serialized correctly ──────────────
def test_email_verified_at_serialized(registered_importer):
    token = registered_importer["token"]
    resp = get_me(token)
    assert resp.status_code == 200
    data = resp.json()
    # For unverified user, email_verified_at should be None or absent
    ev = data.get("email_verified_at")
    assert ev is None or isinstance(ev, str), \
        f"email_verified_at should be None or ISO string, got {type(ev)}: {ev}"
    print(f"PASS: email_verified_at={ev} (None expected for unverified)")
