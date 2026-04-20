"""
NAFIDHA Digital Wallet — Phase F
Pre-paid balance that bypasses per-transaction wait times.
"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from datetime import datetime, timezone
from models import WalletTopUpInput, WalletTransactionType
from database import db
from auth_utils import get_current_user, require_approved_user
from helpers import format_doc, log_audit

router = APIRouter(prefix="/wallet", tags=["wallet"])


async def _get_or_create_wallet(user_id: str) -> dict:
    wallet = await db.user_wallets.find_one({"user_id": user_id})
    if not wallet:
        doc = {
            "user_id": user_id,
            "balance_lyd": 0.0,
            "total_topup": 0.0,
            "total_spent": 0.0,
            "transactions": [],
            "created_at": datetime.now(timezone.utc),
        }
        result = await db.user_wallets.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return doc
    return wallet


@router.get("/my")
async def my_wallet(current_user=Depends(get_current_user)):
    """Get current user's wallet balance."""
    wallet = await _get_or_create_wallet(current_user["_id"])
    return {
        "_id": str(wallet["_id"]),
        "balance_lyd": wallet.get("balance_lyd", 0.0),
        "total_topup": wallet.get("total_topup", 0.0),
        "total_spent": wallet.get("total_spent", 0.0),
        "transactions": (wallet.get("transactions") or [])[-20:],  # Last 20
    }


@router.post("/topup")
async def topup_wallet(data: WalletTopUpInput, current_user=Depends(require_approved_user)):
    """Top up NAFIDHA wallet."""
    if data.amount_lyd <= 0:
        raise HTTPException(400, "المبلغ يجب أن يكون أكبر من صفر")

    wallet = await _get_or_create_wallet(current_user["_id"])
    transaction = {
        "type": WalletTransactionType.TOPUP.value,
        "amount": data.amount_lyd,
        "payment_ref": data.payment_ref,
        "notes": data.notes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "balance_after": wallet.get("balance_lyd", 0) + data.amount_lyd,
    }
    new_balance = wallet.get("balance_lyd", 0) + data.amount_lyd
    await db.user_wallets.update_one(
        {"user_id": current_user["_id"]},
        {
            "$set": {"balance_lyd": new_balance},
            "$inc": {"total_topup": data.amount_lyd},
            "$push": {"transactions": transaction},
        },
        upsert=True,
    )
    await log_audit(
        action="wallet_topup", user_id=current_user["_id"],
        user_name=current_user.get("name_ar", ""), resource_type="wallet",
        resource_id=current_user["_id"],
        details={"amount": data.amount_lyd, "payment_ref": data.payment_ref},
        ip_address="",
    )
    return {
        "message": f"تم شحن المحفظة بمبلغ {data.amount_lyd:.2f} د.ل",
        "new_balance": new_balance,
    }


@router.post("/pay-fee/{fee_id}")
async def pay_fee_from_wallet(fee_id: str, current_user=Depends(require_approved_user)):
    """Deduct a platform fee directly from wallet balance."""
    if not ObjectId.is_valid(fee_id):
        raise HTTPException(400, "معرّف الرسوم غير صالح")

    fee = await db.platform_fees.find_one({"_id": ObjectId(fee_id)})
    if not fee:
        raise HTTPException(404, "الرسوم غير موجودة")
    if fee.get("status") == "paid":
        raise HTTPException(400, "تم سداد هذه الرسوم مسبقاً")
    if fee.get("payer_id") != current_user["_id"] and current_user["role"] not in ("admin",):
        raise HTTPException(403, "غير مصرح")

    wallet = await _get_or_create_wallet(current_user["_id"])
    balance = wallet.get("balance_lyd", 0)
    amount  = fee.get("amount_lyd", 0)

    if balance < amount:
        raise HTTPException(400, f"رصيد المحفظة غير كافٍ ({balance:.2f} د.ل). المطلوب: {amount:.2f} د.ل")

    new_balance = balance - amount
    transaction = {
        "type": WalletTransactionType.DEDUCT.value,
        "amount": -amount,
        "fee_id": fee_id,
        "fee_type": fee.get("fee_type"),
        "notes": f"سداد رسوم {fee.get('fee_type', '')} — رقم {fee.get('acid_number', '')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "balance_after": new_balance,
    }
    await db.user_wallets.update_one(
        {"user_id": current_user["_id"]},
        {
            "$set": {"balance_lyd": new_balance},
            "$inc": {"total_spent": amount},
            "$push": {"transactions": transaction},
        },
    )

    # Mark fee as paid
    await db.platform_fees.update_one(
        {"_id": ObjectId(fee_id)},
        {"$set": {"status": "paid", "payment_ref": "WALLET", "paid_via": "wallet",
                  "paid_at": datetime.now(timezone.utc).isoformat(),
                  "paid_by": current_user["_id"]}}
    )

    # Update acid platform_fees_paid flag
    ref_id = fee.get("reference_id")
    if ref_id and ObjectId.is_valid(ref_id):
        pending = await db.platform_fees.count_documents({"reference_id": ref_id, "status": "pending"})
        if pending == 0:
            await db.acid_requests.update_one(
                {"_id": ObjectId(ref_id)},
                {"$set": {"platform_fees_paid": True}}
            )

    return {
        "message": "تم خصم الرسوم من محفظتك بنجاح",
        "deducted": amount,
        "new_balance": new_balance,
    }
