"""
Renewal Engine — Global Document Renewal for all roles (Phase 2026)
POST /renewal/request     — User submits renewal
GET  /renewal/my-requests — User's own renewals
GET  /renewal/pending     — Officer: pending list
POST /renewal/{id}/approve — Officer: approve + auto-unfreeze
POST /renewal/{id}/reject  — Officer: reject
GET  /renewal/count        — Badge count for navbar
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from bson import ObjectId
from typing import Optional
from datetime import datetime, timezone
import os, shutil

from database import db
from auth_utils import require_roles
from models import UserRole
from services.notification_service import send_notification

router = APIRouter(prefix="/renewal", tags=["Renewal"])

# ── Map doc_type → expiry field in users collection ────────────────────────────
EXPIRY_FIELD_MAP = {
    "statistical_cert":       "statistical_expiry_date",
    "marine_license":         "marine_license_expiry",
    "air_license":            "air_license_expiry",
    "land_license":           "land_license_expiry",
    "commercial_registry":    "license_expiry_date",
    "customs_broker_license": "license_expiry_date",
}

DOC_LABELS = {
    "statistical_cert":       "البطاقة الإحصائية",
    "marine_license":         "الترخيص البحري",
    "air_license":            "ترخيص التشغيل الجوي (AOC)",
    "land_license":           "ترخيص النقل البري",
    "commercial_registry":    "السجل التجاري",
    "customs_broker_license": "ترخيص المخلص الجمركي",
}

_KYC_REVIEWERS   = (UserRole.ADMIN, UserRole.REGISTRATION_OFFICER)
_COMMERCIAL_ROLES = (
    UserRole.IMPORTER, UserRole.CARRIER_AGENT,
    UserRole.CUSTOMS_BROKER, UserRole.FOREIGN_SUPPLIER, UserRole.ADMIN,
)

_UPLOAD_DIR = "/app/uploads/renewals"


def _renewal_to_dict(r: dict) -> dict:
    """تحويل كائن MongoDB لـ dict قابل للـ JSON"""
    r = dict(r)
    r["_id"]     = str(r["_id"])
    r["user_id"] = str(r["user_id"])
    if r.get("processed_by"):
        r["processed_by"] = str(r["processed_by"])
    return r


# ── POST /renewal/request ───────────────────────────────────────────────────────
@router.post("/request")
async def submit_renewal_request(
    doc_type:        str           = Form(...),
    new_expiry_date: Optional[str] = Form(None),
    notes:           Optional[str] = Form(None),
    file:            UploadFile    = File(...),
    current_user=Depends(require_roles(*_COMMERCIAL_ROLES)),
):
    """المستخدم يطلب تجديد وثيقة منتهية أو قاربت الانتهاء"""
    if doc_type not in EXPIRY_FIELD_MAP:
        raise HTTPException(400, f"نوع الوثيقة غير مدعوم: {doc_type}")

    user_oid = ObjectId(current_user["_id"])

    # لا تسمح بطلب تجديد مكرر قيد المراجعة
    existing = await db.renewal_requests.find_one({
        "user_id":  user_oid,
        "doc_type": doc_type,
        "status":   "pending",
    })
    if existing:
        raise HTTPException(409, "يوجد طلب تجديد قيد المراجعة لهذه الوثيقة — انتظر حتى يُعالَج")

    # حفظ الملف
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    ts        = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = f"{current_user['_id']}_{doc_type}_{ts}_{file.filename}"
    file_path = os.path.join(_UPLOAD_DIR, safe_name)
    with open(file_path, "wb") as fh:
        shutil.copyfileobj(file.file, fh)

    now = datetime.now(timezone.utc).isoformat()

    # استخراج تاريخ الانتهاء القديم للتدقيق
    user = await db.users.find_one({"_id": user_oid})
    old_expiry = user.get(EXPIRY_FIELD_MAP.get(doc_type, ""), None) if user else None

    request_doc = {
        "user_id":         user_oid,
        "user_name":       current_user.get("name_ar", current_user.get("name_en", "")),
        "user_email":      current_user.get("email", ""),
        "user_role":       current_user.get("role", ""),
        "doc_type":        doc_type,
        "doc_label":       DOC_LABELS.get(doc_type, doc_type),
        "file_name":       file.filename,
        "file_path":       file_path,
        "old_expiry_date": old_expiry,
        "new_expiry_date": new_expiry_date,
        "notes":           notes,
        "status":          "pending",
        "requested_at":    now,
    }
    result    = await db.renewal_requests.insert_one(request_doc)
    renewal_id = str(result.inserted_id)

    # تسجيل في الـ Timeline
    await db.users.update_one(
        {"_id": user_oid},
        {"$push": {"status_history": {
            "action":     "renewal_requested",
            "actor_name": current_user.get("name_ar", ""),
            "actor_role": current_user.get("role", ""),
            "timestamp":  now,
            "details": {
                "renewal_id":      renewal_id,
                "doc_type":        doc_type,
                "doc_label":       DOC_LABELS.get(doc_type, doc_type),
                "old_expiry_date": old_expiry,
                "new_expiry_date": new_expiry_date,
                "file_name":       file.filename,
            },
        }}}
    )
    return {"message": "تم تقديم طلب التجديد — سيراجعه المأمور قريباً", "renewal_id": renewal_id}


# ── GET /renewal/my-requests ───────────────────────────────────────────────────
@router.get("/my-requests")
async def get_my_renewal_requests(
    current_user=Depends(require_roles(*_COMMERCIAL_ROLES)),
):
    """المستخدم يشاهد طلبات التجديد الخاصة به"""
    user_oid = ObjectId(current_user["_id"])
    cursor = db.renewal_requests.find(
        {"user_id": user_oid},
        {"file_path": 0}
    ).sort("requested_at", -1)
    return [_renewal_to_dict(r) async for r in cursor]


# ── GET /renewal/pending ───────────────────────────────────────────────────────
@router.get("/pending")
async def get_pending_renewals(
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """المأمور يشاهد جميع طلبات التجديد المعلقة"""
    cursor = db.renewal_requests.find(
        {"status": "pending"},
        {"file_path": 0}
    ).sort("requested_at", 1)
    return [_renewal_to_dict(r) async for r in cursor]


# ── POST /renewal/{id}/approve ─────────────────────────────────────────────────
@router.post("/{renewal_id}/approve")
async def approve_renewal(
    renewal_id:      str,
    new_expiry_date: Optional[str] = Form(None),
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """المأمور يعتمد الوثيقة المجددة ويُفعّل الحساب تلقائياً عند الاقتضاء"""
    if not ObjectId.is_valid(renewal_id):
        raise HTTPException(400, "معرّف طلب التجديد غير صالح")

    renewal = await db.renewal_requests.find_one({"_id": ObjectId(renewal_id)})
    if not renewal:
        raise HTTPException(404, "طلب التجديد غير موجود")
    if renewal["status"] != "pending":
        raise HTTPException(409, "تم معالجة هذا الطلب مسبقاً")

    now   = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    user_id  = renewal["user_id"]   # ObjectId (stored as OID from request)
    doc_type = renewal["doc_type"]

    # استخدم تاريخ الانتهاء الذي حدده المأمور، أو الذي قدمه المستخدم
    final_expiry = new_expiry_date or renewal.get("new_expiry_date")

    # تحديث طلب التجديد
    await db.renewal_requests.update_one(
        {"_id": ObjectId(renewal_id)},
        {"$set": {
            "status":              "approved",
            "processed_at":        now,
            "processed_by":        ObjectId(current_user["_id"]),
            "processed_by_name":   current_user.get("name_ar", ""),
            "officer_expiry_date": final_expiry,
        }}
    )

    # بناء حقول تحديث المستخدم
    user_update: dict = {}
    expiry_field = EXPIRY_FIELD_MAP.get(doc_type)
    if expiry_field and final_expiry:
        user_update[expiry_field] = final_expiry

    # ── منطق رفع التجميد التلقائي ────────────────────────────────────────────
    user = await db.users.find_one({"_id": user_id})
    auto_unfrozen = False
    if user and user.get("account_status") == "suspended":
        merged_stat_exp = user_update.get("statistical_expiry_date") or user.get("statistical_expiry_date")
        stat_ok = (merged_stat_exp is None) or (merged_stat_exp >= today)
        if stat_ok:
            # رفع التجميد: إرجاع للحالة السابقة (approved أو partially_approved)
            prev_status = user.get("registration_status", "approved")
            if prev_status not in ("approved", "partially_approved"):
                prev_status = "approved"
            user_update["account_status"] = "active"
            user_update["registration_status"] = prev_status
            auto_unfrozen = True

    if user_update:
        await db.users.update_one({"_id": user_id}, {"$set": user_update})

    # ── تسجيل في الـ Timeline ────────────────────────────────────────────────
    await db.users.update_one(
        {"_id": user_id},
        {"$push": {"status_history": {
            "action":     "renewal_approved",
            "actor_name": current_user.get("name_ar", ""),
            "actor_role": current_user.get("role", ""),
            "timestamp":  now,
            "details": {
                "renewal_id":      renewal_id,
                "doc_type":        doc_type,
                "doc_label":       renewal.get("doc_label", doc_type),
                "old_expiry_date": renewal.get("old_expiry_date"),
                "new_expiry_date": final_expiry,
                "auto_unfrozen":   auto_unfrozen,
                "file_name":       renewal.get("file_name"),
            },
        }}}
    )

    # سجل التدقيق
    await db.audit_logs.insert_one({
        "action":        "renewal_approved",
        "user_id":       ObjectId(current_user["_id"]),
        "user_name":     current_user.get("name_ar", ""),
        "resource_type": "renewal_request",
        "resource_id":   renewal_id,
        "details": {
            "target_user_id": str(user_id),
            "doc_type":       doc_type,
            "old_expiry":     renewal.get("old_expiry_date"),
            "new_expiry":     final_expiry,
            "auto_unfrozen":  auto_unfrozen,
        },
        "timestamp": now,
    })

    msg = f"تم اعتماد تجديد {renewal.get('doc_label', doc_type)}"
    if auto_unfrozen:
        msg += " — وتم رفع التجميد عن الحساب تلقائياً ✅"

    # إشعار المستخدم بالبريد/SMS
    await send_notification(
        str(user_id), "renewal_approved",
        {
            "name":      renewal.get("user_name", ""),
            "doc_label": renewal.get("doc_label", doc_type),
            "new_expiry": final_expiry or "—",
        },
        "ar",
    )
    return {"message": msg, "auto_unfrozen": auto_unfrozen}


# ── POST /renewal/{id}/reject ──────────────────────────────────────────────────
@router.post("/{renewal_id}/reject")
async def reject_renewal(
    renewal_id: str,
    reason:     str = Form(...),
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """المأمور يرفض طلب التجديد مع ذكر السبب"""
    if not ObjectId.is_valid(renewal_id):
        raise HTTPException(400, "معرّف طلب التجديد غير صالح")

    renewal = await db.renewal_requests.find_one({"_id": ObjectId(renewal_id)})
    if not renewal:
        raise HTTPException(404, "طلب التجديد غير موجود")
    if renewal["status"] != "pending":
        raise HTTPException(409, "تم معالجة هذا الطلب مسبقاً")

    now = datetime.now(timezone.utc).isoformat()

    await db.renewal_requests.update_one(
        {"_id": ObjectId(renewal_id)},
        {"$set": {
            "status":            "rejected",
            "processed_at":      now,
            "processed_by":      ObjectId(current_user["_id"]),
            "processed_by_name": current_user.get("name_ar", ""),
            "rejection_reason":  reason,
        }}
    )

    # تسجيل في الـ Timeline
    await db.users.update_one(
        {"_id": renewal["user_id"]},
        {"$push": {"status_history": {
            "action":     "renewal_rejected",
            "actor_name": current_user.get("name_ar", ""),
            "actor_role": current_user.get("role", ""),
            "timestamp":  now,
            "details": {
                "renewal_id": renewal_id,
                "doc_type":   renewal["doc_type"],
                "doc_label":  renewal.get("doc_label", renewal["doc_type"]),
                "reason":     reason,
            },
        }}}
    )
    return {"message": f"تم رفض طلب تجديد {renewal.get('doc_label', renewal['doc_type'])}"}


# ── GET /renewal/count ─────────────────────────────────────────────────────────
@router.get("/count")
async def get_pending_count(current_user=Depends(require_roles(*_KYC_REVIEWERS))):
    """عدد طلبات التجديد المعلقة (للـ badge في الـ navbar)"""
    count = await db.renewal_requests.count_documents({"status": "pending"})
    return {"count": count}
