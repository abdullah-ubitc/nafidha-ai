"""
Service Pricing Routes — إدارة أسعار الخدمات الذكية
GET    /api/service-pricing             — جلب الإعدادات الحالية
PUT    /api/service-pricing             — تحديث سعر المسحة (admin)
PUT    /api/service-pricing/packages    — تحديث قائمة الباقات (admin)
GET    /api/service-pricing/stats       — إحصائيات الاستهلاك الكلية (admin)
"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import List, Optional
from auth_utils import get_current_user, require_roles
from models import UserRole
from database import db

router = APIRouter(prefix="/service-pricing", tags=["service_pricing"])

_DEFAULT_PACKAGES = [
    {"id": "starter",  "name_ar": "الباقة الأساسية",   "scans": 20,  "price_usd": 1.00},
    {"id": "standard", "name_ar": "الباقة القياسية",   "scans": 100, "price_usd": 4.00},
    {"id": "pro",      "name_ar": "الباقة الاحترافية", "scans": 500, "price_usd": 15.00},
]


async def _get_or_create_pricing() -> dict:
    pricing = await db.system_pricing.find_one({"service_type": "ocr_scan"})
    if not pricing:
        doc = {
            "service_type":     "ocr_scan",
            "service_name_ar":  "مسح OCR الذكي",
            "price_per_unit_usd": 0.05,
            "min_balance_usd":  0.05,
            "packages":         _DEFAULT_PACKAGES,
            "created_at":       datetime.now(timezone.utc).isoformat(),
        }
        res = await db.system_pricing.insert_one(doc)
        doc["_id"] = str(res.inserted_id)
        return doc
    pricing["_id"] = str(pricing["_id"])
    return pricing


# ── GET current pricing ────────────────────────────────────────────────────────

@router.get("")
async def get_pricing(current_user=Depends(get_current_user)):
    """جلب إعدادات التسعير الحالية — متاح لجميع المستخدمين."""
    return await _get_or_create_pricing()


# ── PUT update price per unit ──────────────────────────────────────────────────

class PriceUpdateInput(BaseModel):
    price_per_unit_usd: float
    min_balance_usd:    Optional[float] = 0.05


@router.put("")
async def update_price(body: PriceUpdateInput, current_user=Depends(require_roles(UserRole.ADMIN))):
    """تحديث سعر المسحة الواحدة."""
    if body.price_per_unit_usd <= 0:
        raise HTTPException(400, "السعر يجب أن يكون أكبر من صفر")
    now = datetime.now(timezone.utc).isoformat()
    await db.system_pricing.update_one(
        {"service_type": "ocr_scan"},
        {"$set": {
            "price_per_unit_usd": body.price_per_unit_usd,
            "min_balance_usd":    body.min_balance_usd,
            "updated_at":         now,
            "updated_by":         str(current_user["_id"]),
            "updated_by_name":    current_user.get("name_ar", ""),
        }},
        upsert=True,
    )
    return {"message": "تم تحديث سعر المسحة بنجاح", "price_per_unit_usd": body.price_per_unit_usd}


# ── PUT update packages ────────────────────────────────────────────────────────

class PackageItem(BaseModel):
    id:       str
    name_ar:  str
    scans:    int
    price_usd: float


class PackagesInput(BaseModel):
    packages: List[PackageItem]


@router.put("/packages")
async def update_packages(body: PackagesInput, current_user=Depends(require_roles(UserRole.ADMIN))):
    """تحديث قائمة الباقات."""
    if not body.packages:
        raise HTTPException(400, "يجب تعريف باقة واحدة على الأقل")
    pkgs = [p.dict() for p in body.packages]
    now  = datetime.now(timezone.utc).isoformat()
    await db.system_pricing.update_one(
        {"service_type": "ocr_scan"},
        {"$set": {
            "packages":    pkgs,
            "updated_at":  now,
            "updated_by":  str(current_user["_id"]),
        }},
        upsert=True,
    )
    return {"message": "تم تحديث الباقات بنجاح", "packages": pkgs}


# ── GET stats ──────────────────────────────────────────────────────────────────

@router.get("/stats")
async def pricing_stats(current_user=Depends(require_roles(UserRole.ADMIN))):
    """إحصائيات الاستهلاك الكلية للإدارة."""
    # إجمالي المسوحات والتكلفة
    total_agg = await db.api_usage_logs.aggregate([
        {"$group": {"_id": None, "cost": {"$sum": "$cost_usd"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    total_cost  = total_agg[0]["cost"]  if total_agg else 0.0
    total_scans = total_agg[0]["count"] if total_agg else 0

    # حسب نوع الخدمة
    by_type = await db.api_usage_logs.aggregate([
        {"$group": {"_id": "$service_type", "count": {"$sum": 1}, "cost": {"$sum": "$cost_usd"}}}
    ]).to_list(20)

    # أكثر المستخدمين استهلاكاً
    top_raw = await db.api_usage_logs.aggregate([
        {"$group": {"_id": "$user_id", "scans": {"$sum": 1}, "cost": {"$sum": "$cost_usd"}}},
        {"$sort": {"cost": -1}},
        {"$limit": 10},
    ]).to_list(10)
    top_users = []
    for r in top_raw:
        user_doc = None
        try:
            user_doc = await db.users.find_one(
                {"_id": ObjectId(r["_id"])}, {"name_ar": 1, "email": 1}
            )
        except Exception:
            pass
        top_users.append({
            "user_id":       r["_id"],
            "user_name":     user_doc.get("name_ar", "—") if user_doc else "—",
            "user_email":    user_doc.get("email", "—")   if user_doc else "—",
            "total_scans":   r["scans"],
            "total_cost_usd":r["cost"],
        })

    # إجمالي الشحن
    topup_agg = await db.ocr_topup_transactions.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$amount_usd"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    total_topups  = topup_agg[0]["total"] if topup_agg else 0.0
    topup_count   = topup_agg[0]["count"] if topup_agg else 0

    active_wallets = await db.ocr_wallets.count_documents({"balance_usd": {"$gt": 0}})

    # آخر 7 أيام — يومياً
    from datetime import timedelta
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    daily_pipeline = [
        {"$match": {"timestamp": {"$gte": seven_days_ago}}},
        {"$group": {
            "_id":   {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
            "scans": {"$sum": 1},
            "cost":  {"$sum": "$cost_usd"},
        }},
        {"$sort": {"_id": 1}},
    ]
    daily_data = await db.api_usage_logs.aggregate(daily_pipeline).to_list(7)

    return {
        "total_scans":      total_scans,
        "total_cost_usd":   total_cost,
        "total_topups_usd": total_topups,
        "topup_count":      topup_count,
        "active_wallets":   active_wallets,
        "by_service_type":  [{"type": r["_id"], "count": r["count"], "cost": r["cost"]} for r in by_type],
        "top_consumers":    top_users,
        "daily_last_7":     daily_data,
    }
