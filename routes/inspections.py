"""
inspections.py — وحدة المعاينة الميدانية (Field Inspection)
═══════════════════════════════════════════════════════════════
نقاط نهاية المفتش الجمركي:
  • GET  /inspections/assignments  — قائمة الطلبات المخصصة للمعاينة
  • POST /inspections/submit       — رفع تقرير المعاينة (يدعم offline sync)
  • GET  /inspections/{acid_id}    — الاطلاع على تقرير معاينة طلب محدد
  • GET  /inspections/stats        — إحصاءات سريعة للمفتش
"""
from datetime import datetime, timezone
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from bson import ObjectId

from auth_utils import require_roles
from models import UserRole, InspectionReportCreate, InspectionResult
from database import db
from helpers import format_doc, log_audit
from services.notification_service import send_notification
from ws_manager import ws_manager

router = APIRouter(prefix="/inspections", tags=["inspections"])

_INSPECTOR_ROLES = (UserRole.INSPECTOR, UserRole.ADMIN)
_RELEASE_ROLES   = (UserRole.RELEASE_OFFICER, UserRole.ADMIN)


# ─── قائمة الطلبات المنتظرة المعاينة ─────────────────────────────
@router.get("/assignments")
async def get_assignments(current_user=Depends(require_roles(*_INSPECTOR_ROLES))):
    """
    طابور المعاينة الميدانية — يشمل:
    1. الشحنات الجاهزة للمعاينة الفعلية (بعد الخزينة)
    2. الشحنات المعلَّمة مسبقاً للمعاينة (Yellow/Red channel — قبل الخزينة) للتخطيط المسبق
    """
    # ── الشحنات الجاهزة للمعاينة الفعلية (بعد الخزينة) ────────────
    post_treasury = await db.acid_requests.find({
        "treasury_paid": True,
        "gate_released": False,
        "$or": [
            {"inspection_status": {"$exists": False}},
            {"inspection_status": "pending"},
        ],
    }).sort("treasury_paid_at", 1).to_list(200)

    # ── الشحنات المُعلَّمة مسبقاً (Yellow/Red معتمدة لكن قبل الخزينة) ─
    pre_treasury = await db.acid_requests.find({
        "inspection_required": True,
        "inspection_status": "pending",
        "treasury_paid": {"$ne": True},
        "status": {"$in": ["approved", "valued"]},
    }).sort("created_at", 1).to_list(100)

    # ── دمج القائمتين مع تمييز المرحلة ──────────────────────────────
    result = []
    seen_ids = set()

    for item in post_treasury:
        d = format_doc(item)
        d["inspection_required"]  = not item.get("is_green_channel", False)
        d["inspection_stage"]     = "ready_for_inspection"   # جاهز للمعاينة الفعلية
        result.append(d)
        seen_ids.add(str(item["_id"]))

    for item in pre_treasury:
        if str(item["_id"]) in seen_ids:
            continue
        d = format_doc(item)
        d["inspection_required"]  = True
        d["inspection_stage"]     = "pre_inspection_flagged"  # معلَّمة مسبقاً
        result.append(d)

    return result


# ─── إحصاءات المفتش ───────────────────────────────────────────────
@router.get("/stats")
async def get_inspection_stats(current_user=Depends(require_roles(*_INSPECTOR_ROLES))):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    return {
        "pending":          await db.acid_requests.count_documents({
            "treasury_paid": True, "gate_released": False,
            "$or": [{"inspection_status": {"$exists": False}}, {"inspection_status": "pending"}],
        }),
        "compliant_today":  await db.inspections.count_documents({
            "overall_result": "compliant",
            "submitted_at":   {"$gte": today},
        }),
        "non_compliant":    await db.inspections.count_documents({"overall_result": "non_compliant"}),
        "dangerous_flagged": await db.inspections.count_documents({"dangerous_goods_flag": True}),
    }


# ─── تقرير معاينة لطلب محدد ──────────────────────────────────────
@router.get("/{acid_id}")
async def get_inspection_report(
    acid_id: str,
    current_user=Depends(require_roles(*_INSPECTOR_ROLES, *_RELEASE_ROLES)),
):
    if not ObjectId.is_valid(acid_id):
        raise HTTPException(400, "معرّف الطلب غير صالح")
    report = await db.inspections.find_one({"acid_id": acid_id})
    if not report:
        raise HTTPException(404, "لا يوجد تقرير معاينة لهذا الطلب")
    return format_doc(report)


# ─── رفع تقرير المعاينة ───────────────────────────────────────────
@router.post("/submit")
async def submit_inspection(
    body: InspectionReportCreate,
    background_tasks: BackgroundTasks,
    current_user=Depends(require_roles(*_INSPECTOR_ROLES)),
):
    """
    يقبل تقرير المعاينة (يأتي كـ Atomic Unit من IndexedDB عند المزامنة).
    يحدِّث inspection_status في acid_requests تلقائياً.
    """
    if not ObjectId.is_valid(body.acid_id):
        raise HTTPException(400, "معرّف الطلب غير صالح")

    acid = await db.acid_requests.find_one({"_id": ObjectId(body.acid_id)})
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    if acid.get("inspection_status") == "compliant":
        raise HTTPException(409, "تم تسليم تقرير معاينة مطابق لهذا الطلب مسبقاً")

    # ── التحقق من الحقول الإلزامية ────────────────────────────────
    if body.hs_code_match == "not_matching" and not body.suggested_hs_code:
        raise HTTPException(422, "البند المقترح إلزامي عند عدم مطابقة رمز HS")
    if len(body.photos) < 3:
        raise HTTPException(422, "يجب رفع 3 صور على الأقل كأدلة ميدانية")

    uid  = current_user["_id"]
    name = current_user.get("name_ar", "")
    now  = datetime.now(timezone.utc).isoformat()

    report_doc = {
        "acid_id":            body.acid_id,
        "acid_number":        acid.get("acid_number", ""),
        "inspector_id":       uid,
        "inspector_name":     name,

        # القسم 1
        "seal_status":           body.seal_status,
        "new_seal_number":       body.new_seal_number,
        "container_integrity":   body.container_integrity,
        "container_integrity_notes": body.container_integrity_notes,

        # القسم 2
        "hs_code_declared":    acid.get("hs_code", ""),
        "hs_code_match":       body.hs_code_match,
        "suggested_hs_code":   body.suggested_hs_code,
        "origin_country_match": body.origin_country_match,
        "actual_quantity":     body.actual_quantity,
        "actual_weight":       body.actual_weight,
        "declared_quantity":   acid.get("quantity"),

        # القسم 3
        "trademark_status":    body.trademark_status,
        "expiry_date":         body.expiry_date,
        "inspector_notes":     body.inspector_notes,

        # المواد الخطرة
        "dangerous_goods_flag": body.dangerous_goods_flag,
        "dangerous_goods_type": body.dangerous_goods_type,

        # الصور (base64)
        "photos":              body.photos,
        "photos_count":        len(body.photos),

        # النتيجة
        "overall_result":      body.overall_result,

        # التوقيت
        "inspection_started_at":   body.inspection_started_at,
        "inspection_completed_at": body.inspection_completed_at,
        "submitted_at":            now,
    }

    await db.inspections.insert_one(report_doc)

    # ── تحديث حالة المعاينة في acid_requests ─────────────────────
    await db.acid_requests.update_one(
        {"_id": ObjectId(body.acid_id)},
        {"$set": {
            "inspection_status":    body.overall_result,
            "inspection_report_id": str(report_doc.get("_id", "")),
            "inspection_submitted_at": now,
            "updated_at":           now,
        },
         "$push": {"timeline": {
             "event":     f"inspection_{body.overall_result}",
             "timestamp": now,
             "actor":     name,
             "notes":     body.inspector_notes or "",
         }}},
    )

    # ── تنبيه طارئ للمواد الخطرة ──────────────────────────────────
    if body.dangerous_goods_flag:
        background_tasks.add_task(
            _alert_dangerous_goods, body.acid_id, acid.get("acid_number", ""),
            body.dangerous_goods_type or "غير محدد", name, now
        )

    # ── Audit Log ─────────────────────────────────────────────────
    await log_audit(
        action=f"inspection_{body.overall_result}",
        user_id=uid, user_name=name,
        resource_type="acid_request", resource_id=body.acid_id,
        details={
            "overall_result":     body.overall_result,
            "hs_code_match":      body.hs_code_match,
            "dangerous_goods":    body.dangerous_goods_flag,
            "photos_count":       len(body.photos),
        },
        ip_address="",
    )

    return {
        "message": "تم رفع تقرير المعاينة بنجاح",
        "overall_result": body.overall_result,
        "acid_number":    acid.get("acid_number", ""),
    }


# ─── تنبيه طارئ المواد الخطرة ────────────────────────────────────
async def _alert_dangerous_goods(acid_id: str, acid_number: str,
                                  goods_type: str, inspector_name: str, ts: str):
    """يُرسل WebSocket إشعار طارئ لجميع المدراء فور اكتشاف مواد خطرة."""
    admins = await db.users.find({"role": "admin"}, {"_id": 1}).to_list(10)
    for admin in admins:
        try:
            await send_notification(
                str(admin["_id"]),
                "dangerous_goods_detected",
                {
                    "acid_number":     acid_number,
                    "goods_type":      goods_type,
                    "inspector_name":  inspector_name,
                },
                "ar",
                acid_id,
            )
        except Exception:
            pass

    await ws_manager.broadcast_all({
        "type":       "dangerous_goods_alert",
        "level":      "CRITICAL",
        "message_ar": f"🚨 تنبيه طارئ: اكتشاف مواد خطرة في الشحنة {acid_number} — النوع: {goods_type} — المفتش: {inspector_name}",
        "acid_id":    acid_id,
        "timestamp":  ts,
    })



# ═══════════════════════════════════════════════════════════════
# Yellow Channel — مراجعة وثائق فقط (للمخاطر المتوسطة)
# ═══════════════════════════════════════════════════════════════

@router.post("/yellow-review")
async def yellow_channel_review(
    body: dict,
    background_tasks: BackgroundTasks,
    current_user=Depends(require_roles(*_INSPECTOR_ROLES)),
):
    """
    القناة الصفراء — مراجعة وثائق فقط (بدون معاينة ميدانية).
    تُطبَّق على الشحنات ذات المخاطر المتوسطة (risk_level='medium').
    المطلوب: acid_id + decision (approved/rejected) + notes
    """
    acid_id  = body.get("acid_id", "")
    decision = body.get("decision", "")
    notes    = body.get("notes", "")

    if not ObjectId.is_valid(acid_id):
        raise HTTPException(400, "معرّف الطلب غير صالح")
    if decision not in ["approved", "rejected"]:
        raise HTTPException(400, "القرار يجب أن يكون approved أو rejected")

    acid = await db.acid_requests.find_one({"_id": ObjectId(acid_id)})
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    if acid.get("risk_level") == "high":
        raise HTTPException(
            400,
            "هذه الشحنة ذات مخاطرة عالية — يجب إجراء معاينة ميدانية كاملة وليس مراجعة وثائق فقط."
        )
    if acid.get("inspection_status") == "compliant":
        raise HTTPException(409, "تم مراجعة هذه الشحنة مسبقاً")

    now       = datetime.now(timezone.utc).isoformat()
    uid       = current_user["_id"]
    name      = current_user.get("name_ar", "")
    new_insp  = "compliant" if decision == "approved" else "non_compliant"

    await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {
            "$set": {
                "inspection_status":        new_insp,
                "yellow_review_status":     decision,
                "yellow_review_officer_id": uid,
                "yellow_review_notes":      notes,
                "yellow_review_at":         now,
                "updated_at":               now,
            },
            "$push": {"timeline": {
                "event":     f"inspection_{new_insp}",
                "timestamp": now,
                "actor":     name,
                "notes":     f"[القناة الصفراء — مراجعة وثائق] {notes}",
            }},
        }
    )

    await log_audit(
        action=f"yellow_review_{decision}",
        user_id=uid, user_name=name,
        resource_type="acid_request", resource_id=acid_id,
        details={"decision": decision, "notes": notes},
        ip_address="",
    )

    return {
        "message": f"تمت مراجعة الوثائق — القرار: {'مقبول' if decision == 'approved' else 'مرفوض'}",
        "inspection_status": new_insp,
        "channel": "yellow",
    }
