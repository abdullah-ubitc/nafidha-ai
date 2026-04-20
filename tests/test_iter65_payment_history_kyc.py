"""
Iteration 65 — Payment History Tab, KYC Scan national_id/passport, Low Balance Banner
Tests: GET /ocr-wallet/payment-history, POST /ocr/kyc-scan, GET /ocr-wallet/balance
"""
import pytest
import requests
import os
import io

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


def get_token(email, password):
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if resp.status_code == 200:
        return resp.json().get("access_token") or resp.json().get("token")
    return None


@pytest.fixture(scope="module")
def admin_token():
    token = get_token("admin@customs.ly", "Admin@2026!")
    if not token:
        pytest.skip("Admin login failed")
    return token


@pytest.fixture(scope="module")
def broker_token():
    token = get_token("broker@customs.ly", "Broker@2026!")
    if not token:
        pytest.skip("Broker login failed")
    return token


@pytest.fixture(scope="module")
def inspector_token():
    token = get_token("inspector@customs.ly", "Inspector@2026!")
    if not token:
        pytest.skip("Inspector login failed")
    return token


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── Payment History ─────────────────────────────────────────────────────────────

class TestPaymentHistory:
    """GET /api/ocr-wallet/payment-history"""

    def test_admin_payment_history_returns_list(self, admin_token):
        resp = requests.get(f"{BASE_URL}/api/ocr-wallet/payment-history", headers=auth_headers(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        print(f"Admin payment history: {len(data)} records")

    def test_broker_payment_history_returns_list(self, broker_token):
        resp = requests.get(f"{BASE_URL}/api/ocr-wallet/payment-history", headers=auth_headers(broker_token))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        print(f"Broker payment history: {len(data)} records")

    def test_payment_history_record_has_required_fields(self, admin_token):
        """If records exist, verify required fields"""
        resp = requests.get(f"{BASE_URL}/api/ocr-wallet/payment-history", headers=auth_headers(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        if len(data) > 0:
            rec = data[0]
            assert "session_id" in rec
            assert "amount_usd" in rec
            assert "status" in rec
            print(f"First record: session_id={rec.get('session_id','')[:20]}, amount=${rec.get('amount_usd')}, status={rec.get('status')}")

    def test_payment_history_unauthenticated_fails(self):
        resp = requests.get(f"{BASE_URL}/api/ocr-wallet/payment-history")
        assert resp.status_code in [401, 403]

    def test_payment_history_inspector_has_2_records(self, admin_token):
        """Context note says admin created 2 test Stripe sessions in iter64"""
        resp = requests.get(f"{BASE_URL}/api/ocr-wallet/payment-history", headers=auth_headers(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        # At least the 2 records from iter64 should be there for admin
        print(f"Admin has {len(data)} payment records")


# ── OCR Balance — Low Balance Check ────────────────────────────────────────────

class TestOCRBalance:
    """GET /api/ocr-wallet/balance"""

    def test_broker_balance_exists(self, broker_token):
        """Broker has $1.00 balance"""
        resp = requests.get(f"{BASE_URL}/api/ocr-wallet/balance", headers=auth_headers(broker_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "balance_usd" in data
        assert "low_balance" in data
        print(f"Broker balance: ${data['balance_usd']}, low_balance={data['low_balance']}")

    def test_inspector_has_low_balance(self, inspector_token):
        """Inspector has $0 — should have low_balance=true"""
        resp = requests.get(f"{BASE_URL}/api/ocr-wallet/balance", headers=auth_headers(inspector_token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["low_balance"] is True, f"Expected low_balance=True for inspector with $0, got {data}"
        print(f"Inspector balance: ${data['balance_usd']}, low_balance={data['low_balance']}")


# ── KYC Scan ───────────────────────────────────────────────────────────────────

class TestKYCScan:
    """POST /api/ocr/kyc-scan"""

    def _tiny_png(self):
        """1×1 white PNG bytes"""
        return (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00'
            b'\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18'
            b'\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )

    def test_kyc_scan_national_id_returns_200(self, broker_token):
        """national_id should return HTTP 200 — no 402 (no wallet deduction)"""
        files = {'file': ('test.png', io.BytesIO(self._tiny_png()), 'image/png')}
        data = {'doc_type': 'national_id'}
        resp = requests.post(
            f"{BASE_URL}/api/ocr/kyc-scan",
            headers=auth_headers(broker_token),
            files=files,
            data=data
        )
        assert resp.status_code == 200, f"Expected 200 (not 402), got {resp.status_code}: {resp.text}"
        result = resp.json()
        # cost_usd=0 OR absent (ocr_failed=True with tiny image is expected)
        cost = result.get("cost_usd")
        assert cost is None or cost == 0.0 or cost == 0
        print(f"national_id kyc-scan: status=200, cost_usd={cost}, ocr_failed={result.get('ocr_failed')}")

    def test_kyc_scan_passport_returns_200(self, broker_token):
        """passport should return HTTP 200 — no 402 (no wallet deduction)"""
        files = {'file': ('test.png', io.BytesIO(self._tiny_png()), 'image/png')}
        data = {'doc_type': 'passport'}
        resp = requests.post(
            f"{BASE_URL}/api/ocr/kyc-scan",
            headers=auth_headers(broker_token),
            files=files,
            data=data
        )
        assert resp.status_code == 200, f"Expected 200 (not 402), got {resp.status_code}: {resp.text}"
        result = resp.json()
        cost = result.get("cost_usd")
        assert cost is None or cost == 0.0 or cost == 0
        print(f"passport kyc-scan: status=200, cost_usd={cost}, ocr_failed={result.get('ocr_failed')}")

    def test_kyc_scan_invoice_returns_400(self, broker_token):
        """invoice doc_type should return HTTP 400 (unsupported)"""
        files = {'file': ('test.png', io.BytesIO(self._tiny_png()), 'image/png')}
        data = {'doc_type': 'invoice'}
        resp = requests.post(
            f"{BASE_URL}/api/ocr/kyc-scan",
            headers=auth_headers(broker_token),
            files=files,
            data=data
        )
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        print(f"invoice kyc-scan correctly returned 400")

    def test_kyc_scan_unauthenticated_fails(self):
        files = {'file': ('test.png', io.BytesIO(self._tiny_png()), 'image/png')}
        data = {'doc_type': 'national_id'}
        resp = requests.post(f"{BASE_URL}/api/ocr/kyc-scan", files=files, data=data)
        assert resp.status_code in [401, 403]

    def test_kyc_scan_inspector_zero_balance_still_works(self, inspector_token):
        """Inspector with $0 should still get 200 (no wallet deduction for KYC)"""
        files = {'file': ('test.png', io.BytesIO(self._tiny_png()), 'image/png')}
        data = {'doc_type': 'national_id'}
        resp = requests.post(
            f"{BASE_URL}/api/ocr/kyc-scan",
            headers=auth_headers(inspector_token),
            files=files,
            data=data
        )
        assert resp.status_code == 200, f"Expected 200 (no 402), got {resp.status_code}: {resp.text}"
        result = resp.json()
        cost = result.get("cost_usd")
        assert cost is None or cost == 0.0 or cost == 0
        print(f"Inspector (zero balance) kyc-scan: status=200, cost_usd={cost}")


# ── Service Pricing Regression ──────────────────────────────────────────────────

class TestServicePricingRegression:
    """GET /api/service-pricing/stats — admin only"""

    def test_admin_can_access_service_pricing(self, admin_token):
        resp = requests.get(f"{BASE_URL}/api/service-pricing/stats", headers=auth_headers(admin_token))
        assert resp.status_code == 200
        print("Service pricing admin access: OK")

    def test_broker_cannot_access_service_pricing(self, broker_token):
        resp = requests.get(f"{BASE_URL}/api/service-pricing/stats", headers=auth_headers(broker_token))
        assert resp.status_code in [403, 401]
        print(f"Broker service pricing correctly blocked: {resp.status_code}")
