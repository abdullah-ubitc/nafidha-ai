"""Treasury + Guarantees routes"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
from models import TreasuryPayInput, GuaranteeCreate, GuaranteeReleaseInput, UserRole
from database import db
from auth_utils import require_roles
from helpers import format_doc, log_audit, generate_guarantee_number
from ws_manager import ws_manager
from notifications import notify_user_whatsapp
from services.notification_service import notify_role_users

router = APIRouter(tags=["treasury"])


# ---- Treasury Queue & Payment ----
@router.get("/treasury/queue")
async def treasury_queue(current_user=Depends(require_roles(UserRole.TREASURY_OFFICER, UserRole.ADMIN))):
    reqs = await db.acid_requests.find(
        {"status": "valued", "treasury_paid": {"$ne": True}}
    ).sort("created_at", -1).to_list(100)
    return [format_doc(r) for r in reqs]


@router.post("/acid/{acid_id}/treasury-mark-paid")
async def treasury_mark_paid(acid_id: str, data: TreasuryPayInput,
                             background_tasks: BackgroundTasks,
                             current_user=Depends(require_roles(UserRole.TREASURY_OFFICER, UserRole.ADMIN))):
    acid_req = await db.acid_requests.find_one({"_id": ObjectId(acid_id)})
    if not acid_req:
        raise HTTPException(404, "طلب ACID غير موجود")
    if acid_req.get("status") not in ["valued"]:
        raise HTTPException(400, "الطلب لم يُقيَّم بعد من موظف التقدير")
    now = datetime.now(timezone.utc)
    timeline_event = {"event": "treasury_paid", "timestamp": now.isoformat(),
                      "actor": current_user.get("name_ar", ""), "treasury_ref": data.treasury_ref}
    await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {"$set": {"status": "treasury_paid", "treasury_paid": True, "treasury_paid_at": now,
                  "treasury_officer_id": current_user["_id"], "treasury_ref": data.treasury_ref, "updated_at": now},
         "$push": {"timeline": timeline_event}}
    )
    await log_audit(action="acid_treasury_paid", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="acid_request",
                    resource_id=acid_id, details={"treasury_ref": data.treasury_ref})
    background_tasks.add_task(notify_user_whatsapp, acid_req.get("requester_id", ""),
        f"تم تأكيد سداد رسوم الشحنة {acid_req.get('acid_number','')}. بضاعتك جاهزة للإفراج عند البوابة.",
        "treasury_paid", acid_id)
    background_tasks.add_task(ws_manager.broadcast_all, {
        "type": "notification", "message_ar": f"تم تأكيد الدفع للطلب {acid_req.get('acid_number','')} — جاهز للإفراج",
        "acid_id": acid_id, "new_status": "treasury_paid"
    })
    # ── إشعار أمناء البوابة وضباط الإفراج بشحنة جاهزة للإفراج ─────
    _acid_num = acid_req.get("acid_number", "")
    for _role in ["gate_officer", "release_officer"]:
        background_tasks.add_task(
            notify_role_users, _role, "task_ready_for_gate",
            {"acid_number": _acid_num}, acid_id, current_user["_id"],
        )
    return {"message": "تم تأكيد الدفع بنجاح — الطلب جاهز للإفراج البوابي", "new_status": "treasury_paid"}


# ---- Guarantees ----
@router.post("/guarantees")
async def create_guarantee(data: GuaranteeCreate, current_user=Depends(require_roles(UserRole.TREASURY_OFFICER, UserRole.ADMIN))):
    acid = await db.acid_requests.find_one({"_id": ObjectId(data.acid_id)}) if ObjectId.is_valid(data.acid_id) else None
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    gua_number = await generate_guarantee_number()
    doc = {
        "guarantee_number": gua_number, "acid_id": data.acid_id, "acid_number": acid.get("acid_number", ""),
        "guarantee_type": data.guarantee_type, "amount_lyd": data.amount_lyd, "beneficiary": data.beneficiary,
        "description": data.description, "expiry_date": data.expiry_date, "status": "active",
        "created_by": current_user["_id"], "created_by_name": current_user.get("name_ar", ""),
        "released_at": None, "release_reason": None,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    result = await db.guarantees.insert_one(doc)
    await db.acid_requests.update_one(
        {"_id": ObjectId(data.acid_id)},
        {"$set": {"has_guarantee": True, "guarantee_id": str(result.inserted_id),
                  "guarantee_number": gua_number, "updated_at": datetime.now(timezone.utc)}}
    )
    await log_audit(action="guarantee_created", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="guarantee",
                    resource_id=str(result.inserted_id), details={"guarantee_number": gua_number, "amount": data.amount_lyd})
    return format_doc({**doc, "_id": result.inserted_id})


@router.get("/guarantees")
async def list_guarantees(status: Optional[str] = None, current_user=Depends(require_roles(UserRole.TREASURY_OFFICER, UserRole.ADMIN))):
    query = {}
    if status:
        query["status"] = status
    items = await db.guarantees.find(query).sort("created_at", -1).to_list(200)
    return [format_doc(i) for i in items]


@router.put("/guarantees/{guarantee_id}/release")
async def release_guarantee(guarantee_id: str, data: GuaranteeReleaseInput,
                             current_user=Depends(require_roles(UserRole.TREASURY_OFFICER, UserRole.ADMIN))):
    g = await db.guarantees.find_one({"_id": ObjectId(guarantee_id)}) if ObjectId.is_valid(guarantee_id) else None
    if not g:
        raise HTTPException(404, "الضمان غير موجود")
    if g["status"] != "active":
        raise HTTPException(400, "الضمان ليس نشطاً")
    await db.guarantees.update_one(
        {"_id": ObjectId(guarantee_id)},
        {"$set": {"status": "released", "released_at": datetime.now(timezone.utc).isoformat(),
                  "release_reason": data.reason, "updated_at": datetime.now(timezone.utc)}}
    )
    return {"message": "تم الإفراج عن الضمان", "guarantee_number": g.get("guarantee_number")}


@router.get("/guarantees/stats")
async def guarantee_stats(current_user=Depends(require_roles(UserRole.TREASURY_OFFICER, UserRole.ADMIN))):
    return {
        "total": await db.guarantees.count_documents({}),
        "active": await db.guarantees.count_documents({"status": "active"}),
        "released": await db.guarantees.count_documents({"status": "released"}),
        "total_amount_lyd": (await db.guarantees.aggregate([
            {"$match": {"status": "active"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount_lyd"}}}
        ]).to_list(1) or [{"total": 0}])[0]["total"]
    }
