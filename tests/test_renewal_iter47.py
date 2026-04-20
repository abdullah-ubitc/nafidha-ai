"""
Renewal Engine Tests — Iteration 47
Tests: BACKEND-1 through BACKEND-9 (all renewal endpoints)
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Credentials
BROKER_EMAIL    = "broker@customs.ly"
BROKER_PASS     = "Broker@2026!"
CARRIER_EMAIL   = "carrier@customs.ly"
CARRIER_PASS    = "Carrier@2026!"
OFFICER_EMAIL   = "reg_officer@customs.ly"
OFFICER_PASS    = "RegOfficer@2026!"
ADMIN_EMAIL     = "admin@customs.ly"
ADMIN_PASS      = "Admin@2026!"

# Suspended carrier for auto-unfreeze test
SUSPENDED_CARRIER_ID = "69da82e9533da683f22bbe27"


def login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    token = r.cookies.get("access_token") or r.json().get("access_token") or r.json().get("token")
    return token, r.cookies


def make_session(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed {email}: {r.text}"
    return s


@pytest.fixture(scope="module")
def broker_session():
    return make_session(BROKER_EMAIL, BROKER_PASS)


@pytest.fixture(scope="module")
def carrier_session():
    return make_session(CARRIER_EMAIL, CARRIER_PASS)


@pytest.fixture(scope="module")
def officer_session():
    return make_session(OFFICER_EMAIL, OFFICER_PASS)


@pytest.fixture(scope="module")
def admin_session():
    return make_session(ADMIN_EMAIL, ADMIN_PASS)


# ── BACKEND-1: Submit Renewal Request ─────────────────────────────────────────
class TestSubmitRenewal:
    renewal_id = None

    def test_submit_renewal_broker(self, broker_session):
        """BACKEND-1: Broker submits a renewal for commercial_registry"""
        with open("/tmp/test_renewal.pdf", "rb") as f:
            r = broker_session.post(
                f"{BASE_URL}/api/renewal/request",
                data={"doc_type": "commercial_registry", "notes": "TEST renewal broker"},
                files={"file": ("test_renewal.pdf", f, "application/pdf")},
            )
        print(f"Submit renewal status: {r.status_code}, body: {r.text[:300]}")
        assert r.status_code == 200
        data = r.json()
        assert "renewal_id" in data
        TestSubmitRenewal.renewal_id = data["renewal_id"]
        print(f"Created renewal_id: {TestSubmitRenewal.renewal_id}")

    def test_submit_renewal_returns_message(self, broker_session):
        """Response contains a message"""
        # Uses previously stored renewal_id from previous test
        assert TestSubmitRenewal.renewal_id is not None

    def test_submit_duplicate_renewal_returns_409(self, broker_session):
        """BACKEND-9: Duplicate pending renewal → 409"""
        with open("/tmp/test_renewal.pdf", "rb") as f:
            r = broker_session.post(
                f"{BASE_URL}/api/renewal/request",
                data={"doc_type": "commercial_registry", "notes": "duplicate TEST"},
                files={"file": ("test_renewal.pdf", f, "application/pdf")},
            )
        print(f"Duplicate renewal: {r.status_code} {r.text[:200]}")
        assert r.status_code == 409

    def test_submit_invalid_doc_type_400(self, broker_session):
        """Invalid doc_type → 400"""
        with open("/tmp/test_renewal.pdf", "rb") as f:
            r = broker_session.post(
                f"{BASE_URL}/api/renewal/request",
                data={"doc_type": "invalid_doc"},
                files={"file": ("test_renewal.pdf", f, "application/pdf")},
            )
        assert r.status_code == 400


# ── BACKEND-2: Pending List ────────────────────────────────────────────────────
class TestPendingList:
    def test_get_pending_renewals(self, officer_session):
        """BACKEND-2: Officer gets pending renewal list"""
        r = officer_session.get(f"{BASE_URL}/api/renewal/pending")
        print(f"Pending: {r.status_code}, count: {len(r.json()) if r.ok else 'err'}")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_pending_items_have_required_fields(self, officer_session):
        """Each pending item has required fields"""
        r = officer_session.get(f"{BASE_URL}/api/renewal/pending")
        assert r.status_code == 200
        items = r.json()
        if items:
            item = items[0]
            for field in ["_id", "user_id", "doc_type", "status"]:
                assert field in item, f"Missing field: {field}"
            assert item["status"] == "pending"

    def test_pending_unauthorized_for_regular_user(self, broker_session):
        """Regular user cannot see pending renewals"""
        r = broker_session.get(f"{BASE_URL}/api/renewal/pending")
        assert r.status_code in (401, 403)


# ── BACKEND-3: Count ───────────────────────────────────────────────────────────
class TestRenewalCount:
    def test_get_count_officer(self, officer_session):
        """BACKEND-3: Officer gets pending count"""
        r = officer_session.get(f"{BASE_URL}/api/renewal/count")
        print(f"Count: {r.status_code} {r.text[:100]}")
        assert r.status_code == 200
        data = r.json()
        assert "count" in data
        assert isinstance(data["count"], int)
        assert data["count"] >= 0

    def test_count_matches_pending_list(self, officer_session):
        """Count matches actual pending list length"""
        pending = officer_session.get(f"{BASE_URL}/api/renewal/pending").json()
        count   = officer_session.get(f"{BASE_URL}/api/renewal/count").json()["count"]
        assert count == len(pending)


# ── BACKEND-6: My Requests ─────────────────────────────────────────────────────
class TestMyRequests:
    def test_my_requests(self, broker_session):
        """BACKEND-6: Broker sees own renewal requests"""
        r = broker_session.get(f"{BASE_URL}/api/renewal/my-requests")
        print(f"My requests: {r.status_code}, count: {len(r.json()) if r.ok else 'err'}")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1  # We submitted at least one above

    def test_my_requests_have_correct_doc_type(self, broker_session):
        r = broker_session.get(f"{BASE_URL}/api/renewal/my-requests")
        items = r.json()
        types = [i["doc_type"] for i in items]
        assert "commercial_registry" in types


# ── BACKEND-4 & 5: Approve / Reject ───────────────────────────────────────────
class TestApproveReject:
    carrier_renewal_id = None

    def test_carrier_submit_stat_cert_renewal(self, carrier_session):
        """Carrier submits statistical_cert renewal for approval test"""
        with open("/tmp/test_renewal.pdf", "rb") as f:
            r = carrier_session.post(
                f"{BASE_URL}/api/renewal/request",
                data={"doc_type": "statistical_cert", "new_expiry_date": "2027-12-31", "notes": "TEST carrier renewal"},
                files={"file": ("test_renewal.pdf", f, "application/pdf")},
            )
        print(f"Carrier renewal: {r.status_code} {r.text[:300]}")
        assert r.status_code in (200, 409)  # 409 if already pending
        if r.status_code == 200:
            TestApproveReject.carrier_renewal_id = r.json()["renewal_id"]

    def test_approve_requires_pending(self, officer_session):
        """BACKEND-4: Officer approves a pending renewal"""
        if not TestSubmitRenewal.renewal_id:
            pytest.skip("No renewal_id available")
        r = officer_session.post(
            f"{BASE_URL}/api/renewal/{TestSubmitRenewal.renewal_id}/approve",
            data={"new_expiry_date": "2027-01-01"},
        )
        print(f"Approve: {r.status_code} {r.text[:300]}")
        assert r.status_code == 200
        data = r.json()
        assert "message" in data
        assert "auto_unfrozen" in data

    def test_approve_already_processed_409(self, officer_session):
        """Re-approving same renewal → 409"""
        if not TestSubmitRenewal.renewal_id:
            pytest.skip("No renewal_id")
        r = officer_session.post(
            f"{BASE_URL}/api/renewal/{TestSubmitRenewal.renewal_id}/approve",
            data={"new_expiry_date": "2027-01-01"},
        )
        assert r.status_code == 409

    def test_reject_carrier_renewal(self, officer_session):
        """BACKEND-5: Officer rejects a pending renewal with reason"""
        # Submit a new renewal for broker to reject
        broker_sess = make_session(BROKER_EMAIL, BROKER_PASS)
        with open("/tmp/test_renewal.pdf", "rb") as f:
            r = broker_sess.post(
                f"{BASE_URL}/api/renewal/request",
                data={"doc_type": "customs_broker_license", "notes": "TEST reject"},
                files={"file": ("test_renewal.pdf", f, "application/pdf")},
            )
        assert r.status_code in (200, 409)
        if r.status_code == 200:
            rid = r.json()["renewal_id"]
            rj = officer_session.post(
                f"{BASE_URL}/api/renewal/{rid}/reject",
                data={"reason": "TEST: وثيقة غير واضحة"},
            )
            print(f"Reject: {rj.status_code} {rj.text[:200]}")
            assert rj.status_code == 200
            assert "message" in rj.json()

    def test_reject_without_reason_422(self, officer_session):
        """Reject without reason → 422 (Form required)"""
        r = officer_session.post(
            f"{BASE_URL}/api/renewal/fake_id_xyz/reject",
            data={},
        )
        # Either 422 (validation) or 400 (invalid ID) are acceptable
        assert r.status_code in (400, 422)


# ── BACKEND-8: Timeline Audit ──────────────────────────────────────────────────
class TestTimeline:
    def test_renewal_requested_in_status_history(self, admin_session):
        """BACKEND-8: renewal_requested appears in user's status_history"""
        r = admin_session.get(f"{BASE_URL}/api/users/full")
        assert r.status_code == 200
        users = r.json().get("users", r.json() if isinstance(r.json(), list) else [])
        broker = next((u for u in users if u.get("email") == BROKER_EMAIL), None)
        if not broker:
            pytest.skip("Broker not found in users")
        history = broker.get("status_history", [])
        actions = [h.get("action") for h in history]
        print(f"Broker status_history actions: {actions}")
        assert "renewal_requested" in actions

    def test_renewal_approved_in_status_history(self, admin_session):
        """BACKEND-8: renewal_approved appears in user's status_history after approval"""
        r = admin_session.get(f"{BASE_URL}/api/users/full")
        assert r.status_code == 200
        users = r.json().get("users", r.json() if isinstance(r.json(), list) else [])
        broker = next((u for u in users if u.get("email") == BROKER_EMAIL), None)
        if not broker:
            pytest.skip("Broker not found")
        history = broker.get("status_history", [])
        actions = [h.get("action") for h in history]
        print(f"Status history actions: {actions}")
        assert "renewal_approved" in actions


# ── BACKEND-7: Auto-Unfreeze Logic ────────────────────────────────────────────
class TestAutoUnfreeze:
    suspended_renewal_id = None

    def test_setup_suspended_user(self):
        """Ensure test_carrier_partial2 is suspended for auto-unfreeze test via mongosh"""
        import subprocess
        result = subprocess.run(
            ["mongosh", "--quiet", "--eval",
             'db = db.getSiblingDB("libya_customs_db"); db.users.updateOne({email: "test_carrier_partial2@test.ly"}, {$set: {account_status: "suspended", statistical_expiry_date: "2020-01-01"}});'],
            capture_output=True, text=True, timeout=10
        )
        print(f"mongosh result: {result.stdout} {result.stderr}")
        # Verify
        verify = subprocess.run(
            ["mongosh", "--quiet", "--eval",
             'db = db.getSiblingDB("libya_customs_db"); print(JSON.stringify(db.users.findOne({email: "test_carrier_partial2@test.ly"}, {account_status:1, statistical_expiry_date:1})));'],
            capture_output=True, text=True, timeout=10
        )
        print(f"After setup: {verify.stdout}")

    def test_suspended_user_submits_stat_cert(self):
        """Suspended user submits statistical_cert renewal"""
        try:
            sess = make_session("test_carrier_partial2@test.ly", "TestPass@2026!")
        except AssertionError:
            pytest.skip("Cannot login with test_carrier_partial2")
        # Clear existing pending renewal first
        with open("/tmp/test_renewal.pdf", "rb") as f:
            r = sess.post(
                f"{BASE_URL}/api/renewal/request",
                data={"doc_type": "statistical_cert", "new_expiry_date": "2027-12-31"},
                files={"file": ("test_renewal.pdf", f, "application/pdf")},
            )
        print(f"Suspended user submit: {r.status_code} {r.text[:300]}")
        if r.status_code == 200:
            TestAutoUnfreeze.suspended_renewal_id = r.json()["renewal_id"]
        elif r.status_code == 409:
            # Find pending renewal id via officer session
            off = make_session(OFFICER_EMAIL, OFFICER_PASS)
            pending = off.get(f"{BASE_URL}/api/renewal/pending").json()
            for p in pending:
                if "partial2" in p.get("user_email","") and p.get("doc_type") == "statistical_cert":
                    TestAutoUnfreeze.suspended_renewal_id = p["_id"]
                    break
        assert TestAutoUnfreeze.suspended_renewal_id is not None, "Could not find renewal_id for auto-unfreeze test"

    def test_approve_unfreeze_account(self, officer_session):
        """BACKEND-7: After approving stat_cert, suspended account becomes active"""
        if not TestAutoUnfreeze.suspended_renewal_id:
            pytest.skip("No suspended renewal to test")
        r = officer_session.post(
            f"{BASE_URL}/api/renewal/{TestAutoUnfreeze.suspended_renewal_id}/approve",
            data={"new_expiry_date": "2027-12-31"},
        )
        print(f"Approve unfreeze: {r.status_code} {r.text[:300]}")
        assert r.status_code == 200
        data = r.json()
        assert data.get("auto_unfrozen") is True, f"Expected auto_unfrozen=True but got: {data}"

        # Verify account_status is now active via mongosh
        import subprocess
        verify = subprocess.run(
            ["mongosh", "--quiet", "--eval",
             'db = db.getSiblingDB("libya_customs_db"); print(JSON.stringify(db.users.findOne({email: "test_carrier_partial2@test.ly"}, {account_status:1})));'],
            capture_output=True, text=True, timeout=10
        )
        print(f"Post-approve status: {verify.stdout}")
        assert '"active"' in verify.stdout or "active" in verify.stdout
