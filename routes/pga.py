"""PGA (Partner Government Agencies) portal routes"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from bson import ObjectId
from datetime import datetime, timezone
from models import PGAReviewInput, UserRole
from database import db
from auth_utils import get_current_user, require_roles
from helpers import format_doc, log_audit
from ws_manager import ws_manager

router = APIRouter(prefix="/pga", tags=["pga"])


@router.get("/queue")
async def pga_queue(current_user=Depends(require_roles(UserRole.PGA_OFFICER, UserRole.INSPECTOR, UserRole.ADMIN))):
    items = await db.acid_requests.find(
        {"status": "approved", "pga_required": {"$ne": False}}
    ).sort("updated_at", -1).to_list(200)
    return [format_doc(i) for i in items]


@router.post("/{acid_id}/review")
async def pga_review(acid_id: str, data: PGAReviewInput, background_tasks: BackgroundTasks,
                     current_user=Depends(require_roles(UserRole.PGA_OFFICER, UserRole.INSPECTOR, UserRole.ADMIN))):
    if data.action not in ["approve", "reject", "guarantee"]:
        raise HTTPException(400, "الإجراء يجب أن يكون approve أو reject أو guarantee")
    acid = await db.acid_requests.find_one({"_id": ObjectId(acid_id)}) if ObjectId.is_valid(acid_id) else None
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    pga_status_map = {"approve": "approved", "reject": "rejected", "guarantee": "guarantee_required"}
    pga_status = pga_status_map.get(data.action, data.action)
    pga_entry = {
        "pga_officer_id": current_user["_id"], "pga_officer_name": current_user.get("name_ar", ""),
        "agency_name": data.agency_name, "action": pga_status, "notes": data.notes,
        "reference_number": data.reference_number,
        # Phase E fields
        "risk_channel": data.risk_channel.value if data.risk_channel else None,
        "pga_decision": data.pga_decision.value if data.pga_decision else pga_status,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    update_set = {
        "pga_status": pga_status, "pga_agency": data.agency_name, "pga_notes": data.notes,
        "pga_reviewed_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc),
    }
    if data.risk_channel:
        update_set["risk_channel"] = data.risk_channel.value
    await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {"$set": update_set, "$push": {"pga_history": pga_entry,
                                       "timeline": {"event": f"pga_{pga_status}",
                                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                                    "actor": current_user.get("name_ar", ""),
                                                    "agency": data.agency_name}}}
    )
    await db.pga_approvals.insert_one({**pga_entry, "acid_id": acid_id,
                                        "acid_number": acid.get("acid_number", ""),
                                        "created_at": datetime.now(timezone.utc)})
    await log_audit(action=f"pga_{data.action}", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="acid_request",
                    resource_id=acid_id, details={"agency": data.agency_name, "notes": data.notes})
    background_tasks.add_task(ws_manager.broadcast_all, {
        "type": "notification",
        "message_ar": f"الجهة الرقابية {data.agency_name} أصدرت قرار {'موافقة' if data.action == 'approve' else ('ضمان' if data.action == 'guarantee' else 'رفض')} للشحنة {acid.get('acid_number', '')}",
        "acid_id": acid_id, "pga_status": pga_status
    })
    return {"message": f"تم تسجيل قرار الجهة الرقابية: {pga_status}", "pga_status": pga_status}


@router.get("/history/{acid_id}")
async def pga_history(acid_id: str, current_user=Depends(get_current_user)):
    items = await db.pga_approvals.find({"acid_id": acid_id}).sort("created_at", -1).to_list(20)
    return [format_doc(i) for i in items]


@router.get("/stats")
async def pga_stats(current_user=Depends(require_roles(UserRole.PGA_OFFICER, UserRole.INSPECTOR, UserRole.ADMIN))):
    return {
        "total_queue": await db.acid_requests.count_documents({"status": "approved"}),
        "approved": await db.pga_approvals.count_documents({"action": "approved"}),
        "rejected": await db.pga_approvals.count_documents({"action": "rejected"}),
        "pending": await db.acid_requests.count_documents({"status": "approved", "pga_status": {"$exists": False}}),
    }
