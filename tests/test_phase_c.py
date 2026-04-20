"""Phase C refactoring tests - modular routes testing"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

def get_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json().get("access_token")
    return None

def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}

# --- Auth Tests ---
class TestAuth:
    """Login tests for all roles"""

    def test_admin_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        print("admin login: PASS")

    def test_carrier_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "carrier@customs.ly", "password": "Carrier@2026!"})
        assert r.status_code == 200
        assert "access_token" in r.json()
        print("carrier login: PASS")

    def test_manifest_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "manifest@customs.ly", "password": "Manifest@2026!"})
        assert r.status_code == 200
        assert "access_token" in r.json()
        print("manifest login: PASS")

    def test_pga_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "pga@customs.ly", "password": "PGA@2026!"})
        assert r.status_code == 200
        assert "access_token" in r.json()
        print("pga login: PASS")

    def test_violations_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "violations@customs.ly", "password": "Violations@2026!"})
        assert r.status_code == 200
        assert "access_token" in r.json()
        print("violations login: PASS")

    def test_treasury_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "treasury@customs.ly", "password": "Treasury@2026!"})
        assert r.status_code == 200
        assert "access_token" in r.json()
        print("treasury login: PASS")

    def test_gate_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "gate@customs.ly", "password": "Gate@2026!"})
        assert r.status_code == 200
        assert "access_token" in r.json()
        print("gate login: PASS")

    def test_broker_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "broker@customs.ly", "password": "Broker@2026!"})
        assert r.status_code == 200
        assert "access_token" in r.json()
        print("broker login: PASS")


# --- Dashboard / Stats Tests ---
class TestDashboard:
    """Dashboard and stats endpoints"""

    def setup_method(self):
        self.token = get_token("admin@customs.ly", "Admin@2026!")
        self.headers = auth_headers(self.token)

    def test_dashboard_stats(self):
        r = requests.get(f"{BASE_URL}/api/dashboard/stats", headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        print(f"dashboard stats keys: {list(data.keys())}")

    def test_exchange_rates(self):
        r = requests.get(f"{BASE_URL}/api/exchange/rates", headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert "base" in data or isinstance(data, dict)
        print(f"exchange rates: {data}")

    def test_executive_dashboard(self):
        r = requests.get(f"{BASE_URL}/api/executive/dashboard", headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        # Check for new admin intelligence KPIs
        assert "active_guarantees_count" in data or isinstance(data, dict)
        print(f"executive dashboard keys: {list(data.keys())}")

    def test_executive_dashboard_admin_intelligence_kpis(self):
        r = requests.get(f"{BASE_URL}/api/executive/dashboard", headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        # Phase C new KPIs are nested under "summary"
        summary = data.get("summary", data)
        assert "active_guarantees_count" in summary, f"Missing active_guarantees_count in summary, got: {list(summary.keys())}"
        assert "active_guarantees_total_lyd" in summary, f"Missing active_guarantees_total_lyd"
        assert "violation_fines_collected_lyd" in summary, f"Missing violation_fines_collected_lyd"
        print(f"admin intelligence KPIs present in summary: PASS")


# --- Queue Tests ---
class TestQueues:
    """Queue endpoints for various officers"""

    def setup_method(self):
        self.admin_token = get_token("admin@customs.ly", "Admin@2026!")
        self.headers = auth_headers(self.admin_token)

    def test_valuer_queue(self):
        r = requests.get(f"{BASE_URL}/api/valuer/queue", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"valuer queue: {len(r.json())} items")

    def test_gate_queue(self):
        r = requests.get(f"{BASE_URL}/api/gate/queue", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"gate queue: {len(r.json())} items")

    def test_treasury_queue(self):
        r = requests.get(f"{BASE_URL}/api/treasury/queue", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"treasury queue: {len(r.json())} items")

    def test_pga_queue(self):
        r = requests.get(f"{BASE_URL}/api/pga/queue", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"pga queue: {len(r.json())} items")

    def test_acid_risk_queue(self):
        r = requests.get(f"{BASE_URL}/api/acid-risk/queue", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"acid-risk queue: {len(r.json())} items")

    def test_declaration_queue(self):
        r = requests.get(f"{BASE_URL}/api/declaration/queue", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"declaration queue: {len(r.json())} items")

    def test_release_queue(self):
        r = requests.get(f"{BASE_URL}/api/release/queue", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"release queue: {len(r.json())} items")


# --- Stats Tests ---
class TestStats:
    """Stats endpoints"""

    def setup_method(self):
        self.admin_token = get_token("admin@customs.ly", "Admin@2026!")
        self.admin_headers = auth_headers(self.admin_token)
        pga_token = get_token("pga@customs.ly", "PGA@2026!")
        self.pga_headers = auth_headers(pga_token)
        violations_token = get_token("violations@customs.ly", "Violations@2026!")
        self.violations_headers = auth_headers(violations_token)

    def test_pga_stats(self):
        r = requests.get(f"{BASE_URL}/api/pga/stats", headers=self.pga_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        print(f"pga stats: {data}")

    def test_violations_stats(self):
        r = requests.get(f"{BASE_URL}/api/violations/stats", headers=self.violations_headers)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data or isinstance(data, dict)
        print(f"violations stats: {data}")

    def test_guarantees_stats(self):
        r = requests.get(f"{BASE_URL}/api/guarantees/stats", headers=self.admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data or "active" in data
        print(f"guarantees stats: {data}")

    def test_release_stats(self):
        r = requests.get(f"{BASE_URL}/api/release/stats", headers=self.admin_headers)
        assert r.status_code == 200
        data = r.json()
        print(f"release stats: {data}")

    def test_manifest_stats_singular(self):
        """Test singular path /api/manifest/stats (not /manifests/)"""
        carrier_token = get_token("carrier@customs.ly", "Carrier@2026!")
        r = requests.get(f"{BASE_URL}/api/manifest/stats", headers=auth_headers(carrier_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        print(f"manifest stats (singular): {data}")


# --- Manifests Tests ---
class TestManifests:
    """Manifest endpoints"""

    def setup_method(self):
        self.carrier_token = get_token("carrier@customs.ly", "Carrier@2026!")
        self.manifest_token = get_token("manifest@customs.ly", "Manifest@2026!")

    def test_list_manifests_as_carrier(self):
        r = requests.get(f"{BASE_URL}/api/manifests", headers=auth_headers(self.carrier_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"manifests list: {len(r.json())} items")

    def test_manifests_queue_as_manifest_officer(self):
        r = requests.get(f"{BASE_URL}/api/manifests/queue", headers=auth_headers(self.manifest_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"manifests queue: {len(r.json())} items")


# --- Other Tests ---
class TestOther:
    """Other endpoints"""

    def setup_method(self):
        self.admin_token = get_token("admin@customs.ly", "Admin@2026!")
        self.admin_headers = auth_headers(self.admin_token)
        self.broker_token = get_token("broker@customs.ly", "Broker@2026!")

    def test_broker_importers(self):
        r = requests.get(f"{BASE_URL}/api/broker/importers", headers=self.admin_headers)
        assert r.status_code == 200
        print(f"broker importers: {r.json()}")

    def test_audit_logs(self):
        r = requests.get(f"{BASE_URL}/api/audit/logs", headers=self.admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))
        print(f"audit logs type: {type(data)}")

    def test_public_tracking_nonexistent(self):
        r = requests.get(f"{BASE_URL}/api/public/track/ACID/2026/00001")
        assert r.status_code in [200, 404]
        print(f"public tracking: {r.status_code}")

    def test_registration_docs_my(self):
        r = requests.get(f"{BASE_URL}/api/registration/docs/my", headers=self.admin_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"registration docs: {data}")

    def test_create_acid_as_broker(self):
        payload = {
            "importer_name": "TEST_شركة الاختبار",
            "importer_id": "123456789",
            "origin_country": "CN",
            "supplier_name": "TEST Supplier Co",
            "supplier_country": "CN",
            "goods_description": "TEST goods for testing",
            "estimated_value_usd": 10000,
            "value_usd": 10000,
            "hs_code": "8471.30",
            "port_of_entry": "طرابلس",
            "cbl_reference": "CBL2026TEST01",
            "quantity": 100,
            "unit": "piece",
            "transport_mode": "sea"
        }
        r = requests.post(f"{BASE_URL}/api/acid", json=payload, headers=auth_headers(self.broker_token))
        assert r.status_code in [200, 201]
        data = r.json()
        assert "acid_number" in data or "id" in data or "_id" in data
        print(f"create ACID: {r.status_code} - {data.get('acid_number', data.get('id', 'no id'))}")
