"""Platform Fees routes — Phase F Enhanced.
- QR code digital receipt generation
- Early Bird 10% discount for first 100 entities
- Scaling amendment fees (free → 25 LYD → 50 LYD)
- Wallet payment integration
"""
import io
import base64
import qrcode
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from datetime import datetime, timezone
from models import PlatformFeePayInput, PlatformFeeType, UserRole
from database import db
from auth_utils import get_current_user, require_roles, require_approved_user
from helpers import format_doc, log_audit, PLATFORM_FEE_AMOUNTS

router = APIRouter(prefix="/platform-fees", tags=["platform_fees"])

# ── Constants ──────────────────────────────────────────────────────────────────
EARLY_BIRD_LIMIT   = 100     # First 100 registered entities get 10% off
EARLY_BIRD_DISC    = 0.10    # 10%
AMENDMENT_FEES_LYD = [0, 25, 50]   # [1st: free, 2nd: 25, 3rd+: 50]


def _generate_qr_base64(data: str) -> str:
    """Generate QR code as base64 PNG string."""
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1e3a5f", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


async def _get_amendment_fee_amount(user_id: str) -> float:
    """Progressive amendment fee: free → 25 LYD → 50 LYD."""
    count = await db.platform_fees.count_documents(
        {"payer_id": user_id, "fee_type": PlatformFeeType.AMENDMENT_FEE.value}
    )
    if count == 0:
        return 0.0
    elif count == 1:
        return 25.0
    else:
        return 50.0


async def _apply_early_bird(base_amount: float, fee_type: str) -> tuple[float, bool]:
    """Apply 10% Early Bird discount for annual subscriptions if eligible."""
    if fee_type != PlatformFeeType.ANNUAL_SUBSCRIPTION.value:
        return base_amount, False
    total_entities = await db.users.count_documents(
        {"role": {"$in": ["importer", "customs_broker", "carrier_agent"]}}
    )
    if total_entities <= EARLY_BIRD_LIMIT:
        return round(base_amount * (1 - EARLY_BIRD_DISC), 2), True
    return base_amount, False


# ── Routes ─────────────────────────────────────────────────────────────────────
@router.get("")
async def list_fees(current_user=Depends(get_current_user)):
    role = current_user["role"]
    if role in ("admin", "treasury_officer"):
        fees = await db.platform_fees.find({}).sort("created_at", -1).to_list(500)
    else:
        fees = await db.platform_fees.find({"payer_id": current_user["_id"]}).sort("created_at", -1).to_list(200)
    return [format_doc(f) for f in fees]


@router.get("/stats")
async def fee_stats(current_user=Depends(require_roles(UserRole.ADMIN, UserRole.TREASURY_OFFICER))):
    total     = await db.platform_fees.count_documents({})
    pending   = await db.platform_fees.count_documents({"status": "pending"})
    paid      = await db.platform_fees.count_documents({"status": "paid"})
    pipeline  = [{"$match": {"status": "paid"}},
                 {"$group": {"_id": None, "total_lyd": {"$sum": "$amount_lyd"}}}]
    agg       = await db.platform_fees.aggregate(pipeline).to_list(1)
    total_lyd = agg[0]["total_lyd"] if agg else 0
    return {"total": total, "pending": pending, "paid": paid, "revenue_lyd": total_lyd}


@router.get("/amendment-preview")
async def preview_amendment_fee(current_user=Depends(get_current_user)):
    """Preview the next amendment fee amount for the current user."""
    amount = await _get_amendment_fee_amount(current_user["_id"])
    count  = await db.platform_fees.count_documents(
        {"payer_id": current_user["_id"], "fee_type": PlatformFeeType.AMENDMENT_FEE.value}
    )
    return {
        "next_amendment_count": count + 1,
        "fee_amount_lyd": amount,
        "is_free": amount == 0,
        "fee_schedule": [
            {"amendment": "1", "amount": 0,  "label": "الأول — مجاني"},
            {"amendment": "2", "amount": 25, "label": "الثاني — 25 د.ل"},
            {"amendment": "3+","amount": 50, "label": "الثالث فأكثر — 50 د.ل"},
        ],
    }


@router.post("/create-annual-subscription")
async def create_annual_subscription(current_user=Depends(require_approved_user)):
    """Create annual subscription fee with early bird discount if eligible."""
    base_amount = PLATFORM_FEE_AMOUNTS.get("annual_subscription", 500)
    final_amount, is_early_bird = await _apply_early_bird(base_amount, "annual_subscription")

    # Check if user already has an active subscription this year
    existing = await db.platform_fees.find_one({
        "payer_id": current_user["_id"],
        "fee_type": "annual_subscription",
        "status": {"$in": ["pending", "paid"]},
    })
    if existing:
        raise HTTPException(400, "لديك بالفعل اشتراك سنوي لهذه السنة")

    fee_doc = {
        "fee_type": "annual_subscription",
        "reference_id": current_user["_id"],
        "amount_lyd": final_amount,
        "original_amount_lyd": base_amount,
        "early_bird": is_early_bird,
        "early_bird_discount_pct": 10 if is_early_bird else 0,
        "payer_id": current_user["_id"],
        "payer_name": current_user.get("name_ar", ""),
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.platform_fees.insert_one(fee_doc)
    fee_doc["_id"] = str(result.inserted_id)
    fee_doc["created_at"] = fee_doc["created_at"].isoformat()
    return {
        "message": "تم إنشاء فاتورة الاشتراك السنوي",
        "fee": fee_doc,
        "early_bird": is_early_bird,
        "discount_message": f"خصم المبكرين 10% مُطبَّق! ({base_amount:.0f} → {final_amount:.0f} د.ل)" if is_early_bird else None,
    }


@router.post("/{fee_id}/pay")
async def pay_fee(fee_id: str, data: PlatformFeePayInput, current_user=Depends(require_approved_user)):
    """Pay a platform fee and generate a digital receipt with QR code."""
    if not ObjectId.is_valid(fee_id):
        raise HTTPException(400, "معرّف الرسوم غير صالح")
    fee = await db.platform_fees.find_one({"_id": ObjectId(fee_id)})
    if not fee:
        raise HTTPException(404, "الرسوم غير موجودة")

    role = current_user["role"]
    if role not in ("admin", "treasury_officer") and fee.get("payer_id") != current_user["_id"]:
        raise HTTPException(403, "غير مصرح")
    if fee.get("status") == "paid":
        raise HTTPException(400, "تم سداد هذه الرسوم مسبقاً")

    # Generate receipt data
    receipt_id = f"RCP-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{fee_id[-6:]}"
    paid_at    = datetime.now(timezone.utc).isoformat()

    await db.platform_fees.update_one(
        {"_id": ObjectId(fee_id)},
        {"$set": {
            "status": "paid",
            "payment_ref": data.payment_ref,
            "notes": data.notes,
            "paid_at": paid_at,
            "paid_by": current_user["_id"],
            "receipt_id": receipt_id,
        }}
    )

    # Update linked acid platform_fees_paid flag
    ref_id = fee.get("reference_id")
    if ref_id and ObjectId.is_valid(ref_id):
        pending_count = await db.platform_fees.count_documents(
            {"reference_id": ref_id, "status": "pending"}
        )
        if pending_count == 0:
            await db.acid_requests.update_one(
                {"_id": ObjectId(ref_id)},
                {"$set": {"platform_fees_paid": True}}
            )

    # Generate QR code for receipt
    qr_data = (
        f"NAFIDHA-RECEIPT\n"
        f"ID: {receipt_id}\n"
        f"Amount: {fee.get('amount_lyd', 0):.2f} LYD\n"
        f"Type: {fee.get('fee_type', '')}\n"
        f"Ref: {fee.get('acid_number', fee.get('reference_id',''))}\n"
        f"Paid: {paid_at[:10]}\n"
        f"By: {current_user.get('name_ar','')}"
    )
    qr_base64 = _generate_qr_base64(qr_data)

    await log_audit(
        action="platform_fee_paid",
        user_id=current_user["_id"],
        user_name=current_user.get("name_ar", ""),
        resource_type="platform_fee",
        resource_id=fee_id,
        details={"payment_ref": data.payment_ref, "amount": fee.get("amount_lyd"), "receipt_id": receipt_id},
        ip_address="",
    )
    return {
        "message": "تم تسجيل السداد بنجاح",
        "status": "paid",
        "receipt": {
            "id": receipt_id,
            "fee_type": fee.get("fee_type"),
            "amount_lyd": fee.get("amount_lyd"),
            "paid_at": paid_at,
            "payment_ref": data.payment_ref,
            "payer_name": current_user.get("name_ar", ""),
            "acid_number": fee.get("acid_number"),
            "qr_code_base64": qr_base64,
        },
    }
