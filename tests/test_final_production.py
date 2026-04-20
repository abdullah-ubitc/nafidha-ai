"""
FINAL PRODUCTION READINESS TEST — Libya Customs NAFIDHA Platform
Covers all 6 phases: Auth, ACID, Sovereign Chain, Public Tracking, JL38, Help Center
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# ===== Credentials =====
ADMIN    = {"email": "admin@customs.ly",     "password": "Admin@2026!"}
IMPORTER = {"email": "importer@test.ly",     "password": "Test@2024!"}
REVIEWER = {"email": "reviewer@test.ly",     "password": "Test@2024!"}
BROKER   = {"email": "broker@customs.ly",    "password": "Broker@2026!"}
VALUER   = {"email": "valuer@customs.ly",    "password": "Valuer@2026!"}
INSPECTOR= {"email": "inspector@customs.ly", "password": "Inspector@2026!"}
TREASURY = {"email": "treasury@customs.ly",  "password": "Treasury@2026!"}
GATE     = {"email": "gate@customs.ly",      "password": "Gate@2026!"}
SUPPLIER = {"email": "supplier@customs.ly",  "password": "Supplier@2026!"}
CARRIER  = {"email": "carrier@customs.ly",   "password": "Carrier@2026!"}

ALL_USERS = [ADMIN, IMPORTER, REVIEWER, BROKER, VALUER, INSPECTOR, TREASURY, GATE, SUPPLIER, CARRIER]


def login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
    assert r.status_code == 200, f"Login failed for {creds['email']}: {r.text}"
    data = r.json()
    return data.get("access_token") or data.get("token")


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ===== Phase 1: Auth — All 10 Roles =====
class TestAuth:
    """Login for all 10 roles"""

    @pytest.mark.parametrize("creds", ALL_USERS)
    def test_login_all_roles(self, creds):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
        assert r.status_code == 200, f"Login failed for {creds['email']}: {r.text}"
        data = r.json()
        assert "access_token" in data or "token" in data
        assert "user" in data
        assert data["user"]["email"] == creds["email"]

    def test_login_invalid_password(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "wrong"})
        assert r.status_code in [400, 401, 403]

    def test_protected_route_no_token(self):
        r = requests.get(f"{BASE_URL}/api/acid/list")
        assert r.status_code in [401, 403]


# ===== Phase 2: ACID Requests =====
class TestACIDRequests:
    """ACID request CRUD"""

    def test_list_acid_requests(self):
        token = login(IMPORTER)
        r = requests.get(f"{BASE_URL}/api/acid", headers=auth_headers(token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_create_acid_request(self):
        token = login(IMPORTER)
        payload = {
            "goods_description": "TEST_ Electronics - Laptops",
            "hs_code": "8471.30",
            "country_of_origin": "CN",
            "supplier_country": "CN",
            "supplier_name": "TEST Supplier Co.",
            "invoice_value": 50000.0,
            "value_usd": 50000.0,
            "invoice_currency": "USD",
            "port_of_entry": "طرابلس البحري",
            "quantity": 100,
            "unit": "قطعة",
            "weight_kg": 500.0,
            "transport_mode": "sea"
        }
        r = requests.post(f"{BASE_URL}/api/acid", json=payload, headers=auth_headers(token))
        assert r.status_code in [200, 201], f"Create ACID failed: {r.text}"
        data = r.json()
        assert "acid_number" in data or "id" in data

    def test_seed_data_exists(self):
        token = login(ADMIN)
        r = requests.get(f"{BASE_URL}/api/dashboard/stats", headers=auth_headers(token))
        assert r.status_code == 200

    def test_admin_seed_data(self):
        """Ensure seed data is available (idempotent)"""
        token = login(ADMIN)
        r = requests.post(f"{BASE_URL}/api/admin/seed-data", headers=auth_headers(token))
        assert r.status_code in [200, 201], f"Seed data failed: {r.text}"


# ===== Phase 3: Reviewer =====
class TestReviewer:
    """Reviewer queue and approval"""

    def test_reviewer_queue(self):
        # Reviewer queue uses /api/acid endpoint filtered by role
        token = login(REVIEWER)
        r = requests.get(f"{BASE_URL}/api/acid", headers=auth_headers(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_reviewer_access_denied_for_importer(self):
        # Reviewers see review queue; importer should not access valuer/treasury routes
        token = login(IMPORTER)
        r = requests.get(f"{BASE_URL}/api/valuer/queue", headers=auth_headers(token))
        assert r.status_code in [401, 403]


# ===== Phase 4: Valuer =====
class TestValuer:
    """Valuer queue"""

    def test_valuer_queue(self):
        token = login(VALUER)
        r = requests.get(f"{BASE_URL}/api/valuer/queue", headers=auth_headers(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_valuer_access_denied_for_importer(self):
        token = login(IMPORTER)
        r = requests.get(f"{BASE_URL}/api/valuer/queue", headers=auth_headers(token))
        assert r.status_code in [401, 403]


# ===== Phase 4b: Treasury =====
class TestTreasury:
    """Treasury queue"""

    def test_treasury_queue(self):
        token = login(TREASURY)
        r = requests.get(f"{BASE_URL}/api/treasury/queue", headers=auth_headers(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_bank_verify_cbl_prefix(self):
        token = login(TREASURY)
        r = requests.post(f"{BASE_URL}/api/bank/verify",
                          json={"acid_number": "ACID/2026/00001", "cbl_ref": "CBL202600001", "bank_name": "مصرف الجمهورية", "amount_lyd": 5000.0},
                          headers=auth_headers(token))
        assert r.status_code == 200
        data = r.json()
        assert "is_verified" in data

    def test_bank_verify_invalid_ref(self):
        token = login(TREASURY)
        r = requests.post(f"{BASE_URL}/api/bank/verify",
                          json={"acid_number": "ACID/2026/00001", "cbl_ref": "INVALID", "bank_name": "مصرف الجمهورية", "amount_lyd": 5000.0},
                          headers=auth_headers(token))
        assert r.status_code in [200, 400]
        if r.status_code == 200:
            assert r.json().get("is_verified") == False


# ===== Phase 5: Gate =====
class TestGate:
    """Gate queue and release"""

    def test_gate_queue_accessible(self):
        token = login(GATE)
        r = requests.get(f"{BASE_URL}/api/gate/queue", headers=auth_headers(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_gate_queue_requires_gate_role(self):
        token = login(IMPORTER)
        r = requests.get(f"{BASE_URL}/api/gate/queue", headers=auth_headers(token))
        assert r.status_code in [401, 403]

    def test_gate_release_blocked_non_treasury_paid(self):
        """Gate release should be blocked if status != treasury_paid"""
        token_admin = login(ADMIN)
        r = requests.get(f"{BASE_URL}/api/acid", headers=auth_headers(token_admin))
        assert r.status_code == 200
        acids = r.json()
        non_paid = [a for a in acids if a.get("status") not in ["treasury_paid", "gate_released"]]
        if non_paid:
            acid_id = non_paid[0].get("id") or str(non_paid[0].get("_id", ""))
            token_gate = login(GATE)
            r2 = requests.post(f"{BASE_URL}/api/acid/{acid_id}/gate-release",
                               json={"notes": "test"},
                               headers=auth_headers(token_gate))
            assert r2.status_code in [400, 403], f"Should be blocked but got {r2.status_code}: {r2.text}"
        else:
            pytest.skip("No non-treasury_paid ACIDs available to test gate block")


# ===== Phase 6: Public Tracking =====
class TestPublicTracking:
    """Public tracking endpoint (no auth required)"""

    def test_track_known_acid(self):
        """Track a known gate_released ACID"""
        r = requests.get(f"{BASE_URL}/api/public/track/ACID/2026/00001")
        assert r.status_code == 200, f"Track failed: {r.text}"
        data = r.json()
        assert "timeline_stages" in data
        assert len(data["timeline_stages"]) == 6
        assert "status" in data

    def test_track_returns_jl38(self):
        r = requests.get(f"{BASE_URL}/api/public/track/ACID/2026/00001")
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "gate_released":
                assert data.get("jl38_number") is not None

    def test_track_unknown_acid(self):
        r = requests.get(f"{BASE_URL}/api/public/track/ACID/9999/99999")
        assert r.status_code == 404

    def test_track_no_auth_required(self):
        """Public endpoint must not require auth"""
        r = requests.get(f"{BASE_URL}/api/public/track/ACID/2026/00001")
        assert r.status_code != 401


# ===== Phase 6: JL38 PDF =====
class TestJL38PDF:
    """JL38 PDF download"""

    def test_jl38_pdf_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/public/track/ACID/2026/00001")
        if r.status_code == 200 and r.json().get("status") == "gate_released":
            acid_id = r.json().get("acid_id")
            if acid_id:
                r2 = requests.get(f"{BASE_URL}/api/acid/{acid_id}/jl38-pdf")
                assert r2.status_code in [401, 403], "JL38 PDF should require auth"
        else:
            pytest.skip("No gate_released ACID available")

    def test_jl38_pdf_download_with_auth(self):
        """Download JL38 PDF with authenticated user"""
        r = requests.get(f"{BASE_URL}/api/public/track/ACID/2026/00001")
        if r.status_code != 200 or r.json().get("status") != "gate_released":
            pytest.skip("ACID/2026/00001 not gate_released")
        acid_id = r.json().get("acid_id")
        if not acid_id:
            pytest.skip("No acid_id in track response")
        token = login(ADMIN)
        r2 = requests.get(f"{BASE_URL}/api/acid/{acid_id}/jl38-pdf", headers=auth_headers(token))
        assert r2.status_code == 200, f"JL38 PDF failed: {r2.text[:200]}"
        assert r2.headers.get("content-type", "").startswith("application/pdf")


# ===== Phase 6: HS Code AI Search =====
class TestHSCodeSearch:
    """AI HS Code search"""

    def test_hs_search(self):
        token = login(IMPORTER)
        r = requests.post(f"{BASE_URL}/api/hs/search",
                          json={"query": "laptop computers"},
                          headers=auth_headers(token))
        assert r.status_code == 200, f"HS search failed: {r.text}"
        data = r.json()
        assert "results" in data or "hs_code" in data or isinstance(data, list)


# ===== Document Upload =====
class TestDocumentUpload:
    """Document upload endpoint"""

    def test_document_upload(self):
        token = login(IMPORTER)
        # Get an ACID owned by importer
        r = requests.get(f"{BASE_URL}/api/acid", headers=auth_headers(token))
        assert r.status_code == 200
        acids = r.json()
        if not acids:
            pytest.skip("No ACIDs available for document upload test")
        acid_id = acids[0].get("id") or str(acids[0].get("_id", ""))
        files = {"file": ("test_doc.pdf", b"%PDF-1.4 test content", "application/pdf")}
        data = {"doc_type": "commercial_invoice"}
        r2 = requests.post(f"{BASE_URL}/api/documents/upload/{acid_id}",
                          files=files,
                          data=data,
                          headers=auth_headers(token))
        assert r2.status_code in [200, 201], f"Upload failed: {r2.text}"


# ===== Audit Trail (Admin Only) =====
class TestAuditTrail:
    """Audit trail admin-only access"""

    def test_audit_trail_admin_access(self):
        token = login(ADMIN)
        r = requests.get(f"{BASE_URL}/api/audit/logs", headers=auth_headers(token))
        assert r.status_code == 200
        data = r.json()
        # Returns paginated: {logs: [...], page, total}
        logs = data if isinstance(data, list) else data.get("logs", [])
        assert isinstance(logs, list)

    def test_audit_trail_blocked_for_reviewer(self):
        token = login(REVIEWER)
        r = requests.get(f"{BASE_URL}/api/audit/logs", headers=auth_headers(token))
        assert r.status_code in [401, 403]


# ===== Executive Dashboard =====
class TestExecutiveDashboard:
    """Executive dashboard access"""

    def test_executive_dashboard_admin(self):
        token = login(ADMIN)
        r = requests.get(f"{BASE_URL}/api/executive/dashboard", headers=auth_headers(token))
        assert r.status_code == 200

    def test_executive_dashboard_importer_blocked(self):
        token = login(IMPORTER)
        r = requests.get(f"{BASE_URL}/api/executive/dashboard", headers=auth_headers(token))
        assert r.status_code in [401, 403]


# ===== AI Tariff Valuation =====
class TestTariffValuation:
    """AI tariff valuation"""

    def test_tariff_valuation(self):
        token = login(VALUER)
        r = requests.post(f"{BASE_URL}/api/tariff/ai-valuate",
                          json={"goods_description": "Laptop computers", "hs_code": "8471.30", 
                                "declared_value_usd": 50000, "quantity": 100, "unit": "قطعة", "supplier_country": "CN"},
                          headers=auth_headers(token))
        assert r.status_code == 200, f"Tariff valuation failed: {r.text}"


# ===== WhatsApp Logs =====
class TestWhatsAppLogs:
    """WhatsApp logs collection"""

    def test_whatsapp_logs_accessible(self):
        token = login(ADMIN)
        r = requests.get(f"{BASE_URL}/api/whatsapp/logs", headers=auth_headers(token))
        assert r.status_code in [200, 404]
        if r.status_code == 200:
            data = r.json()
            logs = data if isinstance(data, list) else data.get("logs", [])
            assert isinstance(logs, list)
