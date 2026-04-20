"""
Multi-Role Employee Management Tests — iteration 43
Tests: GET /employees, POST /employees, PUT /employees/{id}/roles, PUT /employees/{id}/status
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_EMAIL = "admin@customs.ly"
ADMIN_PASS = "Admin@2026!"
REG_OFFICER_EMAIL = "reg_officer@customs.ly"
REG_OFFICER_PASS = "RegOfficer@2026!"
TEST_EMPLOYEE_EMAIL = "test_suspend_iter43@customs.ly"
TEST_EMPLOYEE_PASS = "TestPass@2026!"

def get_admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    cookies = r.cookies
    return cookies

def get_employee_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password})
    return r.cookies, r.status_code, r.json() if r.headers.get('content-type','').startswith('application/json') else {}


class TestEmployeeListAPI:
    """GET /api/employees — admin gets list with roles array"""

    def test_list_employees_as_admin(self):
        cookies = get_admin_token()
        r = requests.get(f"{BASE_URL}/api/employees", cookies=cookies)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"PASS: GET /employees returned {len(data)} employees")

    def test_list_employees_has_roles_array(self):
        cookies = get_admin_token()
        r = requests.get(f"{BASE_URL}/api/employees", cookies=cookies)
        assert r.status_code == 200
        data = r.json()
        if data:
            emp = data[0]
            assert "roles" in emp, "Each employee must have 'roles' field"
            assert isinstance(emp["roles"], list), "roles must be array"
            print(f"PASS: First employee has roles={emp['roles']}")
        else:
            print("No employees found (empty list)")

    def test_list_employees_unauthorized_as_reg_officer(self):
        cookies, status, _ = get_employee_token(REG_OFFICER_EMAIL, REG_OFFICER_PASS)
        r = requests.get(f"{BASE_URL}/api/employees", cookies=cookies)
        assert r.status_code == 403, f"Expected 403 for non-admin, got {r.status_code}"
        print(f"PASS: reg_officer gets 403 on GET /employees")


class TestCreateEmployee:
    """POST /api/employees — create employee with roles array"""

    created_id = None

    def test_create_employee_single_role(self):
        cookies = get_admin_token()
        payload = {
            "name_ar": "موظف تجريبي إيتر43",
            "name_en": "Test Employee iter43",
            "email": TEST_EMPLOYEE_EMAIL,
            "password": TEST_EMPLOYEE_PASS,
            "roles": ["registration_officer"]
        }
        r = requests.post(f"{BASE_URL}/api/employees", json=payload, cookies=cookies)
        if r.status_code == 409:
            print("Employee already exists — skipping creation")
            return
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "roles" in data, "Response must contain 'roles'"
        assert data["roles"] == ["registration_officer"], f"Expected ['registration_officer'], got {data['roles']}"
        assert data["email"] == TEST_EMPLOYEE_EMAIL
        TestCreateEmployee.created_id = data.get("_id")
        print(f"PASS: Created employee with roles={data['roles']}, id={data.get('_id')}")

    def test_create_employee_invalid_role(self):
        cookies = get_admin_token()
        payload = {
            "name_ar": "موظف غير صالح",
            "email": "invalid_role_test@customs.ly",
            "password": "Test@2026!",
            "roles": ["nonexistent_role"]
        }
        r = requests.post(f"{BASE_URL}/api/employees", json=payload, cookies=cookies)
        assert r.status_code == 400, f"Expected 400 for invalid role, got {r.status_code}"
        print("PASS: Invalid role returns 400")

    def test_create_employee_no_roles_fails(self):
        cookies = get_admin_token()
        payload = {
            "name_ar": "موظف بدون دور",
            "email": "norole_test@customs.ly",
            "password": "Test@2026!",
            "roles": []
        }
        r = requests.post(f"{BASE_URL}/api/employees", json=payload, cookies=cookies)
        assert r.status_code in [400, 422], f"Expected 400/422 for empty roles, got {r.status_code}"
        print(f"PASS: Empty roles returns {r.status_code}")


class TestUpdateRoles:
    """PUT /api/employees/{id}/roles — update to multi-role"""

    def _get_test_employee_id(self, cookies):
        """Find or create test employee"""
        r = requests.get(f"{BASE_URL}/api/employees", cookies=cookies)
        employees = r.json()
        for e in employees:
            if e.get("email") == TEST_EMPLOYEE_EMAIL:
                return e["_id"]
        # Create if missing
        payload = {
            "name_ar": "موظف تجريبي إيتر43",
            "email": TEST_EMPLOYEE_EMAIL,
            "password": TEST_EMPLOYEE_PASS,
            "roles": ["registration_officer"]
        }
        cr = requests.post(f"{BASE_URL}/api/employees", json=payload, cookies=cookies)
        if cr.status_code in [200, 201]:
            return cr.json()["_id"]
        return None

    def test_update_to_multi_role(self):
        cookies = get_admin_token()
        emp_id = self._get_test_employee_id(cookies)
        if not emp_id:
            pytest.skip("Cannot find test employee")
        r = requests.put(f"{BASE_URL}/api/employees/{emp_id}/roles",
                         json={"roles": ["registration_officer", "acid_risk_officer"]},
                         cookies=cookies)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "roles" in data
        assert "registration_officer" in data["roles"]
        assert "acid_risk_officer" in data["roles"]
        assert len(data["roles"]) == 2
        print(f"PASS: Updated roles to {data['roles']}")

    def test_update_roles_verifies_primary_role(self):
        """Primary role (role field) should match first role in array"""
        cookies = get_admin_token()
        emp_id = self._get_test_employee_id(cookies)
        if not emp_id:
            pytest.skip("Cannot find test employee")
        new_roles = ["acid_risk_officer", "registration_officer"]
        r = requests.put(f"{BASE_URL}/api/employees/{emp_id}/roles",
                         json={"roles": new_roles}, cookies=cookies)
        assert r.status_code == 200
        data = r.json()
        assert data.get("role") == "acid_risk_officer", f"Primary role should be first in array, got {data.get('role')}"
        print(f"PASS: Primary role = {data.get('role')} (first in array)")


class TestSuspendEmployee:
    """PUT /api/employees/{id}/status — suspend and verify login rejected"""

    def _get_test_employee_id(self, cookies):
        r = requests.get(f"{BASE_URL}/api/employees", cookies=cookies)
        employees = r.json()
        for e in employees:
            if e.get("email") == TEST_EMPLOYEE_EMAIL:
                return e["_id"]
        return None

    def test_suspend_employee(self):
        cookies = get_admin_token()
        emp_id = self._get_test_employee_id(cookies)
        if not emp_id:
            pytest.skip("Cannot find test employee")
        r = requests.put(f"{BASE_URL}/api/employees/{emp_id}/status",
                         json={"is_active": False}, cookies=cookies)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("is_active") == False
        print(f"PASS: Employee suspended, is_active={data.get('is_active')}")

    def test_suspended_employee_login_rejected(self):
        """After suspension, login should return 403"""
        # First ensure employee is suspended
        admin_cookies = get_admin_token()
        emp_id = self._get_test_employee_id(admin_cookies)
        if not emp_id:
            pytest.skip("Cannot find test employee")
        # Suspend
        requests.put(f"{BASE_URL}/api/employees/{emp_id}/status",
                     json={"is_active": False}, cookies=admin_cookies)
        # Now try to login
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": TEST_EMPLOYEE_EMAIL, "password": TEST_EMPLOYEE_PASS})
        assert r.status_code == 403, f"Expected 403 for suspended user, got {r.status_code}: {r.text}"
        print(f"PASS: Suspended employee login returns {r.status_code}")

    def test_reactivate_employee(self):
        """Cleanup: reactivate employee"""
        admin_cookies = get_admin_token()
        emp_id = self._get_test_employee_id(admin_cookies)
        if not emp_id:
            pytest.skip("Cannot find test employee")
        r = requests.put(f"{BASE_URL}/api/employees/{emp_id}/status",
                         json={"is_active": True}, cookies=admin_cookies)
        assert r.status_code == 200
        assert r.json().get("is_active") == True
        print("PASS: Employee reactivated")


class TestMultiRoleEmployee:
    """Test the test_multi_role@customs.ly employee (registration_officer + acid_risk_officer)"""

    def test_multi_role_employee_login(self):
        """test_multi_role@customs.ly should be able to login"""
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": "test_multi_role@customs.ly", "password": "TestPass@2026!"})
        if r.status_code == 404:
            pytest.skip("test_multi_role@customs.ly does not exist yet — will be created in frontend test")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        user = data.get("user", {})
        roles = user.get("roles", [])
        print(f"Multi-role user roles: {roles}")
        # May have been created already
        print(f"PASS: test_multi_role login successful, roles={roles}")

    def test_reg_officer_login(self):
        """reg_officer should login and have only registration_officer role"""
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": REG_OFFICER_EMAIL, "password": REG_OFFICER_PASS})
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        data = r.json()
        user = data.get("user", {})
        roles = user.get("roles", [])
        assert "registration_officer" in roles, f"Expected registration_officer in roles, got {roles}"
        print(f"PASS: reg_officer login OK, roles={roles}")
