"""Phase 2 backend tests: Documents, SAD, AI Risk, Bank CBL, Public Verify"""
import pytest
import requests
import os
import io

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ACID_ID = "69d230091a546c000aada20e"
ACID_NUMBER = "ACID/2026/00001"

@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return s

@pytest.fixture(scope="module")
def importer_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "importer@test.ly", "password": "Test@2024!"})
    if r.status_code != 200:
        # Try creating importer
        reg = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": "importer@test.ly", "password": "Test@2024!",
            "name_ar": "مستورد تجريبي", "name_en": "Test Importer", "role": "importer"
        })
        r2 = s.post(f"{BASE_URL}/api/auth/login", json={"email": "importer@test.ly", "password": "Test@2024!"})
        if r2.status_code != 200:
            pytest.skip("Could not login as importer")
    return s


class TestDocumentAPIs:
    """Document upload and listing tests"""

    def test_upload_document(self, session):
        # Upload a test file
        files = {"file": ("test_invoice.pdf", io.BytesIO(b"%PDF-1.4 test commercial invoice content"), "application/pdf")}
        data = {"doc_type": "commercial_invoice"}
        # Remove Content-Type header for multipart
        headers = {k: v for k, v in session.headers.items() if k.lower() != "content-type"}
        r = requests.Request("POST", f"{BASE_URL}/api/documents/upload/{ACID_ID}",
                             files=files, data=data, headers=headers, cookies=session.cookies)
        prep = r.prepare()
        resp = session.send(prep)
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        body = resp.json()
        assert "file_id" in body or "document" in body or "message" in body

    def test_list_documents(self, session):
        r = session.get(f"{BASE_URL}/api/documents/{ACID_ID}")
        assert r.status_code == 200, f"List docs failed: {r.text}"
        assert isinstance(r.json(), list)


class TestSADAPIs:
    """SAD form creation and PDF tests"""

    sad_id = None

    def test_create_sad(self, session):
        r = session.post(f"{BASE_URL}/api/sad", json={
            "acid_id": ACID_ID,
            "customs_station": "طرابلس البحري",
            "declaration_type": "import"
        })
        assert r.status_code == 200, f"Create SAD failed: {r.text}"
        body = r.json()
        assert "sad" in body
        TestSADAPIs.sad_id = body["sad"]["_id"]

    def test_get_sad_by_acid(self, session):
        r = session.get(f"{BASE_URL}/api/sad/by-acid/{ACID_ID}")
        assert r.status_code == 200, f"Get SAD failed: {r.text}"
        body = r.json()
        assert "acid_id" in body or "acid_number" in body

    def test_download_sad_pdf(self, session):
        if not TestSADAPIs.sad_id:
            pytest.skip("No SAD ID available")
        r = session.get(f"{BASE_URL}/api/sad/{TestSADAPIs.sad_id}/pdf")
        assert r.status_code == 200, f"PDF download failed: {r.text}"
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert len(r.content) > 100  # PDF should have content


class TestAIRiskAPI:
    """AI Risk analysis tests"""

    def test_ai_risk_normal_goods(self, session):
        r = session.post(f"{BASE_URL}/api/risk/ai-analyze", json={
            "goods_description": "Electronic laptops and computers",
            "hs_code": "847130",
            "value_usd": 5000.0,
            "supplier_country": "China"
        })
        assert r.status_code == 200, f"AI risk failed: {r.text}"
        body = r.json()
        assert "risk_score" in body
        assert "route" in body
        assert body["route"] in ["green", "yellow", "red"]
        assert 0 <= body["risk_score"] <= 100

    def test_ai_risk_prohibited_goods(self, session):
        r = session.post(f"{BASE_URL}/api/risk/ai-analyze", json={
            "goods_description": "Alcoholic beverages - wine",
            "hs_code": "220421",
            "value_usd": 2000.0,
            "supplier_country": "France"
        })
        assert r.status_code == 200, f"AI risk failed: {r.text}"
        body = r.json()
        assert body["route"] == "red" or body["is_prohibited"] == True


class TestBankVerifyAPI:
    """Bank CBL mock verification tests"""

    def test_bank_verify_success(self, session):
        r = session.post(f"{BASE_URL}/api/bank/verify", json={
            "acid_number": ACID_NUMBER,
            "cbl_ref": "CBL20260001",
            "amount_lyd": 5000.0,
            "bank_name": "مصرف الوحدة"
        })
        assert r.status_code == 200, f"Bank verify failed: {r.text}"
        body = r.json()
        assert "is_verified" in body
        assert "status" in body
        assert "verification_id" in body

    def test_bank_verify_invalid_cbl(self, session):
        r = session.post(f"{BASE_URL}/api/bank/verify", json={
            "acid_number": ACID_NUMBER,
            "cbl_ref": "INVALID",
            "amount_lyd": 5000.0
        })
        assert r.status_code == 200, f"Bank verify failed: {r.text}"
        body = r.json()
        assert body["is_verified"] == False

    def test_bank_verify_wrong_acid(self, session):
        r = session.post(f"{BASE_URL}/api/bank/verify", json={
            "acid_number": "ACID/9999/99999",
            "cbl_ref": "CBL20260001",
            "amount_lyd": 5000.0
        })
        assert r.status_code == 404


class TestPublicVerify:
    """Public ACID verification (no auth)"""

    def test_public_verify_by_acid_number(self):
        r = requests.get(f"{BASE_URL}/api/public/verify/{ACID_NUMBER}")
        assert r.status_code == 200, f"Public verify failed: {r.text}"
        body = r.json()
        assert "acid_number" in body or "status" in body

    def test_public_verify_not_found(self):
        r = requests.get(f"{BASE_URL}/api/public/verify/ACID/9999/99999")
        assert r.status_code == 404
