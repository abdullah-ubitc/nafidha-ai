"""
workflow.py — محرك تدفق العمل الشامل (Universal Workflow Engine)
══════════════════════════════════════════════════════════════════
يُطبَّق على:
  • مراجعة KYC      (users collection)        ← registration_officer
  • مراجعة ACID     (acid_requests collection) ← acid_risk_officer
  • Admin           يرى الكل + فك القفل

حقول الـ Workflow المُضافة لكل collection:
  wf_status          : "Unassigned" | "In_Progress" | "Completed" | "Escalated"
  wf_assigned_to     : ObjectId of the officer
  wf_assigned_to_name: cached Arabic name
  wf_claimed_at      : ISO timestamp
  wf_sla_deadline    : ISO timestamp (auto from created_at + SLA hours)
  wf_completed_at    : ISO timestamp
  wf_completed_by    : ObjectId
  wf_completed_by_name: cached name
"""
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal
from fastapi import APIRouter, HTTPException, Depends, Query
from bson import ObjectId
from pydantic import BaseModel

from database import db
from auth_utils import get_current_user, require_roles
from models import UserRole

router = APIRouter(prefix="/workflow", tags=["workflow"])

# ─── Roles & SLA config ────────────────────────────────────────────
_ADMIN         = UserRole.ADMIN
_KYC_OFFICER   = UserRole.REGISTRATION_OFFICER
_ACID_OFFICER  = UserRole.ACID_RISK_OFFICER
_ALL_WF_ROLES  = (_ADMIN, _KYC_OFFICER, _ACID_OFFICER)

_KYC_SLA_HOURS  = 72
_ACID_SLA_HOURS = 48

_KYC_ROLES = ["importer", "customs_broker", "carrier_agent", "foreign_supplier"]
_ACID_STATUSES = ["submitted", "pending", "under_review"]   # reviewable ACID statuses

# ─── Helpers ───────────────────────────────────────────────────────

def _wf_unassigned_query() -> dict:
    """مهمة متاحة = wf_status غير موجود أو = Unassigned"""
    return {"$or": [{"wf_status": {"$exists": False}}, {"wf_status": "Unassigned"}]}


def _sla_deadline(created_at, hours: int) -> str:
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (created_at + timedelta(hours=hours)).isoformat()


def _hours_remaining(deadline_iso: str) -> float:
    """ساعات متبقية حتى الـ SLA (سالب = تخطى الموعد)."""
    try:
        dl = datetime.fromisoformat(deadline_iso)
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)
        return round((dl - datetime.now(timezone.utc)).total_seconds() / 3600, 1)
    except Exception:
        return 9999.0


def _fmt_kyc_task(u: dict) -> dict:
    created = u.get("created_at", datetime.now(timezone.utc))
    deadline = u.get("wf_sla_deadline") or _sla_deadline(created, _KYC_SLA_HOURS)
    wf_status = u.get("wf_status", "Unassigned")
    return {
        "task_id":           str(u["_id"]),
        "task_type":         "kyc_review",
        "task_type_label":   "مراجعة KYC",
        "title":             u.get("name_ar") or u.get("name_en") or u.get("email", ""),
        "subtitle":          u.get("company_name_ar") or u.get("email", ""),
        "meta_role":         u.get("role", ""),
        "meta_email":        u.get("email", ""),
        "meta_phone":        u.get("phone", ""),
        "created_at":        created.isoformat() if hasattr(created, "isoformat") else str(created),
        "wf_status":         wf_status,
        "is_awaiting_correction": wf_status == "Awaiting_Correction",
        "wf_assigned_to":    str(u["wf_assigned_to"]) if u.get("wf_assigned_to") else None,
        "wf_assigned_to_name": u.get("wf_assigned_to_name"),
        "wf_claimed_at":     u.get("wf_claimed_at"),
        "wf_sla_deadline":   deadline,
        "wf_completed_at":    u.get("wf_completed_at"),
        "wf_completed_by_name": u.get("wf_completed_by_name"),
        "wf_review_notes":    u.get("wf_review_notes"),
        "sla_hours_remaining": _hours_remaining(deadline),
        # ── Carrier multi-modal fields ────────────────────────────────────────────
        "transport_modes":          u.get("transport_modes"),
        "transport_modes_approved": u.get("transport_modes_approved"),
        "transport_modes_rejected": u.get("transport_modes_rejected"),
        "statistical_expiry_date":  u.get("statistical_expiry_date"),
        "marine_license_expiry":    u.get("marine_license_expiry"),
        "air_license_expiry":       u.get("air_license_expiry"),
        "land_license_expiry":      u.get("land_license_expiry"),
        # ── Correction info ───────────────────────────────────────────────────────
        "registration_status":      u.get("registration_status", ""),
        "correction_notes":         u.get("correction_notes"),
        "correction_flagged_docs":  u.get("correction_flagged_docs", []),
        "correction_requested_at":  u.get("correction_requested_at"),
    }


def _fmt_acid_task(a: dict) -> dict:
    created = a.get("created_at", datetime.now(timezone.utc))
    deadline = a.get("wf_sla_deadline") or _sla_deadline(created, _ACID_SLA_HOURS)
    return {
        "task_id":           str(a["_id"]),
        "task_type":         "acid_review",
        "task_type_label":   "مراجعة ACID",
        "title":             a.get("acid_number") or str(a["_id"])[:8],
        "subtitle":          a.get("importer_name_ar") or a.get("importer_name") or "",
        "meta_status":       a.get("status", ""),
        "meta_commodity":    a.get("commodity_description", ""),
        "meta_value":        a.get("total_value_usd", ""),
        "meta_origin":       a.get("country_of_origin", ""),
        "created_at":        created.isoformat() if hasattr(created, "isoformat") else str(created),
        "wf_status":         a.get("wf_status", "Unassigned"),
        "wf_assigned_to":    str(a["wf_assigned_to"]) if a.get("wf_assigned_to") else None,
        "wf_assigned_to_name": a.get("wf_assigned_to_name"),
        "wf_claimed_at":     a.get("wf_claimed_at"),
        "wf_sla_deadline":   deadline,
        "wf_completed_at":    a.get("wf_completed_at"),
        "wf_completed_by_name": a.get("wf_completed_by_name"),
        "wf_review_notes":    a.get("wf_review_notes"),
        "sla_hours_remaining": _hours_remaining(deadline),
    }


def _task_types_for_role(roles: list) -> list[str]:
    """
    يُعيد أنواع المهام بناءً على مصفوفة الأدوار (Multi-Role Support).
    موظف بـ registration_officer + acid_risk_officer يرى كلا النوعين.
    """
    types: set = set()
    for r in roles:
        if r == "admin":
            types.update(["kyc_review", "acid_review"])
        elif r == "registration_officer":
            types.add("kyc_review")
        elif r in ("acid_risk_officer", "acid_reviewer"):
            types.add("acid_review")
    return list(types)


async def _fetch_tasks(task_type: str, extra_query: dict, limit: int = 100) -> list:
    if task_type == "kyc_review":
        q = {
            "role": {"$in": _KYC_ROLES},
            "registration_status": {"$in": ["pending", "needs_correction"]},
            **extra_query,
        }
        docs = await db.users.find(q).sort("created_at", 1).limit(limit).to_list(limit)
        return [_fmt_kyc_task(d) for d in docs]
    elif task_type == "acid_review":
        q = {"status": {"$in": _ACID_STATUSES}, **extra_query}
        docs = await db.acid_requests.find(q).sort("created_at", 1).limit(limit).to_list(limit)
        return [_fmt_acid_task(d) for d in docs]
    return []


# ─── Endpoints ─────────────────────────────────────────────────────

@router.get("/pool")
async def get_pool(
    task_type: Optional[str] = None,
    current_user=Depends(require_roles(*_ALL_WF_ROLES)),
):
    """الحوض العام — المهام المتاحة غير المحجوزة."""
    role  = current_user.get("role", "")
    roles = current_user.get("roles") or [role]
    types = [task_type] if task_type else _task_types_for_role(roles)
    result = []
    for t in types:
        result += await _fetch_tasks(t, _wf_unassigned_query())
    return result


@router.get("/my-queue")
async def get_my_queue(
    task_type: Optional[str] = None,
    current_user=Depends(require_roles(*_ALL_WF_ROLES)),
):
    """مهامي — المهام المحجوزة من قِبَل الموظف الحالي (In_Progress + Awaiting_Correction)."""
    uid   = current_user["_id"]
    role  = current_user.get("role", "")
    roles = current_user.get("roles") or [role]
    types = [task_type] if task_type else _task_types_for_role(roles)
    result = []
    for t in types:
        result += await _fetch_tasks(t, {
            "wf_status": {"$in": ["In_Progress", "Awaiting_Correction"]},
            "wf_assigned_to": uid,
        })
    return result


@router.get("/my-history")
async def get_my_history(
    task_type: Optional[str] = None,
    limit: int = Query(50, le=200),
    current_user=Depends(require_roles(*_ALL_WF_ROLES)),
):
    """سجلي — المهام المكتملة من قِبَل الموظف الحالي."""
    uid   = current_user["_id"]
    role  = current_user.get("role", "")
    roles = current_user.get("roles") or [role]
    types = [task_type] if task_type else _task_types_for_role(roles)
    result = []
    for t in types:
        if t == "kyc_review":
            docs = await db.users.find({
                "role": {"$in": _KYC_ROLES},
                "wf_status": "Completed",
                "wf_completed_by": uid,
            }).sort("wf_completed_at", -1).limit(limit).to_list(limit)
            result += [_fmt_kyc_task(d) for d in docs]
        elif t == "acid_review":
            docs = await db.acid_requests.find({
                "wf_status": "Completed",
                "wf_completed_by": uid,
            }).sort("wf_completed_at", -1).limit(limit).to_list(limit)
            result += [_fmt_acid_task(d) for d in docs]
    return result


class ClaimInput(BaseModel):
    task_type: Literal["kyc_review", "acid_review"]
    task_id: str


@router.post("/claim")
async def claim_task(
    body: ClaimInput,
    current_user=Depends(require_roles(*_ALL_WF_ROLES)),
):
    """
    حجز مهمة — عملية ذرية (Atomic) تمنع الحجز المزدوج.
    إذا حجزها موظف آخر في نفس اللحظة، تُرجع 409.
    """
    uid   = current_user["_id"]
    name  = current_user.get("name_ar", current_user.get("name_en", ""))
    now   = datetime.now(timezone.utc).isoformat()

    if not ObjectId.is_valid(body.task_id):
        raise HTTPException(400, "معرّف المهمة غير صالح")

    claim_condition = {"_id": ObjectId(body.task_id),
                       "$or": [{"wf_status": {"$exists": False}}, {"wf_status": "Unassigned"}]}
    claim_update    = {"$set": {
        "wf_status":            "In_Progress",
        "wf_assigned_to":       uid,
        "wf_assigned_to_name":  name,
        "wf_claimed_at":        now,
    }}

    col = db.users if body.task_type == "kyc_review" else db.acid_requests
    result = await col.find_one_and_update(claim_condition, claim_update)
    if not result:
        raise HTTPException(409, "المهمة محجوزة من قِبَل موظف آخر أو غير موجودة")

    # Audit
    await db.audit_logs.insert_one({
        "action": f"workflow_claim_{body.task_type}",
        "user_id": uid, "user_name": name,
        "resource_type": body.task_type, "resource_id": body.task_id,
        "details": {"claimed_at": now},
        "timestamp": now,
    })
    return {"message": "تم حجز المهمة بنجاح", "task_id": body.task_id, "task_type": body.task_type}


class ReleaseInput(BaseModel):
    task_type: Literal["kyc_review", "acid_review"]
    task_id: str
    reason: Optional[str] = None


@router.post("/release")
async def release_task(
    body: ReleaseInput,
    current_user=Depends(require_roles(*_ALL_WF_ROLES)),
):
    """إعادة المهمة للحوض العام (من قِبَل المالك نفسه)."""
    uid  = current_user["_id"]
    name = current_user.get("name_ar", "")
    now  = datetime.now(timezone.utc).isoformat()

    if not ObjectId.is_valid(body.task_id):
        raise HTTPException(400, "معرّف المهمة غير صالح")

    col = db.users if body.task_type == "kyc_review" else db.acid_requests
    result = await col.find_one_and_update(
        {"_id": ObjectId(body.task_id), "wf_assigned_to": uid,
         "wf_status": {"$in": ["In_Progress", "Awaiting_Correction"]}},
        {"$set": {"wf_status": "Unassigned", "wf_assigned_to": None,
                  "wf_assigned_to_name": None, "wf_claimed_at": None}},
    )
    if not result:
        raise HTTPException(404, "لا تملك صلاحية تحرير هذه المهمة")

    await db.audit_logs.insert_one({
        "action": f"workflow_release_{body.task_type}",
        "user_id": uid, "user_name": name,
        "resource_type": body.task_type, "resource_id": body.task_id,
        "details": {"reason": body.reason},
        "timestamp": now,
    })
    return {"message": "تمت إعادة المهمة للحوض العام"}


class CompleteInput(BaseModel):
    task_type: Literal["kyc_review", "acid_review"]
    task_id: str
    notes: str  # إلزامي — يجب توثيق ملاحظات المراجعة


@router.post("/complete")
async def complete_task(
    body: CompleteInput,
    current_user=Depends(require_roles(*_ALL_WF_ROLES)),
):
    """وضع علامة 'مكتملة' على المهمة — الملاحظات إلزامية."""
    uid  = current_user["_id"]
    name = current_user.get("name_ar", "")
    now  = datetime.now(timezone.utc).isoformat()

    if not ObjectId.is_valid(body.task_id):
        raise HTTPException(400, "معرّف المهمة غير صالح")

    notes = (body.notes or "").strip()
    if not notes:
        raise HTTPException(422, "ملاحظات المراجعة إلزامية — يُرجى توثيق نتيجة المراجعة")

    col = db.users if body.task_type == "kyc_review" else db.acid_requests
    result = await col.find_one_and_update(
        {"_id": ObjectId(body.task_id), "wf_assigned_to": uid, "wf_status": "In_Progress"},
        {"$set": {
            "wf_status":            "Completed",
            "wf_completed_at":      now,
            "wf_completed_by":      uid,
            "wf_completed_by_name": name,
            "wf_review_notes":      notes,          # حفظ الملاحظات في المستند نفسه
        }},
    )
    if not result:
        raise HTTPException(404, "المهمة غير موجودة أو لم تُحجز بعد")

    await db.audit_logs.insert_one({
        "action": f"workflow_complete_{body.task_type}",
        "user_id": uid, "user_name": name,
        "resource_type": body.task_type, "resource_id": body.task_id,
        "details": {"notes": notes, "completed_at": now},
        "timestamp": now,
    })
    return {"message": "تم إنجاز المهمة بنجاح"}


# ─── Admin Control Tower ────────────────────────────────────────────

@router.get("/admin/in-progress")
async def admin_in_progress(current_user=Depends(require_roles(_ADMIN))):
    """قائمة جميع المهام المحجوزة حالياً (لاستخدام فك القفل)."""
    kyc_docs  = await db.users.find({
        "role": {"$in": _KYC_ROLES},
        "wf_status": "In_Progress",
    }).sort("wf_claimed_at", 1).limit(100).to_list(100)
    acid_docs = await db.acid_requests.find({
        "wf_status": "In_Progress",
    }).sort("wf_claimed_at", 1).limit(100).to_list(100)
    result = [_fmt_kyc_task(d) for d in kyc_docs] + [_fmt_acid_task(d) for d in acid_docs]
    result.sort(key=lambda x: x.get("wf_claimed_at") or "")
    return result


@router.get("/admin/overview")
async def admin_overview(current_user=Depends(require_roles(_ADMIN))):
    """
    خارطة توزيع العمل للمدير — يعرض الموظفين النشطين وعدد مهامهم.
    """
    pipeline = [
        {"$match": {"wf_status": "In_Progress"}},
        {"$group": {
            "_id": "$wf_assigned_to",
            "name": {"$first": "$wf_assigned_to_name"},
            "count": {"$sum": 1},
            "oldest_claim": {"$min": "$wf_claimed_at"},
        }},
    ]
    kyc_groups  = await db.users.aggregate(pipeline).to_list(100)
    acid_groups = await db.acid_requests.aggregate(pipeline).to_list(100)

    # دمج حسب الموظف
    officers: dict = {}
    for g in kyc_groups:
        oid = str(g["_id"]) if g["_id"] else "unknown"
        officers.setdefault(oid, {"name": g.get("name", ""), "kyc_active": 0, "acid_active": 0, "oldest_claim": g.get("oldest_claim")})
        officers[oid]["kyc_active"] = g["count"]
    for g in acid_groups:
        oid = str(g["_id"]) if g["_id"] else "unknown"
        officers.setdefault(oid, {"name": g.get("name", ""), "kyc_active": 0, "acid_active": 0, "oldest_claim": g.get("oldest_claim")})
        officers[oid]["acid_active"] = g["count"]

    result = []
    for oid, data in officers.items():
        result.append({
            "officer_id":    oid,
            "officer_name":  data["name"],
            "kyc_active":    data["kyc_active"],
            "acid_active":   data["acid_active"],
            "total_active":  data["kyc_active"] + data["acid_active"],
            "oldest_claim":  data.get("oldest_claim"),
        })

    # Total pool counts
    kyc_pool   = await db.users.count_documents({"role": {"$in": _KYC_ROLES}, "registration_status": {"$in": ["pending", "needs_correction"]}, **_wf_unassigned_query()})
    acid_pool  = await db.acid_requests.count_documents({"status": {"$in": _ACID_STATUSES}, **_wf_unassigned_query()})
    kyc_inprog  = await db.users.count_documents({"role": {"$in": _KYC_ROLES}, "registration_status": {"$in": ["pending", "needs_correction"]}, "wf_status": "In_Progress"})
    acid_inprog = await db.acid_requests.count_documents({"status": {"$in": _ACID_STATUSES}, "wf_status": "In_Progress"})

    return {
        "officers":       result,
        "pool_counts":    {"kyc": kyc_pool, "acid": acid_pool},
        "inprogress_counts": {"kyc": kyc_inprog, "acid": acid_inprog},
    }


class ForceReleaseInput(BaseModel):
    task_type: Literal["kyc_review", "acid_review"]
    task_id: str
    reason: Optional[str] = "فك القفل من قِبَل المدير"


@router.post("/admin/force-release")
async def force_release(
    body: ForceReleaseInput,
    current_user=Depends(require_roles(_ADMIN)),
):
    """فك القفل — يُعيد المهمة للحوض بغض النظر عن المالك."""
    if not ObjectId.is_valid(body.task_id):
        raise HTTPException(400, "معرّف المهمة غير صالح")
    now  = datetime.now(timezone.utc).isoformat()
    name = current_user.get("name_ar", "")
    col  = db.users if body.task_type == "kyc_review" else db.acid_requests

    result = await col.find_one_and_update(
        {"_id": ObjectId(body.task_id), "wf_status": "In_Progress"},
        {"$set": {"wf_status": "Unassigned", "wf_assigned_to": None,
                  "wf_assigned_to_name": None, "wf_claimed_at": None}},
    )
    if not result:
        raise HTTPException(404, "المهمة غير موجودة أو ليست محجوزة")

    await db.audit_logs.insert_one({
        "action": f"workflow_force_release_{body.task_type}",
        "user_id": current_user["_id"], "user_name": name,
        "resource_type": body.task_type, "resource_id": body.task_id,
        "details": {"reason": body.reason, "released_from": str(result.get("wf_assigned_to", ""))},
        "timestamp": now,
    })
    return {"message": "تم فك قفل المهمة وإعادتها للحوض العام"}


@router.get("/admin/throughput")
async def admin_throughput(current_user=Depends(require_roles(_ADMIN))):
    """إحصاءات الإنجاز — عدد المهام المكتملة لكل قسم."""
    now   = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week  = (now - timedelta(days=7)).isoformat()

    kyc_today  = await db.users.count_documents({"wf_status": "Completed", "wf_completed_at": {"$gte": today}})
    kyc_week   = await db.users.count_documents({"wf_status": "Completed", "wf_completed_at": {"$gte": week}})
    acid_today = await db.acid_requests.count_documents({"wf_status": "Completed", "wf_completed_at": {"$gte": today}})
    acid_week  = await db.acid_requests.count_documents({"wf_status": "Completed", "wf_completed_at": {"$gte": week}})

    # Per-officer throughput (last 7 days)
    pipeline = [
        {"$match": {"wf_status": "Completed", "wf_completed_at": {"$gte": week}}},
        {"$group": {"_id": "$wf_completed_by_name", "completed": {"$sum": 1}}},
        {"$sort": {"completed": -1}},
        {"$limit": 10},
    ]
    kyc_by_officer  = await db.users.aggregate(pipeline).to_list(10)
    acid_by_officer = await db.acid_requests.aggregate(pipeline).to_list(10)

    return {
        "kyc":  {"today": kyc_today,  "week": kyc_week,  "by_officer": [{"name": d["_id"] or "—", "count": d["completed"]} for d in kyc_by_officer]},
        "acid": {"today": acid_today, "week": acid_week, "by_officer": [{"name": d["_id"] or "—", "count": d["completed"]} for d in acid_by_officer]},
    }


@router.get("/stats")
async def workflow_stats(current_user=Depends(require_roles(*_ALL_WF_ROLES))):
    """إحصاءات سريعة للموظف الحالي + الحوض العام — يدعم Multi-Role."""
    uid   = current_user["_id"]
    role  = current_user.get("role", "")
    roles = current_user.get("roles") or [role]
    types = _task_types_for_role(roles)

    pool = my_q = my_h = 0
    for t in types:
        col = db.users if t == "kyc_review" else db.acid_requests
        base = {"role": {"$in": _KYC_ROLES}, "registration_status": {"$in": ["pending", "needs_correction"]}} if t == "kyc_review" else {"status": {"$in": _ACID_STATUSES}}
        pool += await col.count_documents({**base, **_wf_unassigned_query()})
        my_q += await col.count_documents({
            **base,
            "wf_status": {"$in": ["In_Progress", "Awaiting_Correction"]},
            "wf_assigned_to": uid,
        })
        hist_base = {"role": {"$in": _KYC_ROLES}} if t == "kyc_review" else {}
        my_h += await col.count_documents({**hist_base, "wf_status": "Completed", "wf_completed_by": uid})

    return {"pool": pool, "my_queue": my_q, "my_history": my_h}
