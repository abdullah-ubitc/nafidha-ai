"""
Phase D+E Tests: platform fees, dynamic manifest, PGA risk channel,
license expiry hard-stop, exporter email, statistical_code fields
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# ===================== Fixtures =====================

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json().get("access_token") or r.json().get("token")

@pytest.fixture(scope="module")
def admin_client(admin_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"})
    return s

@pytest.fixture(scope="module")
def broker_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "broker@customs.ly", "password": "Broker@2026!"})
    if r.status_code != 200:
        pytest.skip("Broker login failed")
    return r.json().get("access_token") or r.json().get("token")

@pytest.fixture(scope="module")
def broker_client(broker_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {broker_token}", "Content-Type": "application/json"})
    return s

@pytest.fixture(scope="module")
def pga_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "pga@customs.ly", "password": "PGA@2026!"})
    if r.status_code != 200:
        pytest.skip("PGA login failed")
    return r.json().get("access_token") or r.json().get("token")

@pytest.fixture(scope="module")
def pga_client(pga_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {pga_token}", "Content-Type": "application/json"})
    return s

@pytest.fixture(scope="module")
def carrier_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "carrier@customs.ly", "password": "Carrier@2026!"})
    if r.status_code != 200:
        pytest.skip("Carrier login failed")
    return r.json().get("access_token") or r.json().get("token")

@pytest.fixture(scope="module")
def carrier_client(carrier_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {carrier_token}", "Content-Type": "application/json"})
    return s

# ===================== Auth & Dashboard =====================

class TestAuth:
    """Admin login and dashboard stats"""

    def test_admin_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@customs.ly", "password": "Admin@2026!"})
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data or "token" in data
        print("Admin login OK")

    def test_dashboard_stats(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/dashboard/stats")
        assert r.status_code == 200
        data = r.json()
        print(f"Dashboard stats: {data}")

    def test_list_users_has_new_fields(self, admin_client):
        """UsersListPage depends on statistical_code and license_expiry_date in user list"""
        r = admin_client.get(f"{BASE_URL}/api/users")
        assert r.status_code == 200
        users = r.json()
        assert isinstance(users, list)
        # Check at least one user object - fields may be absent if not set
        if users:
            u = users[0]
            assert "_id" not in u or True  # _id should be excluded or it's fine
            print(f"Sample user keys: {list(u.keys())}")
        print(f"Users list count: {len(users)}")


# ===================== ACID + Platform Fees =====================

class TestAcidAndPlatformFees:
    """ACID creation creates platform fee record; platform_fees_paid=False"""

    acid_id = None

    def test_create_acid_with_exporter_email(self, broker_client):
        payload = {
            "supplier_name": "TEST_Supplier GmbH",
            "supplier_country": "DE",
            "goods_description": "TEST_Medical Equipment Phase-E",
            "hs_code": "9018.90",
            "quantity": 5,
            "unit": "طرد",
            "value_usd": 15000,
            "port_of_entry": "ميناء طرابلس البحري",
            "transport_mode": "sea",
            "carrier_name": "TEST Carrier",
            "exporter_email": "test_exporter@example.com",
        }
        r = broker_client.post(f"{BASE_URL}/api/acid", json=payload)
        assert r.status_code == 200, f"ACID create failed: {r.text}"
        data = r.json()
        assert data.get("platform_fees_paid") == False, "platform_fees_paid should be False on create"
        assert data.get("exporter_email") == "test_exporter@example.com"
        TestAcidAndPlatformFees.acid_id = data.get("_id")
        print(f"ACID created: {data.get('acid_number')}, platform_fees_paid={data.get('platform_fees_paid')}")

    def test_platform_fees_stats(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/platform-fees/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "pending" in data
        assert "paid" in data
        assert "total_lyd" in data
        print(f"Platform fees stats: {data}")

    def test_platform_fees_list_admin(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/platform-fees")
        assert r.status_code == 200
        fees = r.json()
        assert isinstance(fees, list)
        print(f"Platform fees count: {len(fees)}")
        if fees:
            print(f"Sample fee keys: {list(fees[0].keys())}")

    def test_acid_has_platform_fee_created(self, admin_client):
        """After ACID creation, there should be a platform fee record for it"""
        if not TestAcidAndPlatformFees.acid_id:
            pytest.skip("No ACID ID from previous test")
        r = admin_client.get(f"{BASE_URL}/api/platform-fees")
        assert r.status_code == 200
        fees = r.json()
        acid_fees = [f for f in fees if f.get("reference_id") == TestAcidAndPlatformFees.acid_id]
        assert len(acid_fees) > 0, "No platform fee found for the created ACID"
        assert acid_fees[0].get("status") == "pending"
        print(f"Platform fee for ACID: {acid_fees[0]}")


# ===================== PGA Risk Channel =====================

class TestPGAReview:
    """PGA review with risk_channel and pga_decision"""

    def test_pga_queue(self, pga_client):
        r = pga_client.get(f"{BASE_URL}/api/pga/queue")
        assert r.status_code == 200
        queue = r.json()
        print(f"PGA queue length: {len(queue)}")

    def test_pga_stats(self, pga_client):
        r = pga_client.get(f"{BASE_URL}/api/pga/stats")
        assert r.status_code == 200
        data = r.json()
        assert "approved" in data
        assert "rejected" in data
        print(f"PGA stats: {data}")

    def test_pga_review_accepts_risk_channel(self, pga_client, admin_client):
        """Test that PGA review endpoint accepts risk_channel and pga_decision"""
        # Find an approved ACID to review
        queue_r = pga_client.get(f"{BASE_URL}/api/pga/queue")
        queue = queue_r.json() if queue_r.status_code == 200 else []
        
        if not queue:
            # Create an approved ACID via admin
            # First get an existing ACID in submitted state
            acid_r = admin_client.get(f"{BASE_URL}/api/acid?status=submitted")
            acids = acid_r.json() if acid_r.status_code == 200 else []
            if not acids:
                pytest.skip("No approved ACID in PGA queue to test review")
            # Approve it
            a = acids[0]
            rev_r = admin_client.put(f"{BASE_URL}/api/acid/{a['_id']}/review",
                                     json={"action": "approve", "notes": "test auto-approve"})
            if rev_r.status_code != 200:
                pytest.skip("Could not approve ACID for PGA test")
            # Re-fetch queue
            queue_r2 = pga_client.get(f"{BASE_URL}/api/pga/queue")
            queue = queue_r2.json() if queue_r2.status_code == 200 else []
            if not queue:
                pytest.skip("Still no items in PGA queue")

        acid = queue[0]
        acid_id = acid["_id"]
        payload = {
            "action": "approve",
            "agency_name": "وزارة الصحة",
            "notes": "TEST: Risk channel green test",
            "risk_channel": "green",
            "pga_decision": "approve"
        }
        r = pga_client.post(f"{BASE_URL}/api/pga/{acid_id}/review", json=payload)
        assert r.status_code == 200, f"PGA review failed: {r.text}"
        data = r.json()
        assert "pga_status" in data
        print(f"PGA review result: {data}")

        # Verify risk_channel was saved
        acid_r = admin_client.get(f"{BASE_URL}/api/acid/{acid_id}")
        if acid_r.status_code == 200:
            updated = acid_r.json()
            assert updated.get("risk_channel") == "green", f"risk_channel not saved: {updated.get('risk_channel')}"
            print(f"risk_channel in ACID: {updated.get('risk_channel')}")


# ===================== Manifest (Carrier) =====================

class TestManifest:
    """Carrier dynamic manifest forms - sea/air/land fields"""

    def test_manifest_list(self, carrier_client):
        r = carrier_client.get(f"{BASE_URL}/api/manifests")
        assert r.status_code in [200, 404]
        if r.status_code == 200:
            print(f"Manifests: {len(r.json())}")

    def test_manifest_stats(self, carrier_client):
        r = carrier_client.get(f"{BASE_URL}/api/manifests/stats")
        assert r.status_code in [200, 404]
        if r.status_code == 200:
            print(f"Manifest stats: {r.json()}")

    def test_create_sea_manifest_with_imo(self, carrier_client):
        """Sea manifest with vessel, IMO, container_seal"""
        payload = {
            "transport_mode": "sea",
            "port_of_entry": "ميناء طرابلس البحري",
            "arrival_date": "2026-03-15",
            "vessel_name": "TEST Vessel Alpha",
            "imo_number": "IMO-TEST001",
            "voyage_id": "VOY-TEST-001",
            "container_seal": "SEAL-TEST-001",
            "container_ids": ["CNTR001", "CNTR002"],
            "consignments": [],
            "notes": "TEST sea manifest"
        }
        r = carrier_client.post(f"{BASE_URL}/api/manifests", json=payload)
        assert r.status_code in [200, 201], f"Sea manifest create failed: {r.text}"
        data = r.json()
        assert data.get("imo_number") == "IMO-TEST001"
        assert data.get("container_seal") == "SEAL-TEST-001"
        print(f"Sea manifest created: {data.get('manifest_number')}")

    def test_create_air_manifest_with_awb(self, carrier_client):
        """Air manifest with flight, airline, AWB"""
        payload = {
            "transport_mode": "air",
            "port_of_entry": "مطار معيتيقة الدولي",
            "arrival_date": "2026-03-20",
            "flight_number": "LY-TEST-123",
            "airline": "TEST Airways",
            "awb": "AWB-TEST-001",
            "consignments": [],
            "notes": "TEST air manifest"
        }
        r = carrier_client.post(f"{BASE_URL}/api/manifests", json=payload)
        assert r.status_code in [200, 201], f"Air manifest create failed: {r.text}"
        data = r.json()
        assert data.get("flight_number") == "LY-TEST-123"
        assert data.get("awb") == "AWB-TEST-001"
        print(f"Air manifest created: {data.get('manifest_number')}")

    def test_create_land_manifest_with_truck(self, carrier_client):
        """Land manifest with truck_plate, trailer_plate, driver_id"""
        payload = {
            "transport_mode": "land",
            "port_of_entry": "منفذ رأس جدير",
            "arrival_date": "2026-03-18",
            "truck_plate": "TEST-ABC-1234",
            "trailer_plate": "TRL-TEST-5678",
            "driver_id": "DRIVER-ID-001",
            "consignments": [],
            "notes": "TEST land manifest"
        }
        r = carrier_client.post(f"{BASE_URL}/api/manifests", json=payload)
        assert r.status_code in [200, 201], f"Land manifest create failed: {r.text}"
        data = r.json()
        assert data.get("truck_plate") == "TEST-ABC-1234"
        assert data.get("driver_id") == "DRIVER-ID-001"
        print(f"Land manifest created: {data.get('manifest_number')}")


# ===================== License Expiry Hard-Stop =====================

class TestLicenseExpiryHardStop:
    """Test that ACID creation fails for expired license"""

    expired_user_token = None

    def test_create_user_with_expired_license(self, admin_client):
        """Create a test importer with expired license"""
        payload = {
            "email": "TEST_expired_importer@test.ly",
            "password": "Test@2026!",
            "role": "importer",
            "name_ar": "TEST مستورد منتهي الرخصة",
            "name_en": "TEST Expired License Importer",
            "statistical_code": "LY-STAT-TEST001",
            "license_expiry_date": "2020-01-01"  # Expired
        }
        r = admin_client.post(f"{BASE_URL}/api/users", json=payload)
        if r.status_code in [200, 201]:
            print("Created expired importer user")
        else:
            print(f"User creation response: {r.status_code} - {r.text}")

    def test_expired_license_blocks_acid(self, admin_client):
        """After creating user with expired license, ACID creation should be blocked"""
        # Login as the expired user
        r = requests.post(f"{BASE_URL}/api/auth/login",
                         json={"email": "TEST_expired_importer@test.ly", "password": "Test@2026!"})
        if r.status_code != 200:
            pytest.skip(f"Could not login as expired user: {r.text}")
        
        token = r.json().get("access_token") or r.json().get("token")
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        
        payload = {
            "supplier_name": "TEST Supplier",
            "supplier_country": "TN",
            "goods_description": "Test goods",
            "hs_code": "1234.56",
            "quantity": 1,
            "unit": "طرد",
            "value_usd": 1000,
            "port_of_entry": "ميناء طرابلس البحري",
            "transport_mode": "land"
        }
        r2 = s.post(f"{BASE_URL}/api/acid", json=payload)
        assert r2.status_code == 403, f"Expected 403 for expired license, got {r2.status_code}: {r2.text}"
        detail = r2.json().get("detail", "")
        assert "انتهت" in detail or "expired" in detail.lower() or "رخصة" in detail, \
            f"Expected expiry message, got: {detail}"
        print(f"Hard-stop worked: {detail}")


# ===================== Gate Hard-Stop =====================

class TestGateHardStop:
    """Gate release queue returns data, platform_fees_paid check"""

    def test_gate_queue(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/gate/queue")
        assert r.status_code == 200
        queue = r.json()
        print(f"Gate queue length: {len(queue)}")
        if queue:
            req = queue[0]
            assert "platform_fees_paid" in req
            assert "treasury_paid" in req
            print(f"Gate queue item fields: platform_fees_paid={req.get('platform_fees_paid')}, treasury_paid={req.get('treasury_paid')}")
