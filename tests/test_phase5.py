"""Phase 5: Sovereign Chain Workflow Tests"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


def login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


@pytest.fixture(scope="module")
def admin_token():
    t = login("admin@customs.ly", "Admin@2026!")
    assert t, "Admin login failed"
    return t


@pytest.fixture(scope="module")
def valuer_token():
    t = login("valuer@customs.ly", "Valuer@2026!")
    assert t, "Valuer login failed"
    return t


@pytest.fixture(scope="module")
def treasury_token():
    t = login("treasury@customs.ly", "Treasury@2026!")
    assert t, "Treasury login failed"
    return t


@pytest.fixture(scope="module")
def gate_token():
    t = login("gate@customs.ly", "Gate@2026!")
    assert t, "Gate login failed"
    return t


@pytest.fixture(scope="module")
def broker_token():
    t = login("broker@customs.ly", "Broker@2026!")
    assert t, "Broker login failed"
    return t


@pytest.fixture(scope="module")
def inspector_token():
    t = login("inspector@customs.ly", "Inspector@2026!")
    assert t, "Inspector login failed"
    return t


@pytest.fixture(scope="module")
def supplier_token():
    t = login("supplier@customs.ly", "Supplier@2026!")
    assert t, "Supplier login failed"
    return t


@pytest.fixture(scope="module")
def carrier_token():
    t = login("carrier@customs.ly", "Carrier@2026!")
    assert t, "Carrier login failed"
    return t


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ===== Login Tests for all 7 new accounts =====
class TestNewAccountLogins:
    def test_broker_login(self):
        t = login("broker@customs.ly", "Broker@2026!")
        assert t, "Broker login failed"

    def test_valuer_login(self):
        t = login("valuer@customs.ly", "Valuer@2026!")
        assert t, "Valuer login failed"

    def test_inspector_login(self):
        t = login("inspector@customs.ly", "Inspector@2026!")
        assert t, "Inspector login failed"

    def test_treasury_login(self):
        t = login("treasury@customs.ly", "Treasury@2026!")
        assert t, "Treasury login failed"

    def test_gate_login(self):
        t = login("gate@customs.ly", "Gate@2026!")
        assert t, "Gate login failed"

    def test_supplier_login(self):
        t = login("supplier@customs.ly", "Supplier@2026!")
        assert t, "Supplier login failed"

    def test_carrier_login(self):
        t = login("carrier@customs.ly", "Carrier@2026!")
        assert t, "Carrier login failed"


# ===== Valuer Queue =====
class TestValuerQueue:
    def test_valuer_queue_accessible(self, valuer_token):
        r = requests.get(f"{BASE_URL}/api/valuer/queue", headers=auth_headers(valuer_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"Valuer queue count: {len(data)}")

    def test_valuer_queue_has_items(self, valuer_token):
        r = requests.get(f"{BASE_URL}/api/valuer/queue", headers=auth_headers(valuer_token))
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1, f"Expected >=1 items in valuer queue, got {len(data)}"

    def test_valuer_queue_returns_approved_status(self, valuer_token):
        r = requests.get(f"{BASE_URL}/api/valuer/queue", headers=auth_headers(valuer_token))
        data = r.json()
        if data:
            # All items should be approved status
            for item in data[:3]:
                assert item.get("status") == "approved", f"Expected approved, got {item.get('status')}"

    def test_non_valuer_cannot_access_valuer_queue(self, gate_token):
        r = requests.get(f"{BASE_URL}/api/valuer/queue", headers=auth_headers(gate_token))
        assert r.status_code == 403


# ===== Treasury Queue =====
class TestTreasuryQueue:
    def test_treasury_queue_accessible(self, treasury_token):
        r = requests.get(f"{BASE_URL}/api/treasury/queue", headers=auth_headers(treasury_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"Treasury queue count: {len(data)}")

    def test_non_treasury_cannot_access(self, valuer_token):
        r = requests.get(f"{BASE_URL}/api/treasury/queue", headers=auth_headers(valuer_token))
        assert r.status_code == 403


# ===== Gate Queue =====
class TestGateQueue:
    def test_gate_queue_accessible(self, gate_token):
        r = requests.get(f"{BASE_URL}/api/gate/queue", headers=auth_headers(gate_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"Gate queue count: {len(data)}")

    def test_non_gate_cannot_access(self, valuer_token):
        r = requests.get(f"{BASE_URL}/api/gate/queue", headers=auth_headers(valuer_token))
        assert r.status_code == 403


# ===== Gate Release BLOCKED test =====
class TestGateReleaseBlocked:
    def test_gate_release_blocked_if_not_treasury_paid(self, gate_token, valuer_token, admin_token):
        # Find an approved ACID (not treasury_paid)
        r = requests.get(f"{BASE_URL}/api/valuer/queue", headers=auth_headers(valuer_token))
        assert r.status_code == 200
        queue = r.json()
        if not queue:
            pytest.skip("No approved ACIDs in valuer queue to test gate block")
        acid_id = queue[0]["_id"]
        # Try gate-release on approved ACID (should fail)
        r2 = requests.post(f"{BASE_URL}/api/acid/{acid_id}/gate-release",
                           json={"notes": "test"},
                           headers=auth_headers(gate_token))
        assert r2.status_code in [400, 403], f"Expected 400/403 blocking gate release, got {r2.status_code}: {r2.text}"
        print(f"Gate release blocked correctly: {r2.status_code} - {r2.json()}")


# ===== Admin Users Full =====
class TestAdminUsersFull:
    def test_admin_users_full(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/users-full", headers=auth_headers(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert "users" in data or isinstance(data, dict) or isinstance(data, list)
        print(f"admin/users-full response keys: {list(data.keys()) if isinstance(data, dict) else 'list'}")
        if isinstance(data, dict):
            total = data.get("total") or data.get("total_users") or len(data.get("users", []))
            print(f"Total users: {total}")
            by_role = data.get("by_role")
            print(f"By role: {by_role}")

    def test_non_admin_cannot_access_users_full(self, valuer_token):
        r = requests.get(f"{BASE_URL}/api/admin/users-full", headers=auth_headers(valuer_token))
        assert r.status_code == 403


# ===== WhatsApp Logs =====
class TestWhatsAppLogs:
    def test_whatsapp_logs_accessible_to_admin(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/whatsapp/logs", headers=auth_headers(admin_token))
        assert r.status_code == 200
        data = r.json()
        print(f"WhatsApp logs response: {data}")
        assert "logs" in data or isinstance(data, list) or isinstance(data, dict)

    def test_non_admin_cannot_access_whatsapp_logs(self, valuer_token):
        r = requests.get(f"{BASE_URL}/api/whatsapp/logs", headers=auth_headers(valuer_token))
        assert r.status_code == 403


# ===== Broker Endpoints =====
class TestBrokerEndpoints:
    def test_broker_importers(self, broker_token):
        r = requests.get(f"{BASE_URL}/api/broker/importers", headers=auth_headers(broker_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"Broker importers count: {len(data)}")

    def test_broker_my_requests(self, broker_token):
        r = requests.get(f"{BASE_URL}/api/broker/my-requests", headers=auth_headers(broker_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"Broker my-requests count: {len(data)}")

    def test_non_broker_cannot_access_broker_importers(self, gate_token):
        r = requests.get(f"{BASE_URL}/api/broker/importers", headers=auth_headers(gate_token))
        assert r.status_code == 403


# ===== Full Sovereign Chain Flow =====
class TestSovereignChain:
    """Test the full chain: valuer submits valuation → treasury marks paid → gate releases"""

    def test_submit_valuation_on_approved_acid(self, valuer_token, admin_token):
        # Get an approved ACID from valuer queue
        r = requests.get(f"{BASE_URL}/api/valuer/queue", headers=auth_headers(valuer_token))
        assert r.status_code == 200
        queue = r.json()
        if not queue:
            pytest.skip("No ACIDs in valuer queue")
        acid = queue[0]
        acid_id = acid["_id"]
        # Submit valuation
        r2 = requests.post(f"{BASE_URL}/api/acid/{acid_id}/submit-valuation",
                           json={"acid_id": acid_id, "confirmed_value_usd": acid.get("value_usd", 5000.0), "valuation_notes": "TEST valuation"},
                           headers=auth_headers(valuer_token))
        assert r2.status_code == 200, f"Submit valuation failed: {r2.status_code} {r2.text}"
        data = r2.json()
        print(f"Valuation submitted: {data}")
        assert data.get("new_status") == "valued"
        return acid_id

    def test_treasury_mark_paid_after_valuation(self, valuer_token, treasury_token):
        # Get item from treasury queue (should appear after valuation)
        r = requests.get(f"{BASE_URL}/api/treasury/queue", headers=auth_headers(treasury_token))
        assert r.status_code == 200
        queue = r.json()
        if not queue:
            pytest.skip("No valued ACIDs in treasury queue")
        acid_id = queue[0]["_id"]
        r2 = requests.post(f"{BASE_URL}/api/acid/{acid_id}/treasury-mark-paid",
                           json={"treasury_ref": "CBL20260099TEST", "notes": "TEST payment"},
                           headers=auth_headers(treasury_token))
        assert r2.status_code == 200, f"Treasury mark paid failed: {r2.status_code} {r2.text}"
        data = r2.json()
        print(f"Treasury paid: {data}")
        assert data.get("new_status") == "treasury_paid"

    def test_gate_release_after_treasury_paid(self, gate_token):
        r = requests.get(f"{BASE_URL}/api/gate/queue", headers=auth_headers(gate_token))
        assert r.status_code == 200
        queue = r.json()
        if not queue:
            pytest.skip("No treasury_paid ACIDs in gate queue")
        acid_id = queue[0]["_id"]
        r2 = requests.post(f"{BASE_URL}/api/acid/{acid_id}/gate-release",
                           json={"notes": "TEST gate release"},
                           headers=auth_headers(gate_token))
        assert r2.status_code == 200, f"Gate release failed: {r2.status_code} {r2.text}"
        data = r2.json()
        print(f"Gate released: {data}")
        assert "jl38_number" in data
        assert data["jl38_number"].startswith("JL38/")
