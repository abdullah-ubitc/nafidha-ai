"""Customs Valuer workflow routes"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from bson import ObjectId
from datetime import datetime, timezone
from models import ValuationInput, UserRole
from database import db
from auth_utils import require_roles
from helpers import format_doc, log_audit
from ws_manager import ws_manager
from notifications import notify_user_whatsapp
from services.notification_service import notify_role_users

router = APIRouter(tags=["valuer"])


@router.get("/valuer/queue")
async def valuer_queue(current_user=Depends(require_roles(UserRole.CUSTOMS_VALUER, UserRole.ADMIN))):
    """
    طابور التقييم الجمركي — الترتيب الصحيح: قبول البيان ← التقييم ← الخزينة.
    لا يظهر الطلب في طابور المُقيِّم إلا بعد قبول البيان الجمركي (declaration_accepted=True).
    """
    reqs = await db.acid_requests.find(
        {
            "status": "approved",
            "valuation_confirmed": {"$ne": True},
            "declaration_accepted": True,   # ← البيان مقبول أولاً
        }
    ).sort("created_at", -1).to_list(100)
    return [format_doc(r) for r in reqs]


@router.post("/acid/{acid_id}/submit-valuation")
async def submit_valuation(acid_id: str, data: ValuationInput,
                           background_tasks: BackgroundTasks,
                           current_user=Depends(require_roles(UserRole.CUSTOMS_VALUER, UserRole.ADMIN))):
    acid_req = await db.acid_requests.find_one({"_id": ObjectId(acid_id)})
    if not acid_req:
        raise HTTPException(404, "طلب ACID غير موجود")
    if acid_req.get("status") not in ["approved"]:
        raise HTTPException(400, "الطلب غير جاهز للتقييم — يجب أن يكون معتمداً أولاً")
    # ── التسلسل الإلزامي: البيان يُقبل قبل التقييم ─────────────────
    if not acid_req.get("declaration_accepted", False):
        raise HTTPException(
            400,
            "لا يمكن البدء في التقييم الجمركي قبل قبول البيان الجمركي (SAD) من مأمور البيان. "
            "الترتيب الصحيح: قبول البيان ← التقييم ← الخزينة."
        )
    now = datetime.now(timezone.utc)
    timeline_event = {"event": "valued", "timestamp": now.isoformat(), "actor": current_user.get("name_ar", ""),
                      "notes": data.valuation_notes or "", "confirmed_value_usd": data.confirmed_value_usd}
    await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {"$set": {"status": "valued", "valuation_confirmed": True, "valuation_confirmed_at": now,
                  "valuer_id": current_user["_id"], "confirmed_value_usd": data.confirmed_value_usd,
                  "valuation_notes": data.valuation_notes, "updated_at": now},
         "$push": {"timeline": timeline_event}}
    )
    await log_audit(action="acid_valued", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="acid_request",
                    resource_id=acid_id, details={"confirmed_value_usd": data.confirmed_value_usd, "notes": data.valuation_notes})
    background_tasks.add_task(notify_user_whatsapp, acid_req.get("requester_id", ""),
        f"تم تقييم شحنتك رقم {acid_req.get('acid_number','')} بقيمة ${data.confirmed_value_usd:,.0f}. يُرجى التوجه لسداد الرسوم الجمركية.",
        "valuation_completed", acid_id)
    background_tasks.add_task(ws_manager.broadcast_all, {
        "type": "notification", "message_ar": f"تم تقييم الطلب {acid_req.get('acid_number','')} — ينتظر السداد",
        "acid_id": acid_id, "new_status": "valued"
    })
    # ── إشعار موظفي الخزينة بوصول شحنة جاهزة للسداد ──────────────
    background_tasks.add_task(
        notify_role_users,
        "treasury_officer",
        "task_ready_for_treasury",
        {
            "acid_number": acid_req.get("acid_number", ""),
            "confirmed_value": f"{data.confirmed_value_usd:,.0f}",
        },
        acid_id,
        current_user["_id"],
    )
    return {"message": "تم تأكيد التقييم الجمركي بنجاح", "new_status": "valued", "confirmed_value_usd": data.confirmed_value_usd}
