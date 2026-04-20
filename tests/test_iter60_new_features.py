"""
iter60: Test 3 new features:
1. Timeline View in ShipmentStatusBoard
2. P2 Enforcement (inspection_required on medium/high risk approval)
3. JL38 PDF print button (backend endpoint)
+ Regression: gate lock without platform_fees_paid, valuation without declaration_accepted
"""
import pytest
import requests
import os
from bson import ObjectId
from datetime import datetime, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_CREDS = {"email": "admin@customs.ly", "password": "Admin@2026!"}
ACID_OFFICER_CREDS = {"email": "acid@customs.ly", "password": "Acid@2026!"}
INSPECTOR_CREDS = {"email": "inspector@customs.ly", "password": "Inspector@2026!"}
GATE_CREDS = {"email": "gate@customs.ly", "password": "Gate@2026!"}


def login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.cookies


def auth_headers(cookies):
    return {}  # use session cookies


def make_session(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds)
    assert r.status_code == 200, f"Login failed for {creds['email']}: {r.text}"
    return s


# ─── Fixture: Admin session ──────────────────────────────────────────────────
@pytest.fixture(scope="module")
def admin_session():
    return make_session(ADMIN_CREDS)


@pytest.fixture(scope="module")
def inspector_session():
    return make_session(INSPECTOR_CREDS)


@pytest.fixture(scope="module")
def gate_session():
    return make_session(GATE_CREDS)


# ─── Feature 1: Timeline in ShipmentStatusBoard ─────────────────────────────
class TestTimelineAPI:
    """Timeline field must be present in shipment-status-board response"""

    def test_status_board_returns_200(self, gate_session):
        r = gate_session.get(f"{BASE_URL}/api/gate/shipment-status-board")
        assert r.status_code == 200, r.text

    def test_shipments_have_timeline_field(self, gate_session):
        r = gate_session.get(f"{BASE_URL}/api/gate/shipment-status-board")
        assert r.status_code == 200
        data = r.json()
        shipments = data.get("shipments", [])
        assert len(shipments) > 0, "No shipments found — cannot verify timeline field"
        # Every shipment must have a 'timeline' key
        for s in shipments[:5]:
            assert "timeline" in s, f"Missing 'timeline' field in shipment {s.get('acid_number')}"

    def test_timeline_is_list(self, gate_session):
        r = gate_session.get(f"{BASE_URL}/api/gate/shipment-status-board")
        data = r.json()
        shipments = data.get("shipments", [])
        for s in shipments[:5]:
            assert isinstance(s["timeline"], list), f"timeline not a list for {s.get('acid_number')}"

    def test_timeline_events_have_required_fields(self, gate_session):
        r = gate_session.get(f"{BASE_URL}/api/gate/shipment-status-board")
        data = r.json()
        shipments = data.get("shipments", [])
        # Find a shipment with non-empty timeline
        shipment_with_tl = next((s for s in shipments if s.get("timeline")), None)
        if shipment_with_tl is None:
            pytest.skip("No shipments with timeline events found")
        tl = shipment_with_tl["timeline"]
        for ev in tl[:3]:
            assert "event" in ev, f"Missing 'event' in timeline: {ev}"
            assert "timestamp" in ev, f"Missing 'timestamp' in timeline: {ev}"


# ─── Feature 2: P2 Enforcement ──────────────────────────────────────────────
class TestP2Enforcement:
    """P2: Approving ACID with risk_level=medium/high sets inspection_required=True"""

    def _find_or_create_acid(self, admin_session, risk_level="high"):
        """Find an existing submitted ACID with given risk_level, or create one via DB"""
        # Use admin to query DB via API
        r = admin_session.get(f"{BASE_URL}/api/acid?status=submitted&limit=100")
        if r.status_code == 200:
            acids = r.json()
            if isinstance(acids, dict):
                acids = acids.get("requests", acids.get("items", []))
            # Find one with the target risk_level
            target = next((a for a in acids if a.get("risk_level") == risk_level), None)
            if target:
                return target
        return None

    def test_inspector_queue_returns_200(self, inspector_session):
        r = inspector_session.get(f"{BASE_URL}/api/inspections/assignments")
        assert r.status_code == 200, r.text

    def test_inspector_queue_returns_list(self, inspector_session):
        r = inspector_session.get(f"{BASE_URL}/api/inspections/assignments")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"

    def test_inspector_queue_has_inspection_stage(self, inspector_session):
        """All items in queue should have inspection_stage field"""
        r = inspector_session.get(f"{BASE_URL}/api/inspections/assignments")
        data = r.json()
        if not data:
            pytest.skip("Inspector queue is empty")
        for item in data[:5]:
            assert "inspection_stage" in item, f"Missing inspection_stage in {item.get('acid_number')}"

    def test_pre_treasury_items_in_queue(self, inspector_session):
        """Pre-treasury items (pre_inspection_flagged) should appear in queue"""
        r = inspector_session.get(f"{BASE_URL}/api/inspections/assignments")
        data = r.json()
        stages = [item.get("inspection_stage") for item in data]
        # We can have both ready_for_inspection and pre_inspection_flagged
        print(f"Inspection stages found: {set(stages)}")
        # At least one of the expected stages
        assert any(s in stages for s in ["ready_for_inspection", "pre_inspection_flagged"]) or len(data) == 0, \
            f"Unexpected stages: {set(stages)}"

    def test_p2_enforcement_via_approve_flow(self, admin_session):
        """Approve a medium-risk ACID via workflow claim+approve and verify inspection_required=True"""
        # Find a submitted medium/high risk ACID
        r = admin_session.get(f"{BASE_URL}/api/acid?status=submitted&limit=100")
        if r.status_code != 200:
            pytest.skip("Cannot query submitted ACIDs")
        acids = r.json()
        if isinstance(acids, dict):
            acids = acids.get("requests", acids.get("items", []))
        target = next((a for a in acids if a.get("risk_level") in ["medium", "high"] and not a.get("is_green_channel")), None)
        if not target:
            # Check already-approved ones (P2 was just deployed)
            r2 = admin_session.get(f"{BASE_URL}/api/acid?status=approved&limit=100")
            acids2 = r2.json()
            if isinstance(acids2, dict): acids2 = acids2.get("requests", acids2.get("items", []))
            already = next((a for a in acids2 if a.get("risk_level") in ["medium","high"] and a.get("inspection_required")), None)
            if already:
                assert already["inspection_required"] == True
                return
            pytest.skip("No submitted medium/high risk ACIDs to test P2 flow")
        acid_id = target["_id"]
        # Claim then approve
        claim_r = admin_session.post(f"{BASE_URL}/api/workflow/claim", json={"task_id": acid_id, "task_type": "acid_review"})
        if claim_r.status_code != 200:
            pytest.skip(f"Cannot claim workflow task: {claim_r.text}")
        approve_r = admin_session.put(f"{BASE_URL}/api/acid/{acid_id}/review", json={"action": "approve", "notes": "P2 test"})
        assert approve_r.status_code == 200, f"Approve failed: {approve_r.text}"
        # Verify inspection_required
        check_r = admin_session.get(f"{BASE_URL}/api/acid/{target['acid_number'].replace('/', '%2F')}")
        assert check_r.status_code == 200
        updated = check_r.json()
        assert updated.get("inspection_required") == True, f"inspection_required not set: {updated.get('inspection_required')}"
        assert updated.get("inspection_status") == "pending"
        # Verify inspection_required event in timeline
        tl_events = [e["event"] for e in updated.get("timeline", [])]
        assert "inspection_required" in tl_events, f"inspection_required event missing from timeline: {tl_events}"

    def test_low_risk_no_inspection_required(self, admin_session):
        """Low risk ACIDs should NOT have inspection_required=True from approval alone"""
        r = admin_session.get(f"{BASE_URL}/api/acid?status=approved&limit=100")
        if r.status_code != 200:
            pytest.skip("Cannot query approved ACIDs")
        acids = r.json()
        if isinstance(acids, dict):
            acids = acids.get("requests", acids.get("items", []))
        low_risk = [a for a in acids if a.get("risk_level") == "low" or a.get("is_green_channel")]
        if not low_risk:
            pytest.skip("No low-risk approved ACIDs found")
        for acid in low_risk[:3]:
            # For low risk, inspection_required should be False or absent
            insp = acid.get("inspection_required", False)
            assert not insp, f"ACID {acid.get('acid_number')} is low-risk but inspection_required={insp}"


# ─── Feature 3: JL38 PDF API ─────────────────────────────────────────────────
class TestJL38PDF:
    """JL38 PDF endpoint for released shipments"""

    def test_jl38_pdf_released_shipment(self, admin_session):
        """GET /api/acid/{id}/jl38-pdf returns PDF for released shipment"""
        r = admin_session.get(f"{BASE_URL}/api/gate/shipment-status-board?status_filter=released")
        assert r.status_code == 200, r.text
        data = r.json()
        released = [s for s in data.get("shipments", []) if s.get("gate_released") and s.get("jl38_number")]
        if not released:
            pytest.skip("No released shipments with JL38 number found")
        ship = released[0]
        acid_id = ship["acid_id"]
        pdf_r = admin_session.get(f"{BASE_URL}/api/acid/{acid_id}/jl38-pdf")
        assert pdf_r.status_code == 200, f"JL38 PDF failed: {pdf_r.text}"
        assert pdf_r.headers.get("content-type", "").startswith("application/pdf"), \
            f"Expected PDF, got: {pdf_r.headers.get('content-type')}"

    def test_jl38_pdf_unreleased_returns_400(self, admin_session):
        """GET /api/acid/{id}/jl38-pdf returns 400 for unreleased shipment"""
        r = admin_session.get(f"{BASE_URL}/api/gate/shipment-status-board?status_filter=in_progress")
        if r.status_code != 200:
            pytest.skip("Cannot get in-progress shipments")
        data = r.json()
        in_progress = [s for s in data.get("shipments", []) if not s.get("gate_released")]
        if not in_progress:
            pytest.skip("No in-progress shipments found")
        acid_id = in_progress[0]["acid_id"]
        pdf_r = admin_session.get(f"{BASE_URL}/api/acid/{acid_id}/jl38-pdf")
        assert pdf_r.status_code == 400, f"Expected 400, got {pdf_r.status_code}"


# ─── Regressions ─────────────────────────────────────────────────────────────
class TestRegressions:

    def test_gate_release_blocked_without_platform_fees(self, gate_session, admin_session):
        """Gate release must return 403 when platform_fees_paid=False"""
        # Find a treasury_paid shipment that doesn't have platform fees paid
        r = admin_session.get(f"{BASE_URL}/api/acid?status=treasury_paid&limit=50")
        if r.status_code != 200:
            pytest.skip("Cannot query treasury_paid ACIDs")
        acids = r.json()
        if isinstance(acids, dict):
            acids = acids.get("requests", acids.get("items", []))
        blocked = [a for a in acids if not a.get("platform_fees_paid")]
        if not blocked:
            pytest.skip("No treasury_paid ACIDs without platform_fees_paid found")
        acid_id = blocked[0]["_id"]
        release_r = gate_session.post(f"{BASE_URL}/api/acid/{acid_id}/gate-release", json={"notes": ""})
        assert release_r.status_code == 403, f"Expected 403, got {release_r.status_code}: {release_r.text}"

    def test_valuation_requires_declaration_accepted(self, admin_session):
        """Valuation submission must return 400 when declaration_accepted=False"""
        # Find an ACID without declaration_accepted
        r = admin_session.get(f"{BASE_URL}/api/acid?status=approved&limit=50")
        if r.status_code != 200:
            pytest.skip("Cannot query ACIDs")
        acids = r.json()
        if isinstance(acids, dict):
            acids = acids.get("requests", acids.get("items", []))
        no_decl = [a for a in acids if not a.get("declaration_accepted")]
        if not no_decl:
            pytest.skip("No ACIDs without declaration_accepted found")
        acid_id = no_decl[0]["_id"]
        # Correct endpoint and payload per ValuationInput model
        valuation_payload = {
            "acid_id": acid_id,
            "confirmed_value_usd": 1000,
            "valuation_notes": "test",
        }
        val_r = admin_session.post(f"{BASE_URL}/api/acid/{acid_id}/submit-valuation", json=valuation_payload)
        assert val_r.status_code == 400, f"Expected 400 (no declaration), got {val_r.status_code}: {val_r.text}"
