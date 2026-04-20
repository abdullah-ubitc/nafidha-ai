"""Phase 3 backend tests: Exchange Rates, Tariff Lookup, AI Valuation, Executive Dashboard, Audit Logs"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return s


@pytest.fixture(scope="module")
def importer_session():
    """Use reviewer session - reviewers cannot access audit logs (admin-only) but can access exec dashboard"""
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "reviewer@test.ly", "password": "Test@2024!"})
    if r.status_code != 200:
        pytest.skip(f"Reviewer login failed: {r.text}")
    return s


# ---- Exchange Rate Tests ----
class TestExchangeRates:
    """GET /api/exchange/rates - public endpoint"""

    def test_exchange_rates_success(self):
        r = requests.get(f"{BASE_URL}/api/exchange/rates")
        assert r.status_code == 200
        data = r.json()
        assert data["base_currency"] == "LYD"
        assert "rates" in data
        assert data["rates"]["USD"] == 4.87

    def test_exchange_rates_has_major_currencies(self):
        r = requests.get(f"{BASE_URL}/api/exchange/rates")
        assert r.status_code == 200
        rates = r.json()["rates"]
        for cur in ["USD", "EUR", "GBP", "AED", "SAR"]:
            assert cur in rates, f"Missing currency: {cur}"

    def test_exchange_rates_has_source(self):
        r = requests.get(f"{BASE_URL}/api/exchange/rates")
        data = r.json()
        assert "source" in data
        assert "CBL" in data["source"] or "ليبيا" in data["source"]


# ---- Tariff Lookup Tests ----
class TestTariffLookup:
    """GET /api/tariff/lookup?hs_code=XXXX - requires auth"""

    def test_tariff_lookup_8517(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/tariff/lookup?hs_code=8517")
        assert r.status_code == 200
        data = r.json()
        assert data["hs_code"] == "8517"
        assert data["chapter"] == "85"
        assert data["duty_rate"] == 0.05
        assert data["duty_rate_pct"] == "5%"

    def test_tariff_lookup_vehicles_chapter87(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/tariff/lookup?hs_code=8703")
        assert r.status_code == 200
        data = r.json()
        assert data["chapter"] == "87"
        assert data["duty_rate"] == 0.25
        assert data["duty_rate_pct"] == "25%"

    def test_tariff_lookup_arms_chapter93(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/tariff/lookup?hs_code=9301")
        assert r.status_code == 200
        data = r.json()
        assert data["chapter"] == "93"
        assert data["duty_rate"] == 0.30
        assert data["duty_rate_pct"] == "30%"

    def test_tariff_lookup_has_vat_rate(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/tariff/lookup?hs_code=8517")
        data = r.json()
        assert data["vat_rate"] == 0.09
        assert data["vat_rate_pct"] == "9%"

    def test_tariff_lookup_has_arabic_desc(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/tariff/lookup?hs_code=8517")
        data = r.json()
        assert "description_ar" in data
        assert len(data["description_ar"]) > 2

    def test_tariff_lookup_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/tariff/lookup?hs_code=8517")
        assert r.status_code in [401, 403]


# ---- Executive Dashboard Tests ----
class TestExecutiveDashboard:
    """GET /api/executive/dashboard - admin/reviewer/valuer/inspector roles only"""

    def test_exec_dashboard_admin_access(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/executive/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "summary" in data
        assert "monthly_trend" in data
        assert "port_performance" in data
        assert "risk_distribution" in data

    def test_exec_dashboard_summary_fields(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/executive/dashboard")
        data = r.json()
        summary = data["summary"]
        for field in ["total_requests", "approved", "pending", "rejected", "high_risk",
                      "revenue_collected_lyd", "cbl_usd_rate"]:
            assert field in summary, f"Missing field: {field}"
        assert summary["cbl_usd_rate"] == 4.87

    def test_exec_dashboard_monthly_trend_is_list(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/executive/dashboard")
        data = r.json()
        assert isinstance(data["monthly_trend"], list)

    def test_exec_dashboard_reviewer_allowed(self, importer_session):
        """reviewer (acid_reviewer role) should have access"""
        r = importer_session.get(f"{BASE_URL}/api/executive/dashboard")
        assert r.status_code == 200

    def test_exec_dashboard_unauthenticated_denied(self):
        r = requests.get(f"{BASE_URL}/api/executive/dashboard")
        assert r.status_code in [401, 403]


# ---- Audit Logs Tests ----
class TestAuditLogs:
    """GET /api/audit/logs - admin only"""

    def test_audit_logs_admin_access(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/audit/logs")
        assert r.status_code == 200
        data = r.json()
        assert "logs" in data
        assert "total" in data
        assert isinstance(data["logs"], list)

    def test_audit_logs_structure(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/audit/logs")
        data = r.json()
        # Returns proper structure even when empty
        assert data["total"] >= 0
        assert data["page"] == 1

    def test_audit_logs_reviewer_denied(self, importer_session):
        """reviewer (acid_reviewer) should NOT have access to audit logs (admin only)"""
        r = importer_session.get(f"{BASE_URL}/api/audit/logs")
        assert r.status_code in [401, 403]

    def test_audit_logs_unauthenticated_denied(self):
        r = requests.get(f"{BASE_URL}/api/audit/logs")
        assert r.status_code in [401, 403]


# ---- AI Tariff Valuation Tests ----
class TestAITariffValuation:
    """POST /api/tariff/ai-valuate - requires auth"""

    def test_ai_valuate_customs_evasion(self, admin_session):
        """1000 iPhones declared at $100 total - obvious under-valuation"""
        payload = {
            "goods_description": "هواتف ذكية آيفون 15 برو",
            "hs_code": "8517",
            "declared_value_usd": 100.0,
            "quantity": 1000,
            "unit": "قطعة",
            "supplier_country": "الصين"
        }
        r = admin_session.post(f"{BASE_URL}/api/tariff/ai-valuate", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert "alert_type" in data
        assert data["alert_type"] == "customs_evasion"
        assert data["alert_severity"] in ["high", "critical"]
        assert data["declared_value_usd"] == 100.0

    def test_ai_valuate_response_fields(self, admin_session):
        payload = {
            "goods_description": "سيارات مرسيدس",
            "hs_code": "8703",
            "declared_value_usd": 5000000.0,  # Over-valued
            "quantity": 10,
            "unit": "قطعة",
            "supplier_country": "ألمانيا"
        }
        r = admin_session.post(f"{BASE_URL}/api/tariff/ai-valuate", json=payload)
        assert r.status_code == 200
        data = r.json()
        for field in ["estimated_market_value_usd", "declared_vs_market_ratio", "alert_type",
                      "duty_rate_pct", "analysis_ar"]:
            assert field in data, f"Missing field: {field}"

    def test_ai_valuate_requires_auth(self):
        payload = {
            "goods_description": "هواتف", "hs_code": "8517",
            "declared_value_usd": 100.0, "quantity": 10,
            "unit": "قطعة", "supplier_country": "الصين"
        }
        r = requests.post(f"{BASE_URL}/api/tariff/ai-valuate", json=payload)
        assert r.status_code in [401, 403]


# ---- SAD TARIFF_2022 Rate Test ----
class TestSADTariffRates:
    """Verify SAD creation uses TARIFF_2022 rates"""

    def test_tariff_lookup_chapter87_is_25pct(self, admin_session):
        """Vehicles (87xx) should be 25%, not old hardcoded 20%"""
        r = admin_session.get(f"{BASE_URL}/api/tariff/lookup?hs_code=8703")
        assert r.status_code == 200
        data = r.json()
        assert data["duty_rate"] == 0.25, f"Expected 25% for vehicles, got {data['duty_rate']}"

    def test_tariff_lookup_chapter84_is_5pct(self, admin_session):
        """Machinery (84xx) should be 5%"""
        r = admin_session.get(f"{BASE_URL}/api/tariff/lookup?hs_code=8471")
        assert r.status_code == 200
        data = r.json()
        assert data["duty_rate"] == 0.05
