"""
Phase 2026 Importer Registration Re-engineering Tests (Iteration 45)
Tests: register with Phase 2026 fields, new DOC_TYPES upload acceptance
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestImporterRegistrationPhase2026:
    """Test 1: POST /api/auth/register with importer + Phase 2026 fields"""

    def test_register_importer_phase2026_fields_stored(self):
        """Register importer with Phase 2026 fields and verify they are stored"""
        ts = int(time.time())
        payload = {
            "email": f"TEST_wizard_iter45_{ts}@test.ly",
            "password": "TestPass@2026!",
            "role": "importer",
            "name_ar": "شركة اختبار المستورد",
            "name_en": "Test Importer Co",
            "entity_type": "company",
            # Phase 2026 fields
            "legal_name_ar": "شركة اختبار المستورد للتجارة",
            "legal_name_en": "Test Importer Trading Co",
            "cr_number": "CR-2024-TEST45",
            "cr_expiry_date": "2026-12-31",
            "vat_number": "LY-VAT-12345",
            "address_ar": "طريق الميناء، طرابلس",
            "address_en": "Port Road, Tripoli",
            "statistical_code": "SC-TEST-45678",
            "statistical_expiry_date": "2025-06-30",
            "rep_full_name_ar": "أحمد محمد الاختبار",
            "rep_full_name_en": "Ahmed M. Test",
            "rep_id_type": "national_id",
            "rep_id_number": "1234567890",
            "rep_nationality": "ليبي",
            "rep_job_title": "signing_manager",
            "rep_mobile": "218912345678",
        }
        res = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
        assert res.status_code == 200, f"Register failed: {res.status_code} — {res.text}"
        data = res.json()

        # Check response structure
        assert "user" in data
        assert "access_token" in data
        user = data["user"]

        # Verify Phase 2026 fields in response
        assert user.get("legal_name_ar") == payload["legal_name_ar"], f"legal_name_ar mismatch: {user.get('legal_name_ar')}"
        assert user.get("legal_name_en") == payload["legal_name_en"]
        assert user.get("cr_number") == payload["cr_number"]
        assert user.get("cr_expiry_date") == payload["cr_expiry_date"]
        assert user.get("statistical_code") == payload["statistical_code"]
        assert user.get("statistical_expiry_date") == payload["statistical_expiry_date"]
        assert user.get("rep_full_name_ar") == payload["rep_full_name_ar"]
        assert user.get("rep_job_title") == payload["rep_job_title"]
        assert user.get("rep_mobile") == payload["rep_mobile"]
        assert user.get("role") == "importer"
        assert user.get("registration_status") == "email_unverified"

        print(f"✅ Phase 2026 fields stored correctly for {payload['email']}")
        # Store token for cleanup
        self.__class__.access_token = data["access_token"]
        self.__class__.user_id = user.get("_id")

    def test_register_importer_duplicate_email_rejected(self):
        """Duplicate email should return 400"""
        # Use wizard_test_importer which already exists
        payload = {
            "email": "wizard_test_importer@test.ly",
            "password": "TestPass@2026!",
            "role": "importer",
            "name_ar": "test",
            "name_en": "test",
        }
        res = requests.post(f"{BASE_URL}/api/auth/register", json=payload)
        assert res.status_code == 400, f"Expected 400, got {res.status_code}"
        print("✅ Duplicate email correctly rejected with 400")


class TestDocUploadNewDocTypes:
    """Test 2: New DOC_TYPES accepted in POST /api/registration/docs/upload"""

    @pytest.fixture(autouse=True)
    def get_token(self):
        """Login as wizard_test_importer to get auth token"""
        res = requests.post(f"{BASE_URL}/api/auth/login",
                            json={"email": "wizard_test_importer@test.ly", "password": "TestPass@2026!"})
        assert res.status_code == 200, f"Login failed: {res.status_code}"
        self.token = res.json()["access_token"]

    def _upload_doc(self, doc_type, file_content=b"test content", filename="test.jpg"):
        headers = {"Authorization": f"Bearer {self.token}"}
        files = {"file": (filename, file_content, "image/jpeg")}
        data = {"doc_type": doc_type}
        return requests.post(
            f"{BASE_URL}/api/registration/docs/upload",
            headers=headers,
            files=files,
            data=data,
        )

    def test_upload_commercial_registry_front(self):
        """commercial_registry_front should be accepted (200)"""
        res = self._upload_doc("commercial_registry_front")
        assert res.status_code == 200, f"Expected 200, got {res.status_code} — {res.text}"
        data = res.json()
        assert data.get("doc_type") == "commercial_registry_front"
        assert "file_id" in data
        print(f"✅ commercial_registry_front uploaded: file_id={data['file_id']}")

    def test_upload_commercial_registry_back(self):
        """commercial_registry_back should be accepted (200)"""
        res = self._upload_doc("commercial_registry_back")
        assert res.status_code == 200, f"Expected 200, got {res.status_code} — {res.text}"
        print("✅ commercial_registry_back accepted")

    def test_upload_national_id_front(self):
        """national_id_front should be accepted (200)"""
        res = self._upload_doc("national_id_front")
        assert res.status_code == 200, f"Expected 200, got {res.status_code} — {res.text}"
        print("✅ national_id_front accepted")

    def test_upload_national_id_back(self):
        """national_id_back should be accepted (200)"""
        res = self._upload_doc("national_id_back")
        assert res.status_code == 200, f"Expected 200, got {res.status_code} — {res.text}"
        print("✅ national_id_back accepted")

    def test_upload_statistical_cert_front(self):
        """statistical_cert_front should be accepted (200)"""
        res = self._upload_doc("statistical_cert_front")
        assert res.status_code == 200, f"Expected 200, got {res.status_code} — {res.text}"
        print("✅ statistical_cert_front accepted")

    def test_upload_statistical_cert_back(self):
        """statistical_cert_back should be accepted (200)"""
        res = self._upload_doc("statistical_cert_back")
        assert res.status_code == 200, f"Expected 200, got {res.status_code} — {res.text}"
        print("✅ statistical_cert_back accepted")

    def test_upload_authorization_letter(self):
        """authorization_letter should be accepted (200)"""
        res = self._upload_doc("authorization_letter")
        assert res.status_code == 200, f"Expected 200, got {res.status_code} — {res.text}"
        print("✅ authorization_letter accepted")

    def test_upload_invalid_doc_type_rejected(self):
        """Invalid doc_type should return 400"""
        res = self._upload_doc("invalid_doc_type_xyz")
        assert res.status_code == 400, f"Expected 400, got {res.status_code}"
        print("✅ Invalid doc_type correctly rejected with 400")


class TestExpiryAlertData:
    """Test 10: Verify wizard_test_importer has correct expiry dates in DB"""

    def test_wizard_importer_has_expired_statistical_date(self):
        """wizard_test_importer should have statistical_expiry_date=2024-06-01 (expired)"""
        # Login as reg_officer to see user details
        login_res = requests.post(f"{BASE_URL}/api/auth/login",
                                  json={"email": "reg_officer@customs.ly", "password": "RegOfficer@2026!"})
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]

        # Get list of pending/all registrations and find wizard_test_importer
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get(f"{BASE_URL}/api/kyc/registrations?status=pending", headers=headers)
        assert res.status_code == 200, f"Failed: {res.status_code}"
        
        users = res.json()
        wiz_user = next((u for u in users if u.get("email") == "wizard_test_importer@test.ly"), None)
        
        if wiz_user is None:
            # Try approved or any status
            for status in ["approved", "needs_correction"]:
                res2 = requests.get(f"{BASE_URL}/api/kyc/registrations?status={status}", headers=headers)
                if res2.status_code == 200:
                    users2 = res2.json()
                    wiz_user = next((u for u in users2 if u.get("email") == "wizard_test_importer@test.ly"), None)
                    if wiz_user:
                        break
        
        assert wiz_user is not None, "wizard_test_importer@test.ly not found in registrations"
        stat_exp = wiz_user.get("statistical_expiry_date")
        print(f"wizard_test_importer statistical_expiry_date: {stat_exp}")
        print(f"wizard_test_importer cr_expiry_date: {wiz_user.get('cr_expiry_date')}")
        assert stat_exp == "2024-06-01", f"Expected 2024-06-01, got {stat_exp}"
        print("✅ wizard_test_importer has statistical_expiry_date=2024-06-01 (expired) in DB")
