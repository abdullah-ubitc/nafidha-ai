"""Gate release routes (JL38 final release) + Shipment Status Board"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
from models import GateReleaseInput, UserRole
from database import db
from auth_utils import require_roles
from helpers import format_doc, log_audit, generate_jl38_number
from ws_manager import ws_manager
from notifications import notify_user_whatsapp

router = APIRouter(tags=["gate"])


@router.get("/gate/queue")
async def gate_queue(current_user=Depends(require_roles(UserRole.GATE_OFFICER, UserRole.ADMIN))):
    reqs = await db.acid_requests.find(
        {"status": "treasury_paid", "gate_released": {"$ne": True}}
    ).sort("created_at", 1).to_list(100)
    return [format_doc(r) for r in reqs]


@router.post("/acid/{acid_id}/gate-release")
async def gate_release(acid_id: str, data: GateReleaseInput,
                       background_tasks: BackgroundTasks,
                       current_user=Depends(require_roles(UserRole.GATE_OFFICER, UserRole.ADMIN))):
    acid_req = await db.acid_requests.find_one({"_id": ObjectId(acid_id)})
    if not acid_req:
        raise HTTPException(404, "طلب ACID غير موجود")
    if not acid_req.get("treasury_paid"):
        raise HTTPException(403, "مرفوض: لم يتم تأكيد سداد الرسوم الجمركية من أمين الخزينة. لا يمكن إصدار JL38.")
    # Phase E Hard-Stop: Platform fees must also be paid
    if not acid_req.get("platform_fees_paid"):
        raise HTTPException(403, "مرفوض — الخط الأحمر: لم يتم سداد رسوم المنصة التشغيلية (NAFIDHA). يجب سداد جميع الرسوم قبل الإفراج النهائي.")
    if acid_req.get("status") != "treasury_paid":
        raise HTTPException(400, f"حالة الطلب الحالية ({acid_req.get('status')}) لا تسمح بالإفراج. يجب أن يكون 'treasury_paid'.")
    jl38_number = await generate_jl38_number()
    now = datetime.now(timezone.utc)
    timeline_event = {"event": "gate_released", "timestamp": now.isoformat(),
                      "actor": current_user.get("name_ar", ""), "jl38_number": jl38_number, "notes": data.notes}
    await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {"$set": {"status": "gate_released", "gate_released": True, "gate_released_at": now,
                  "gate_officer_id": current_user["_id"], "jl38_number": jl38_number, "updated_at": now},
         "$push": {"timeline": timeline_event}}
    )
    await log_audit(action="acid_gate_released", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="acid_request",
                    resource_id=acid_id, details={"jl38_number": jl38_number})
    background_tasks.add_task(notify_user_whatsapp, acid_req.get("requester_id", ""),
        f"تم الإفراج النهائي عن شحنتك {acid_req.get('acid_number','')}. رقم وثيقة الإفراج: {jl38_number}.",
        "gate_released", acid_id)
    background_tasks.add_task(ws_manager.broadcast_all, {
        "type": "notification", "message_ar": f"تم إصدار JL38 للطلب {acid_req.get('acid_number','')} — الإفراج النهائي",
        "acid_id": acid_id, "new_status": "gate_released", "jl38_number": jl38_number
    })
    return {"message": "تم الإفراج النهائي بنجاح", "jl38_number": jl38_number, "new_status": "gate_released"}


# ═══════════════════════════════════════════════════════════════
# لوحة حالة الرحلات — 9 محطات جمركية
# ═══════════════════════════════════════════════════════════════

STEP_ORDER = [
    "acid_submitted",
    "acid_approved",
    "manifest_accepted",
    "do_issued",
    "declaration_accepted",
    "valued",
    "treasury_paid",
    "inspection_done",
    "gate_released",
]


def _compute_steps(acid: dict, manifest_accepted: bool) -> dict:
    """يحسب حالة كل محطة من المحطات التسع لطلب ACID."""
    risk  = acid.get("risk_level", "medium")
    is_green = acid.get("is_green_channel", False) or risk == "low"
    insp  = acid.get("inspection_status")
    return {
        "acid_submitted":       True,
        "acid_approved":        acid.get("status") in ["approved", "valued", "treasury_paid", "gate_released"],
        "manifest_accepted":    manifest_accepted,
        "do_issued":            bool(acid.get("do_issued")),
        "declaration_accepted": bool(acid.get("declaration_accepted")),
        "valued":               bool(acid.get("valuation_confirmed")),
        "treasury_paid":        bool(acid.get("treasury_paid")),
        "inspection_done":      is_green or insp == "compliant",
        "gate_released":        bool(acid.get("gate_released")),
    }


@router.get("/gate/shipment-status-board")
async def shipment_status_board(
    status_filter: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(require_roles(UserRole.GATE_OFFICER, UserRole.ADMIN)),
):
    """
    لوحة حالة الرحلات — تعرض جميع الشحنات مع محطاتها التسع لمأموري البوابة.
    status_filter: all | ready | in_progress | released
    """
    # ── بناء الفلتر ───────────────────────────────────────────────
    if status_filter == "ready":
        query = {"status": "treasury_paid", "gate_released": {"$ne": True}}
    elif status_filter == "in_progress":
        query = {
            "status": {"$in": ["submitted", "under_review", "approved", "valued"]},
            "gate_released": {"$ne": True},
        }
    elif status_filter == "released":
        query = {"gate_released": True}
    else:
        query = {"status": {"$nin": ["rejected", "amendment_required"]}}

    acids = await db.acid_requests.find(query).sort("created_at", -1).limit(limit).to_list(limit)

    shipments = []
    for acid in acids:
        acid_id  = str(acid["_id"])
        acid_num = acid.get("acid_number", "")

        # ── جلب حالة المانيفست المرتبط ───────────────────────────
        manifest = await db.manifests.find_one(
            {"consignments.acid_number": acid_num, "status": "accepted"},
            {"_id": 0, "manifest_number": 1},
        )
        manifest_accepted = bool(manifest)

        # ── جلب رقم SAD ─────────────────────────────────────────
        sad = await db.sad_forms.find_one(
            {"acid_id": acid_id, "is_active": True},
            {"_id": 0, "sad_number": 1, "status": 1},
        )

        steps = _compute_steps(acid, manifest_accepted)

        # ── حساب المحطة الحالية (آخر خطوة مكتملة) ───────────────
        current_step_idx = 0
        for i, key in enumerate(STEP_ORDER):
            if steps[key]:
                current_step_idx = i

        # ── تحديد ما إذا كانت هناك محطة محجوبة ──────────────────
        # محجوبة = الخزينة مدفوعة لكن رسوم المنصة لم تُسدَّد
        is_blocked = (
            acid.get("treasury_paid")
            and not acid.get("platform_fees_paid")
            and not acid.get("gate_released")
        )

        created_at = acid.get("created_at")
        shipments.append({
            "acid_id":          acid_id,
            "acid_number":      acid_num,
            "status":           acid.get("status", ""),
            "risk_level":       acid.get("risk_level", "medium"),
            "is_green_channel": acid.get("is_green_channel", False),
            "goods_description": acid.get("goods_description", "")[:60],
            "requester_name":   acid.get("requester_name_ar") or acid.get("requester_name_en", ""),
            "port_of_entry":    acid.get("port_of_entry", ""),
            "transport_mode":   acid.get("transport_mode", ""),
            "treasury_paid":    bool(acid.get("treasury_paid")),
            "platform_fees_paid": bool(acid.get("platform_fees_paid")),
            "gate_released":    bool(acid.get("gate_released")),
            "jl38_number":      acid.get("jl38_number"),
            "inspection_status": acid.get("inspection_status"),
            "is_blocked":       is_blocked,
            "manifest_number":  manifest.get("manifest_number") if manifest else None,
            "sad_number":       sad.get("sad_number") if sad else None,
            "steps":            steps,
            "current_step_idx": current_step_idx,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
            "timeline":         acid.get("timeline", []),
        })

    # ── إحصائيات سريعة ──────────────────────────────────────────
    now_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stats = {
        "total_active":      await db.acid_requests.count_documents(
            {"status": {"$nin": ["rejected", "amendment_required", "gate_released"]}}
        ),
        "ready_for_release": await db.acid_requests.count_documents(
            {"status": "treasury_paid", "gate_released": {"$ne": True}}
        ),
        "released_today":    await db.acid_requests.count_documents(
            {"gate_released": True, "gate_released_at": {"$gte": now_day}}
        ),
        "blocked":           await db.acid_requests.count_documents(
            {"treasury_paid": True, "platform_fees_paid": {"$ne": True}, "gate_released": {"$ne": True}}
        ),
    }

    return {"shipments": shipments, "stats": stats}
