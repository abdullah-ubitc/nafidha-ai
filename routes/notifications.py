"""Notification CRUD endpoints — Phase L
GET  /notifications              — قائمة الإشعارات (آخر 50)
GET  /notifications/unread-count — عدد غير المقروءة (للـ badge)
PUT  /notifications/{id}/read    — تعليم مقروء
PUT  /notifications/read-all     — تعليم الكل مقروء
"""
from bson import ObjectId
from fastapi import APIRouter, Depends
from database import db
from auth_utils import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _fmt(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("")
async def list_notifications(current_user=Depends(get_current_user)):
    """آخر 50 إشعاراً للمستخدم الحالي."""
    docs = await db.notifications.find(
        {"user_id": current_user["_id"]}
    ).sort("created_at", -1).limit(50).to_list(50)
    return [_fmt(d) for d in docs]


@router.get("/unread-count")
async def unread_count(current_user=Depends(get_current_user)):
    count = await db.notifications.count_documents(
        {"user_id": current_user["_id"], "is_read": False}
    )
    return {"count": count}


@router.put("/{notif_id}/read")
async def mark_read(notif_id: str, current_user=Depends(get_current_user)):
    try:
        await db.notifications.update_one(
            {"_id": ObjectId(notif_id), "user_id": current_user["_id"]},
            {"$set": {"is_read": True}}
        )
    except Exception:
        pass
    return {"ok": True}


@router.put("/read-all")
async def mark_all_read(current_user=Depends(get_current_user)):
    await db.notifications.update_many(
        {"user_id": current_user["_id"], "is_read": False},
        {"$set": {"is_read": True}}
    )
    return {"ok": True}
