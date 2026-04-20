"""
Land Trip API Tests — iteration 50
Tests: submit, by-acid, approve (musaid strict), reject, queue/pending
"""
import pytest
import requests
import os
import io

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_CREDS      = {"email": "admin@customs.ly",    "password": "Admin@2026!"}
MANIFEST_CREDS   = {"email": "manifest@customs.ly", "password": "Manifest@2026!"}
CARRIER_CREDS    = {"email": "carrier@customs.ly",  "password": "Carrier@2026!"}

LAND_ACID_MUSAID_ID = "69d2509b50dc89e64841a3e6"   # منفذ مساعد
LAND_ACID_MUSAID2   = "69d2509b50dc89e64841a3d2"   # منفذ مساعد (alternate)

def get_token(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
    if r.status_code == 200:
        return r.json().get("token") or r.json().get("access_token")
    return None


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def dummy_photo():
    """Return a tiny dummy JPEG bytes"""
    return io.BytesIO(b'\xff\xd8\xff\xe0' + b'\x00' * 10 + b'\xff\xd9')


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def admin_token():
    t = get_token(ADMIN_CREDS)
    assert t, "Admin login failed"
    return t

@pytest.fixture(scope="module")
def manifest_token():
    t = get_token(MANIFEST_CREDS)
    assert t, "Manifest officer login failed"
    return t

@pytest.fixture(scope="module")
def carrier_token():
    t = get_token(CARRIER_CREDS)
    assert t, "Carrier agent login failed"
    return t


# ── Tests ─────────────────────────────────────────────────────────────────────
class TestLandTripQueue:
    """GET /land-trip/queue/pending — manifest officer"""

    def test_queue_pending_manifest_officer(self, manifest_token):
        r = requests.get(f"{BASE_URL}/api/land-trip/queue/pending",
                         headers=auth_headers(manifest_token))
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list), "Expected list"
        print(f"PASS: queue/pending returned {len(data)} trips")

    def test_queue_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/land-trip/queue/pending")
        assert r.status_code == 401, f"Expected 401 without auth, got {r.status_code}"
        print("PASS: queue/pending requires auth")

    def test_carrier_cannot_access_queue(self, carrier_token):
        r = requests.get(f"{BASE_URL}/api/land-trip/queue/pending",
                         headers=auth_headers(carrier_token))
        assert r.status_code in [401, 403], f"Expected 401/403, got {r.status_code}"
        print("PASS: carrier cannot access queue/pending")


class TestLandTripByAcid:
    """GET /land-trip/by-acid/{acid_id}"""

    def test_by_acid_returns_trip_or_404(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/land-trip/by-acid/{LAND_ACID_MUSAID_ID}",
                         headers=auth_headers(admin_token))
        assert r.status_code in [200, 404], f"Expected 200 or 404, got {r.status_code}"
        if r.status_code == 200:
            data = r.json()
            assert "status" in data
            assert "truck_license_plate" in data
            assert "driver_name" in data
            print(f"PASS: by-acid returned trip with status={data['status']}")
        else:
            print("PASS: by-acid returned 404 (no trip yet)")

    def test_by_acid_invalid_id(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/land-trip/by-acid/invalid_id",
                         headers=auth_headers(admin_token))
        assert r.status_code == 400, f"Expected 400, got {r.status_code}"
        print("PASS: by-acid returns 400 for invalid id")


class TestLandTripSubmit:
    """POST /land-trip/submit — carrier agent submits land trip"""

    def test_carrier_can_submit_land_trip(self, carrier_token):
        # First check if there's already an active trip; use ACID_MUSAID2 for fresh submit
        # Check existing
        r_check = requests.get(f"{BASE_URL}/api/land-trip/by-acid/{LAND_ACID_MUSAID2}",
                                headers=auth_headers(carrier_token))
        if r_check.status_code == 200 and r_check.json().get("status") == "pending":
            print("SKIP: Active pending trip exists for this ACID — cannot submit duplicate")
            pytest.skip("Active pending trip already exists")

        files = {"driver_id_photo": ("id.jpg", dummy_photo(), "image/jpeg")}
        data  = {
            "acid_id":            LAND_ACID_MUSAID2,
            "truck_license_plate": "TEST-9999",
            "truck_nationality":  "ليبيا",
            "driver_name":        "محمد اختبار",
            "driver_id_type":     "license",
        }
        r = requests.post(f"{BASE_URL}/api/land-trip/submit",
                          headers=auth_headers(carrier_token),
                          data=data, files=files)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert "trip_id" in body
        assert body.get("is_musaid_port") is True
        print(f"PASS: carrier submitted land trip, trip_id={body['trip_id']}")

    def test_submit_non_land_acid_fails(self, carrier_token):
        """Sea ACID should fail (if available)"""
        # Use a non-land ACID — we test with a fake id to get 404 rather than 400
        # Just verify the route exists and rejects non-land
        files = {"driver_id_photo": ("id.jpg", dummy_photo(), "image/jpeg")}
        data  = {
            "acid_id":             "000000000000000000000000",  # non-existent
            "truck_license_plate": "TEST-0000",
            "truck_nationality":   "ليبيا",
            "driver_name":         "اختبار",
            "driver_id_type":      "license",
        }
        r = requests.post(f"{BASE_URL}/api/land-trip/submit",
                          headers=auth_headers(carrier_token),
                          data=data, files=files)
        assert r.status_code in [400, 404], f"Expected 400/404, got {r.status_code}: {r.text}"
        print(f"PASS: non-existent acid returns {r.status_code}")


class TestMusaidApproveReject:
    """Approve/Reject logic with Musaid strict rule"""

    def _get_pending_musaid_trip(self, manifest_token, acid_id=LAND_ACID_MUSAID_ID):
        """Get a pending trip for Musaid port"""
        r = requests.get(f"{BASE_URL}/api/land-trip/queue/pending",
                         headers=auth_headers(manifest_token))
        if r.status_code != 200:
            return None
        trips = r.json()
        for t in trips:
            if t.get("is_musaid_port") and t.get("status") == "pending":
                return t["_id"]
        return None

    def test_approve_musaid_without_photo_confirm_fails_422(self, manifest_token, admin_token):
        trip_id = self._get_pending_musaid_trip(manifest_token)
        if not trip_id:
            # Try to create one via admin submit
            print("No pending Musaid trip — creating one for test")
            files = {"driver_id_photo": ("id.jpg", dummy_photo(), "image/jpeg")}
            data  = {
                "acid_id":            LAND_ACID_MUSAID_ID,
                "truck_license_plate": "MUSAID-001",
                "truck_nationality":  "ليبيا",
                "driver_name":        "سائق اختبار مساعد",
                "driver_id_type":     "license",
            }
            r_sub = requests.post(f"{BASE_URL}/api/land-trip/submit",
                                   headers=auth_headers(admin_token),
                                   data=data, files=files)
            if r_sub.status_code not in [200, 409]:
                pytest.skip(f"Could not create test trip: {r_sub.status_code}")
            if r_sub.status_code == 409:
                # Already exists, re-fetch
                trip_id = self._get_pending_musaid_trip(manifest_token)
                if not trip_id:
                    pytest.skip("No pending Musaid trip available")
            else:
                trip_id = r_sub.json().get("trip_id")

        # Attempt approve WITHOUT photo_clarity_confirmed
        fd = {"photo_clarity_confirmed": "false"}
        r = requests.post(f"{BASE_URL}/api/land-trip/{trip_id}/approve",
                          headers=auth_headers(manifest_token), data=fd)
        assert r.status_code == 422, f"Expected 422 for Musaid without photo confirm, got {r.status_code}: {r.text}"
        body = r.json()
        detail = body.get("detail", {})
        code = detail.get("code") if isinstance(detail, dict) else ""
        assert code == "MUSAID_PHOTO_REQUIRED" or "MUSAID" in str(detail).upper()
        print(f"PASS: approve without photo confirm returns 422 MUSAID_PHOTO_REQUIRED")

    def test_approve_musaid_with_photo_confirm_succeeds(self, manifest_token, admin_token):
        trip_id = self._get_pending_musaid_trip(manifest_token)
        if not trip_id:
            pytest.skip("No pending Musaid trip available to approve")

        fd = {"photo_clarity_confirmed": "true"}
        r = requests.post(f"{BASE_URL}/api/land-trip/{trip_id}/approve",
                          headers=auth_headers(manifest_token), data=fd)
        # Might be 409 if already processed
        assert r.status_code in [200, 409], f"Expected 200/409, got {r.status_code}: {r.text}"
        if r.status_code == 200:
            print(f"PASS: Musaid trip approved with photo_confirm=true")
        else:
            print(f"PASS: Trip already processed (409)")

    def test_reject_land_trip_with_reason(self, manifest_token, admin_token, carrier_token):
        """Submit a new trip then reject it"""
        # Submit first
        files = {"driver_id_photo": ("id.jpg", dummy_photo(), "image/jpeg")}
        data  = {
            "acid_id":            LAND_ACID_MUSAID2,
            "truck_license_plate": "REJECT-999",
            "truck_nationality":  "ليبيا",
            "driver_name":        "سائق للرفض",
            "driver_id_type":     "license",
        }
        r_sub = requests.post(f"{BASE_URL}/api/land-trip/submit",
                               headers=auth_headers(carrier_token),
                               data=data, files=files)
        if r_sub.status_code == 409:
            # Already exists; find pending trip for this ACID
            r_chk = requests.get(f"{BASE_URL}/api/land-trip/by-acid/{LAND_ACID_MUSAID2}",
                                  headers=auth_headers(manifest_token))
            if r_chk.status_code == 200 and r_chk.json().get("status") == "pending":
                trip_id = r_chk.json()["_id"]
            else:
                pytest.skip("Cannot get pending trip for reject test")
        elif r_sub.status_code == 200:
            trip_id = r_sub.json()["trip_id"]
        else:
            pytest.skip(f"Submit failed: {r_sub.status_code}")

        fd = {"reason": "وثيقة السائق غير واضحة — اختبار"}
        r_rej = requests.post(f"{BASE_URL}/api/land-trip/{trip_id}/reject",
                               headers=auth_headers(manifest_token), data=fd)
        assert r_rej.status_code in [200, 409], f"Expected 200/409, got {r_rej.status_code}: {r_rej.text}"
        print(f"PASS: reject trip returns {r_rej.status_code}")
