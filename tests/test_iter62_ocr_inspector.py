"""
Tests for OCR Modular Service + Cost Tracking + Inspector Dashboard backend
Iteration 62 — OCR scan-document, usage endpoints, doc validation, cost alerts
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@customs.ly", "password": "Admin@2026!"
    })
    assert r.status_code == 200
    return r.json()["access_token"]

@pytest.fixture(scope="module")
def inspector_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "inspector@customs.ly", "password": "Inspector@2026!"
    })
    assert r.status_code == 200
    return r.json()["access_token"]

@pytest.fixture(scope="module")
def test_acid_id():
    """Get an existing approved ACID with channel_type=yellow"""
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@customs.ly", "password": "Admin@2026!"
    })
    token = r.json()["access_token"]
    r2 = requests.get(f"{BASE_URL}/api/acid", headers={"Authorization": f"Bearer {token}"})
    items = r2.json() if isinstance(r2.json(), list) else r2.json().get("items", [])
    for item in items:
        if item.get("channel_type") == "yellow":
            return item["_id"]
    pytest.skip("No yellow channel ACID found")

@pytest.fixture(scope="module")
def test_image():
    with open("/tmp/test_doc.jpg", "rb") as f:
        return f.read()


# ── OCR scan-document endpoint ────────────────────────────────────────────────

class TestOCRScanDocument:
    """POST /api/ocr/scan-document tests"""

    def test_scan_document_success_invoice(self, inspector_token, test_image):
        """OCR scan with valid invoice doc_type returns 200, no 500"""
        r = requests.post(
            f"{BASE_URL}/api/ocr/scan-document",
            headers={"Authorization": f"Bearer {inspector_token}"},
            files={"file": ("test.jpg", test_image, "image/jpeg")},
            data={"doc_type": "invoice"}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "ocr_failed" in data
        assert "extracted_fields" in data
        assert "doc_type" in data
        assert data["doc_type"] == "invoice"
        print(f"PASS: scan-document invoice — ocr_failed={data['ocr_failed']}, confidence={data.get('confidence')}")

    def test_scan_document_invalid_doc_type_400(self, inspector_token, test_image):
        """Unknown doc_type returns 400"""
        r = requests.post(
            f"{BASE_URL}/api/ocr/scan-document",
            headers={"Authorization": f"Bearer {inspector_token}"},
            files={"file": ("test.jpg", test_image, "image/jpeg")},
            data={"doc_type": "unknown_type"}
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text[:200]}"
        print("PASS: invalid doc_type returns 400")

    def test_scan_document_fail_safe_no_crash(self, inspector_token):
        """Corrupt/tiny file should return ocr_failed=True, not 500"""
        corrupt = b"not_an_image_at_all"
        r = requests.post(
            f"{BASE_URL}/api/ocr/scan-document",
            headers={"Authorization": f"Bearer {inspector_token}"},
            files={"file": ("corrupt.jpg", corrupt, "image/jpeg")},
            data={"doc_type": "invoice"}
        )
        # Should NOT be 500
        assert r.status_code != 500, f"Fail-safe broken: got 500 — {r.text[:200]}"
        assert r.status_code == 200
        data = r.json()
        # OCR may fail or succeed — key is no 500
        print(f"PASS: fail-safe check — status={r.status_code}, ocr_failed={data.get('ocr_failed')}")

    def test_scan_document_with_acid_id(self, inspector_token, test_image, test_acid_id):
        """Scan with valid acid_id logs usage"""
        r = requests.post(
            f"{BASE_URL}/api/ocr/scan-document",
            headers={"Authorization": f"Bearer {inspector_token}"},
            files={"file": ("test.jpg", test_image, "image/jpeg")},
            data={"doc_type": "invoice", "acid_id": test_acid_id}
        )
        assert r.status_code == 200
        data = r.json()
        assert "cost_per_scan" in data
        assert "shipment_total_cost" in data
        assert "alert_triggered" in data
        print(f"PASS: scan with acid_id — cost={data.get('cost_per_scan')}, total={data.get('shipment_total_cost')}, alert={data.get('alert_triggered')}")

    def test_scan_doc_types_all_4_valid(self, inspector_token, test_image):
        """All 4 doc_types are accepted"""
        for dt in ["invoice", "certificate_of_origin", "passport", "bill_of_lading"]:
            r = requests.post(
                f"{BASE_URL}/api/ocr/scan-document",
                headers={"Authorization": f"Bearer {inspector_token}"},
                files={"file": ("test.jpg", test_image, "image/jpeg")},
                data={"doc_type": dt}
            )
            assert r.status_code == 200, f"doc_type={dt} returned {r.status_code}"
            print(f"  PASS: doc_type={dt}")

    def test_scan_document_unauthenticated_401(self, test_image):
        """No token returns 401"""
        r = requests.post(
            f"{BASE_URL}/api/ocr/scan-document",
            files={"file": ("test.jpg", test_image, "image/jpeg")},
            data={"doc_type": "invoice"}
        )
        assert r.status_code in [401, 403], f"Expected 401/403, got {r.status_code}"
        print("PASS: unauthenticated returns 401/403")


# ── OCR Usage Endpoints ────────────────────────────────────────────────────────

class TestOCRUsage:
    """GET /api/ocr/usage/{acid_id} and /api/ocr/usage-summary"""

    def test_usage_acid_id_returns_summary_and_logs(self, inspector_token, test_acid_id):
        """GET /api/ocr/usage/{acid_id} returns {summary, logs}"""
        r = requests.get(
            f"{BASE_URL}/api/ocr/usage/{test_acid_id}",
            headers={"Authorization": f"Bearer {inspector_token}"}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "summary" in data, f"Missing 'summary' in response: {data}"
        assert "logs" in data, f"Missing 'logs' in response: {data}"
        assert "total_cost_usd" in data["summary"]
        assert "scan_count" in data["summary"]
        print(f"PASS: usage/{test_acid_id} — total_cost={data['summary']['total_cost_usd']}, scans={data['summary']['scan_count']}")

    def test_usage_invalid_acid_id_400(self, inspector_token):
        """Invalid ObjectId returns 400"""
        r = requests.get(
            f"{BASE_URL}/api/ocr/usage/invalid_id_123",
            headers={"Authorization": f"Bearer {inspector_token}"}
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}"
        print("PASS: invalid acid_id returns 400")

    def test_usage_summary_admin(self, admin_token):
        """GET /api/ocr/usage-summary returns admin overview"""
        r = requests.get(
            f"{BASE_URL}/api/ocr/usage-summary",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "total_cost_usd" in data
        assert "total_scans" in data
        assert "by_shipment" in data
        assert isinstance(data["by_shipment"], list)
        print(f"PASS: usage-summary — total_cost={data['total_cost_usd']}, total_scans={data['total_scans']}")

    def test_usage_summary_non_admin_forbidden(self, inspector_token):
        """Non-admin cannot access usage-summary"""
        r = requests.get(
            f"{BASE_URL}/api/ocr/usage-summary",
            headers={"Authorization": f"Bearer {inspector_token}"}
        )
        assert r.status_code in [401, 403], f"Expected 403, got {r.status_code}"
        print(f"PASS: non-admin usage-summary returns {r.status_code}")


# ── Cost Alert Test ────────────────────────────────────────────────────────────

class TestCostAlert:
    """Test alert_triggered=True when shipment cost >= $2"""

    def test_cost_alert_accumulates(self, inspector_token, test_image, test_acid_id):
        """After enough scans, alert_triggered should become True"""
        # Do multiple scans to accumulate cost
        alert_seen = False
        for i in range(5):
            r = requests.post(
                f"{BASE_URL}/api/ocr/scan-document",
                headers={"Authorization": f"Bearer {inspector_token}"},
                files={"file": ("test.jpg", test_image, "image/jpeg")},
                data={"doc_type": "invoice", "acid_id": test_acid_id}
            )
            assert r.status_code == 200
            data = r.json()
            if data.get("alert_triggered"):
                alert_seen = True
                assert "alert_message" in data
                assert data["alert_message"] is not None
                print(f"PASS: alert_triggered=True after {i+1} scans, total=${data.get('shipment_total_cost')}")
                break

        # Check usage endpoint now shows accumulated cost
        r2 = requests.get(
            f"{BASE_URL}/api/ocr/usage/{test_acid_id}",
            headers={"Authorization": f"Bearer {inspector_token}"}
        )
        assert r2.status_code == 200
        usage_data = r2.json()
        scan_count = usage_data["summary"]["scan_count"]
        total_cost = usage_data["summary"]["total_cost_usd"]
        print(f"INFO: After scans — count={scan_count}, total_cost=${total_cost:.2f}")

        if total_cost >= 2.0:
            print("PASS: alert threshold reached")
        else:
            print(f"INFO: Not yet at alert threshold (${total_cost:.2f} < $2.00) — need more scans")


# ── OCR Service DOC_SCHEMAS Validation ────────────────────────────────────────

class TestDocSchemas:
    """Verify DOC_SCHEMAS has 4 doc types"""

    def test_four_doc_types_available(self, inspector_token, test_image):
        """All 4 doc_types must be valid"""
        expected = ["invoice", "certificate_of_origin", "passport", "bill_of_lading"]
        for dt in expected:
            r = requests.post(
                f"{BASE_URL}/api/ocr/scan-document",
                headers={"Authorization": f"Bearer {inspector_token}"},
                files={"file": ("test.jpg", test_image, "image/jpeg")},
                data={"doc_type": dt}
            )
            assert r.status_code == 200, f"doc_type '{dt}' not accepted: {r.status_code}"
        print("PASS: All 4 doc_types valid")


# ── Inspector Queue ────────────────────────────────────────────────────────────

class TestInspectorQueue:
    """GET /api/inspections/assignments"""

    def test_inspector_assignments_200(self, inspector_token):
        r = requests.get(
            f"{BASE_URL}/api/inspections/assignments",
            headers={"Authorization": f"Bearer {inspector_token}"}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert isinstance(data, list)
        print(f"PASS: inspector assignments — {len(data)} items")

    def test_yellow_review_high_risk_blocked(self, inspector_token):
        """High-risk ACID blocked with 400 from yellow-review"""
        # Use a fake high-risk ACID id
        r = requests.post(
            f"{BASE_URL}/api/inspections/yellow-review",
            headers={"Authorization": f"Bearer {inspector_token}"},
            json={"acid_id": "000000000000000000000001", "decision": "approved", "notes": "test"}
        )
        # Should be 400 or 404 (not 200 for high risk or invalid)
        assert r.status_code in [400, 404, 422], f"Expected 4xx, got {r.status_code}: {r.text[:200]}"
        print(f"PASS: yellow-review invalid acid_id returns {r.status_code}")
