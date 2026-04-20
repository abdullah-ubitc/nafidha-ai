"""
Employee management — create/list/update/suspend internal staff (admin only)
Multi-Role Support: كل موظف يمكن أن يحمل أدواراً متعددة
"""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
from database import db
from auth_utils import get_current_user, hash_password, require_roles
from models import UserRole, INTERNAL_CUSTOMS_ROLES
from helpers import log_audit

router = APIRouter(prefix="/employees", tags=["employees"])


# ── Pydantic models ──────────────────────────────────────────────────────────

class EmployeeCreate(BaseModel):
    name_ar: str
    name_en: Optional[str] = ""
    email: str
    password: str
    roles: List[str]  # مصفوفة الأدوار (الأول = الرئيسي)


class RolesUpdate(BaseModel):
    roles: List[str]


class StatusUpdate(BaseModel):
    is_active: bool


# ── Helpers ──────────────────────────────────────────────────────────────────

def _validate_roles(roles: List[str]):
    if not roles:
        raise HTTPException(400, "يجب تحديد دور واحد على الأقل")
    invalid = [r for r in roles if r not in INTERNAL_CUSTOMS_ROLES]
    if invalid:
        raise HTTPException(400, f"أدوار غير مسموحة للموظفين الداخليين: {invalid}")


def _format_employee(u: dict) -> dict:
    if "_id" in u and not isinstance(u["_id"], str):
        u["_id"] = str(u["_id"])
    u.pop("password_hash", None)
    u.pop("email_verify_token", None)
    if "created_at" in u and isinstance(u["created_at"], datetime):
        u["created_at"] = u["created_at"].isoformat()
    # ضمان وجود roles array
    if not u.get("roles"):
        u["roles"] = [u["role"]] if u.get("role") else []
    # ضمان وجود is_active
    if "is_active" not in u:
        u["is_active"] = True
    return u


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_employees(current_user=Depends(require_roles(UserRole.ADMIN))):
    """قائمة كل الموظفين الداخليين (admin فقط)"""
    cursor = db.users.find(
        {"role": {"$in": list(INTERNAL_CUSTOMS_ROLES)}},
        {"password_hash": 0, "email_verify_token": 0}
    ).sort("created_at", -1)
    employees = [_format_employee(u) async for u in cursor]
    return employees


@router.post("")
async def create_employee(
    data: EmployeeCreate,
    current_user=Depends(require_roles(UserRole.ADMIN))
):
    """إنشاء موظف جديد متعدد الأدوار"""
    _validate_roles(data.roles)

    existing = await db.users.find_one({"email": data.email.lower().strip()})
    if existing:
        raise HTTPException(409, "البريد الإلكتروني مستخدم بالفعل")

    primary_role = data.roles[0]
    new_employee = {
        "email": data.email.lower().strip(),
        "password_hash": hash_password(data.password),
        "role": primary_role,
        "roles": data.roles,
        "name_ar": data.name_ar.strip(),
        "name_en": (data.name_en or "").strip(),
        "is_verified": True,
        "is_active": True,
        "registration_status": "approved",
        "email_verified_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
        "created_by": current_user["_id"],
        "created_by_name": current_user.get("name_ar", ""),
    }

    result = await db.users.insert_one(new_employee)
    new_employee["_id"] = str(result.inserted_id)

    await log_audit(
        action="employee_created",
        user_id=current_user["_id"],
        user_name=current_user.get("name_ar", ""),
        resource_type="user",
        resource_id=str(result.inserted_id),
        details={"email": data.email, "roles": data.roles},
    )

    return _format_employee(new_employee)


@router.put("/{employee_id}/roles")
async def update_roles(
    employee_id: str,
    data: RolesUpdate,
    current_user=Depends(require_roles(UserRole.ADMIN))
):
    """تحديث أدوار موظف — يدخل حيز التنفيذ فور تسجيل الدخول القادم"""
    _validate_roles(data.roles)

    try:
        oid = ObjectId(employee_id)
    except Exception:
        raise HTTPException(400, "معرف غير صالح")

    employee = await db.users.find_one({"_id": oid})
    if not employee:
        raise HTTPException(404, "الموظف غير موجود")
    if employee.get("role") not in INTERNAL_CUSTOMS_ROLES:
        raise HTTPException(403, "لا يمكن تعديل أدوار المستخدمين التجاريين من هنا")
    if employee.get("email") == "admin@customs.ly":
        raise HTTPException(403, "لا يمكن تعديل أدوار حساب المدير الرئيسي")

    primary_role = data.roles[0]
    old_roles = employee.get("roles", [employee.get("role")])
    await db.users.update_one(
        {"_id": oid},
        {"$set": {"roles": data.roles, "role": primary_role}}
    )

    await log_audit(
        action="employee_roles_updated",
        user_id=current_user["_id"],
        user_name=current_user.get("name_ar", ""),
        resource_type="user",
        resource_id=employee_id,
        details={"old_roles": old_roles, "new_roles": data.roles},
    )

    updated = await db.users.find_one({"_id": oid}, {"password_hash": 0})
    return _format_employee(updated)


@router.put("/{employee_id}/status")
async def update_status(
    employee_id: str,
    data: StatusUpdate,
    current_user=Depends(require_roles(UserRole.ADMIN))
):
    """تفعيل / تعليق حساب موظف"""
    if employee_id == current_user["_id"]:
        raise HTTPException(400, "لا يمكنك تعليق حسابك الشخصي")

    try:
        oid = ObjectId(employee_id)
    except Exception:
        raise HTTPException(400, "معرف غير صالح")

    employee = await db.users.find_one({"_id": oid})
    if not employee:
        raise HTTPException(404, "الموظف غير موجود")
    if employee.get("email") == "admin@customs.ly":
        raise HTTPException(403, "لا يمكن تعليق حساب المدير الرئيسي")

    await db.users.update_one({"_id": oid}, {"$set": {"is_active": data.is_active}})

    await log_audit(
        action="employee_status_updated",
        user_id=current_user["_id"],
        user_name=current_user.get("name_ar", ""),
        resource_type="user",
        resource_id=employee_id,
        details={"is_active": data.is_active},
    )

    return {"success": True, "is_active": data.is_active}
