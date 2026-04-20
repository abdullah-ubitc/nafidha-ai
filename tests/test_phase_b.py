"""Phase B backend tests: PGA, Violations, Guarantees, SAD JL119 PDF"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

def get_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json().get("access_token")
    return None

@pytest.fixture(scope="module")
def pga_headers():
    token = get_token("pga@customs.ly", "PGA@2026!")
    assert token, "PGA officer login failed"
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture(scope="module")
def violations_headers():
    token = get_token("violations@customs.ly", "Violations@2026!")
    assert token, "Violations officer login failed"
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture(scope="module")
def treasury_headers():
    token = get_token("treasury@customs.ly", "Treasury@2026!")
    assert token, "Treasury officer login failed"
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture(scope="module")
def admin_headers():
    token = get_token("admin@customs.ly", "Admin@2026!")
    assert token, "Admin login failed"
    return {"Authorization": f"Bearer {token}"}

# PGA Tests
class TestPGA:
    """PGA officer tests"""

    def test_pga_login(self):
        token = get_token("pga@customs.ly", "PGA@2026!")
        assert token is not None
        print("PGA login: PASS")

    def test_pga_queue(self, pga_headers):
        r = requests.get(f"{BASE_URL}/api/pga/queue", headers=pga_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"PGA queue: {len(data)} items - PASS")

    def test_pga_stats(self, pga_headers):
        r = requests.get(f"{BASE_URL}/api/pga/stats", headers=pga_headers)
        assert r.status_code == 200
        data = r.json()
        assert "pending" in data
        print(f"PGA stats: {data} - PASS")

    def test_pga_review_approve(self, pga_headers):
        # Get queue to find an acid_id
        r = requests.get(f"{BASE_URL}/api/pga/queue", headers=pga_headers)
        queue = r.json()
        if not queue:
            pytest.skip("PGA queue is empty")
        acid_id = queue[0].get("acid_id") or queue[0].get("_id") or queue[0].get("id")
        payload = {
            "action": "approve",
            "agency_name": "وزارة الصحة",
            "reference_number": "TEST_REF_001",
            "notes": "Test approval"
        }
        r2 = requests.post(f"{BASE_URL}/api/pga/{acid_id}/review", json=payload, headers=pga_headers)
        assert r2.status_code == 200
        data = r2.json()
        assert "pga_status" in data
        assert data["pga_status"] == "approved"
        print(f"PGA review approve: {data} - PASS")

# Violations Tests
class TestViolations:
    """Violations officer tests"""

    def test_violations_login(self):
        token = get_token("violations@customs.ly", "Violations@2026!")
        assert token is not None
        print("Violations login: PASS")

    def test_create_violation(self, violations_headers):
        # Get an ACID ID first
        r = requests.get(f"{BASE_URL}/api/acid-risk/queue", headers=violations_headers)
        acid_list = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []
        if not acid_list:
            # Try admin endpoint
            admin_token = get_token("admin@customs.ly", "Admin@2026!")
            r2 = requests.get(f"{BASE_URL}/api/acid-risk/queue", headers={"Authorization": f"Bearer {admin_token}"})
            acid_list = r2.json() if r2.status_code == 200 and isinstance(r2.json(), list) else []
        
        acid_id = acid_list[0].get("_id") or acid_list[0].get("acid_id") or acid_list[0].get("id") if acid_list else None
        if not acid_id:
            pytest.skip("No ACID IDs available")

        payload = {
            "acid_id": acid_id,
            "violation_type": "under_declaration",
            "description_ar": "اختبار - تم اكتشاف تخفيض في القيمة"
        }
        r2 = requests.post(f"{BASE_URL}/api/violations", json=payload, headers=violations_headers)
        assert r2.status_code in [200, 201]
        data = r2.json()
        # Check violation number format VIO/YEAR/NNNNN
        vio_number = data.get("violation_number") or data.get("number") or ""
        print(f"Created violation: {vio_number} - PASS")
        return data

    def test_list_violations(self, violations_headers):
        r = requests.get(f"{BASE_URL}/api/violations", headers=violations_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"List violations: {len(data)} items - PASS")

    def test_violation_number_format(self, violations_headers):
        r = requests.get(f"{BASE_URL}/api/violations", headers=violations_headers)
        violations = r.json()
        if violations:
            vio_num = violations[0].get("violation_number", "")
            assert vio_num.startswith("VIO/"), f"Expected VIO/ format, got: {vio_num}"
            print(f"Violation number format correct: {vio_num} - PASS")
        else:
            pytest.skip("No violations to check format")

    def test_issue_fine(self, violations_headers):
        r = requests.get(f"{BASE_URL}/api/violations", headers=violations_headers)
        violations = r.json()
        if not violations:
            pytest.skip("No violations to fine")
        vio_id = str(violations[0].get("id") or violations[0].get("_id", ""))
        payload = {"fine_amount_lyd": 5000, "fine_reason": "Undervaluation penalty"}
        r2 = requests.put(f"{BASE_URL}/api/violations/{vio_id}/fine", json=payload, headers=violations_headers)
        assert r2.status_code == 200
        print(f"Issue fine: PASS")

# Guarantees Tests
class TestGuarantees:
    """Treasury officer guarantees tests"""

    def test_treasury_login(self):
        token = get_token("treasury@customs.ly", "Treasury@2026!")
        assert token is not None
        print("Treasury login: PASS")

    def test_create_guarantee(self, treasury_headers):
        # Use known ACID ID from seed data
        admin_token = get_token("admin@customs.ly", "Admin@2026!")
        r = requests.get(f"{BASE_URL}/api/acid-risk/queue", headers={"Authorization": f"Bearer {admin_token}"})
        items = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []
        acid_id = items[0].get("_id") if items else "69d2509b50dc89e64841a3bb"

        payload = {
            "acid_id": acid_id,
            "amount_lyd": 10000,
            "guarantee_type": "bank_guarantee",
            "beneficiary": "عمليات الجمارك"
        }
        r2 = requests.post(f"{BASE_URL}/api/guarantees", json=payload, headers=treasury_headers)
        assert r2.status_code in [200, 201]
        data = r2.json()
        gua_number = data.get("guarantee_number") or data.get("number") or ""
        print(f"Created guarantee: {gua_number} - PASS")

    def test_guarantee_number_format(self, treasury_headers):
        r = requests.get(f"{BASE_URL}/api/guarantees", headers=treasury_headers)
        assert r.status_code == 200
        guarantees = r.json()
        if guarantees:
            gua_num = guarantees[0].get("guarantee_number", "")
            assert gua_num.startswith("GUA/"), f"Expected GUA/ format, got: {gua_num}"
            print(f"Guarantee number format correct: {gua_num} - PASS")
        else:
            pytest.skip("No guarantees to check format")

    def test_list_guarantees(self, treasury_headers):
        r = requests.get(f"{BASE_URL}/api/guarantees", headers=treasury_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"List guarantees: {len(data)} items - PASS")

    def test_guarantees_stats(self, treasury_headers):
        r = requests.get(f"{BASE_URL}/api/guarantees/stats", headers=treasury_headers)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        print(f"Guarantees stats: {data} - PASS")

# SAD JL119 PDF
class TestSADPDF:
    """SAD JL119 PDF download tests"""

    def test_jl119_pdf_download(self, admin_headers):
        sad_id = "69d238f97c24aea5be0b5946"
        r = requests.get(f"{BASE_URL}/api/sad/{sad_id}/jl119-pdf", headers=admin_headers)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert len(r.content) > 100
        print(f"JL119 PDF: {len(r.content)} bytes - PASS")

    def test_jl119_pdf_unauthorized(self):
        sad_id = "69d238f97c24aea5be0b5946"
        r = requests.get(f"{BASE_URL}/api/sad/{sad_id}/jl119-pdf")
        assert r.status_code in [401, 403]
        print("JL119 PDF unauthorized: PASS")
