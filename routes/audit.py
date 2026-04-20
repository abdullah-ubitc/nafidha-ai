"""Audit trail routes"""
from fastapi import APIRouter, Depends
from datetime import datetime
from models import UserRole
from database import db
from auth_utils import require_roles

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs")
async def get_audit_logs(
    page: int = 1, limit: int = 50,
    current_user=Depends(require_roles(UserRole.ADMIN, UserRole.ACID_REVIEWER))
):
    skip = (page - 1) * limit
    logs = await db.audit_logs.find({}).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.audit_logs.count_documents({})
    result = []
    for log in logs:
        log["_id"] = str(log["_id"])
        if isinstance(log.get("timestamp"), datetime):
            log["timestamp"] = log["timestamp"].isoformat()
        result.append(log)
    return {"logs": result, "total": total, "page": page, "pages": (total + limit - 1) // limit}
