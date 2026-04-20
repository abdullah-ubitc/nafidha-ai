"""Violations management routes"""
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
from models import ViolationCreate, ViolationFineInput, UserRole
from database import db
from auth_utils import require_roles
from helpers import format_doc, log_audit, generate_violation_number
from constants import VIOLATION_TYPES
from ws_manager import ws_manager

router = APIRouter(prefix="/violations", tags=["violations"])


@router.post("")
async def create_violation(data: ViolationCreate,
                           current_user=Depends(require_roles(UserRole.VIOLATIONS_OFFICER, UserRole.INSPECTOR, UserRole.ADMIN))):
    acid = await db.acid_requests.find_one({"_id": ObjectId(data.acid_id)}) if ObjectId.is_valid(data.acid_id) else None
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    vio_number = await generate_violation_number()
    doc = {
        "violation_number": vio_number, "acid_id": data.acid_id, "acid_number": acid.get("acid_number", ""),
        "importer_name": acid.get("company_name_ar") or acid.get("importer_name_ar", ""),
        "violation_type": data.violation_type,
        "violation_type_ar": VIOLATION_TYPES.get(data.violation_type, data.violation_type),
        "description_ar": data.description_ar, "fine_amount_lyd": data.fine_amount_lyd or 0,
        "status": "open", "opened_by": current_user["_id"],
        "opened_by_name": current_user.get("name_ar", ""), "investigation_notes": [],
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    result = await db.violations.insert_one(doc)
    await db.acid_requests.update_one(
        {"_id": ObjectId(data.acid_id)},
        {"$set": {"has_violation": True, "violation_id": str(result.inserted_id),
                  "violation_number": vio_number, "updated_at": datetime.now(timezone.utc)}}
    )
    await log_audit(action="violation_opened", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="violation",
                    resource_id=str(result.inserted_id), details={"violation_number": vio_number, "type": data.violation_type})
    await ws_manager.broadcast_all({
        "type": "notification",
        "message_ar": f"تم فتح ملف مخالفة {vio_number} للشحنة {acid.get('acid_number', '')}",
        "acid_id": data.acid_id, "violation_number": vio_number
    })
    return format_doc({**doc, "_id": result.inserted_id})


@router.get("")
async def list_violations(status: Optional[str] = None,
                          current_user=Depends(require_roles(UserRole.VIOLATIONS_OFFICER, UserRole.INSPECTOR, UserRole.ADMIN))):
    query = {"status": status} if status else {}
    items = await db.violations.find(query).sort("created_at", -1).to_list(200)
    return [format_doc(i) for i in items]


@router.put("/{violation_id}/fine")
async def issue_fine(violation_id: str, data: ViolationFineInput,
                     current_user=Depends(require_roles(UserRole.VIOLATIONS_OFFICER, UserRole.ADMIN))):
    v = await db.violations.find_one({"_id": ObjectId(violation_id)}) if ObjectId.is_valid(violation_id) else None
    if not v:
        raise HTTPException(404, "ملف المخالفة غير موجود")
    await db.violations.update_one(
        {"_id": ObjectId(violation_id)},
        {"$set": {"status": "fined", "fine_amount_lyd": data.fine_amount_lyd,
                  "fine_reason": data.fine_reason, "fined_at": datetime.now(timezone.utc).isoformat(),
                  "fined_by": current_user["_id"], "updated_at": datetime.now(timezone.utc)},
         "$push": {"investigation_notes": {"note": f"غرامة مالية: {data.fine_amount_lyd} LYD — {data.fine_reason}",
                    "by": current_user.get("name_ar", ""), "at": datetime.now(timezone.utc).isoformat()}}}
    )
    return {"message": f"تم إصدار غرامة بقيمة {data.fine_amount_lyd} د.ل", "violation_number": v.get("violation_number")}


@router.put("/{violation_id}/close")
async def close_violation(violation_id: str, current_user=Depends(require_roles(UserRole.VIOLATIONS_OFFICER, UserRole.ADMIN))):
    await db.violations.update_one(
        {"_id": ObjectId(violation_id)},
        {"$set": {"status": "closed", "closed_at": datetime.now(timezone.utc).isoformat(),
                  "closed_by": current_user["_id"], "updated_at": datetime.now(timezone.utc)}}
    )
    return {"message": "تم إغلاق ملف المخالفة"}


@router.get("/stats")
async def violation_stats(current_user=Depends(require_roles(UserRole.VIOLATIONS_OFFICER, UserRole.INSPECTOR, UserRole.ADMIN))):
    total_fines = await db.violations.aggregate([
        {"$match": {"status": "fined"}}, {"$group": {"_id": None, "total": {"$sum": "$fine_amount_lyd"}}}
    ]).to_list(1)
    return {
        "total": await db.violations.count_documents({}),
        "open": await db.violations.count_documents({"status": "open"}),
        "under_investigation": await db.violations.count_documents({"status": "under_investigation"}),
        "fined": await db.violations.count_documents({"status": "fined"}),
        "closed": await db.violations.count_documents({"status": "closed"}),
        "total_fines_lyd": (total_fines[0]["total"] if total_fines else 0),
    }
