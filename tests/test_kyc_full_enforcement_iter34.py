"""
Iteration 34: Full KYC enforcement across ALL commercial user action endpoints.
Tests that unverified/pending users are blocked on all write endpoints,
and that approved users/admin can proceed normally.
"""
import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# ── Cookie helpers ────────────────────────────────────────────────────────────

def load_cookies(path: str) -> dict:
    """Parse Netscape-format cookie file into dict."""
    cookies = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookies[parts[5]] = parts[6]
    except Exception:
        pass
    return cookies


def session_with_cookies(cookie_path: str) -> requests.Session:
    s = requests.Session()
    for k, v in load_cookies(cookie_path).items():
        s.cookies.set(k, v)
    return s


def login_session(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    return s


def register_unverified_user(role: str) -> requests.Session:
    """Register a new user (email_unverified) and return a cookie session."""
    uid = uuid.uuid4().hex[:8]
    payload = {
        "email": f"test_{role}_{uid}@test.ly",
        "password": "Test@2026!",
        "name_ar": f"اختبار {role}",
        "name_en": f"Test {role}",
        "role": role,
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    assert r.status_code == 200, f"Register failed: {r.status_code} {r.text}"
    # The registration returns a token/cookie; use session cookies directly
    s = requests.Session()
    s.cookies.update(r.cookies)
    # Try to extract access_token from response body too
    data = r.json()
    if "access_token" in data:
        s.cookies.set("access_token", data["access_token"])
    return s


# ── Minimal request bodies ─────────────────────────────────────────────────────

MANIFEST_PAYLOAD = {
    "transport_mode": "sea",
    "port_of_entry": "طرابلس البحري",
    "arrival_date": "2026-02-15",
    "vessel_name": "Test Vessel",
    "consignments": [],
}

WALLET_TOPUP_PAYLOAD = {
    "amount_lyd": 100.0,
    "payment_ref": "TEST-REF-001",
    "notes": "test topup",
}

BANK_VERIFY_PAYLOAD = {
    "acid_number": "ACID-TEST-0001",
    "cbl_ref": "CBL12345678",
    "bank_name": "بنك الوحدة",
    "amount_lyd": 500.0,
}

PLATFORM_FEE_SUB_PAYLOAD = {}  # POST body empty

SAD_UPDATE_PAYLOAD = {"cbl_bank_ref": "CBL-UPDATE-001"}


def _assert_kyc_blocked(response: requests.Response, endpoint: str):
    """Assert response is 403 with KYC_NOT_APPROVED."""
    assert response.status_code == 403, (
        f"[{endpoint}] Expected 403, got {response.status_code}: {response.text}"
    )
    detail = response.json().get("detail", {})
    code = detail.get("code") if isinstance(detail, dict) else str(detail)
    assert code == "KYC_NOT_APPROVED", (
        f"[{endpoint}] Expected KYC_NOT_APPROVED, got: {detail}"
    )
    print(f"  ✅ PASS [{endpoint}]: 403 KYC_NOT_APPROVED confirmed")


def _assert_not_kyc_blocked(response: requests.Response, endpoint: str):
    """Assert response is NOT 403 KYC_NOT_APPROVED (may fail for other reasons)."""
    if response.status_code == 403:
        detail = response.json().get("detail", {})
        code = detail.get("code") if isinstance(detail, dict) else str(detail)
        assert code != "KYC_NOT_APPROVED", (
            f"[{endpoint}] Should NOT be KYC blocked but got KYC_NOT_APPROVED"
        )
    print(f"  ✅ PASS [{endpoint}]: Not KYC-blocked (status={response.status_code})")


# ── TESTS: Unverified importer (email_unverified) ─────────────────────────────

class TestEmailUnverifiedBlocked:
    """All write endpoints must return 403 KYC_NOT_APPROVED for email_unverified users."""

    @pytest.fixture(scope="class")
    def unverified_importer(self):
        """Register a new unverified importer."""
        return register_unverified_user("importer")

    @pytest.fixture(scope="class")
    def unverified_carrier(self):
        """Register a new unverified carrier_agent."""
        return register_unverified_user("carrier_agent")

    def test_acid_blocked_for_unverified_importer(self, unverified_importer):
        """Regression: POST /api/acid blocked for email_unverified importer."""
        r = unverified_importer.post(f"{BASE_URL}/api/acid", json={
            "importer_name_ar": "مستورد اختبار",
            "importer_name_en": "Test Importer",
            "goods_description_ar": "بضاعة اختبار",
            "goods_description_en": "Test goods",
            "hs_code": "0101",
            "origin_country": "IT",
            "value_usd": 1000.0,
            "currency": "USD",
            "supplier_name": "Test Supplier",
        })
        _assert_kyc_blocked(r, "POST /api/acid")

    def test_manifest_blocked_for_unverified_carrier(self, unverified_carrier):
        """POST /api/manifests blocked for email_unverified carrier_agent."""
        r = unverified_carrier.post(f"{BASE_URL}/api/manifests", json=MANIFEST_PAYLOAD)
        _assert_kyc_blocked(r, "POST /api/manifests")

    def test_sad_blocked_for_unverified_importer(self, unverified_importer):
        """POST /api/sad blocked for email_unverified importer."""
        r = unverified_importer.post(f"{BASE_URL}/api/sad", json={
            "acid_id": "507f1f77bcf86cd799439011",
            "declaration_type": "import",
            "customs_station": "طرابلس",
        })
        _assert_kyc_blocked(r, "POST /api/sad")

    def test_wallet_topup_blocked_for_unverified(self, unverified_importer):
        """POST /api/wallet/topup blocked for email_unverified user."""
        r = unverified_importer.post(f"{BASE_URL}/api/wallet/topup", json=WALLET_TOPUP_PAYLOAD)
        _assert_kyc_blocked(r, "POST /api/wallet/topup")

    def test_bank_verify_blocked_for_unverified(self, unverified_importer):
        """POST /api/bank/verify blocked for email_unverified user."""
        r = unverified_importer.post(f"{BASE_URL}/api/bank/verify", json=BANK_VERIFY_PAYLOAD)
        _assert_kyc_blocked(r, "POST /api/bank/verify")

    def test_platform_fee_subscription_blocked_for_unverified(self, unverified_importer):
        """POST /api/platform-fees/create-annual-subscription blocked for email_unverified."""
        r = unverified_importer.post(f"{BASE_URL}/api/platform-fees/create-annual-subscription")
        _assert_kyc_blocked(r, "POST /api/platform-fees/create-annual-subscription")

    def test_document_delete_blocked_for_unverified(self, unverified_importer):
        """DELETE /api/documents/{id} blocked for email_unverified user."""
        r = unverified_importer.delete(f"{BASE_URL}/api/documents/nonexistent-file-id")
        _assert_kyc_blocked(r, "DELETE /api/documents/{id}")

    def test_sad_update_blocked_for_unverified(self, unverified_importer):
        """PUT /api/sad/{id} blocked for email_unverified user."""
        r = unverified_importer.put(
            f"{BASE_URL}/api/sad/507f1f77bcf86cd799439011",
            json=SAD_UPDATE_PAYLOAD
        )
        _assert_kyc_blocked(r, "PUT /api/sad/{id}")


# ── TESTS: Pending importer (email verified, KYC pending) ─────────────────────

def create_pending_session() -> requests.Session:
    """Register user, verify email via DB, return session (pending status)."""
    from pymongo import MongoClient
    uid = uuid.uuid4().hex[:8]
    email = f"test_pending_{uid}@test.ly"
    payload = {
        "email": email, "password": "Test@2026!",
        "name_ar": "معلق اختبار", "name_en": "Test Pending",
        "role": "importer",
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
    assert r.status_code == 200, f"Register failed: {r.status_code} {r.text}"

    # Get session from registration
    s = requests.Session()
    s.cookies.update(r.cookies)
    access_token = r.json().get("access_token")
    if access_token:
        s.cookies.set("access_token", access_token)

    # Get verify token from DB and call verify-email
    client = MongoClient("mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "libya_customs")
    db = client[db_name]
    user = db.users.find_one({"email": email})
    client.close()

    if user and user.get("email_verify_token"):
        token = user["email_verify_token"]
        vr = requests.get(f"{BASE_URL}/api/auth/verify-email/{token}")
        assert vr.status_code == 200, f"Email verify failed: {vr.status_code}"

    return s


class TestPendingUserBlocked:
    """Pending users (email_verified, KYC not approved) blocked on write endpoints."""

    @pytest.fixture(scope="class")
    def pending_session(self):
        try:
            return create_pending_session()
        except Exception as e:
            pytest.skip(f"Cannot create pending session: {e}")

    def test_wallet_topup_blocked_for_pending(self, pending_session):
        r = pending_session.post(f"{BASE_URL}/api/wallet/topup", json=WALLET_TOPUP_PAYLOAD)
        _assert_kyc_blocked(r, "POST /api/wallet/topup (pending)")

    def test_platform_fee_blocked_for_pending(self, pending_session):
        r = pending_session.post(f"{BASE_URL}/api/platform-fees/create-annual-subscription")
        _assert_kyc_blocked(r, "POST /api/platform-fees/create-annual-subscription (pending)")

    def test_sad_update_blocked_for_pending(self, pending_session):
        r = pending_session.put(
            f"{BASE_URL}/api/sad/507f1f77bcf86cd799439011",
            json=SAD_UPDATE_PAYLOAD
        )
        _assert_kyc_blocked(r, "PUT /api/sad/{id} (pending)")

    def test_registration_doc_upload_NOT_blocked_for_pending(self, pending_session):
        """
        EXCEPTION: POST /api/registration/docs/upload must NOT be blocked.
        Uses get_current_user (not require_approved_user).
        """
        import io
        files = {"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}
        data = {"doc_type": "national_id"}
        r = pending_session.post(
            f"{BASE_URL}/api/registration/docs/upload",
            files=files,
            data=data,
        )
        # Must NOT be 403 KYC_NOT_APPROVED
        if r.status_code == 403:
            detail = r.json().get("detail", {})
            code = detail.get("code") if isinstance(detail, dict) else str(detail)
            assert code != "KYC_NOT_APPROVED", (
                "FAIL: registration/docs/upload is KYC-blocking pending users (should be exception!)"
            )
        print(f"  ✅ PASS [registration/docs/upload (pending)]: Not KYC-blocked (status={r.status_code})")


# ── TESTS: Approved users NOT blocked ────────────────────────────────────────

class TestApprovedUsersNotBlocked:
    """Approved broker and carrier must NOT be blocked by KYC."""

    @pytest.fixture(scope="class")
    def broker_session(self):
        try:
            return login_session("broker@customs.ly", "Broker@2026!")
        except Exception as e:
            pytest.skip(f"Broker login failed: {e}")

    @pytest.fixture(scope="class")
    def carrier_session(self):
        try:
            return login_session("carrier@customs.ly", "Carrier@2026!")
        except Exception as e:
            pytest.skip(f"Carrier login failed: {e}")

    def test_approved_broker_wallet_topup_not_kyc_blocked(self, broker_session):
        """Approved broker: wallet topup NOT blocked by KYC (may fail for other reasons)."""
        r = broker_session.post(f"{BASE_URL}/api/wallet/topup", json=WALLET_TOPUP_PAYLOAD)
        _assert_not_kyc_blocked(r, "POST /api/wallet/topup (approved broker)")

    def test_approved_broker_platform_fee_not_kyc_blocked(self, broker_session):
        """Approved broker: platform fee subscription NOT blocked by KYC."""
        r = broker_session.post(f"{BASE_URL}/api/platform-fees/create-annual-subscription")
        _assert_not_kyc_blocked(r, "POST /api/platform-fees/create-annual-subscription (approved broker)")

    def test_approved_carrier_manifest_not_kyc_blocked(self, carrier_session):
        """Approved carrier: manifest creation NOT blocked by KYC."""
        r = carrier_session.post(f"{BASE_URL}/api/manifests", json=MANIFEST_PAYLOAD)
        _assert_not_kyc_blocked(r, "POST /api/manifests (approved carrier)")


# ── TESTS: Admin bypass ────────────────────────────────────────────────────────

class TestAdminBypassesKYC:
    """Admin user should not be blocked by any KYC check."""

    @pytest.fixture(scope="class")
    def admin_session(self):
        try:
            return login_session("admin@customs.ly", "Admin@2026!")
        except Exception as e:
            # Try cookies
            cookies = load_cookies("/tmp/admin_cookies.txt")
            if not cookies:
                pytest.skip(f"Admin login/cookies unavailable: {e}")
            s = requests.Session()
            s.cookies.update(cookies)
            return s

    def test_admin_wallet_topup_not_kyc_blocked(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/wallet/topup", json=WALLET_TOPUP_PAYLOAD)
        _assert_not_kyc_blocked(r, "POST /api/wallet/topup (admin)")

    def test_admin_manifest_create_not_kyc_blocked(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/manifests", json=MANIFEST_PAYLOAD)
        _assert_not_kyc_blocked(r, "POST /api/manifests (admin)")

    def test_admin_platform_fee_not_kyc_blocked(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/platform-fees/create-annual-subscription")
        _assert_not_kyc_blocked(r, "POST /api/platform-fees/create-annual-subscription (admin)")

    def test_admin_sad_update_not_kyc_blocked(self, admin_session):
        r = admin_session.put(
            f"{BASE_URL}/api/sad/507f1f77bcf86cd799439011",
            json=SAD_UPDATE_PAYLOAD
        )
        _assert_not_kyc_blocked(r, "PUT /api/sad/{id} (admin)")
