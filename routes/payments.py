"""
Stripe Payment Routes — نظام المدفوعات
POST /payments/checkout/verification  — رسوم توثيق المصدر ($100/سنة)
POST /payments/checkout/acid-fee      — رسوم طلب ACID (قابلة للضبط من الأدمن)
POST /payments/checkout/ocr-wallet    — شحن محفظة OCR عبر Stripe (الباقات الذكية)
GET  /payments/status/{session_id}    — استعلام حالة الدفع + تفعيل الحساب
GET  /payments/admin/config           — جلب إعدادات الرسوم
POST /payments/admin/config           — تحديث رسوم ACID (أدمن فقط)
GET  /payments/history                — سجل مدفوعات المستخدم الحالي
POST /api/webhook/stripe              — Stripe Webhook
"""
import os
from fastapi import APIRouter, HTTPException, Depends, Request
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from typing import Optional

from database import db
from auth_utils import get_current_user, require_roles, hash_password
from models import UserRole, VerificationCheckoutRequest, AcidFeeCheckoutRequest, AdminAcidFeeUpdate
from services.email_service import send_event_email
from emergentintegrations.payments.stripe.checkout import (
    StripeCheckout, CheckoutSessionRequest
)
from pydantic import BaseModel

router = APIRouter(prefix="/payments", tags=["payments"])

VERIFICATION_FEE_USD: float = 100.0
DEFAULT_ACID_FEE_USD: float = 50.0


# ── Helpers ────────────────────────────────────────────────────────────────────

def _stripe(request: Request) -> StripeCheckout:
    api_key = os.environ.get("STRIPE_API_KEY", "")
    if not api_key:
        raise HTTPException(500, "Stripe API key not configured")
    host_url = str(request.base_url).rstrip("/")
    webhook_url = f"{host_url}/api/webhook/stripe"
    return StripeCheckout(api_key=api_key, webhook_url=webhook_url)


async def _acid_fee() -> float:
    cfg = await db.admin_config.find_one({"key": "acid_fee_usd"})
    return float(cfg.get("value", DEFAULT_ACID_FEE_USD)) if cfg else DEFAULT_ACID_FEE_USD


def _tx_dict(tx: dict) -> dict:
    d = {k: v for k, v in tx.items() if k != "_id"}
    return d


# ── POST /payments/checkout/verification ──────────────────────────────────────

@router.post("/checkout/verification")
async def create_verification_checkout(
    body: VerificationCheckoutRequest,
    request: Request,
):
    """إنشاء جلسة Stripe Checkout لرسوم توثيق المصدر ($100/سنة) — لا يتطلب تسجيل دخول"""
    exporter = await db.global_exporters.find_one({"tax_id": body.exporter_tax_id})
    if not exporter:
        raise HTTPException(404, "المصدر غير موجود في السجل")

    # منع الدفع المتكرر للسنة الحالية
    already_paid = await db.payment_transactions.find_one({
        "exporter_tax_id": body.exporter_tax_id,
        "payment_type":    "verification",
        "payment_status":  "paid",
    })
    if already_paid:
        raise HTTPException(409, "تم دفع رسوم التوثيق مسبقاً — حسابك نشط")

    sc = _stripe(request)
    origin = body.origin_url.rstrip("/")
    session = await sc.create_checkout_session(CheckoutSessionRequest(
        amount=float(VERIFICATION_FEE_USD),
        currency="usd",
        success_url=f"{origin}/register/exporter/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{origin}/register/exporter",
        metadata={
            "payment_type":     "verification",
            "exporter_tax_id":  body.exporter_tax_id,
        },
    ))

    now = datetime.now(timezone.utc).isoformat()
    await db.payment_transactions.insert_one({
        "session_id":       session.session_id,
        "payment_type":     "verification",
        "amount_usd":       float(VERIFICATION_FEE_USD),
        "currency":         "usd",
        "exporter_tax_id":  body.exporter_tax_id,
        "acid_id":          None,
        "user_id":          None,
        "status":           "pending",
        "payment_status":   "unpaid",
        "metadata":         {"payment_type": "verification", "exporter_tax_id": body.exporter_tax_id},
        "created_at":       now,
        "updated_at":       now,
    })

    return {"checkout_url": session.url, "session_id": session.session_id}


# ── POST /payments/checkout/acid-fee ──────────────────────────────────────────

@router.post("/checkout/acid-fee")
async def create_acid_fee_checkout(
    body: AcidFeeCheckoutRequest,
    request: Request,
    current_user=Depends(get_current_user),
):
    """إنشاء جلسة Stripe Checkout لرسوم طلب ACID"""
    if not ObjectId.is_valid(body.acid_id):
        raise HTTPException(400, "معرّف ACID غير صالح")
    acid = await db.acid_requests.find_one({"_id": ObjectId(body.acid_id)})
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    if acid.get("acid_fee_paid"):
        raise HTTPException(409, "رسوم ACID مدفوعة مسبقاً")

    fee = await _acid_fee()
    sc = _stripe(request)
    origin = body.origin_url.rstrip("/")
    acid_num = acid.get("acid_number", body.acid_id)

    session = await sc.create_checkout_session(CheckoutSessionRequest(
        amount=float(fee),
        currency="usd",
        success_url=f"{origin}/dashboard/acid/{body.acid_id}?session_id={{CHECKOUT_SESSION_ID}}&payment=acid_fee",
        cancel_url=f"{origin}/dashboard/acid/{body.acid_id}",
        metadata={
            "payment_type": "acid_fee",
            "acid_id":      body.acid_id,
            "acid_number":  acid_num,
            "user_id":      current_user.get("_id", ""),
        },
    ))

    now = datetime.now(timezone.utc).isoformat()
    await db.payment_transactions.insert_one({
        "session_id":      session.session_id,
        "payment_type":    "acid_fee",
        "amount_usd":      float(fee),
        "currency":        "usd",
        "exporter_tax_id": None,
        "acid_id":         body.acid_id,
        "acid_number":     acid_num,
        "user_id":         current_user.get("_id"),
        "status":          "pending",
        "payment_status":  "unpaid",
        "metadata": {
            "payment_type": "acid_fee",
            "acid_id":      body.acid_id,
            "acid_number":  acid_num,
        },
        "created_at": now,
        "updated_at": now,
    })

    return {"checkout_url": session.url, "session_id": session.session_id, "fee_usd": fee}


# ── POST /payments/checkout/ocr-wallet ────────────────────────────────────────

class OcrWalletCheckoutRequest(BaseModel):
    package_id:  str
    origin_url:  str  # رابط الأصل لبناء success/cancel URLs


@router.post("/checkout/ocr-wallet")
async def create_ocr_wallet_checkout(
    body: OcrWalletCheckoutRequest,
    request: Request,
    current_user=Depends(get_current_user),
):
    """إنشاء جلسة Stripe Checkout لشحن محفظة OCR — الدفع أولاً ثم الشحن"""
    # جلب إعدادات التسعير
    pricing = await db.system_pricing.find_one({"service_type": "ocr_scan"})
    if not pricing:
        raise HTTPException(503, "إعدادات التسعير غير موجودة — تواصل مع المدير")

    packages = pricing.get("packages", [])
    pkg = next((p for p in packages if p["id"] == body.package_id), None)
    if not pkg:
        raise HTTPException(400, f"الباقة '{body.package_id}' غير موجودة")

    amount_usd = pkg.get("price_usd") or (pkg["scans"] * pricing.get("price_per_unit_usd", 0.05))
    user_id    = str(current_user["_id"])
    user_name  = current_user.get("name_ar", "")

    sc = _stripe(request)
    origin = body.origin_url.rstrip("/")

    session = await sc.create_checkout_session(CheckoutSessionRequest(
        amount=float(amount_usd),
        currency="usd",
        success_url=f"{origin}/dashboard/ocr-wallet?session_id={{CHECKOUT_SESSION_ID}}&payment=ocr_wallet_topup",
        cancel_url=f"{origin}/dashboard/ocr-wallet",
        metadata={
            "payment_type": "ocr_wallet_topup",
            "package_id":   body.package_id,
            "package_name": pkg["name_ar"],
            "scans_added":  str(pkg["scans"]),
            "user_id":      user_id,
            "user_name":    user_name,
        },
    ))

    now = datetime.now(timezone.utc).isoformat()
    await db.payment_transactions.insert_one({
        "session_id":     session.session_id,
        "payment_type":   "ocr_wallet_topup",
        "amount_usd":     float(amount_usd),
        "currency":       "usd",
        "user_id":        user_id,
        "user_name":      user_name,
        "package_id":     body.package_id,
        "package_name":   pkg["name_ar"],
        "scans_added":    pkg["scans"],
        "status":         "pending",
        "payment_status": "unpaid",
        "metadata": {
            "payment_type": "ocr_wallet_topup",
            "package_id":   body.package_id,
            "user_id":      user_id,
        },
        "created_at": now,
        "updated_at": now,
    })

    return {
        "checkout_url": session.url,
        "session_id":   session.session_id,
        "package":      pkg,
        "amount_usd":   amount_usd,
    }


# ── GET /payments/status/{session_id} ─────────────────────────────────────────

@router.get("/status/{session_id}")
async def check_payment_status(session_id: str, request: Request):
    """استعلام حالة الدفع — يُفعِّل الحساب تلقائياً عند نجاح الدفع"""
    tx = await db.payment_transactions.find_one({"session_id": session_id})
    if not tx:
        raise HTTPException(404, "جلسة الدفع غير موجودة")

    # إذا تمت المعالجة مسبقاً
    if tx.get("payment_status") == "paid":
        result = {
            "status":         "complete",
            "payment_status": "paid",
            "payment_type":   tx.get("payment_type"),
        }
        if tx.get("payment_type") == "verification":
            result["exporter_tax_id"] = tx.get("exporter_tax_id")
            exporter = await db.global_exporters.find_one(
                {"tax_id": tx.get("exporter_tax_id")}, {"_id": 0}
            )
            if exporter:
                result["login_email"] = exporter.get("email", "")
        elif tx.get("payment_type") == "ocr_wallet_topup":
            result["package_id"]   = tx.get("package_id")
            result["scans_added"]  = tx.get("scans_added")
            result["amount_usd"]   = tx.get("amount_usd")
        return result

    # استعلام Stripe
    sc = _stripe(request)
    try:
        stripe_status = await sc.get_checkout_status(session_id)
    except Exception:
        return {"status": "pending", "payment_status": "unpaid"}

    if stripe_status.payment_status == "paid":
        now = datetime.now(timezone.utc).isoformat()
        # تحديث سجل الدفع
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"status": "complete", "payment_status": "paid", "updated_at": now}}
        )
        # تنفيذ إجراءات ما بعد الدفع
        result = {"status": "complete", "payment_status": "paid", "payment_type": tx.get("payment_type")}
        if tx.get("payment_type") == "verification":
            login_email = await _activate_exporter(tx, now)
            result["exporter_tax_id"] = tx.get("exporter_tax_id")
            result["login_email"] = login_email
        elif tx.get("payment_type") == "acid_fee":
            await _activate_acid_fee(tx, now)
        elif tx.get("payment_type") == "ocr_wallet_topup":
            await _activate_ocr_wallet_topup(tx, now)
        return result

    return {
        "status":         stripe_status.status,
        "payment_status": stripe_status.payment_status,
        "payment_type":   tx.get("payment_type"),
    }


async def _activate_exporter(tx: dict, now: str) -> str:
    """تفعيل حساب المصدر وإنشاء مستخدم النظام بعد الدفع"""
    tax_id = tx.get("exporter_tax_id")
    if not tax_id:
        return ""

    # تحديث global_exporters
    expiry = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    await db.global_exporters.update_one(
        {"tax_id": tax_id},
        {"$set": {
            "account_status":               "approved",
            "is_verified":                  True,
            "verified_at":                  now,
            "verification_fee_paid_at":     now,
            "verification_fee_expires_at":  expiry,
            "updated_at":                   now,
        }}
    )

    exporter = await db.global_exporters.find_one({"tax_id": tax_id})
    if not exporter:
        return ""

    email = exporter.get("email", "")

    # إنشاء حساب users إذا لم يوجد
    existing_user = await db.users.find_one({"email": email})
    if not existing_user and exporter.get("_password_hash"):
        user_doc = {
            "email":               email,
            "password_hash":       exporter["_password_hash"],
            "role":                "foreign_supplier",
            "name_ar":             exporter.get("company_name", ""),
            "name_en":             exporter.get("company_name", ""),
            "company_name_ar":     exporter.get("company_name", ""),
            "phone":               exporter.get("phone", ""),
            "tax_id_tin":          tax_id,
            "registration_status": "approved",
            "account_status":      "active",
            "is_email_verified":   True,
            "is_active":           True,
            "is_verified":         True,
            "exporter_type":       exporter.get("exporter_type", "global"),
            "created_at":          now,
            "updated_at":          now,
        }
        result = await db.users.insert_one(user_doc)
        await db.global_exporters.update_one(
            {"tax_id": tax_id},
            {"$set": {"user_id": str(result.inserted_id)}}
        )
    elif existing_user:
        await db.users.update_one(
            {"email": email},
            {"$set": {"registration_status": "approved", "is_verified": True, "updated_at": now}}
        )

    # ── إرسال إيميل تأكيد التوثيق للمصدر ─────────────────────────────
    if email:
        expiry = (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%d")
        exporter_rec = await db.global_exporters.find_one({"tax_id": tax_id}, {"_id": 0})
        company_name = exporter_rec.get("company_name", "") if exporter_rec else ""
        import asyncio
        asyncio.ensure_future(send_event_email(
            "exporter_verified", email,
            {
                "company_name": company_name,
                "tax_id":       tax_id,
                "email":        email,
                "expires_at":   expiry,
            }
        ))
    return email


async def _activate_ocr_wallet_topup(tx: dict, now: str):
    """شحن محفظة OCR بعد تأكيد دفع Stripe."""
    user_id    = tx.get("user_id")
    amount_usd = float(tx.get("amount_usd", 0))
    scans      = int(tx.get("scans_added", 0))
    pkg_name   = tx.get("package_name", "")
    pkg_id     = tx.get("package_id", "")
    if not user_id or amount_usd <= 0:
        return
    result = await db.ocr_wallets.find_one_and_update(
        {"user_id": user_id},
        {"$inc": {"balance_usd": amount_usd, "total_topups_usd": amount_usd}, "$set": {"updated_at": now}},
        return_document=True,
        upsert=True,
    )
    new_balance = result["balance_usd"] if result else amount_usd
    await db.ocr_topup_transactions.insert_one({
        "user_id": user_id, "user_name": tx.get("user_name", ""),
        "package_id": pkg_id, "package_name_ar": pkg_name,
        "scans_added": scans, "amount_usd": amount_usd,
        "balance_before": new_balance - amount_usd, "balance_after": new_balance,
        "payment_session": tx.get("session_id"), "created_at": now,
    })
    # SMS إشعار بالشحن (يعمل عند توفر Twilio credentials)
    try:
        from services.notification_service import _send_twilio_sms
        import asyncio as _asyncio
        user = await db.users.find_one({"_id": ObjectId(user_id)}, {"phone": 1})
        if user and user.get("phone"):
            msg = f"تم شحن محفظة OCR بـ {scans} مسحة ({pkg_name}). رصيدك: ${new_balance:.2f} — نافذة الجمارك الليبية"
            _asyncio.ensure_future(_send_twilio_sms(user["phone"], msg))
    except Exception:
        pass


async def _activate_acid_fee(tx: dict, now: str):
    """تأشير طلب ACID كمدفوع الرسوم"""
    acid_id = tx.get("acid_id")
    if not acid_id or not ObjectId.is_valid(acid_id):
        return
    await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {"$set": {
            "acid_fee_paid":         True,
            "acid_fee_paid_at":      now,
            "acid_fee_amount_usd":   tx.get("amount_usd", DEFAULT_ACID_FEE_USD),
        }}
    )


# ── Admin Config ──────────────────────────────────────────────────────────────

@router.get("/admin/config")
async def get_payment_config(current_user=Depends(require_roles(UserRole.ADMIN))):
    """جلب إعدادات الرسوم الحالية"""
    fee = await _acid_fee()
    return {
        "acid_fee_usd":         fee,
        "verification_fee_usd": VERIFICATION_FEE_USD,
    }


@router.post("/admin/config")
async def update_payment_config(
    body: AdminAcidFeeUpdate,
    current_user=Depends(require_roles(UserRole.ADMIN)),
):
    """تحديث رسوم ACID (أدمن فقط)"""
    if body.amount_usd <= 0:
        raise HTTPException(400, "المبلغ يجب أن يكون أكبر من صفر")
    now = datetime.now(timezone.utc).isoformat()
    await db.admin_config.update_one(
        {"key": "acid_fee_usd"},
        {"$set": {"key": "acid_fee_usd", "value": body.amount_usd, "updated_at": now, "updated_by": current_user.get("_id")}},
        upsert=True,
    )
    return {"message": f"تم تحديث رسوم ACID إلى ${body.amount_usd:.2f}", "amount_usd": body.amount_usd}


# ── Payment History ────────────────────────────────────────────────────────────

@router.get("/history")
async def payment_history(current_user=Depends(get_current_user)):
    """سجل مدفوعات المستخدم الحالي"""
    role = current_user["role"]
    if role in ("admin", "treasury_officer"):
        txs = await db.payment_transactions.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    else:
        tax_id = current_user.get("tax_id_tin", "")
        query = {"$or": [
            {"user_id": current_user.get("_id")},
            {"exporter_tax_id": tax_id} if tax_id else {"_id": None},
        ]}
        txs = await db.payment_transactions.find(query, {"_id": 0}).sort("created_at", -1).to_list(100)
    return txs


# ── Payment Revenue Stats (Admin) ─────────────────────────────────────────────

@router.get("/stats")
async def payment_stats(current_user=Depends(require_roles(UserRole.ADMIN))):
    """إحصاءات إيرادات المدفوعات للمدير"""
    # ─ إجمالي الإيرادات
    summary_pipeline = [
        {"$match": {"payment_status": "paid"}},
        {"$group": {
            "_id":                  None,
            "total_revenue":        {"$sum": "$amount_usd"},
            "verification_revenue": {"$sum": {"$cond": [{"$eq": ["$payment_type", "verification"]}, "$amount_usd", 0]}},
            "acid_fee_revenue":     {"$sum": {"$cond": [{"$eq": ["$payment_type", "acid_fee"]}, "$amount_usd", 0]}},
            "total_count":          {"$sum": 1},
            "verification_count":   {"$sum": {"$cond": [{"$eq": ["$payment_type", "verification"]}, 1, 0]}},
            "acid_fee_count":       {"$sum": {"$cond": [{"$eq": ["$payment_type", "acid_fee"]}, 1, 0]}},
        }},
    ]
    summary_res = await db.payment_transactions.aggregate(summary_pipeline).to_list(1)
    summary = summary_res[0] if summary_res else {
        "total_revenue": 0, "verification_revenue": 0, "acid_fee_revenue": 0,
        "total_count": 0, "verification_count": 0, "acid_fee_count": 0,
    }
    summary.pop("_id", None)

    # ─ المدفوعات الشهرية (آخر 12 شهراً)
    monthly_pipeline = [
        {"$match": {"payment_status": "paid"}},
        {"$project": {
            "month":        {"$substr": ["$created_at", 0, 7]},
            "amount_usd":   1,
            "payment_type": 1,
        }},
        {"$group": {
            "_id":         "$month",
            "total":       {"$sum": "$amount_usd"},
            "verification":{"$sum": {"$cond": [{"$eq": ["$payment_type", "verification"]}, "$amount_usd", 0]}},
            "acid_fee":    {"$sum": {"$cond": [{"$eq": ["$payment_type", "acid_fee"]}, "$amount_usd", 0]}},
            "count":       {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
        {"$limit": 12},
    ]
    monthly_res = await db.payment_transactions.aggregate(monthly_pipeline).to_list(12)
    monthly = [
        {"month": r["_id"], "total": r["total"], "verification": r["verification"],
         "acid_fee": r["acid_fee"], "count": r["count"]}
        for r in monthly_res
    ]

    # ─ آخر 15 معاملة
    recent = await db.payment_transactions.find(
        {"payment_status": "paid"}, {"_id": 0}
    ).sort("created_at", -1).to_list(15)

    # ─ إجمالي المعلق
    pending_count = await db.payment_transactions.count_documents({"payment_status": "unpaid"})
    pending_amount = await db.payment_transactions.aggregate([
        {"$match": {"payment_status": "unpaid"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount_usd"}}},
    ]).to_list(1)
    pending_total = pending_amount[0]["total"] if pending_amount else 0

    return {
        "summary":        summary,
        "monthly":        monthly,
        "recent":         recent,
        "pending_count":  pending_count,
        "pending_amount": pending_total,
    }
