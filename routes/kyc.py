"""KYC Management Routes — Phase L + Phase M (License Expiry Tracking)
مراجعة وقبول/رفض طلبات تسجيل المستخدمين التجاريين + تتبع انتهاء الرخص.
يمتلك الصلاحية: admin + registration_officer
"""
from datetime import datetime, timezone, timedelta
import os
from fastapi import APIRouter, HTTPException, Depends, Query
from bson import ObjectId
from pydantic import BaseModel
from typing import Optional, List
from database import db
from auth_utils import get_current_user, require_roles
from models import UserRole
from services.notification_service import send_notification
from services.scheduler_service import (
    run_license_expiry_check,
    get_last_run,
    get_next_run_time,
    run_sla_breach_check,
    get_sla_job_next_run,
    get_report_job_next_run,
    run_land_trip_escalation,
    get_land_trip_escalation_next_run,
    run_weekly_report_email,
)

router = APIRouter(prefix="/kyc", tags=["kyc"])

# الأدوار المخوّلة بمراجعة KYC
_KYC_REVIEWERS = (UserRole.ADMIN, UserRole.REGISTRATION_OFFICER)


class KYCApproveInput(BaseModel):
    license_expiry_date: Optional[str] = None  # تاريخ انتهاء الرخصة التجارية
    # ── Carrier Partial Approval ─────────────────────────────────────────────────
    approved_modes: Optional[List[str]] = None   # ["sea", "air"] — الوسائط المقبولة
    rejected_modes: Optional[List[str]] = None   # ["land"] — الوسائط المرفوضة
    mode_expiry_dates: Optional[dict] = None     # {"sea": "2027-01-01", "air": "2027-06-30"}
    partial_rejection_reason: Optional[str] = None  # سبب رفض بعض الوسائط


class KYCRejectInput(BaseModel):
    reason: str


class KYCCorrectInput(BaseModel):
    notes: str                          # ملاحظات التصحيح — إلزامية
    flagged_docs: Optional[list[str]] = []  # أنواع الوثائق المطلوب تصحيحها


def _fmt_user(u: dict) -> dict:
    u["_id"] = str(u.get("_id", ""))
    u.pop("password_hash", None)
    return u


def _require_task_lock(user: dict, current_user: dict) -> None:
    """
    يتحقق أن المأمور يحمل القفل النشط (In_Progress) على هذا المستخدم.
    يُرفع 423 إذا لم يكن المأمور هو من حجز المهمة.
    """
    wf_status   = user.get("wf_status", "Unassigned")
    assigned_to = str(user.get("wf_assigned_to", "")) if user.get("wf_assigned_to") else ""
    officer_id  = str(current_user["_id"])

    if wf_status != "In_Progress" or assigned_to != officer_id:
        locked_by = user.get("wf_assigned_to_name", "")
        msg = (
            f"هذا الملف محجوز بواسطة {locked_by} — يجب الانتظار حتى يُحرَّر الملف"
            if (wf_status == "In_Progress" and assigned_to != officer_id and locked_by)
            else "يجب حجز المهمة من حوض المهام أولاً قبل اتخاذ هذا القرار"
        )
        raise HTTPException(
            status_code=423,
            detail={"code": "LOCK_REQUIRED", "message": msg, "locked_by": locked_by},
        )


@router.get("/registrations")
async def list_registrations(
    status: Optional[str] = "pending",
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """قائمة طلبات التسجيل حسب الحالة (pending / approved / rejected / all)."""
    query = {}
    if status and status != "all":
        query["registration_status"] = status
    # عرض الأدوار التجارية فقط
    query["role"] = {"$in": ["importer", "customs_broker", "carrier_agent", "foreign_supplier"]}
    users = await db.users.find(query).sort("created_at", -1).to_list(200)
    return [_fmt_user(u) for u in users]


@router.get("/registrations/stats")
async def kyc_stats(current_user=Depends(require_roles(*_KYC_REVIEWERS))):
    """إحصاءات طلبات KYC لعرضها في لوحة مأمور التسجيل."""
    base = {"role": {"$in": ["importer", "customs_broker", "carrier_agent", "foreign_supplier"]}}
    pending    = await db.users.count_documents({**base, "registration_status": "pending"})
    approved   = await db.users.count_documents({**base, "registration_status": "approved"})
    rejected   = await db.users.count_documents({**base, "registration_status": "rejected"})
    correction = await db.users.count_documents({**base, "registration_status": "needs_correction"})
    unverified = await db.users.count_documents({**base, "registration_status": "email_unverified"})
    return {"pending": pending, "approved": approved, "rejected": rejected, "needs_correction": correction, "email_unverified": unverified}


@router.post("/{user_id}/approve")
async def approve_registration(
    user_id: str,
    data: KYCApproveInput = None,
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """اعتماد المستخدم — يُفعِّل حسابه ويُرسل إشعاراً له. يدعم القبول الجزئي لوكلاء الشحن."""
    if data is None:
        data = KYCApproveInput()
    if not ObjectId.is_valid(user_id):
        raise HTTPException(400, "معرّف مستخدم غير صالح")
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    # ── قفل المهمة: يجب أن يكون المأمور هو من يحمل القفل النشط ──
    _require_task_lock(user, current_user)
    now = datetime.now(timezone.utc).isoformat()

    # ── تحديد حالة القبول (كامل / جزئي) ────────────────────────────────────────
    is_carrier = user.get("role") == "carrier_agent"
    has_mode_decision = data.approved_modes is not None or data.rejected_modes is not None

    approved_modes = data.approved_modes or []
    rejected_modes = data.rejected_modes or []

    if is_carrier and has_mode_decision:
        if not approved_modes:
            raise HTTPException(400, "يجب اعتماد وسيط نقل واحد على الأقل — استخدم نقطة الرفض لرفض الطلب بالكامل")
        new_status = "approved" if not rejected_modes else "partially_approved"
    else:
        new_status = "approved"
        if is_carrier:
            approved_modes = user.get("transport_modes", [])
            rejected_modes = []

    # ── فحص التجميد التلقائي: البطاقة الإحصائية ────────────────────────────────
    stat_exp = user.get("statistical_expiry_date")
    account_status = "active"
    if stat_exp:
        today = datetime.now(timezone.utc).date().isoformat()
        if stat_exp < today:
            account_status = "suspended"

    update_fields: dict = {
        "registration_status": new_status,
        "rejection_reason": None,
        "kyc_approved_by": current_user["_id"],
        "kyc_approved_by_name": current_user.get("name_ar", ""),
        "kyc_approved_at": now,
        "account_status": account_status,
    }
    if data.license_expiry_date:
        update_fields["license_expiry_date"] = data.license_expiry_date

    # ── حقول الناقل: الوسائط المقبولة/المرفوضة + تواريخ الانتهاء ─────────────
    if is_carrier and (approved_modes or has_mode_decision):
        update_fields["transport_modes_approved"] = approved_modes
        update_fields["transport_modes_rejected"] = rejected_modes
        if data.mode_expiry_dates:
            for mode, expiry in data.mode_expiry_dates.items():
                update_fields[f"{mode}_license_expiry"] = expiry

    timeline_action = "approved" if new_status == "approved" else "partially_approved"
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set":  update_fields,
            "$push": {"status_history": {
                "action":     timeline_action,
                "actor_name": current_user.get("name_ar", ""),
                "actor_role": current_user.get("role", ""),
                "timestamp":  now,
                "details":    {
                    "license_expiry_date":      data.license_expiry_date or None,
                    "approved_modes":           approved_modes if is_carrier else None,
                    "rejected_modes":           rejected_modes if is_carrier else None,
                    "partial_rejection_reason": data.partial_rejection_reason if rejected_modes else None,
                    "auto_suspended":           account_status == "suspended",
                },
            }},
        }
    )
    # سجل التدقيق
    await db.audit_logs.insert_one({
        "action": f"kyc_{timeline_action}",
        "user_id": current_user["_id"],
        "user_name": current_user.get("name_ar", ""),
        "resource_type": "user",
        "resource_id": user_id,
        "details": {
            "email":          user.get("email"),
            "role":           user.get("role"),
            "approved_modes": approved_modes,
            "rejected_modes": rejected_modes,
            "status":         new_status,
            "account_status": account_status,
        },
        "timestamp": now,
    })
    # إشعار داخلي للمستخدم
    await send_notification(
        user_id, "kyc_approved",
        {"name": user.get("name_ar", user.get("name_en", ""))},
        "ar",
    )
    # بناء رسالة الاستجابة
    MODE_AR = {"sea": "بحري", "air": "جوي", "land": "بري"}
    if new_status == "partially_approved":
        ap = " + ".join(MODE_AR.get(m, m) for m in approved_modes)
        rj = " + ".join(MODE_AR.get(m, m) for m in rejected_modes)
        msg = f"تم القبول الجزئي — مقبول: {ap} | مرفوض: {rj}"
    else:
        msg = f"تم اعتماد حساب {user.get('email')} بنجاح"
    if account_status == "suspended":
        msg += " — تم تجميد الحساب تلقائياً (البطاقة الإحصائية منتهية)"
    return {"message": msg, "status": new_status, "account_status": account_status}


@router.post("/{user_id}/reject")
async def reject_registration(
    user_id: str,
    data: KYCRejectInput,
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """رفض طلب التسجيل مع ذكر السبب."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(400, "معرّف مستخدم غير صالح")
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    # ── قفل المهمة: يجب أن يكون المأمور هو من يحمل القفل النشط ──
    _require_task_lock(user, current_user)
    now = datetime.now(timezone.utc).isoformat()
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "registration_status": "rejected",
                "rejection_reason": data.reason,
                "kyc_rejected_by": current_user["_id"],
                "kyc_rejected_by_name": current_user.get("name_ar", ""),
                "kyc_rejected_at": now,
            },
            "$push": {"status_history": {
                "action":     "rejected",
                "actor_name": current_user.get("name_ar", ""),
                "actor_role": current_user.get("role", ""),
                "timestamp":  now,
                "details":    {"reason": data.reason},
            }},
        }
    )
    await db.audit_logs.insert_one({
        "action": "kyc_rejected",
        "user_id": current_user["_id"],
        "user_name": current_user.get("name_ar", ""),
        "resource_type": "user",
        "resource_id": user_id,
        "details": {"email": user.get("email"), "reason": data.reason},
        "timestamp": now,
    })
    # إشعار رفض للمستخدم
    await send_notification(
        user_id, "kyc_rejected",
        {"name": user.get("name_ar", ""), "reason": data.reason},
        "ar",
    )
    return {"message": f"تم رفض طلب {user.get('email')}", "status": "rejected"}


@router.post("/{user_id}/correct")
async def request_correction(
    user_id: str,
    data: KYCCorrectInput,
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """طلب تصحيح وثائق المستخدم — يُعيد المهمة للحوض بعد تصحيح المستورد لوثائقه."""
    if not data.notes.strip():
        raise HTTPException(422, "ملاحظات التصحيح إلزامية")
    if not ObjectId.is_valid(user_id):
        raise HTTPException(400, "معرّف مستخدم غير صالح")
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    # ── قفل المهمة: يجب أن يكون المأمور هو من يحمل القفل النشط ──
    _require_task_lock(user, current_user)
    now = datetime.now(timezone.utc).isoformat()
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "registration_status":           "needs_correction",
                "correction_notes":              data.notes.strip(),
                "correction_flagged_docs":       data.flagged_docs or [],
                "correction_requested_by":       current_user["_id"],
                "correction_requested_by_name":  current_user.get("name_ar", ""),
                "correction_requested_at":       now,
    # ── الإبقاء على القفل لدى المأمور — Awaiting_Correction ──
                "wf_status":           "Awaiting_Correction",
                # wf_assigned_to يبقى كما هو (لا يُمسح) — المأمور يحتفظ بالملف
            },
            "$push": {"status_history": {
                "action":     "correction_requested",
                "actor_name": current_user.get("name_ar", ""),
                "actor_role": current_user.get("role", ""),
                "timestamp":  now,
                "details":    {
                    "notes":        data.notes.strip(),
                    "flagged_docs": data.flagged_docs or [],
                },
            }},
        }
    )
    await db.audit_logs.insert_one({
        "action":      "kyc_correction_requested",
        "user_id":     current_user["_id"],
        "user_name":   current_user.get("name_ar", ""),
        "resource_type": "user",
        "resource_id": user_id,
        "details":     {
            "email": user.get("email"),
            "notes": data.notes,
            "flagged_docs": data.flagged_docs,
        },
        "timestamp": now,
    })
    await send_notification(
        user_id, "kyc_correction_requested",
        {"name": user.get("name_ar", user.get("name_en", "")), "notes": data.notes.strip()},
        "ar",
    )
    return {"message": f"تم طلب تصحيح وثائق {user.get('email')}", "status": "needs_correction"}


@router.post("/resubmit")
async def resubmit_docs(
    current_user=Depends(get_current_user),
):
    """
    المستورد يُعيد تقديم وثائقه بعد طلب التعديل — يُعيد الطلب للحوض عند المأمور.
    متاح لأي مستخدم مُعتمَد الـ JWT (بدون قيد الدور) ليعمل حتى قبل الاعتماد.
    """
    user_id = current_user["_id"]
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    if user.get("registration_status") != "needs_correction":
        raise HTTPException(400, "لا يمكن إعادة التقديم — الحساب ليس في حالة 'بحاجة تعديل'")

    now = datetime.now(timezone.utc).isoformat()
    resubmission_count = int(user.get("resubmission_count") or 0) + 1

    # ── استعادة المهمة للمأمور الأصلي إن كانت Awaiting_Correction ──
    correction_officer_id   = user.get("wf_assigned_to")      # ObjectId
    correction_officer_name = user.get("wf_assigned_to_name", "")

    if correction_officer_id and user.get("wf_status") == "Awaiting_Correction":
        new_wf_status           = "In_Progress"
        new_wf_assigned_to      = correction_officer_id
        new_wf_assigned_to_name = correction_officer_name
    else:
        new_wf_status           = "Unassigned"
        new_wf_assigned_to      = None
        new_wf_assigned_to_name = None

    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "registration_status": "pending",
                "is_resubmission":     True,
                "resubmission_count":  resubmission_count,
                "resubmitted_at":      now,
                "wf_status":           new_wf_status,
                "wf_assigned_to":      new_wf_assigned_to,
                "wf_assigned_to_name": new_wf_assigned_to_name,
                "wf_claimed_at":       now if new_wf_status == "In_Progress" else None,
            },
            "$push": {"status_history": {
                "action":     "docs_resubmitted",
                "actor_name": current_user.get("name_ar", current_user.get("name_en", "")),
                "actor_role": current_user.get("role", ""),
                "timestamp":  now,
                "details":    {"resubmission_count": resubmission_count},
            }},
        }
    )
    await db.audit_logs.insert_one({
        "action":      "kyc_resubmitted",
        "user_id":     user_id,
        "user_name":   current_user.get("name_ar", current_user.get("name_en", "")),
        "resource_type": "user",
        "resource_id": user_id,
        "details":     {"resubmission_count": resubmission_count},
        "timestamp":   now,
    })
    # إشعار المأمور الأصلي إن عاد الملف إليه
    if correction_officer_id and new_wf_status == "In_Progress":
        await send_notification(
            str(correction_officer_id),
            "kyc_docs_returned_to_officer",
            {"applicant_name": current_user.get("name_ar", current_user.get("name_en", ""))},
            "ar",
        )
    return {
        "message": "تم إرسال التعديلات بنجاح — طلبك الآن قيد المراجعة مرة أخرى",
        "status":  "pending",
        "resubmission_count": resubmission_count,
    }


@router.get("/{user_id}")
async def get_user_detail(
    user_id: str,
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """تفاصيل مستخدم واحد للـ Drawer — يُستخدم من WorkflowPoolPage."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(400, "معرّف غير صالح")
    u = await db.users.find_one({"_id": ObjectId(user_id)})
    if not u:
        raise HTTPException(404, "المستخدم غير موجود")
    return _fmt_user(u)



async def mark_officer_viewed(
    user_id: str,
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """
    يُسجَّل عندما يفتح المأمور تفاصيل ملف المستخدم.
    يُخبر المستخدم أن هناك من يعمل على طلبه.
    مُقيَّد بـ 5 دقائق لتجنب التكرار المتزامن.
    """
    if not ObjectId.is_valid(user_id):
        return {"message": "ok"}

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # تحقق من آخر حدث viewed لتجنب التكرار خلال 5 دقائق
    u = await db.users.find_one({"_id": ObjectId(user_id)}, {"status_history": {"$slice": -1}})
    if u:
        last_entries = u.get("status_history") or []
        if last_entries:
            last = last_entries[-1]
            if last.get("action") == "officer_viewed":
                try:
                    last_ts = datetime.fromisoformat(last["timestamp"].replace("Z", "+00:00"))
                    if (now - last_ts).total_seconds() < 300:
                        return {"message": "ok", "throttled": True}
                except Exception:
                    pass

    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$push": {"status_history": {
            "action":     "officer_viewed",
            "actor_name": current_user.get("name_ar", ""),
            "actor_role": current_user.get("role", ""),
            "timestamp":  now_iso,
            "details":    {},
        }}}
    )
    return {"message": "ok"}


# ══════════════════════════════════════════════════════════════════
# Phase M — License Expiry Tracking (تتبع انتهاء الرخص)
# ══════════════════════════════════════════════════════════════════

_COMMERCIAL_ROLES = ["importer", "customs_broker", "carrier_agent", "foreign_supplier"]


def _days_remaining(expiry_str: str) -> int:
    """أيام متبقية من اليوم حتى تاريخ الانتهاء (سالب = منتهي)."""
    try:
        expiry = datetime.fromisoformat(expiry_str).date()
        return (expiry - datetime.now(timezone.utc).date()).days
    except Exception:
        return 9999


@router.get("/expiring-licenses")
async def expiring_licenses(
    days: int = Query(30, ge=1, le=365),
    include_expired: bool = Query(False),
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """
    قائمة المستخدمين التجاريين الذين ستنتهي رخصتهم خلال N يوم.
    include_expired=True → يشمل الرخص المنتهية بالفعل.
    """
    today     = datetime.now(timezone.utc).date().isoformat()
    cutoff    = (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()

    query: dict = {
        "role":                {"$in": _COMMERCIAL_ROLES},
        "registration_status": "approved",
        "license_expiry_date": {"$exists": True, "$ne": None, "$lte": cutoff},
    }
    if not include_expired:
        query["license_expiry_date"]["$gte"] = today   # type: ignore[index]

    users = await db.users.find(query).sort("license_expiry_date", 1).to_list(300)
    result = []
    for u in users:
        fmt = _fmt_user(u)
        fmt["days_remaining"] = _days_remaining(u.get("license_expiry_date", ""))
        result.append(fmt)
    return result


@router.get("/expiring-licenses/stats")
async def expiring_stats(current_user=Depends(require_roles(*_KYC_REVIEWERS))):
    """إحصاءات الرخص: ستنتهي خلال 30 يوماً + منتهية بالفعل."""
    today   = datetime.now(timezone.utc).date().isoformat()
    cutoff  = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
    base    = {"role": {"$in": _COMMERCIAL_ROLES}, "registration_status": "approved",
               "license_expiry_date": {"$exists": True, "$ne": None}}

    expiring_soon = await db.users.count_documents({
        **base, "license_expiry_date": {"$gte": today, "$lte": cutoff}
    })
    already_expired = await db.users.count_documents({
        **base, "license_expiry_date": {"$lt": today}
    })
    return {"expiring_soon_30d": expiring_soon, "already_expired": already_expired}


@router.post("/notify-expiring")
async def notify_expiring_bulk(
    days: int = Query(30, ge=1, le=365),
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """إرسال تنبيهات تجديد جماعية لجميع المستخدمين الذين ستنتهي رخصهم خلال N يوم."""
    today  = datetime.now(timezone.utc).date().isoformat()
    cutoff = (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()
    users  = await db.users.find({
        "role":                {"$in": _COMMERCIAL_ROLES},
        "registration_status": "approved",
        "license_expiry_date": {"$gte": today, "$lte": cutoff},
    }).to_list(300)

    sent = 0
    for u in users:
        uid = str(u["_id"])
        days_left = _days_remaining(u.get("license_expiry_date", ""))
        await send_notification(
            uid, "license_expiry_reminder",
            {
                "name":      u.get("name_ar", u.get("name_en", "")),
                "days":      str(days_left),
                "expiry":    u.get("license_expiry_date", ""),
            },
            "ar",
        )
        sent += 1

    now = datetime.now(timezone.utc).isoformat()
    await db.audit_logs.insert_one({
        "action":     "license_expiry_bulk_notify",
        "user_id":    current_user["_id"],
        "user_name":  current_user.get("name_ar", ""),
        "resource_type": "users",
        "details":    {"days": days, "sent_count": sent},
        "timestamp":  now,
    })
    return {"message": f"تم إرسال {sent} إشعار تجديد", "sent": sent}


@router.post("/{user_id}/notify-expiry")
async def notify_single_expiry(
    user_id: str,
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """إرسال تنبيه تجديد لمستخدم واحد."""
    if not ObjectId.is_valid(user_id):
        raise HTTPException(400, "معرّف مستخدم غير صالح")
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    days_left = _days_remaining(user.get("license_expiry_date", ""))
    await send_notification(
        user_id, "license_expiry_reminder",
        {
            "name":   user.get("name_ar", user.get("name_en", "")),
            "days":   str(days_left),
            "expiry": user.get("license_expiry_date", ""),
        },
        "ar",
    )
    return {"message": f"تم إرسال تنبيه التجديد إلى {user.get('email')}", "days_remaining": days_left}


# ══════════════════════════════════════════════════════════════════
# Scheduler Status & Manual Trigger
# ══════════════════════════════════════════════════════════════════

@router.get("/scheduler/status")
async def scheduler_status(current_user=Depends(require_roles(*_KYC_REVIEWERS))):
    """
    حالة الـ scheduler: آخر تشغيل + التشغيل القادم.
    يُستخدم في لوحة التحكم لعرض بطاقة "الفحص التلقائي".
    """
    return {
        "last_run":                       get_last_run(),
        "next_run":                       get_next_run_time(),
        "schedule":                       "يومياً الساعة 09:00 UTC",
        "job_id":                         "license_expiry_check",
        "sla_next_run":                   get_sla_job_next_run(),
        "sla_interval":                   "كل 15 دقيقة",
        "weekly_report_next_run":         get_report_job_next_run(),
        "weekly_report_schedule":         "كل خميس 17:00 UTC",
        "land_trip_escalation_next_run":  get_land_trip_escalation_next_run(),
        "land_trip_escalation_schedule":  "كل ساعة (SLA: 24h)",
    }


@router.post("/scheduler/trigger-sla")
async def trigger_sla_check_now(current_user=Depends(require_roles(*_KYC_REVIEWERS))):
    """تشغيل يدوي فوري لفحص SLA (للاختبار)."""
    result = await run_sla_breach_check()
    return {
        "message": f"اكتمل فحص SLA — خروقات: {result['breaches_found']} | إشعارات: {result['notifications_sent']}",
        "details": result,
    }


@router.post("/scheduler/trigger-land-escalation")
async def trigger_land_escalation_now(current_user=Depends(require_roles(*_KYC_REVIEWERS))):
    """تشغيل يدوي فوري لتصعيد الرحلات البرية المتأخرة (للاختبار)."""
    result = await run_land_trip_escalation()
    return {
        "message": f"اكتمل تصعيد الرحلات — تم تصعيد {result['escalated']} رحلة",
        "details": result,
    }


@router.post("/scheduler/trigger")
async def trigger_scheduler_now(current_user=Depends(require_roles(*_KYC_REVIEWERS))):
    """
    تشغيل يدوي فوري لمهمة فحص الرخص (للاختبار أو الاستخدام الطارئ).
    مُسجَّل في Audit Log تماماً كالتشغيل التلقائي.
    """
    result = await run_license_expiry_check()
    return {
        "message": f"تم التشغيل اليدوي — أُرسِلت {result['sent']} إشعارات تجديد",
        "details": result,
    }


@router.post("/scheduler/trigger-weekly-report")
async def trigger_weekly_report_now(current_user=Depends(require_roles(UserRole.ADMIN))):
    """
    تشغيل يدوي فوري للتقرير الأسبوعي — يُولِّد PDF ويُرسله بالبريد لجميع المدراء.
    مُتاح للـ Admin فقط.
    """
    result = await run_weekly_report_email()
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message", "خطأ في توليد التقرير"))
    return {
        "message": "تم توليد التقرير الأسبوعي وإرساله بالبريد الإلكتروني بنجاح",
        "details": result,
    }


# ══════════════════════════════════════════════════════════════════
# System Settings — إعدادات المنظومة الديناميكية
# ══════════════════════════════════════════════════════════════════

_SETTINGS_DOC_ID = "kyc_settings"
_DEFAULT_WARN_DAYS = int(os.environ.get("LICENSE_EXPIRY_WARN_DAYS", "30"))


async def _get_warn_days() -> int:
    """يقرأ قيمة نطاق التنبيه من DB (يرجع لـ env var إذا لم توجد)."""
    doc = await db.system_settings.find_one({"_id": _SETTINGS_DOC_ID})
    if doc and isinstance(doc.get("license_expiry_warn_days"), int):
        return doc["license_expiry_warn_days"]
    return _DEFAULT_WARN_DAYS


@router.get("/settings")
async def get_kyc_settings(current_user=Depends(require_roles(*_KYC_REVIEWERS))):
    """يُرجع الإعدادات الديناميكية الحالية للنظام."""
    days = await _get_warn_days()
    doc  = await db.system_settings.find_one({"_id": _SETTINGS_DOC_ID})
    return {
        "license_expiry_warn_days": days,
        "default_from_env":         _DEFAULT_WARN_DAYS,
        "updated_at":    doc.get("updated_at")    if doc else None,
        "updated_by":    doc.get("updated_by")    if doc else None,
        "updated_by_name": doc.get("updated_by_name") if doc else None,
    }


class KYCSettingsInput(BaseModel):
    license_expiry_warn_days: int


@router.post("/settings")
async def update_kyc_settings(
    data: KYCSettingsInput,
    current_user=Depends(require_roles(*_KYC_REVIEWERS)),
):
    """تحديث نطاق أيام التنبيه المبكر (يُخزَّن في DB ويُطبَّق فوراً)."""
    if not (1 <= data.license_expiry_warn_days <= 365):
        raise HTTPException(422, "القيمة يجب أن تكون بين 1 و 365 يوماً")
    now = datetime.now(timezone.utc).isoformat()
    await db.system_settings.update_one(
        {"_id": _SETTINGS_DOC_ID},
        {"$set": {
            "license_expiry_warn_days": data.license_expiry_warn_days,
            "updated_at":              now,
            "updated_by":              str(current_user.get("_id", "")),
            "updated_by_name":         current_user.get("name_ar", ""),
        }},
        upsert=True,
    )
    await db.audit_logs.insert_one({
        "action":       "kyc_settings_updated",
        "user_id":      str(current_user.get("_id", "")),
        "user_name":    current_user.get("name_ar", ""),
        "resource_type":"system_settings",
        "resource_id":  _SETTINGS_DOC_ID,
        "details":      {"license_expiry_warn_days": data.license_expiry_warn_days},
        "timestamp":    now,
    })
    return {
        "message": f"تم تحديث نطاق التنبيه إلى {data.license_expiry_warn_days} يوماً",
        "license_expiry_warn_days": data.license_expiry_warn_days,
    }
