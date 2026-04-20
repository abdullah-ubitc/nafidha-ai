"""User management routes"""
from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
from models import UserRole
from database import db
from auth_utils import require_roles, format_user, get_current_user

router = APIRouter(prefix="/users", tags=["users"])

# ── Port → Region mapping (for ACID broker filtering) ─────────────────────────
PORT_TO_REGION = {
    "طرابلس البحري": "TRP",    "مطار طرابلس الدولي": "TRP",
    "مطار معيتيقة": "TRP",     "رأس جدير البري": "TRP",
    "منفذ الوازن": "TRP",      "ميناء الزاوية": "ZWT",
    "ميناء الخمس": "ZWT",      "ميناء زوارة": "ZWT",
    "أمبروزية البري": "ZWT",
    "بنغازي البحري": "BNG",    "مطار بنينة الدولي": "BNG",
    "منفذ مساعد": "BNG",       "منفذ أمساعد": "BNG",
    "ميناء درنة": "BNG",       "ميناء راس لانوف": "BNG",
    "مصراتة البحري": "MSR",    "مطار مصراتة": "MSR",
    "مطار سبها": "SBH",        "منفذ الشورف": "SBH",
}

# Regions with Musaid as priority port
MUSAID_REGIONS = {"BNG", "MSR"}


# ── GET /users/available-brokers ──────────────────────────────────────────────
@router.get("/available-brokers")
async def get_available_brokers(
    port_of_entry: Optional[str] = Query(None, description="Filter brokers by port region"),
    current_user=Depends(get_current_user),
):
    """
    يُرجع قائمة المخلصين الجمركيين النشطين (غير المجمَّدين) المؤهَّلين للمنفذ المحدد.
    - شركات التخليص: وصول وطني — تظهر دائماً
    - مخلص فردي: يظهر فقط إذا كانت منطقته تخدم منفذ الدخول المحدد
    """
    today = datetime.now(timezone.utc).date().isoformat()

    base_filter = {
        "role":                "customs_broker",
        "registration_status": "approved",
        "account_status":      "active",
    }

    all_brokers = await db.users.find(
        base_filter,
        {
            "_id": 1, "name_ar": 1, "name_en": 1,
            "company_name_ar": 1, "company_name_en": 1,
            "broker_type": 1, "customs_region": 1,
            "broker_license_number": 1, "broker_license_expiry": 1,
            "statistical_expiry_date": 1, "email": 1,
        }
    ).to_list(200)

    port_region = PORT_TO_REGION.get(port_of_entry) if port_of_entry else None
    result = []
    for broker in all_brokers:
        b = {
            "_id":               str(broker["_id"]),
            "name_ar":           broker.get("name_ar", ""),
            "name_en":           broker.get("name_en", ""),
            "company_name_ar":   broker.get("company_name_ar", ""),
            "company_name_en":   broker.get("company_name_en", ""),
            "broker_type":       broker.get("broker_type", "individual"),
            "customs_region":    broker.get("customs_region", ""),
            "broker_license_number": broker.get("broker_license_number", ""),
            "statistical_expiry_date": broker.get("statistical_expiry_date", ""),
            "email":             broker.get("email", ""),
            "is_musaid_priority": False,
        }

        is_company = b["broker_type"] == "company"

        # تصفية جغرافية
        if port_region and not is_company:
            if b["customs_region"] != port_region:
                continue  # مخلص فردي خارج منطقة المنفذ — يُستبعد

        # Musaid Priority للمخلصين في BNG/MSR
        broker_region = b["customs_region"] or ""
        if broker_region in MUSAID_REGIONS:
            b["is_musaid_priority"] = True

        result.append(b)

    # ترتيب: Musaid priority أولاً، ثم companies، ثم individuals
    result.sort(key=lambda x: (0 if x["is_musaid_priority"] else 1, 0 if x["broker_type"] == "company" else 1))
    return result


@router.get("")
async def list_users(current_user=Depends(require_roles(UserRole.ADMIN, UserRole.ACID_REVIEWER))):
    users = await db.users.find({}, {"password_hash": 0}).to_list(200)
    return [format_user(u) for u in users]


@router.get("/stats")
async def users_stats(current_user=Depends(require_roles(UserRole.ADMIN))):
    pipeline = [{"$group": {"_id": "$role", "count": {"$sum": 1}}}]
    result = await db.users.aggregate(pipeline).to_list(20)
    return {item["_id"]: item["count"] for item in result}


@router.put("/{user_id}/status")
async def update_user_status(user_id: str, data: dict, current_user=Depends(require_roles(UserRole.ADMIN))):
    # Self-suspension guard: admin cannot suspend their own account
    if str(current_user["_id"]) == user_id and not data.get("is_active", True):
        raise HTTPException(400, "لا يمكنك تعليق حسابك الخاص")
    if not ObjectId.is_valid(user_id):
        raise HTTPException(400, "معرّف المستخدم غير صالح")
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"is_active": data.get("is_active", True)}})
    return {"message": "Updated"}


@router.get("/full")
async def get_users_full(current_user=Depends(require_roles(UserRole.ADMIN))):
    users = await db.users.find({}, {"password_hash": 0}).to_list(500)
    result = []
    for u in users:
        u["_id"] = str(u["_id"])
        if isinstance(u.get("created_at"), datetime):
            u["created_at"] = u["created_at"].isoformat()
        result.append(u)
    by_role = {}
    for u in result:
        role = u.get("role", "unknown")
        by_role.setdefault(role, []).append(u)
    return {"users": result, "by_role": by_role, "total": len(result)}


@router.get("/admin/expired-count")
async def get_expired_count(current_user=Depends(require_roles(UserRole.ADMIN))):
    """Preview: count of users with expired licenses still active."""
    today = datetime.now(timezone.utc).date().isoformat()
    count = await db.users.count_documents({
        "license_expiry_date": {"$lt": today, "$ne": None},
        "is_active": True,
        "role": {"$in": ["importer", "customs_broker", "carrier_agent"]}
    })
    return {"expired_active_count": count, "as_of": today}


@router.post("/admin/suspend-expired")
async def suspend_expired_licenses(current_user=Depends(require_roles(UserRole.ADMIN))):
    """Auto-suspend all active users whose license_expiry_date has passed."""
    today = datetime.now(timezone.utc).date().isoformat()
    result = await db.users.update_many(
        {
            "license_expiry_date": {"$lt": today, "$ne": None},
            "is_active": True,
            "role": {"$in": ["importer", "customs_broker", "carrier_agent"]}
        },
        {"$set": {"is_active": False, "suspended_reason": "license_expired",
                  "suspended_at": datetime.now(timezone.utc).isoformat()}}
    )
    return {
        "message": f"تم تعليق {result.modified_count} حساب بسبب انتهاء صلاحية الرخصة",
        "suspended_count": result.modified_count,
    }


@router.get("/{user_id}/verification-samples")
async def get_verification_samples(user_id: str, current_user=Depends(get_current_user)):
    """
    Phase F — Return signature_sample and stamp_sample file_ids for visual verification.
    Accessible by officers and the owner.
    """
    allowed_roles = {"admin", "acid_reviewer", "acid_risk_officer", "manifest_officer",
                     "declaration_officer", "release_officer", "inspector", "customs_valuer"}
    if current_user["_id"] != user_id and current_user.get("role") not in allowed_roles:
        raise HTTPException(403, "غير مصرح")

    user = await db.users.find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id) else None
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")

    # Fetch signature and stamp registration docs
    sig_doc   = await db.registration_docs.find_one({"user_id": user_id, "doc_type": "signature_sample"})
    stamp_doc = await db.registration_docs.find_one({"user_id": user_id, "doc_type": "stamp_sample"})

    return {
        "user_id": user_id,
        "name_ar": user.get("name_ar", ""),
        "company_name_ar": user.get("company_name_ar", ""),
        "statistical_code": user.get("statistical_code"),
        "signature_file_id": sig_doc.get("file_id") if sig_doc else None,
        "stamp_file_id": stamp_doc.get("file_id") if stamp_doc else None,
        "signature_available": bool(sig_doc),
        "stamp_available": bool(stamp_doc),
    }
