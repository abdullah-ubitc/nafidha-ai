"""
OCR Wallet Routes — محفظة OCR للمستخدمين
GET  /api/ocr-wallet/balance     — رصيد المستخدم الحالي
GET  /api/ocr-wallet/packages    — الباقات المتاحة
POST /api/ocr-wallet/topup       — شحن رصيد عبر شراء باقة
GET  /api/ocr-wallet/history     — سجل الشحن والاستهلاك
GET  /api/ocr-wallet/admin/all   — جميع المحافظ (admin)
"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional
from auth_utils import get_current_user, require_roles
from models import UserRole
from database import db

router = APIRouter(prefix="/ocr-wallet", tags=["ocr_wallet"])


# ── Helpers ────────────────────────────────────────────────────────────────────

async def get_or_create_wallet(user_id: str) -> dict:
    """جلب أو إنشاء محفظة OCR للمستخدم — آمن للتكرار."""
    wallet = await db.ocr_wallets.find_one({"user_id": user_id})
    if not wallet:
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "user_id": user_id,
            "balance_usd": 0.0,
            "total_topups_usd": 0.0,
            "total_spent_usd": 0.0,
            "created_at": now,
            "updated_at": now,
        }
        res = await db.ocr_wallets.insert_one(doc)
        doc["_id"] = str(res.inserted_id)
        return doc
    wallet["_id"] = str(wallet["_id"])
    return wallet


async def get_active_pricing() -> dict:
    """جلب إعدادات التسعير النشطة — fallback للقيم الافتراضية."""
    pricing = await db.system_pricing.find_one({"service_type": "ocr_scan"})
    if not pricing:
        return {
            "price_per_unit_usd": 0.05,
            "min_balance_usd": 0.05,
            "packages": [
                {"id": "starter",  "name_ar": "الباقة الأساسية",  "scans": 20,  "price_usd": 1.00},
                {"id": "standard", "name_ar": "الباقة القياسية",  "scans": 100, "price_usd": 4.00},
                {"id": "pro",      "name_ar": "الباقة الاحترافية","scans": 500, "price_usd": 15.00},
            ],
        }
    pricing.pop("_id", None)
    return pricing


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/payment-history")
async def payment_history(current_user=Depends(get_current_user)):
    """سجل مدفوعات OCR عبر Stripe — فواتير ورقم الجلسة."""
    user_id = str(current_user["_id"])
    txs = await db.payment_transactions.find(
        {"user_id": user_id, "payment_type": "ocr_wallet_topup"}
    ).sort("created_at", -1).to_list(50)

    result = []
    for tx in txs:
        tx.pop("_id", None)
        result.append({
            "session_id":     tx.get("session_id", ""),
            "package_name":   tx.get("package_name", ""),
            "package_id":     tx.get("package_id", ""),
            "scans_added":    tx.get("scans_added", 0),
            "amount_usd":     tx.get("amount_usd", 0.0),
            "status":         tx.get("payment_status", "pending"),
            "created_at":     tx.get("created_at", ""),
            "updated_at":     tx.get("updated_at", ""),
        })
    return result


@router.get("/balance")
async def get_ocr_balance(current_user=Depends(get_current_user)):
    """رصيد محفظة OCR للمستخدم الحالي."""
    user_id  = str(current_user["_id"])
    wallet   = await get_or_create_wallet(user_id)
    pricing  = await get_active_pricing()
    price_pu = pricing["price_per_unit_usd"]
    remaining_scans = int(wallet["balance_usd"] / price_pu) if price_pu > 0 else 0
    return {
        "balance_usd":       wallet["balance_usd"],
        "remaining_scans":   remaining_scans,
        "price_per_scan_usd": price_pu,
        "total_topups_usd":  wallet["total_topups_usd"],
        "total_spent_usd":   wallet["total_spent_usd"],
        "low_balance":       wallet["balance_usd"] < pricing.get("min_balance_usd", 0.05),
    }


@router.get("/packages")
async def list_packages(current_user=Depends(get_current_user)):
    """الباقات المتاحة للشراء."""
    pricing = await get_active_pricing()
    return {
        "price_per_scan_usd": pricing["price_per_unit_usd"],
        "packages":           pricing.get("packages", []),
    }


class TopUpInput(BaseModel):
    package_id: str


@router.post("/topup")
async def topup_wallet(body: TopUpInput, current_user=Depends(get_current_user)):
    """شحن رصيد OCR عبر شراء باقة."""
    pricing  = await get_active_pricing()
    packages = pricing.get("packages", [])
    pkg      = next((p for p in packages if p["id"] == body.package_id), None)
    if not pkg:
        raise HTTPException(400, "الباقة غير موجودة — تأكد من معرّف الباقة")

    user_id  = str(current_user["_id"])
    wallet   = await get_or_create_wallet(user_id)
    balance_before = wallet["balance_usd"]

    # حساب القيمة المضافة: استخدام price_usd الباقة أو scans × price_per_unit
    amount_usd = pkg.get("price_usd") or (pkg["scans"] * pricing["price_per_unit_usd"])
    scans_added = pkg["scans"]
    now = datetime.now(timezone.utc).isoformat()

    # تحديث ذرّي
    updated = await db.ocr_wallets.find_one_and_update(
        {"user_id": user_id},
        {
            "$inc": {"balance_usd": amount_usd, "total_topups_usd": amount_usd},
            "$set": {"updated_at": now},
        },
        return_document=True,
        upsert=True,
    )
    new_balance = updated["balance_usd"] if updated else balance_before + amount_usd

    # تسجيل المعاملة
    await db.ocr_topup_transactions.insert_one({
        "user_id":        user_id,
        "user_name":      current_user.get("name_ar", ""),
        "package_id":     pkg["id"],
        "package_name_ar":pkg["name_ar"],
        "scans_added":    scans_added,
        "amount_usd":     amount_usd,
        "balance_before": balance_before,
        "balance_after":  new_balance,
        "created_at":     now,
    })

    price_pu = pricing["price_per_unit_usd"]
    return {
        "message":          f"تم شحن الرصيد بنجاح — {scans_added} مسحة مضافة",
        "package":          pkg,
        "amount_usd":       amount_usd,
        "balance_before":   balance_before,
        "balance_after":    new_balance,
        "scans_available":  int(new_balance / price_pu) if price_pu > 0 else 0,
    }


@router.get("/history")
async def wallet_history(current_user=Depends(get_current_user)):
    """سجل الشحن والاستهلاك للمستخدم."""
    user_id = str(current_user["_id"])

    topups = await db.ocr_topup_transactions.find({"user_id": user_id}).sort("created_at", -1).to_list(50)
    for t in topups:
        t.pop("_id", None)
        t["type"] = "topup"

    usage = await db.api_usage_logs.find({"user_id": user_id}).sort("timestamp", -1).to_list(100)
    for u in usage:
        u.pop("_id", None)
        u["type"] = "usage"
        if hasattr(u.get("timestamp"), "isoformat"):
            u["timestamp"] = u["timestamp"].isoformat()

    wallet = await get_or_create_wallet(user_id)
    pricing = await get_active_pricing()
    price_pu = pricing["price_per_unit_usd"]
    wallet.pop("_id", None)

    return {
        "wallet":  {**wallet, "remaining_scans": int(wallet["balance_usd"] / price_pu) if price_pu > 0 else 0},
        "topups":  topups,
        "usage":   usage,
    }


@router.get("/admin/all")
async def admin_all_wallets(current_user=Depends(require_roles(UserRole.ADMIN))):
    """جميع محافظ المستخدمين — للإدارة."""
    wallets = await db.ocr_wallets.find({}).sort("total_spent_usd", -1).to_list(200)
    result  = []
    for w in wallets:
        w.pop("_id", None)
        try:
            user = await db.users.find_one(
                {"_id": ObjectId(w["user_id"])},
                {"name_ar": 1, "email": 1, "role": 1}
            )
            if user:
                w["user_name_ar"] = user.get("name_ar", "")
                w["user_email"]   = user.get("email", "")
                w["user_role"]    = user.get("role", "")
        except Exception:
            pass
        result.append(w)
    return result
