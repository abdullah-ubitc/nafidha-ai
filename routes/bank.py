"""Bank CBL verification routes"""
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from datetime import datetime, timezone
from models import BankVerifyInput
from database import db
from auth_utils import get_current_user, require_approved_user

router = APIRouter(prefix="/bank", tags=["bank"])


@router.post("/verify")
async def verify_bank_transfer(data: BankVerifyInput, current_user=Depends(require_approved_user)):
    acid_req = await db.acid_requests.find_one({"acid_number": data.acid_number})
    if not acid_req:
        raise HTTPException(404, "رقم ACID غير موجود")
    sad = await db.sad_forms.find_one({"acid_number": data.acid_number, "is_active": True})
    expected = sad["total_lyd"] if sad else None
    cbl_valid = len(data.cbl_ref) >= 8 and data.cbl_ref.upper().startswith("CBL")
    amount_ok = (expected is None) or (abs(data.amount_lyd - expected) < 1.0)
    is_verified = cbl_valid and amount_ok
    verify_doc = {
        "acid_number": data.acid_number, "acid_id": str(acid_req["_id"]),
        "cbl_ref": data.cbl_ref, "bank_name": data.bank_name,
        "amount_lyd": data.amount_lyd, "expected_amount_lyd": expected,
        "is_verified": is_verified, "verified_by": current_user["_id"],
        "verified_at": datetime.now(timezone.utc),
        "status": "matched" if is_verified else "unmatched"
    }
    result = await db.bank_verifications.insert_one(verify_doc)
    if is_verified and sad:
        await db.sad_forms.update_one(
            {"_id": sad["_id"]},
            {"$set": {"cbl_bank_ref": data.cbl_ref, "status": "submitted", "updated_at": datetime.now(timezone.utc)}}
        )
    return {
        "acid_number": data.acid_number, "cbl_ref": data.cbl_ref, "bank_name": data.bank_name,
        "amount_lyd": data.amount_lyd, "expected_amount_lyd": expected,
        "is_verified": is_verified, "status": verify_doc["status"],
        "status_ar": "مطابق" if is_verified else "غير مطابق",
        "message_ar": "تم التحقق من الحوالة بنجاح" if is_verified else "فشل التحقق - تحقق من رمز CBL والمبلغ",
        "transaction_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "verification_id": str(result.inserted_id)
    }


@router.get("/history/{acid_id}")
async def bank_history(acid_id: str, current_user=Depends(get_current_user)):
    acid_req = await db.acid_requests.find_one({"_id": ObjectId(acid_id)}) if ObjectId.is_valid(acid_id) else None
    if not acid_req:
        raise HTTPException(404, "طلب ACID غير موجود")
    records = await db.bank_verifications.find(
        {"acid_number": acid_req.get("acid_number")}
    ).sort("verified_at", -1).to_list(20)
    result = []
    for r in records:
        r["_id"] = str(r["_id"])
        if isinstance(r.get("verified_at"), datetime):
            r["verified_at"] = r["verified_at"].isoformat()
        result.append(r)
    return result
