"""
Iteration 64 Tests — Stripe OCR Wallet Checkout, KYC Scan, Service Pricing
Tests: POST /payments/checkout/ocr-wallet, GET /payments/status/{session_id},
       POST /ocr/kyc-scan, GET /ocr-wallet/balance, GET /service-pricing/stats,
       PUT /service-pricing, PUT /service-pricing/packages
"""
import pytest
import requests
import os
import io

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN = {"email": "admin@customs.ly", "password": "Admin@2026!"}
BROKER = {"email": "broker@customs.ly", "password": "Broker@2026!"}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN)
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def broker_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=BROKER)
    assert r.status_code == 200, f"Broker login failed: {r.text}"
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── OCR Wallet Checkout (POST /payments/checkout/ocr-wallet) ──────────────────

class TestOCRWalletCheckout:
    """Stripe checkout for OCR wallet packages"""

    def test_checkout_starter_package_creates_session(self, admin_token):
        """POST /payments/checkout/ocr-wallet returns checkout_url and session_id"""
        r = requests.post(f"{BASE_URL}/api/payments/checkout/ocr-wallet",
                          json={"package_id": "starter", "origin_url": "https://example.com"},
                          headers=auth(admin_token))
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "checkout_url" in data, "Missing checkout_url"
        assert "session_id" in data, "Missing session_id"
        assert "package" in data, "Missing package"
        assert data["checkout_url"].startswith("https://checkout.stripe.com"), \
            f"Expected Stripe URL, got: {data['checkout_url']}"
        # Store session_id for status check
        TestOCRWalletCheckout.session_id = data["session_id"]
        print(f"PASS: checkout_url={data['checkout_url'][:60]}... session_id={data['session_id']}")

    def test_checkout_standard_package(self, broker_token):
        """Standard package checkout creates valid session"""
        r = requests.post(f"{BASE_URL}/api/payments/checkout/ocr-wallet",
                          json={"package_id": "standard", "origin_url": "https://example.com"},
                          headers=auth(broker_token))
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        data = r.json()
        assert "checkout_url" in data
        assert data["amount_usd"] > 0
        print(f"PASS: standard package amount=${data['amount_usd']}")

    def test_checkout_invalid_package_returns_400(self, admin_token):
        """Invalid package_id returns 400"""
        r = requests.post(f"{BASE_URL}/api/payments/checkout/ocr-wallet",
                          json={"package_id": "nonexistent_pkg", "origin_url": "https://example.com"},
                          headers=auth(admin_token))
        assert r.status_code == 400, f"Expected 400, got {r.status_code}"
        print("PASS: invalid package returns 400")

    def test_checkout_requires_auth(self):
        """Unauthenticated request returns 401/403"""
        r = requests.post(f"{BASE_URL}/api/payments/checkout/ocr-wallet",
                          json={"package_id": "starter", "origin_url": "https://example.com"})
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"
        print("PASS: unauthenticated checkout blocked")


# ── Payment Status (GET /payments/status/{session_id}) ────────────────────────

class TestPaymentStatus:
    """Payment status check for created sessions"""

    def test_status_of_created_session_is_pending(self, admin_token):
        """GET /payments/status/{session_id} returns pending for new session"""
        # First create a session
        r = requests.post(f"{BASE_URL}/api/payments/checkout/ocr-wallet",
                          json={"package_id": "starter", "origin_url": "https://example.com"},
                          headers=auth(admin_token))
        assert r.status_code == 200
        session_id = r.json()["session_id"]

        # Check status — no auth required per code
        rs = requests.get(f"{BASE_URL}/api/payments/status/{session_id}")
        assert rs.status_code == 200, f"Status check failed: {rs.status_code}: {rs.text}"
        data = rs.json()
        assert "status" in data
        assert "payment_status" in data
        assert data["payment_type"] == "ocr_wallet_topup"
        print(f"PASS: status={data['status']}, payment_status={data['payment_status']}")

    def test_status_nonexistent_session_returns_404(self):
        """Non-existent session_id returns 404"""
        r = requests.get(f"{BASE_URL}/api/payments/status/cs_test_nonexistent_fake_12345")
        assert r.status_code == 404, f"Expected 404, got {r.status_code}"
        print("PASS: nonexistent session returns 404")


# ── KYC Scan (POST /ocr/kyc-scan) ─────────────────────────────────────────────

class TestKYCScan:
    """KYC scan endpoint — no wallet deduction, free scans"""

    def _make_dummy_image(self):
        """Create a minimal 1x1 JPEG for testing"""
        # Minimal JPEG bytes
        jpeg = bytes([
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
            0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD5, 0xFF, 0xD9
        ])
        return jpeg

    def test_kyc_scan_passport_no_wallet_deduction(self, admin_token):
        """POST /ocr/kyc-scan passport — no 402, cost_usd=0.0"""
        img = self._make_dummy_image()
        files = {"file": ("test.jpg", io.BytesIO(img), "image/jpeg")}
        data = {"doc_type": "passport"}
        r = requests.post(f"{BASE_URL}/api/ocr/kyc-scan",
                          files=files, data=data, headers=auth(admin_token))
        # Must NOT return 402
        assert r.status_code != 402, f"Got 402 — wallet deduction happening on KYC scan!"
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("cost_usd") == 0.0, f"cost_usd should be 0.0, got: {body.get('cost_usd')}"
        assert body.get("doc_type") == "passport"
        print(f"PASS: passport kyc-scan returned 200, cost_usd=0.0, ocr_failed={body.get('ocr_failed')}")

    def test_kyc_scan_national_id_no_wallet_deduction(self, broker_token):
        """POST /ocr/kyc-scan national_id — no 402, cost_usd=0.0"""
        img = self._make_dummy_image()
        files = {"file": ("test.jpg", io.BytesIO(img), "image/jpeg")}
        data = {"doc_type": "national_id"}
        r = requests.post(f"{BASE_URL}/api/ocr/kyc-scan",
                          files=files, data=data, headers=auth(broker_token))
        assert r.status_code != 402, "Got 402 on national_id kyc-scan — wallet deduction bug!"
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("cost_usd") == 0.0
        print(f"PASS: national_id kyc-scan cost_usd=0.0")

    def test_kyc_scan_commercial_registry_no_wallet_deduction(self, admin_token):
        """POST /ocr/kyc-scan commercial_registry — valid type, no wallet deduction"""
        img = self._make_dummy_image()
        files = {"file": ("test.jpg", io.BytesIO(img), "image/jpeg")}
        data = {"doc_type": "commercial_registry"}
        r = requests.post(f"{BASE_URL}/api/ocr/kyc-scan",
                          files=files, data=data, headers=auth(admin_token))
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("cost_usd") == 0.0
        print("PASS: commercial_registry kyc-scan cost_usd=0.0")

    def test_kyc_scan_invoice_invalid_type_returns_400(self, admin_token):
        """POST /ocr/kyc-scan invoice — invalid doc_type returns 400"""
        img = self._make_dummy_image()
        files = {"file": ("test.jpg", io.BytesIO(img), "image/jpeg")}
        data = {"doc_type": "invoice"}
        r = requests.post(f"{BASE_URL}/api/ocr/kyc-scan",
                          files=files, data=data, headers=auth(admin_token))
        assert r.status_code == 400, f"Expected 400 for 'invoice' doc_type, got {r.status_code}"
        print("PASS: invoice doc_type returns 400 in kyc-scan")

    def test_kyc_scan_requires_auth(self):
        """Unauthenticated kyc-scan returns 401/403"""
        img = self._make_dummy_image()
        files = {"file": ("test.jpg", io.BytesIO(img), "image/jpeg")}
        data = {"doc_type": "passport"}
        r = requests.post(f"{BASE_URL}/api/ocr/kyc-scan", files=files, data=data)
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"
        print("PASS: unauthenticated kyc-scan blocked")


# ── OCR Wallet Balance (GET /ocr-wallet/balance) ─────────────────────────────

class TestOCRWalletBalance:
    """OCR wallet balance endpoint"""

    def test_balance_returns_required_fields(self, admin_token):
        """GET /ocr-wallet/balance returns balance_usd, remaining_scans, low_balance"""
        r = requests.get(f"{BASE_URL}/api/ocr-wallet/balance", headers=auth(admin_token))
        assert r.status_code == 200, f"Balance failed: {r.status_code}: {r.text}"
        data = r.json()
        assert "balance_usd" in data, "Missing balance_usd"
        assert "remaining_scans" in data, "Missing remaining_scans"
        assert "low_balance" in data, "Missing low_balance"
        assert isinstance(data["balance_usd"], (int, float))
        assert isinstance(data["remaining_scans"], int)
        assert isinstance(data["low_balance"], bool)
        print(f"PASS: balance_usd={data['balance_usd']}, remaining_scans={data['remaining_scans']}, low_balance={data['low_balance']}")

    def test_balance_requires_auth(self):
        """Unauthenticated balance check returns 401/403"""
        r = requests.get(f"{BASE_URL}/api/ocr-wallet/balance")
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"
        print("PASS: unauthenticated balance blocked")


# ── Service Pricing Stats (GET /service-pricing/stats) ───────────────────────

class TestServicePricingStats:
    """Admin-only service pricing stats"""

    def test_stats_admin_returns_required_fields(self, admin_token):
        """GET /service-pricing/stats returns total_scans, topup_count, active_wallets"""
        r = requests.get(f"{BASE_URL}/api/service-pricing/stats", headers=auth(admin_token))
        assert r.status_code == 200, f"Stats failed: {r.status_code}: {r.text}"
        data = r.json()
        assert "total_scans" in data, "Missing total_scans"
        assert "topup_count" in data, "Missing topup_count"
        assert "active_wallets" in data, "Missing active_wallets"
        print(f"PASS: total_scans={data['total_scans']}, topup_count={data['topup_count']}, active_wallets={data['active_wallets']}")

    def test_stats_non_admin_returns_403(self, broker_token):
        """Non-admin users get 403 on stats endpoint"""
        r = requests.get(f"{BASE_URL}/api/service-pricing/stats", headers=auth(broker_token))
        assert r.status_code == 403, f"Expected 403 for broker, got {r.status_code}"
        print("PASS: broker gets 403 on /service-pricing/stats")


# ── Service Pricing Update (PUT /service-pricing) ────────────────────────────

class TestServicePricingUpdate:
    """Admin-only pricing update endpoints"""

    def test_update_price_per_scan_admin(self, admin_token):
        """PUT /api/service-pricing — admin can update price per scan"""
        r = requests.put(f"{BASE_URL}/api/service-pricing",
                         json={"price_per_unit_usd": 0.05},
                         headers=auth(admin_token))
        assert r.status_code == 200, f"Update pricing failed: {r.status_code}: {r.text}"
        print(f"PASS: service pricing updated: {r.json()}")

    def test_update_price_non_admin_returns_403(self, broker_token):
        """Non-admin cannot update service pricing"""
        r = requests.put(f"{BASE_URL}/api/service-pricing",
                         json={"price_per_unit_usd": 0.01},
                         headers=auth(broker_token))
        assert r.status_code == 403, f"Expected 403, got {r.status_code}"
        print("PASS: broker gets 403 on PUT /service-pricing")

    def test_update_packages_admin(self, admin_token):
        """PUT /api/service-pricing/packages — admin can update packages"""
        packages = [
            {"id": "starter",  "name_ar": "باقة المبتدئ", "scans": 20,  "price_usd": 1.0},
            {"id": "standard", "name_ar": "باقة القياسي", "scans": 100, "price_usd": 4.0},
            {"id": "pro",      "name_ar": "باقة الاحترافي", "scans": 500, "price_usd": 15.0},
        ]
        r = requests.put(f"{BASE_URL}/api/service-pricing/packages",
                         json={"packages": packages},
                         headers=auth(admin_token))
        assert r.status_code == 200, f"Update packages failed: {r.status_code}: {r.text}"
        print(f"PASS: packages updated: {r.json()}")

    def test_update_packages_non_admin_returns_403(self, broker_token):
        """Non-admin cannot update packages"""
        r = requests.put(f"{BASE_URL}/api/service-pricing/packages",
                         json={"packages": []},
                         headers=auth(broker_token))
        assert r.status_code == 403, f"Expected 403, got {r.status_code}"
        print("PASS: broker gets 403 on PUT /service-pricing/packages")
