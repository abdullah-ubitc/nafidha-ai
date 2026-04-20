"""
E2E Full Chain Test — NAFIDHA Libya Customs
Tests the complete 10-step customs chain from ACID submission to gate release.
Also tests ShipmentStatusBoard API and regression checks.
Chain: ACID submit → WF claim → ACID approve → Manifest → Manifest accept → DO issue
       → SAD → Declaration accept → Valuation → Treasury → Platform fees → Gate release
"""
import pytest
import requests
import os
import subprocess
from bson import ObjectId

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# ── Credentials ──────────────────────────────────────────────────────────────
ADMIN_CREDS       = {"email": "admin@customs.ly",        "password": "Admin@2026!"}
BROKER_CREDS      = {"email": "broker@customs.ly",       "password": "Broker@2026!"}  # broker = submitter
ACIDRISK_CREDS    = {"email": "acidrisk@customs.ly",     "password": "AcidRisk@2026!"}
CARRIER_CREDS     = {"email": "carrier@customs.ly",      "password": "Carrier@2026!"}
MANIFEST_CREDS    = {"email": "manifest@customs.ly",     "password": "Manifest@2026!"}
DECLARATION_CREDS = {"email": "declaration@customs.ly",  "password": "Declaration@2026!"}
VALUER_CREDS      = {"email": "valuer@customs.ly",       "password": "Valuer@2026!"}
TREASURY_CREDS    = {"email": "treasury@customs.ly",     "password": "Treasury@2026!"}
GATE_CREDS        = {"email": "gate@customs.ly",         "password": "Gate@2026!"}

state = {}   # shared state across all tests in module


def make_session(creds: dict) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds)
    assert r.status_code == 200, f"Login failed {creds['email']}: {r.text}"
    return s


MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "libya_customs_db"


def mongo_set(acid_id: str, fields: dict):
    """Directly update MongoDB fields for testing purposes."""
    set_expr = ", ".join(f"'{k}': {repr(v)}" for k, v in fields.items())
    script = f"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
async def run():
    client = AsyncIOMotorClient('{MONGO_URL}')
    db = client['{DB_NAME}']
    r = await db.acid_requests.update_one({{'_id': ObjectId('{acid_id}')}}, {{'$set': {{{set_expr}}}}})
    print(f"DONE modified={{r.modified_count}}")
asyncio.run(run())
"""
    result = subprocess.run(["python3", "-c", script], capture_output=True, text=True, timeout=15)
    assert "DONE" in result.stdout, f"MongoDB update failed: stdout={result.stdout}, stderr={result.stderr}"


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def broker_s():
    return make_session(BROKER_CREDS)

@pytest.fixture(scope="module")
def acidrisk_s():
    return make_session(ACIDRISK_CREDS)

@pytest.fixture(scope="module")
def admin_s():
    return make_session(ADMIN_CREDS)

@pytest.fixture(scope="module")
def carrier_s():
    return make_session(CARRIER_CREDS)

@pytest.fixture(scope="module")
def manifest_s():
    return make_session(MANIFEST_CREDS)

@pytest.fixture(scope="module")
def declaration_s():
    return make_session(DECLARATION_CREDS)

@pytest.fixture(scope="module")
def valuer_s():
    return make_session(VALUER_CREDS)

@pytest.fixture(scope="module")
def treasury_s():
    return make_session(TREASURY_CREDS)

@pytest.fixture(scope="module")
def gate_s():
    return make_session(GATE_CREDS)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: ACID Submission
# ══════════════════════════════════════════════════════════════════════════════
def test_step1_acid_submit(broker_s):
    payload = {
        "supplier_name": "TEST E2E Supplier GmbH",
        "supplier_country": "Germany",
        "goods_description": "TEST E2E electronic components for full chain test",
        "hs_code": "8542",
        "quantity": 100,
        "unit": "unit",
        "value_usd": 5000,
        "port_of_entry": "طرابلس البحري",
        "transport_mode": "sea",
        "carrier_name": "TEST Carrier",
        "bill_of_lading": "BL-TEST-E2E-001",
        "estimated_arrival": "2026-06-01",
    }
    resp = broker_s.post(f"{BASE_URL}/api/acid", json=payload)
    assert resp.status_code in [200, 201], f"ACID create failed: {resp.text}"
    d = resp.json()
    acid_id = d.get("acid_id") or d.get("id") or d.get("_id")
    acid_number = d.get("acid_number")
    assert acid_id and acid_number
    state["acid_id"] = acid_id
    state["acid_number"] = acid_number
    print(f"PASS Step1: ACID={acid_number} id={acid_id}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: Workflow Claim + ACID Approve
# ══════════════════════════════════════════════════════════════════════════════
def test_step2a_workflow_claim(acidrisk_s):
    acid_id = state.get("acid_id")
    assert acid_id, "acid_id not set"
    resp = acidrisk_s.post(f"{BASE_URL}/api/workflow/claim",
                           json={"task_type": "acid_review", "task_id": acid_id})
    assert resp.status_code in [200, 201], f"Workflow claim failed: {resp.text}"
    print(f"PASS Step2a: Task claimed by acidrisk officer")


def test_step2b_acid_approve(acidrisk_s):
    acid_id = state.get("acid_id")
    assert acid_id, "acid_id not set"
    resp = acidrisk_s.put(f"{BASE_URL}/api/acid/{acid_id}/review",
                          json={"action": "approve", "notes": "E2E test approval"})
    assert resp.status_code == 200, f"ACID review failed: {resp.text}"
    d = resp.json()
    assert d.get("new_status") == "approved"
    state["acid_approved"] = True
    print(f"PASS Step2b: ACID approved")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Carrier submits Manifest
# ══════════════════════════════════════════════════════════════════════════════
def test_step3_manifest_create(carrier_s):
    acid_number = state.get("acid_number")
    assert acid_number, "acid_number not set"
    payload = {
        "transport_mode": "sea",
        "port_of_entry": "طرابلس البحري",
        "arrival_date": "2026-06-01",
        "vessel_name": "MV TEST E2E VESSEL",
        "imo_number": "IMO-TEST-001",
        "voyage_id": "VOY-E2E-001",
        "consignments": [
            {"acid_number": acid_number, "goods_description": "TEST E2E electronics", "weight_kg": 500}
        ],
    }
    resp = carrier_s.post(f"{BASE_URL}/api/manifests", json=payload)
    assert resp.status_code in [200, 201], f"Manifest create failed: {resp.text}"
    d = resp.json()
    manifest_id = d.get("manifest_id") or d.get("id") or d.get("_id")
    if not manifest_id and "manifest" in d:
        manifest_id = d["manifest"].get("_id") or d["manifest"].get("id")
    assert manifest_id
    state["manifest_id"] = manifest_id
    print(f"PASS Step3: Manifest id={manifest_id}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4: Manifest Officer accepts (Fix 4 regression: all ACIDs approved)
# ══════════════════════════════════════════════════════════════════════════════
def test_step4_manifest_accept(manifest_s):
    manifest_id = state.get("manifest_id")
    assert manifest_id, "manifest_id not set"
    resp = manifest_s.put(f"{BASE_URL}/api/manifests/{manifest_id}/review",
                          json={"action": "accept", "notes": "E2E all ACIDs approved"})
    assert resp.status_code == 200, f"Manifest accept failed: {resp.text}"
    d = resp.json()
    assert d.get("new_status") == "accepted"
    state["manifest_accepted"] = True
    print(f"PASS Step4: Manifest accepted (Fix4 regression OK)")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5: Carrier issues DO
# ══════════════════════════════════════════════════════════════════════════════
def test_step5_issue_do(carrier_s):
    manifest_id = state.get("manifest_id")
    assert manifest_id, "manifest_id not set"
    resp = carrier_s.put(f"{BASE_URL}/api/manifests/{manifest_id}/issue-do",
                         json={"freight_fees_paid": True})
    assert resp.status_code == 200, f"Issue DO failed: {resp.text}"
    d = resp.json()
    assert d.get("do_number")
    state["do_issued"] = True
    print(f"PASS Step5: DO issued {d.get('do_number')}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6: Broker creates SAD (requires do_issued=True)
# ══════════════════════════════════════════════════════════════════════════════
def test_step6_create_sad(broker_s):
    acid_id = state.get("acid_id")
    assert acid_id, "acid_id not set"
    payload = {
        "acid_id": acid_id,
        "cbl_bank_ref": "CBL-E2E-001",
        "customs_station": "طرابلس البحري",
        "declaration_type": "import",
    }
    resp = broker_s.post(f"{BASE_URL}/api/sad", json=payload)
    assert resp.status_code in [200, 201], f"SAD create failed: {resp.text}"
    d = resp.json()
    sad = d.get("sad") or d
    sad_id = sad.get("_id") or sad.get("id")
    assert sad_id
    state["sad_id"] = sad_id
    print(f"PASS Step6: SAD id={sad_id}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7: Declaration Officer reviews SAD — accept
# ══════════════════════════════════════════════════════════════════════════════
def test_step7_declaration_accept(declaration_s):
    sad_id = state.get("sad_id")
    assert sad_id, "sad_id not set"
    resp = declaration_s.put(f"{BASE_URL}/api/declaration/{sad_id}/review",
                             json={"action": "accept", "notes": "E2E test"})
    assert resp.status_code == 200, f"Declaration review failed: {resp.text}"
    d = resp.json()
    assert "declaration_accepted" in str(d.get("new_status", ""))
    state["declaration_accepted"] = True
    print(f"PASS Step7: Declaration accepted")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8: Customs Valuer submits valuation (Fix 1: requires declaration_accepted)
# ══════════════════════════════════════════════════════════════════════════════
def test_step8_valuation(valuer_s):
    acid_id = state.get("acid_id")
    assert acid_id
    assert state.get("declaration_accepted"), "declaration must be accepted first"
    resp = valuer_s.post(f"{BASE_URL}/api/acid/{acid_id}/submit-valuation",
                         json={"acid_id": acid_id, "confirmed_value_usd": 5000.0, "valuation_notes": "E2E"})
    assert resp.status_code == 200, f"Valuation failed: {resp.text}"
    d = resp.json()
    assert d.get("new_status") == "valued"
    state["valued"] = True
    print(f"PASS Step8: Valued (Fix1 regression OK)")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 9: Treasury marks paid
# ══════════════════════════════════════════════════════════════════════════════
def test_step9_treasury_paid(treasury_s):
    acid_id = state.get("acid_id")
    assert acid_id
    resp = treasury_s.post(f"{BASE_URL}/api/acid/{acid_id}/treasury-mark-paid",
                           json={"treasury_ref": "TRES-E2E-001", "notes": "E2E"})
    assert resp.status_code == 200, f"Treasury mark paid failed: {resp.text}"
    d = resp.json()
    assert d.get("new_status") == "treasury_paid"
    state["treasury_paid"] = True
    print(f"PASS Step9: Treasury paid")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 10a: Gate release blocked without platform fees (Fix 2)
# ══════════════════════════════════════════════════════════════════════════════
def test_step10a_gate_blocked_without_platform_fees(gate_s):
    acid_id = state.get("acid_id")
    assert acid_id
    resp = gate_s.post(f"{BASE_URL}/api/acid/{acid_id}/gate-release", json={"notes": ""})
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    print(f"PASS Step10a: Gate correctly blocked without platform fees (Fix2)")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 10b: Pay platform fees via MongoDB, then gate release succeeds
# ══════════════════════════════════════════════════════════════════════════════
def test_step10b_gate_release_after_platform_fees(gate_s):
    acid_id = state.get("acid_id")
    assert acid_id
    # Simulate platform fees payment
    mongo_set(acid_id, {"platform_fees_paid": True})
    resp = gate_s.post(f"{BASE_URL}/api/acid/{acid_id}/gate-release", json={"notes": "E2E release"})
    assert resp.status_code == 200, f"Gate release failed: {resp.text}"
    d = resp.json()
    assert d.get("jl38_number"), f"No jl38_number: {d}"
    assert d.get("new_status") == "gate_released"
    state["gate_released"] = True
    state["jl38_number"] = d.get("jl38_number")
    print(f"PASS Step10b: Gate released JL38={d.get('jl38_number')} (Fix2 regression OK)")


# ══════════════════════════════════════════════════════════════════════════════
# ShipmentStatusBoard API Tests
# ══════════════════════════════════════════════════════════════════════════════
def test_status_board_returns_200(gate_s):
    resp = gate_s.get(f"{BASE_URL}/api/gate/shipment-status-board")
    assert resp.status_code == 200, f"Status board: {resp.text}"
    d = resp.json()
    assert "shipments" in d and "stats" in d
    print(f"PASS: Status board returns 200 with {len(d['shipments'])} shipments")


def test_status_board_stats_keys(gate_s):
    resp = gate_s.get(f"{BASE_URL}/api/gate/shipment-status-board")
    assert resp.status_code == 200
    stats = resp.json()["stats"]
    for k in ["total_active", "ready_for_release", "released_today", "blocked"]:
        assert k in stats, f"Missing stats key: {k}"
    print(f"PASS: Stats keys: {list(stats.keys())}")


def test_status_board_9_step_keys(gate_s):
    resp = gate_s.get(f"{BASE_URL}/api/gate/shipment-status-board?limit=5")
    assert resp.status_code == 200
    ships = resp.json()["shipments"]
    if not ships:
        pytest.skip("No shipments")
    ship = ships[0]
    assert "steps" in ship and "current_step_idx" in ship
    expected = ["acid_submitted","acid_approved","manifest_accepted","do_issued",
                "declaration_accepted","valued","treasury_paid","inspection_done","gate_released"]
    for k in expected:
        assert k in ship["steps"], f"Missing step key: {k}"
    print(f"PASS: All 9 step keys present")


def test_status_filter_ready(gate_s):
    resp = gate_s.get(f"{BASE_URL}/api/gate/shipment-status-board?status_filter=ready")
    assert resp.status_code == 200
    for s in resp.json()["shipments"]:
        assert s["treasury_paid"] is True
        assert s["gate_released"] is False
    print(f"PASS: status_filter=ready returns only treasury_paid non-released")


def test_shipments_have_acid_number(gate_s):
    resp = gate_s.get(f"{BASE_URL}/api/gate/shipment-status-board?limit=5")
    assert resp.status_code == 200
    ships = resp.json()["shipments"]
    if not ships:
        pytest.skip("No shipments")
    for s in ships:
        assert s.get("acid_number"), f"Missing acid_number in {s.get('acid_id')}"
    print(f"PASS: All shipments have acid_number")


def test_e2e_released_in_board(gate_s):
    if not state.get("gate_released"):
        pytest.skip("gate_released not completed")
    resp = gate_s.get(f"{BASE_URL}/api/gate/shipment-status-board?status_filter=released")
    assert resp.status_code == 200
    ids = [s["acid_id"] for s in resp.json()["shipments"]]
    assert state["acid_id"] in ids, f"E2E acid {state['acid_id']} not in released"
    print(f"PASS: E2E released shipment visible in board")


# ══════════════════════════════════════════════════════════════════════════════
# Fix 3 Regression: Low risk ACID can be released without inspection
# ══════════════════════════════════════════════════════════════════════════════
def test_fix3_low_risk_green_channel(admin_s, acidrisk_s, carrier_s, manifest_s,
                                     declaration_s, valuer_s, treasury_s, gate_s):
    """Fix 3: Low-risk ACID should be released without inspection"""
    # 1. Create ACID (low value = low risk)
    resp = admin_s.post(f"{BASE_URL}/api/acid", json={
        "supplier_name": "TEST FIX3 Supplier",
        "supplier_country": "Tunisia",
        "goods_description": "TEST FIX3 low risk goods",
        "hs_code": "6101",
        "quantity": 5,
        "unit": "unit",
        "value_usd": 50,
        "port_of_entry": "طرابلس البحري",
        "transport_mode": "land",
    })
    assert resp.status_code in [200, 201], f"ACID create: {resp.text}"
    d = resp.json()
    acid_id = d.get("acid_id") or d.get("id") or d.get("_id")
    print(f"Fix3 ACID: id={acid_id}, risk={d.get('risk_level')}")

    # 2. WF claim + approve using admin (admin should be able to claim and review)
    claim_resp = admin_s.post(f"{BASE_URL}/api/workflow/claim",
                              json={"task_type": "acid_review", "task_id": acid_id})
    if claim_resp.status_code not in [200, 201]:
        # May fail if admin doesn't have workflow role — use acidrisk officer
        # Reset and try acidrisk
        mongo_set(acid_id, {"wf_status": "Unassigned", "wf_assigned_to": None})
        claim_resp = acidrisk_s.post(f"{BASE_URL}/api/workflow/claim",
                                     json={"task_type": "acid_review", "task_id": acid_id})
        assert claim_resp.status_code in [200, 201], f"Claim: {claim_resp.text}"
        rev = acidrisk_s.put(f"{BASE_URL}/api/acid/{acid_id}/review", json={"action": "approve"})
    else:
        rev = admin_s.put(f"{BASE_URL}/api/acid/{acid_id}/review", json={"action": "approve"})

    assert rev.status_code == 200, f"Approve: {rev.text}"

    # Use MongoDB to fast-forward all remaining steps
    mongo_set(acid_id, {
        "declaration_accepted": True,
        "valuation_confirmed": True,
        "confirmed_value_usd": 50.0,
        "status": "treasury_paid",
        "treasury_paid": True,
        "platform_fees_paid": True,
        "risk_level": "low",
        "is_green_channel": True,
        "do_issued": True,
    })

    # Gate release should work for low risk without inspection
    resp = gate_s.post(f"{BASE_URL}/api/acid/{acid_id}/gate-release", json={"notes": "Fix3 regression"})
    assert resp.status_code == 200, f"Low-risk release failed: {resp.text}"
    d = resp.json()
    assert d.get("new_status") == "gate_released"
    print(f"PASS Fix3: Low risk released without inspection: {d.get('jl38_number')}")
