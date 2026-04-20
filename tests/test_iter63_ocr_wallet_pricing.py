"""
OCR Wallet & Service Pricing — iteration 63
Tests: service-pricing, ocr-wallet (balance/packages/topup/history), threshold logic
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# ── Auth helpers ──────────────────────────────────────────────────────────────

def login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.cookies, r.json().get("access_token")
    return None, None


@pytest.fixture(scope="module")
def admin_session():
    cookies, token = login("admin@customs.ly", "Admin@2026!")
    assert cookies is not None, "Admin login failed"
    s = requests.Session()
    s.cookies.update(cookies)
    return s


@pytest.fixture(scope="module")
def broker_session():
    cookies, token = login("broker@customs.ly", "Broker@2026!")
    assert cookies is not None, "Broker login failed"
    s = requests.Session()
    s.cookies.update(cookies)
    return s


# ── service-pricing ──────────────────────────────────────────────────────────

class TestServicePricing:

    def test_get_pricing_returns_three_packages(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/service-pricing")
        assert r.status_code == 200
        data = r.json()
        assert "packages" in data
        assert len(data["packages"]) == 3
        ids = [p["id"] for p in data["packages"]]
        assert "starter" in ids and "standard" in ids and "pro" in ids
        print(f"PASS: service-pricing returns {len(data['packages'])} packages, price_per_unit={data.get('price_per_unit_usd')}")

    def test_get_pricing_has_price_per_unit(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/service-pricing")
        assert r.status_code == 200
        data = r.json()
        assert "price_per_unit_usd" in data
        assert data["price_per_unit_usd"] > 0
        print(f"PASS: price_per_unit_usd = {data['price_per_unit_usd']}")

    def test_stats_admin_only(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/service-pricing/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total_scans" in data
        assert "total_cost_usd" in data
        assert "active_wallets" in data
        print(f"PASS: stats total_scans={data['total_scans']}, total_cost={data['total_cost_usd']}")

    def test_stats_forbidden_for_broker(self, broker_session):
        r = broker_session.get(f"{BASE_URL}/api/service-pricing/stats")
        assert r.status_code == 403
        print("PASS: stats correctly returns 403 for non-admin")

    def test_update_price_admin(self, admin_session):
        r = admin_session.put(f"{BASE_URL}/api/service-pricing", json={
            "price_per_unit_usd": 0.05,
            "min_balance_usd": 0.05
        })
        assert r.status_code == 200
        data = r.json()
        assert data["price_per_unit_usd"] == 0.05
        print("PASS: PUT service-pricing updated price to 0.05")

    def test_update_packages_admin(self, admin_session):
        r = admin_session.put(f"{BASE_URL}/api/service-pricing/packages", json={
            "packages": [
                {"id": "starter",  "name_ar": "الباقة الأساسية",   "scans": 20,  "price_usd": 1.00},
                {"id": "standard", "name_ar": "الباقة القياسية",   "scans": 100, "price_usd": 4.00},
                {"id": "pro",      "name_ar": "الباقة الاحترافية", "scans": 500, "price_usd": 15.00},
            ]
        })
        assert r.status_code == 200
        data = r.json()
        assert len(data["packages"]) == 3
        print("PASS: PUT packages restored 3 default packages")

    def test_update_price_forbidden_for_broker(self, broker_session):
        r = broker_session.put(f"{BASE_URL}/api/service-pricing", json={"price_per_unit_usd": 0.01})
        assert r.status_code == 403
        print("PASS: PUT service-pricing returns 403 for broker")


# ── ocr-wallet ────────────────────────────────────────────────────────────────

class TestOCRWallet:

    def test_balance_returns_fields(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/ocr-wallet/balance")
        assert r.status_code == 200
        data = r.json()
        assert "balance_usd" in data
        assert "remaining_scans" in data
        assert "price_per_scan_usd" in data
        print(f"PASS: balance_usd={data['balance_usd']}, remaining_scans={data['remaining_scans']}")

    def test_packages_list(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/ocr-wallet/packages")
        assert r.status_code == 200
        data = r.json()
        assert "packages" in data
        assert len(data["packages"]) >= 1
        print(f"PASS: {len(data['packages'])} packages returned")

    def test_topup_starter_package(self, broker_session):
        """Buy starter package for broker to enable OCR later"""
        r = broker_session.post(f"{BASE_URL}/api/ocr-wallet/topup", json={"package_id": "starter"})
        assert r.status_code == 200
        data = r.json()
        assert "balance_after" in data
        assert data["balance_after"] > 0
        print(f"PASS: topup successful, balance_after={data['balance_after']}")

    def test_history_returns_data(self, broker_session):
        r = broker_session.get(f"{BASE_URL}/api/ocr-wallet/history")
        assert r.status_code == 200
        data = r.json()
        assert "wallet" in data
        assert "topups" in data
        assert "usage" in data
        assert len(data["topups"]) >= 1  # we just topped up
        print(f"PASS: history has {len(data['topups'])} topups, {len(data['usage'])} usage records")

    def test_topup_invalid_package(self, broker_session):
        r = broker_session.post(f"{BASE_URL}/api/ocr-wallet/topup", json={"package_id": "nonexistent"})
        assert r.status_code == 400
        print("PASS: invalid package returns 400")


# ── Threshold logic ──────────────────────────────────────────────────────────

class TestThresholdLogic:

    def test_zero_balance_returns_402(self):
        """Create a fresh session (admin but drain balance or use a fresh user without wallet)"""
        # Use a fresh user that has no wallet — inspector role
        cookies, _ = login("inspector@customs.ly", "Inspector@2026!")
        assert cookies is not None
        s = requests.Session()
        s.cookies.update(cookies)

        # inspector has no wallet → balance = 0
        r_bal = s.get(f"{BASE_URL}/api/ocr-wallet/balance")
        balance = r_bal.json().get("balance_usd", 0)
        print(f"Inspector balance: {balance}")

        if balance >= 0.05:
            pytest.skip("Inspector already has balance — skip threshold test")

        import io
        dummy_img = b'\xff\xd8\xff\xe0' + b'\x00' * 100  # minimal jpeg-like bytes
        r = s.post(
            f"{BASE_URL}/api/ocr/scan-document",
            files={"file": ("test.jpg", io.BytesIO(dummy_img), "image/jpeg")},
            data={"doc_type": "invoice", "acid_id": ""},
        )
        assert r.status_code == 402
        data = r.json()
        assert data.get("error_code") == "INSUFFICIENT_OCR_BALANCE"
        print(f"PASS: 402 returned with error_code=INSUFFICIENT_OCR_BALANCE, balance={data.get('remaining_balance_usd')}")

    def test_after_topup_scan_allowed(self):
        """Broker now has balance after topup in previous test class — scan should attempt (not 402)"""
        cookies, _ = login("broker@customs.ly", "Broker@2026!")
        s = requests.Session()
        s.cookies.update(cookies)

        # Verify balance > 0
        r_bal = s.get(f"{BASE_URL}/api/ocr-wallet/balance")
        balance = r_bal.json().get("balance_usd", 0)
        print(f"Broker balance before scan: {balance}")

        if balance < 0.05:
            pytest.skip("Broker has no balance — topup test may have failed")

        import io
        dummy_img = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        r = s.post(
            f"{BASE_URL}/api/ocr/scan-document",
            files={"file": ("test.jpg", io.BytesIO(dummy_img), "image/jpeg")},
            data={"doc_type": "invoice", "acid_id": ""},
        )
        # Should not be 402
        assert r.status_code != 402, f"Expected non-402 after topup but got {r.status_code}"
        # 200 with ocr_failed=True is acceptable (bad image)
        data = r.json()
        print(f"PASS: scan returned {r.status_code}, ocr_failed={data.get('ocr_failed')}")
