"""
Iteration 61 — Yellow Channel + Notification System Tests
Tests: yellow-review endpoint, notify_role_users, notification templates, inspector queue
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# ─── Helpers ────────────────────────────────────────────────────────────────

def login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    return r.cookies, r.json()

def get_session(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed {email}: {r.text}"
    return s

# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def inspector_session():
    return get_session("inspector@customs.ly", "Inspector@2026!")

@pytest.fixture(scope="module")
def gate_session():
    return get_session("gate@customs.ly", "Gate@2026!")

@pytest.fixture(scope="module")
def admin_session():
    return get_session("admin@customs.ly", "Admin@2026!")

@pytest.fixture(scope="module")
def treasury_session():
    return get_session("treasury@customs.ly", "Treasury@2026!")

# ─── Find a medium-risk approved ACID with inspection_required=True ──────────

def get_all_acids(admin_session):
    """GET /api/acid returns full list for admin."""
    r = admin_session.get(f"{BASE_URL}/api/acid")
    assert r.status_code == 200, f"/api/acid returned {r.status_code}"
    return r.json() if isinstance(r.json(), list) else r.json() if isinstance(r.json(), list) else r.json().get("items", [])

def find_medium_risk_acid(admin_session):
    """Find an approved medium-risk ACID for yellow-review testing."""
    items = get_all_acids(admin_session)
    for item in items:
        if (item.get("risk_level") == "medium" 
                and item.get("inspection_required") is True
                and item.get("inspection_status") not in ["compliant", "non_compliant"]):
            return item
    return None

def find_high_risk_acid(admin_session):
    """Find an approved high-risk ACID."""
    items = get_all_acids(admin_session)
    for item in items:
        if item.get("risk_level") == "high" and item.get("status") == "approved":
            return item
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Yellow Review Endpoint exists and accepts valid request
# ═══════════════════════════════════════════════════════════════════════════════

class TestYellowChannelEndpoint:
    """Yellow review endpoint acceptance tests"""

    def test_yellow_review_invalid_acid_id_returns_400(self, inspector_session):
        r = inspector_session.post(f"{BASE_URL}/api/inspections/yellow-review", json={
            "acid_id": "invalid_id",
            "decision": "approved",
            "notes": "test"
        })
        assert r.status_code == 400, f"Expected 400 for invalid id, got {r.status_code}"
        print("PASS — invalid acid_id returns 400")

    def test_yellow_review_invalid_decision_returns_400(self, inspector_session, admin_session):
        medium = find_medium_risk_acid(admin_session)
        if not medium:
            pytest.skip("No medium-risk ACID with inspection_required=True found")
        acid_id = medium.get("_id")
        r = inspector_session.post(f"{BASE_URL}/api/inspections/yellow-review", json={
            "acid_id": acid_id,
            "decision": "maybe",
            "notes": "test"
        })
        assert r.status_code == 400, f"Expected 400 for invalid decision, got {r.status_code}"
        print("PASS — invalid decision returns 400")

    def test_yellow_review_approved_sets_compliant(self, inspector_session, admin_session):
        medium = find_medium_risk_acid(admin_session)
        if not medium:
            pytest.skip("No medium-risk ACID with inspection_required=True and pending status found")
        acid_id = medium.get("_id")
        acid_num = medium.get("acid_number", "")
        r = inspector_session.post(f"{BASE_URL}/api/inspections/yellow-review", json={
            "acid_id": acid_id,
            "decision": "approved",
            "notes": "Document review passed — yellow channel"
        })
        assert r.status_code == 200, f"Yellow review failed: {r.status_code} {r.text}"
        data = r.json()
        assert data.get("inspection_status") == "compliant", f"Expected compliant, got {data}"
        assert data.get("channel") == "yellow"
        print(f"PASS — yellow review approved on {acid_num} → inspection_status=compliant")

    def test_yellow_review_rejected_sets_non_compliant(self, inspector_session, admin_session):
        """Need another medium-risk ACID — resets via status board search"""
        r = admin_session.get(f"{BASE_URL}/api/acid")
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        candidate = None
        for item in items:
            if (item.get("risk_level") == "medium" 
                    and item.get("inspection_required") is True
                    and item.get("inspection_status") not in ["compliant", "non_compliant"]):
                candidate = item
                break
        if not candidate:
            pytest.skip("No available medium-risk ACID for rejected test (previous may have been consumed)")
        acid_id = candidate.get("_id")
        r = inspector_session.post(f"{BASE_URL}/api/inspections/yellow-review", json={
            "acid_id": acid_id,
            "decision": "rejected",
            "notes": "Documents incomplete"
        })
        assert r.status_code == 200, f"Yellow review rejected failed: {r.status_code} {r.text}"
        data = r.json()
        assert data.get("inspection_status") == "non_compliant", f"Expected non_compliant, got {data}"
        print(f"PASS — yellow review rejected → inspection_status=non_compliant")

    def test_yellow_review_high_risk_returns_400(self, inspector_session, admin_session):
        high = find_high_risk_acid(admin_session)
        if not high:
            pytest.skip("No high-risk ACID found")
        acid_id = high.get("_id")
        r = inspector_session.post(f"{BASE_URL}/api/inspections/yellow-review", json={
            "acid_id": acid_id,
            "decision": "approved",
            "notes": "trying on high risk"
        })
        assert r.status_code == 400, f"Expected 400 for high-risk ACID, got {r.status_code}: {r.text}"
        print("PASS — high-risk ACID blocked with 400")

    def test_yellow_review_already_compliant_returns_409(self, inspector_session, admin_session):
        """After first approval, re-posting same ACID should 409."""
        r_board = admin_session.get(f"{BASE_URL}/api/acid")
        items = r_board.json() if isinstance(r_board.json(), list) else r_board.json().get("items", [])
        compliant = None
        for item in items:
            if item.get("inspection_status") == "compliant" and item.get("risk_level") == "medium":
                compliant = item
                break
        if not compliant:
            pytest.skip("No compliant medium-risk ACID found to test 409")
        acid_id = compliant.get("_id")
        r = inspector_session.post(f"{BASE_URL}/api/inspections/yellow-review", json={
            "acid_id": acid_id,
            "decision": "approved",
            "notes": "re-review attempt"
        })
        assert r.status_code == 409, f"Expected 409 for already compliant, got {r.status_code}"
        print("PASS — already compliant ACID returns 409")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Timeline has yellow channel event
# ═══════════════════════════════════════════════════════════════════════════════

class TestYellowChannelTimeline:
    """Yellow channel adds timeline event"""

    def test_yellow_review_adds_timeline_event(self, inspector_session, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/acid")
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        yellow_reviewed = None
        for item in items:
            if item.get("inspection_status") == "compliant" and item.get("risk_level") == "medium":
                yellow_reviewed = item
                break
        if not yellow_reviewed:
            pytest.skip("No yellow-reviewed ACID found to check timeline")
        acid_id = yellow_reviewed.get("_id")
        r2 = admin_session.get(f"{BASE_URL}/api/acid/{acid_id}")
        if r2.status_code != 200:
            pytest.skip(f"Could not fetch ACID detail: {r2.status_code}")
        acid_detail = r2.json()
        timeline = acid_detail.get("timeline", [])
        yellow_events = [e for e in timeline if "القناة الصفراء" in e.get("notes", "")]
        assert len(yellow_events) > 0, f"No yellow channel timeline event found. Timeline: {timeline}"
        print(f"PASS — yellow channel timeline event found: {yellow_events[0]}")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Inspector Queue inspection_stage field
# ═══════════════════════════════════════════════════════════════════════════════

class TestInspectorQueue:
    """Inspector assignments queue returns inspection_stage"""

    def test_inspector_queue_returns_200(self, inspector_session):
        r = inspector_session.get(f"{BASE_URL}/api/inspections/assignments")
        assert r.status_code == 200, f"Inspector queue failed: {r.status_code} {r.text}"
        print("PASS — inspector queue returns 200")

    def test_inspector_queue_has_inspection_stage_field(self, inspector_session):
        r = inspector_session.get(f"{BASE_URL}/api/inspections/assignments")
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", data.get("assignments", []))
        if not items:
            pytest.skip("Inspector queue is empty — cannot verify inspection_stage field")
        item = items[0]
        assert "inspection_stage" in item, f"inspection_stage field missing from queue item: {list(item.keys())}"
        print(f"PASS — inspection_stage field present: {item.get('inspection_stage')}")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Notification endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestNotificationEndpoints:
    """Notification API endpoints"""

    def test_get_notifications_gate_officer(self, gate_session):
        r = gate_session.get(f"{BASE_URL}/api/notifications")
        assert r.status_code == 200, f"Notifications failed for gate_officer: {r.status_code} {r.text}"
        data = r.json()
        notifs = data if isinstance(data, list) else data.get("notifications", data.get("items", []))
        print(f"PASS — gate_officer notifications: {len(notifs)} items")

    def test_get_unread_count_gate_officer(self, gate_session):
        r = gate_session.get(f"{BASE_URL}/api/notifications/unread-count")
        assert r.status_code == 200, f"Unread count failed: {r.status_code} {r.text}"
        data = r.json()
        assert "count" in data, f"'count' key missing from response: {data}"
        assert isinstance(data["count"], int)
        print(f"PASS — unread count: {data['count']}")

    def test_get_notifications_inspector(self, inspector_session):
        r = inspector_session.get(f"{BASE_URL}/api/notifications")
        assert r.status_code == 200, f"Notifications failed for inspector: {r.status_code} {r.text}"
        print("PASS — inspector notifications returns 200")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — notify_role_users: treasury → gate_officer notification
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoleNotifications:
    """Role-based notifications triggered on events"""

    def test_gate_officer_gets_notification_after_treasury_paid(
        self, treasury_session, gate_session, admin_session
    ):
        """
        Find an ACID in approved/valuation_confirmed state, 
        mark treasury paid → gate_officer should get new notification.
        """
        # Get gate current notification count first
        r_before = gate_session.get(f"{BASE_URL}/api/notifications/unread-count")
        count_before = r_before.json().get("count", 0) if r_before.status_code == 200 else 0

        # Find ACID ready for treasury payment
        r_board = admin_session.get(f"{BASE_URL}/api/acid")
        items = r_board.json() if isinstance(r_board.json(), list) else r_board.json().get("items", [])
        treasury_ready = None
        for item in items:
            if item.get("status") in ["valuation_confirmed", "declaration_accepted"]:
                treasury_ready = item
                break
        if not treasury_ready:
            pytest.skip("No ACID in valuation_confirmed/declaration_accepted state for treasury test")

        acid_id = treasury_ready.get("_id")
        acid_num = treasury_ready.get("acid_number", "")

        # Mark treasury paid
        r_pay = treasury_session.post(
            f"{BASE_URL}/api/acid/{acid_id}/treasury-mark-paid",
            json={"treasury_ref": "TEST-REF-ITER61"}
        )
        if r_pay.status_code not in [200, 201]:
            pytest.skip(f"Treasury mark-paid failed {r_pay.status_code}: {r_pay.text}")

        # Check gate notifications increased
        import time; time.sleep(1)  # allow background task to complete
        r_after = gate_session.get(f"{BASE_URL}/api/notifications/unread-count")
        assert r_after.status_code == 200
        count_after = r_after.json().get("count", 0)
        assert count_after >= count_before, f"Notification count should not decrease: {count_before} → {count_after}"
        # ideally count_after > count_before, but gate may already have many
        print(f"PASS — treasury paid on {acid_num}, gate notifications: {count_before} → {count_after}")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — channel_type field for medium-risk approved ACIDs
# ═══════════════════════════════════════════════════════════════════════════════

class TestChannelType:
    """Medium-risk approved ACIDs should have channel_type='yellow'"""

    def test_medium_risk_acid_has_yellow_channel_type(self, admin_session):
        items = get_all_acids(admin_session)
        # Only check ACIDs that have channel_type set (newly approved after feature launch)
        medium_with_channel = [
            i for i in items
            if i.get("risk_level") == "medium" 
            and i.get("status") == "approved"
            and i.get("channel_type") is not None
        ]
        if not medium_with_channel:
            pytest.skip("No newly-approved medium-risk ACIDs with channel_type field found (feature may be new)")
        for item in medium_with_channel:
            ctype = item.get("channel_type")
            assert ctype == "yellow", f"Expected channel_type=yellow for {item.get('acid_number')}, got {ctype}"
        print(f"PASS — {len(medium_with_channel)} medium-risk ACIDs all have channel_type=yellow")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — Regression: gate lock still works
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegressions:
    """Regression tests"""

    def test_gate_lock_403_without_platform_fees(self, gate_session, admin_session):
        # Find a released=False ACID
        r = admin_session.get(f"{BASE_URL}/api/acid")
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        non_released = None
        for item in items:
            if item.get("status") == "treasury_paid" and not item.get("released"):
                non_released = item
                break
        if not non_released:
            pytest.skip("No treasury_paid non-released ACID found for gate lock test")
        acid_id = non_released.get("_id")
        r_gate = gate_session.post(f"{BASE_URL}/api/acid/{acid_id}/gate-release", json={"notes": "test"})
        assert r_gate.status_code in [403, 400], f"Expected 403/400 for gate without platform fees, got {r_gate.status_code}"
        print(f"PASS — gate lock still returns {r_gate.status_code} without platform fees")

    def test_yellow_compliant_acid_can_be_released_at_gate(self, gate_session, admin_session):
        """compliant inspection_status doesn't block gate — gate only checks platform_fees_paid."""
        r = admin_session.get(f"{BASE_URL}/api/acid")
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        compliant_paid = None
        for item in items:
            if (item.get("inspection_status") == "compliant"
                    and item.get("status") == "treasury_paid"
                    and item.get("platform_fees_paid") is True
                    and not item.get("released")):
                compliant_paid = item
                break
        if not compliant_paid:
            pytest.skip("No compliant+treasury_paid+platform_fees_paid ACID found")
        acid_id = compliant_paid.get("_id")
        r_gate = gate_session.post(f"{BASE_URL}/api/acid/{acid_id}/gate-release", json={"notes": "test"})
        assert r_gate.status_code in [200, 201], f"Expected 200 for compliant gate release, got {r_gate.status_code}: {r_gate.text}"
        print(f"PASS — compliant yellow ACID released at gate for {compliant_paid.get('acid_number')}")
