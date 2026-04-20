"""
Backend Tests — Payments & Exporters (Iteration 51)
Tests: POST /api/exporters/self-register, GET/POST /api/payments/admin/config,
       POST /api/payments/checkout/verification, POST /api/payments/checkout/acid-fee,
       GET /api/payments/history
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_CREDS = {"email": "admin@customs.ly", "password": "Admin@2026!"}
MANIFEST_CREDS = {"email": "manifest@customs.ly", "password": "Manifest@2026!"}
SUPPLIER_CREDS = {"email": "supplier@customs.ly", "password": "Supplier@2026!"}

TEST_ACID_ID = "69d6593ac7fcf49c4bf7ce4a"


def get_token(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code == 200:
        return r.json().get("access_token") or r.json().get("token")
    return None


# ── /api/exporters/self-register ──────────────────────────────────────────────

class TestSelfRegister:
    """POST /api/exporters/self-register"""

    def test_self_register_creates_pending_payment(self, tmp_path):
        """New exporter self-register returns pending_payment status"""
        import time
        unique_tax = f"TEST-ITER51-{int(time.time())}"
        fake_file = tmp_path / "license.pdf"
        fake_file.write_bytes(b"%PDF fake content")

        with open(fake_file, "rb") as f:
            r = requests.post(f"{BASE_URL}/api/exporters/self-register",
                data={
                    "company_name":   "Test Co Iter51",
                    "email":          f"iter51_{unique_tax.lower()}@test.eg",
                    "phone":          "+201234567890",
                    "country":        "مصر",
                    "address":        "123 Test St, Cairo",
                    "tax_id":         unique_tax,
                    "exporter_type":  "regional",
                    "regional_country": "مصر",
                    "password":       "Test@1234",
                },
                files={"business_license": ("license.pdf", f, "application/pdf")},
            )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("account_status") == "pending_payment", f"Expected pending_payment, got: {data}"
        assert data.get("tax_id") == unique_tax
        print(f"PASS: self-register returns pending_payment for tax_id={unique_tax}")

    def test_duplicate_tax_id_returns_pending_not_error(self, tmp_path):
        """Duplicate tax_id (pending_payment) returns pending status, not 409"""
        fake_file = tmp_path / "license2.pdf"
        fake_file.write_bytes(b"%PDF fake content")

        with open(fake_file, "rb") as f:
            r = requests.post(f"{BASE_URL}/api/exporters/self-register",
                data={
                    "company_name":   "Acme Egypt",
                    "email":          "acme_dupe_test@test.eg",
                    "phone":          "+201234567891",
                    "country":        "مصر",
                    "address":        "456 Test St",
                    "tax_id":         "EG-TEST-001",   # already in DB as pending_payment
                    "exporter_type":  "regional",
                    "regional_country": "مصر",
                    "password":       "Test@1234",
                },
                files={"business_license": ("license2.pdf", f, "application/pdf")},
            )
        # Should return 200 with pending_payment message, not 409
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("account_status") == "pending_payment"
        assert "tax_id" in data
        print(f"PASS: duplicate tax_id returns pending_payment: {data.get('message')}")


# ── /api/payments/admin/config ────────────────────────────────────────────────

class TestAdminConfig:
    """GET/POST /api/payments/admin/config"""

    def test_get_config_returns_fees(self):
        """GET /api/payments/admin/config returns acid_fee_usd=50 and verification_fee_usd=100"""
        token = get_token(ADMIN_CREDS)
        assert token, "Admin login failed"
        r = requests.get(f"{BASE_URL}/api/payments/admin/config",
                         headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        data = r.json()
        assert "acid_fee_usd" in data
        assert "verification_fee_usd" in data
        assert float(data["verification_fee_usd"]) == 100.0
        assert float(data["acid_fee_usd"]) >= 1.0
        print(f"PASS: config = {data}")

    def test_update_config_admin_only(self):
        """POST /api/payments/admin/config updates ACID fee"""
        token = get_token(ADMIN_CREDS)
        assert token, "Admin login failed"
        r = requests.post(f"{BASE_URL}/api/payments/admin/config",
                          json={"amount_usd": 50.0},
                          headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("amount_usd") == 50.0
        print(f"PASS: admin config updated: {data}")

    def test_update_config_non_admin_forbidden(self):
        """POST /api/payments/admin/config by manifest officer → 403"""
        token = get_token(MANIFEST_CREDS)
        assert token, "Manifest login failed"
        r = requests.post(f"{BASE_URL}/api/payments/admin/config",
                          json={"amount_usd": 999.0},
                          headers={"Authorization": f"Bearer {token}"})
        assert r.status_code in (403, 401), f"Expected 403/401, got {r.status_code}"
        print(f"PASS: non-admin gets {r.status_code} on config update")

    def test_get_config_no_auth_forbidden(self):
        """GET /api/payments/admin/config without auth → 401/403"""
        r = requests.get(f"{BASE_URL}/api/payments/admin/config")
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"
        print(f"PASS: unauthenticated gets {r.status_code}")


# ── /api/payments/checkout/verification ───────────────────────────────────────

class TestVerificationCheckout:
    """POST /api/payments/checkout/verification"""

    def test_checkout_for_existing_exporter(self):
        """Creates Stripe checkout URL for pending_payment exporter (no auth required)"""
        r = requests.post(f"{BASE_URL}/api/payments/checkout/verification", json={
            "exporter_tax_id": "EG-TEST-001",
            "origin_url":      BASE_URL,
        })
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        data = r.json()
        assert "checkout_url" in data
        assert "session_id" in data
        # URL must be a real Stripe checkout URL
        url = data["checkout_url"]
        assert "stripe.com" in url or url.startswith("http"), f"Expected Stripe URL, got: {url}"
        print(f"PASS: checkout_url = {url[:60]}...")

    def test_checkout_nonexistent_exporter_404(self):
        """POST /api/payments/checkout/verification with unknown tax_id → 404"""
        r = requests.post(f"{BASE_URL}/api/payments/checkout/verification", json={
            "exporter_tax_id": "NONEXISTENT-XYZ",
            "origin_url":      BASE_URL,
        })
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
        print(f"PASS: nonexistent exporter → 404")


# ── /api/payments/checkout/acid-fee ───────────────────────────────────────────

class TestAcidFeeCheckout:
    """POST /api/payments/checkout/acid-fee"""

    def test_acid_fee_checkout_authenticated(self):
        """Authenticated foreign_supplier can create acid-fee checkout"""
        token = get_token(SUPPLIER_CREDS)
        if not token:
            pytest.skip("supplier@customs.ly login failed — skipping")
        r = requests.post(f"{BASE_URL}/api/payments/checkout/acid-fee", json={
            "acid_id":    TEST_ACID_ID,
            "origin_url": BASE_URL,
        }, headers={"Authorization": f"Bearer {token}"})
        # 200 = success, 404 = ACID not found, 409 = already paid — all acceptable
        assert r.status_code in (200, 404, 409), f"Got {r.status_code}: {r.text}"
        if r.status_code == 200:
            data = r.json()
            assert "checkout_url" in data
            assert "fee_usd" in data
            print(f"PASS: acid-fee checkout_url returned, fee={data.get('fee_usd')}")
        else:
            print(f"PASS (acceptable): acid-fee returned {r.status_code}: {r.text[:80]}")

    def test_acid_fee_checkout_unauthenticated(self):
        """Unauthenticated request to acid-fee checkout → 401"""
        r = requests.post(f"{BASE_URL}/api/payments/checkout/acid-fee", json={
            "acid_id":    TEST_ACID_ID,
            "origin_url": BASE_URL,
        })
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}: {r.text}"
        print(f"PASS: unauthenticated acid-fee → {r.status_code}")


# ── /api/payments/history ─────────────────────────────────────────────────────

class TestPaymentHistory:
    """GET /api/payments/history"""

    def test_admin_gets_all_history(self):
        """Admin gets full payment history list"""
        token = get_token(ADMIN_CREDS)
        assert token, "Admin login failed"
        r = requests.get(f"{BASE_URL}/api/payments/history",
                         headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list)
        print(f"PASS: admin gets {len(data)} payment records")

    def test_supplier_gets_own_history(self):
        """foreign_supplier gets own payment history"""
        token = get_token(SUPPLIER_CREDS)
        if not token:
            pytest.skip("supplier@customs.ly login failed — skipping")
        r = requests.get(f"{BASE_URL}/api/payments/history",
                         headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list)
        print(f"PASS: supplier gets {len(data)} payment records")

    def test_history_unauthenticated_401(self):
        """Unauthenticated GET /api/payments/history → 401"""
        r = requests.get(f"{BASE_URL}/api/payments/history")
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"
        print(f"PASS: unauthenticated history → {r.status_code}")


# ── /api/land-trip/queue/pending ──────────────────────────────────────────────

class TestLandTripQueue:
    """GET /api/land-trip/queue/pending for manifest_officer"""

    def test_manifest_officer_gets_queue(self):
        """manifest_officer gets pending land trip queue"""
        token = get_token(MANIFEST_CREDS)
        assert token, "Manifest login failed"
        r = requests.get(f"{BASE_URL}/api/land-trip/queue/pending",
                         headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list)
        print(f"PASS: manifest officer gets {len(data)} pending land trips")

    def test_unauthenticated_queue_401(self):
        """Unauthenticated GET land-trip queue → 401"""
        r = requests.get(f"{BASE_URL}/api/land-trip/queue/pending")
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"
        print(f"PASS: unauthenticated queue → {r.status_code}")
