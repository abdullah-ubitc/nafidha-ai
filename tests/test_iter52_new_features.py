"""
Iteration 52 Backend Tests:
- GET /api/payments/stats — revenue stats for admin
- POST /api/payments/admin/config — update ACID fee
- POST /api/ocr/extract-cr — OCR CR extraction
- POST /api/ocr/extract-container — OCR container code extraction
"""
import pytest
import requests
import os
import io

# Load frontend .env for REACT_APP_BACKEND_URL
_env_path = "/app/frontend/.env"
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def inspector_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "inspector@customs.ly", "password": "Inspector@2026!"})
    assert r.status_code == 200, f"Inspector login failed: {r.text}"
    return r.json()["access_token"]


class TestPaymentStats:
    """Tests for GET /api/payments/stats endpoint"""

    def test_stats_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/payments/stats")
        assert r.status_code in (401, 403), f"Expected auth error, got {r.status_code}"

    def test_stats_admin_returns_correct_structure(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/payments/stats",
                         headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200, f"Stats failed: {r.text}"
        data = r.json()
        # Check required top-level keys
        assert "summary" in data, "Missing 'summary' key"
        assert "monthly" in data, "Missing 'monthly' key"
        assert "recent" in data, "Missing 'recent' key"
        assert "pending_count" in data, "Missing 'pending_count' key"
        assert "pending_amount" in data, "Missing 'pending_amount' key"

    def test_stats_summary_has_required_fields(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/payments/stats",
                         headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        summary = r.json()["summary"]
        for field in ["total_revenue", "verification_revenue", "acid_fee_revenue",
                      "total_count", "verification_count", "acid_fee_count"]:
            assert field in summary, f"Missing summary field: {field}"

    def test_stats_monthly_is_list(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/payments/stats",
                         headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert isinstance(r.json()["monthly"], list)

    def test_stats_recent_is_list(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/payments/stats",
                         headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert isinstance(r.json()["recent"], list)

    def test_stats_non_admin_forbidden(self, inspector_token):
        r = requests.get(f"{BASE_URL}/api/payments/stats",
                         headers={"Authorization": f"Bearer {inspector_token}"})
        assert r.status_code in (403, 401), f"Expected 403, got {r.status_code}"


class TestPaymentAdminConfig:
    """Tests for POST /api/payments/admin/config"""

    def test_update_acid_fee_success(self, admin_token):
        r = requests.post(f"{BASE_URL}/api/payments/admin/config",
                          json={"amount_usd": 75.0},
                          headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200, f"Failed: {r.text}"
        data = r.json()
        assert data["amount_usd"] == 75.0

    def test_get_config_reflects_update(self, admin_token):
        # Set to 60
        requests.post(f"{BASE_URL}/api/payments/admin/config",
                      json={"amount_usd": 60.0},
                      headers={"Authorization": f"Bearer {admin_token}"})
        # GET to verify
        r = requests.get(f"{BASE_URL}/api/payments/admin/config",
                         headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert r.json()["acid_fee_usd"] == 60.0

    def test_update_acid_fee_zero_rejected(self, admin_token):
        r = requests.post(f"{BASE_URL}/api/payments/admin/config",
                          json={"amount_usd": 0},
                          headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 400

    def test_update_fee_non_admin_forbidden(self, inspector_token):
        r = requests.post(f"{BASE_URL}/api/payments/admin/config",
                          json={"amount_usd": 100.0},
                          headers={"Authorization": f"Bearer {inspector_token}"})
        assert r.status_code in (403, 401)

    def test_restore_default_fee(self, admin_token):
        """Restore to default 50 after tests"""
        r = requests.post(f"{BASE_URL}/api/payments/admin/config",
                          json={"amount_usd": 50.0},
                          headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200


class TestOCRExtractCR:
    """Tests for POST /api/ocr/extract-cr"""

    def test_extract_cr_requires_auth(self):
        dummy = io.BytesIO(b"dummy image content")
        r = requests.post(f"{BASE_URL}/api/ocr/extract-cr",
                          files={"file": ("test.jpg", dummy, "image/jpeg")})
        assert r.status_code in (401, 403), f"Expected auth error, got {r.status_code}"

    def test_extract_cr_returns_expected_keys(self, admin_token):
        """Send a small dummy image — expect JSON with cr_number/cr_expiry keys"""
        # 1x1 white JPEG (smallest valid JPEG)
        tiny_jpeg = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
            0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
            0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
            0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
            0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
            0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
            0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
            0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
            0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
            0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
            0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
            0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
            0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
            0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
            0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
            0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
            0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
            0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
            0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
            0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
            0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
            0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
            0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD0, 0xFF, 0xD9
        ])
        r = requests.post(f"{BASE_URL}/api/ocr/extract-cr",
                          files={"file": ("test.jpg", io.BytesIO(tiny_jpeg), "image/jpeg")},
                          headers={"Authorization": f"Bearer {admin_token}"})
        # Should return 200 with JSON (even if cr_number is null - no real document)
        assert r.status_code == 200, f"OCR extract-cr failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "cr_number" in data, "Missing cr_number key"
        assert "cr_expiry" in data, "Missing cr_expiry key"
        assert "confidence" in data, "Missing confidence key"
        print(f"OCR CR result: cr_number={data.get('cr_number')}, confidence={data.get('confidence')}")


class TestOCRExtractContainer:
    """Tests for POST /api/ocr/extract-container"""

    def test_extract_container_requires_auth(self):
        dummy = io.BytesIO(b"dummy")
        r = requests.post(f"{BASE_URL}/api/ocr/extract-container",
                          files={"file": ("test.jpg", dummy, "image/jpeg")})
        assert r.status_code in (401, 403)

    def test_extract_container_returns_expected_keys(self, admin_token):
        tiny_jpeg = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
            0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
            0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
            0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
            0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
            0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
            0x09, 0x0A, 0x0B, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F,
            0x00, 0xFB, 0xD0, 0xFF, 0xD9
        ])
        r = requests.post(f"{BASE_URL}/api/ocr/extract-container",
                          files={"file": ("container.jpg", io.BytesIO(tiny_jpeg), "image/jpeg")},
                          headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200, f"OCR extract-container failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "container_code" in data, "Missing container_code key"
        assert "confidence" in data, "Missing confidence key"
        print(f"OCR Container result: container_code={data.get('container_code')}, confidence={data.get('confidence')}")
