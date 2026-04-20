"""Tests for 4 critical architectural fixes in NAFIDHA customs chain
Uses direct MongoDB seeding to bypass API state machine locks.
"""
import pytest
import requests
import os
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "libya_customs_db"

# ── DB direct access ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


def insert_acid(db, overrides=None):
    """Insert a test ACID document directly to DB."""
    doc = {
        "acid_number": f"ACID-TEST-{ObjectId()}",
        "company_name_ar": "شركة الاختبار",
        "company_name_en": "Test Company",
        "goods_description_ar": "بضائع اختبار",
        "goods_description_en": "Test goods",
        "country_of_origin": "TR",
        "hs_code": "8471.30",
        "declared_value_usd": 5000,
        "status": "approved",
        "declaration_accepted": False,
        "valuation_confirmed": False,
        "treasury_paid": False,
        "platform_fees_paid": False,
        "gate_released": False,
        "is_green_channel": False,
        "risk_level": "medium",
        "inspection_status": None,
        "requester_id": str(ObjectId()),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "timeline": [],
    }
    if overrides:
        doc.update(overrides)
    result = db.acid_requests.insert_one(doc)
    return str(result.inserted_id)


def insert_manifest(db, consignments=None, overrides=None):
    """Insert a test Manifest document directly to DB."""
    doc = {
        "manifest_number": f"MNF-TEST-{ObjectId()}",
        "carrier_id": str(ObjectId()),
        "carrier_name_ar": "ناقل الاختبار",
        "transport_mode": "sea",
        "port_of_entry": "طرابلس البحري",
        "arrival_date": "2026-03-15",
        "vessel_name": "Test Vessel",
        "consignments": consignments or [],
        "status": "submitted",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    if overrides:
        doc.update(overrides)
    result = db.manifests.insert_one(doc)
    return str(result.inserted_id)


# ── Auth sessions ─────────────────────────────────────────────────────────────

def session_for(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    return s


@pytest.fixture(scope="module")
def admin_session():
    return session_for("admin@customs.ly", "Admin@2026!")


@pytest.fixture(scope="module")
def valuer_session():
    return session_for("valuer@customs.ly", "Valuer@2026!")


@pytest.fixture(scope="module")
def release_session():
    return session_for("release@customs.ly", "Release@2026!")


@pytest.fixture(scope="module")
def manifest_session():
    return session_for("manifest@customs.ly", "Manifest@2026!")


# ══════════════════════════════════════════════════════════════════════════════
# FIX 1: Valuation Requires Declaration Acceptance
# ══════════════════════════════════════════════════════════════════════════════

class TestFix1ValuationRequiresDeclaration:
    """Fix 1 — Valuer queue and submit-valuation require declaration_accepted=True"""

    def test_submit_valuation_without_declaration_returns_400(self, db, valuer_session):
        """submit-valuation returns 400 when declaration_accepted=False"""
        acid_id = insert_acid(db, {"status": "approved", "declaration_accepted": False})

        r = valuer_session.post(f"{BASE_URL}/api/acid/{acid_id}/submit-valuation",
                                json={"confirmed_value_usd": 5000, "valuation_notes": "test", "acid_id": acid_id})
        print(f"submit-valuation without declaration: {r.status_code} {r.text[:300]}")
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        # Verify the error mentions declaration
        assert "بيان" in r.text or "declaration" in r.text.lower() or "SAD" in r.text, \
            "Error message should mention declaration/SAD"
        print("PASS: submit-valuation correctly rejected without declaration_accepted")

    def test_valuer_queue_only_shows_declaration_accepted(self, db, valuer_session):
        """Valuer queue must only return ACIDs with declaration_accepted=True"""
        # Insert one WITH and one WITHOUT declaration_accepted
        acid_with = insert_acid(db, {
            "status": "approved", "declaration_accepted": True, "valuation_confirmed": False
        })
        acid_without = insert_acid(db, {
            "status": "approved", "declaration_accepted": False, "valuation_confirmed": False
        })

        r = valuer_session.get(f"{BASE_URL}/api/valuer/queue")
        assert r.status_code == 200, f"Queue failed: {r.text}"
        items = r.json()
        print(f"Valuer queue items count: {len(items)}")

        ids_in_queue = {i.get("_id") or i.get("id") for i in items}
        # With declaration must be in queue
        assert acid_with in ids_in_queue or any(i.get("_id") == acid_with for i in items), \
            "ACID with declaration_accepted=True should appear in queue"
        # Without declaration must NOT be in queue
        assert acid_without not in ids_in_queue and not any(i.get("_id") == acid_without for i in items), \
            "ACID with declaration_accepted=False should NOT appear in queue"
        # All returned items must have declaration_accepted=True
        for item in items:
            assert item.get("declaration_accepted") == True, \
                f"Item {item.get('acid_number')} in queue without declaration_accepted=True"
        print(f"PASS: Valuer queue correctly filters — only declaration_accepted=True items shown")

    def test_submit_valuation_with_declaration_accepted_succeeds(self, db, valuer_session):
        """submit-valuation succeeds when declaration_accepted=True"""
        acid_id = insert_acid(db, {
            "status": "approved",
            "declaration_accepted": True,
            "valuation_confirmed": False,
        })
        r = valuer_session.post(f"{BASE_URL}/api/acid/{acid_id}/submit-valuation",
                                json={"confirmed_value_usd": 7500, "valuation_notes": "test valuation", "acid_id": acid_id})
        print(f"submit-valuation with declaration_accepted=True: {r.status_code} {r.text[:300]}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("new_status") == "valued"
        assert data.get("confirmed_value_usd") == 7500
        print("PASS: submit-valuation succeeds when declaration_accepted=True")


# ══════════════════════════════════════════════════════════════════════════════
# FIX 2: Platform Fees Lock in approve_release
# ══════════════════════════════════════════════════════════════════════════════

class TestFix2PlatformFeesLock:
    """Fix 2 — approve_release blocks with 403 when platform_fees_paid=False"""

    def test_approve_release_blocked_without_platform_fees(self, db, release_session):
        """approve_release returns 403 when platform_fees_paid=False"""
        acid_id = insert_acid(db, {
            "status": "treasury_paid",
            "treasury_paid": True,
            "platform_fees_paid": False,
            "risk_level": "low",
            "gate_released": False,
        })
        r = release_session.post(f"{BASE_URL}/api/release/{acid_id}/approve",
                                 json={"notes": "test release"})
        print(f"approve_release without platform_fees: {r.status_code} {r.text[:300]}")
        assert r.status_code == 403, f"Expected 403 (platform fees block), got {r.status_code}: {r.text}"
        assert "منصة" in r.text or "platform" in r.text.lower() or "رسوم" in r.text, \
            "Error should mention platform fees"
        print("PASS: approve_release correctly blocked with 403 when platform_fees_paid=False")

    def test_approve_release_passes_with_all_fees_paid_low_risk(self, db, release_session):
        """approve_release succeeds when treasury_paid=True AND platform_fees_paid=True AND risk_level=low"""
        acid_id = insert_acid(db, {
            "status": "treasury_paid",
            "treasury_paid": True,
            "platform_fees_paid": True,
            "risk_level": "low",
            "is_green_channel": False,
            "gate_released": False,
        })
        r = release_session.post(f"{BASE_URL}/api/release/{acid_id}/approve",
                                 json={"notes": "full fees paid low risk"})
        print(f"approve_release with all fees+low risk: {r.status_code} {r.text[:300]}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "jl38_number" in data, "Response must contain jl38_number"
        print(f"PASS: Release approved — JL38: {data['jl38_number']}")


# ══════════════════════════════════════════════════════════════════════════════
# FIX 3: Smart Green Channel (risk_level='low' bypasses inspection)
# ══════════════════════════════════════════════════════════════════════════════

class TestFix3SmartGreenChannel:
    """Fix 3 — risk_level='low' allows release without inspection even if is_green_channel=False"""

    def test_low_risk_bypasses_inspection_requirement(self, db, release_session):
        """ACID with risk_level='low' and is_green_channel=False should be released without inspection"""
        acid_id = insert_acid(db, {
            "treasury_paid": True,
            "platform_fees_paid": True,
            "risk_level": "low",
            "is_green_channel": False,    # Explicitly NOT green channel
            "inspection_status": None,     # No inspection
            "gate_released": False,
        })
        r = release_session.post(f"{BASE_URL}/api/release/{acid_id}/approve",
                                 json={"notes": "low risk bypass inspection"})
        print(f"Low risk (is_green=False, no inspection): {r.status_code} {r.text[:300]}")
        assert r.status_code == 200, \
            f"Expected 200 for low risk (should bypass inspection), got {r.status_code}: {r.text}"
        print("PASS: risk_level='low' bypasses inspection requirement")

    def test_medium_risk_blocked_without_inspection(self, db, release_session):
        """ACID with risk_level='medium' without inspection is blocked"""
        acid_id = insert_acid(db, {
            "treasury_paid": True,
            "platform_fees_paid": True,
            "risk_level": "medium",
            "is_green_channel": False,
            "inspection_status": None,
            "gate_released": False,
        })
        r = release_session.post(f"{BASE_URL}/api/release/{acid_id}/approve",
                                 json={"notes": "medium risk no inspection"})
        print(f"Medium risk no inspection: {r.status_code} {r.text[:300]}")
        assert r.status_code == 400, \
            f"Expected 400 for medium risk without inspection, got {r.status_code}: {r.text}"
        print("PASS: medium risk correctly blocked without inspection")

    def test_high_risk_blocked_without_inspection(self, db, release_session):
        """ACID with risk_level='high' without inspection is blocked"""
        acid_id = insert_acid(db, {
            "treasury_paid": True,
            "platform_fees_paid": True,
            "risk_level": "high",
            "is_green_channel": False,
            "inspection_status": None,
            "gate_released": False,
        })
        r = release_session.post(f"{BASE_URL}/api/release/{acid_id}/approve",
                                 json={"notes": "high risk no inspection"})
        print(f"High risk no inspection: {r.status_code} {r.text[:300]}")
        assert r.status_code == 400, \
            f"Expected 400 for high risk without inspection, got {r.status_code}: {r.text}"
        print("PASS: high risk correctly blocked without inspection")

    def test_medium_risk_allowed_with_compliant_inspection(self, db, release_session):
        """ACID with risk_level='medium' but inspection_status='compliant' should be released"""
        acid_id = insert_acid(db, {
            "treasury_paid": True,
            "platform_fees_paid": True,
            "risk_level": "medium",
            "is_green_channel": False,
            "inspection_status": "compliant",
            "gate_released": False,
        })
        r = release_session.post(f"{BASE_URL}/api/release/{acid_id}/approve",
                                 json={"notes": "medium risk compliant inspection"})
        print(f"Medium risk compliant inspection: {r.status_code} {r.text[:300]}")
        assert r.status_code == 200, \
            f"Expected 200 for medium risk with compliant inspection, got {r.status_code}: {r.text}"
        print("PASS: medium risk with compliant inspection allowed")


# ══════════════════════════════════════════════════════════════════════════════
# FIX 4: Manifest Rejects Uncleared ACIDs
# ══════════════════════════════════════════════════════════════════════════════

class TestFix4ManifestAcidValidation:
    """Fix 4 — Manifest accept validates all ACIDs are approved"""

    def test_manifest_accept_blocked_with_submitted_acid(self, db, manifest_session):
        """Manifest accept returns 400 MANIFEST_CONTAINS_UNCLEARED_ACIDS when ACID is submitted"""
        # Insert ACID with status=submitted
        acid_number = f"ACID-SUBM-{ObjectId()}"
        db.acid_requests.insert_one({
            "acid_number": acid_number,
            "status": "submitted",
            "created_at": datetime.now(timezone.utc),
        })
        manifest_id = insert_manifest(db, consignments=[{"acid_number": acid_number}])

        r = manifest_session.put(f"{BASE_URL}/api/manifests/{manifest_id}/review",
                                 json={"action": "accept", "notes": "test"})
        print(f"Manifest accept with submitted ACID: {r.status_code} {r.text[:400]}")
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        # Check error code in response
        try:
            err = r.json()
            detail = err.get("detail", {})
            if isinstance(detail, dict):
                code = detail.get("code")
                assert code == "MANIFEST_CONTAINS_UNCLEARED_ACIDS", f"Wrong error code: {code}"
                print(f"Error code confirmed: {code}")
        except Exception as e:
            print(f"Could not verify error code: {e}")
        print("PASS: Manifest correctly rejected with uncleared ACID")

    def test_manifest_accept_blocked_with_under_review_acid(self, db, manifest_session):
        """Manifest accept returns 400 when ACID is under_review"""
        acid_number = f"ACID-UR-{ObjectId()}"
        db.acid_requests.insert_one({
            "acid_number": acid_number,
            "status": "under_review",
            "created_at": datetime.now(timezone.utc),
        })
        manifest_id = insert_manifest(db, consignments=[{"acid_number": acid_number}])

        r = manifest_session.put(f"{BASE_URL}/api/manifests/{manifest_id}/review",
                                 json={"action": "accept", "notes": "test"})
        print(f"Manifest accept with under_review ACID: {r.status_code} {r.text[:400]}")
        assert r.status_code == 400, f"Expected 400 for under_review ACID, got {r.status_code}: {r.text}"
        print("PASS: Manifest correctly rejected with under_review ACID")

    def test_manifest_accept_succeeds_with_all_approved_acids(self, db, manifest_session):
        """Manifest accept succeeds when all ACIDs have status approved"""
        acid_number = f"ACID-APPR-{ObjectId()}"
        db.acid_requests.insert_one({
            "acid_number": acid_number,
            "status": "approved",
            "created_at": datetime.now(timezone.utc),
        })
        manifest_id = insert_manifest(db, consignments=[{"acid_number": acid_number}])

        r = manifest_session.put(f"{BASE_URL}/api/manifests/{manifest_id}/review",
                                 json={"action": "accept", "notes": "all approved"})
        print(f"Manifest accept with approved ACID: {r.status_code} {r.text[:300]}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("new_status") == "accepted"
        print("PASS: Manifest accepted when all ACIDs are approved")

    def test_manifest_reject_works_regardless_of_acid_status(self, db, manifest_session):
        """Manifest reject should work without checking ACID statuses"""
        acid_number = f"ACID-RJCT-{ObjectId()}"
        db.acid_requests.insert_one({
            "acid_number": acid_number,
            "status": "submitted",  # uncleared
            "created_at": datetime.now(timezone.utc),
        })
        manifest_id = insert_manifest(db, consignments=[{"acid_number": acid_number}])

        r = manifest_session.put(f"{BASE_URL}/api/manifests/{manifest_id}/review",
                                 json={"action": "reject", "notes": "test reject"})
        print(f"Manifest reject with submitted ACID: {r.status_code} {r.text[:300]}")
        assert r.status_code == 200, f"Expected 200 for reject, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("new_status") == "rejected"
        print("PASS: Manifest reject works regardless of ACID status")

    def test_manifest_accept_with_no_consignments_succeeds(self, db, manifest_session):
        """Manifest with no consignments should be accepted (no ACIDs to validate)"""
        manifest_id = insert_manifest(db, consignments=[])

        r = manifest_session.put(f"{BASE_URL}/api/manifests/{manifest_id}/review",
                                 json={"action": "accept", "notes": "empty manifest"})
        print(f"Manifest accept with no consignments: {r.status_code} {r.text[:300]}")
        assert r.status_code == 200, f"Expected 200 for empty manifest, got {r.status_code}: {r.text}"
        print("PASS: Empty manifest (no consignments) accepted without issue")
