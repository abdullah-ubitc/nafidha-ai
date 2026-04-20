"""SAD form routes: create, get, update, download JL159 + JL119 PDFs"""
import io
import os
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from bson import ObjectId
from datetime import datetime, timezone
from models import SADCreate, SADUpdate, UserRole
from database import db
from auth_utils import get_current_user, require_roles, require_approved_user
from helpers import generate_sad_number, generate_jl159_number, log_audit
from constants import TARIFF_2022, CURRENT_CBL_RATES
from pdf_generator import generate_jl159_pdf_bytes, generate_jl119_pdf_bytes
from services.notification_service import notify_role_users

router = APIRouter(prefix="/sad", tags=["sad"])


@router.post("")
async def create_sad(
    data: SADCreate,
    background_tasks: BackgroundTasks,
    current_user=Depends(require_roles(UserRole.CUSTOMS_BROKER, UserRole.IMPORTER, UserRole.ADMIN, UserRole.CUSTOMS_VALUER))
):
    acid_req = await db.acid_requests.find_one({"_id": ObjectId(data.acid_id)}) if ObjectId.is_valid(data.acid_id) else None
    if not acid_req:
        raise HTTPException(404, "طلب ACID غير موجود")

    # ── Phase F Hard Guard: DO must be issued before SAD ──
    if not acid_req.get("do_issued", False):
        raise HTTPException(
            400,
            "لا يمكن تقديم البيان الجمركي قبل إصدار أمر التسليم (DO) من الناقل. "
            "يرجى انتظار تأكيد الناقل على سداد رسوم الشحن."
        )
    existing = await db.sad_forms.find_one({"acid_id": data.acid_id, "is_active": True})
    if existing:
        existing["_id"] = str(existing["_id"])
        for k in ["created_at", "updated_at"]:
            if isinstance(existing.get(k), datetime):
                existing[k] = existing[k].isoformat()
        return {"message": "SAD موجود مسبقاً", "sad": existing}
    value_usd = acid_req.get("value_usd", 0)
    hs = acid_req.get("hs_code", "").strip()
    tariff_info = TARIFF_2022.get(hs[:2] if hs else "", {"rate": 0.20, "desc_ar": "بضائع متنوعة", "desc_en": "Miscellaneous"})
    customs_rate = tariff_info["rate"]
    exch = CURRENT_CBL_RATES.get("USD", 4.87)
    cdusd = round(value_usd * customs_rate, 2)
    cdlyd = round(cdusd * exch, 2)
    vatusd = round((value_usd + cdusd) * 0.09, 2)
    vatlyd = round(vatusd * exch, 2)
    sad_doc = {
        "sad_number": await generate_sad_number(),
        "receipt_number": await generate_jl159_number(),
        "acid_id": data.acid_id, "acid_number": acid_req.get("acid_number"),
        "declarant_id": current_user["_id"],
        "declarant_name": current_user.get("name_ar") or current_user.get("name_en"),
        "declaration_type": data.declaration_type,
        "customs_station": data.customs_station, "cbl_bank_ref": data.cbl_bank_ref,
        "status": "draft", "is_active": True,
        "value_usd": value_usd, "value_lyd": round(value_usd * exch, 2),
        "customs_rate_pct": f"{customs_rate * 100:.0f}%",
        "customs_duty_usd": cdusd, "customs_duty_lyd": cdlyd,
        "vat_rate_pct": "9%", "vat_usd": vatusd, "vat_lyd": vatlyd,
        "total_usd": round(cdusd + vatusd, 2), "total_lyd": round(cdlyd + vatlyd, 2),
        "exchange_rate": exch,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)
    }
    result = await db.sad_forms.insert_one(sad_doc)
    sad_doc["_id"] = str(result.inserted_id)
    sad_doc["created_at"] = sad_doc["created_at"].isoformat()
    sad_doc["updated_at"] = sad_doc["updated_at"].isoformat()
    # ── إشعار مأموري البيان بوصول SAD جديد للمراجعة ─────────────
    background_tasks.add_task(
        notify_role_users,
        "declaration_officer",
        "task_sad_submitted",
        {
            "sad_number": sad_doc.get("sad_number", ""),
            "acid_number": acid_req.get("acid_number", ""),
        },
        data.acid_id,
        current_user["_id"],
    )
    return {"message": "تم إنشاء نموذج SAD بنجاح", "sad": sad_doc}


@router.get("/by-acid/{acid_id}")
async def get_sad_by_acid(acid_id: str, current_user=Depends(get_current_user)):
    sad = await db.sad_forms.find_one({"acid_id": acid_id, "is_active": True}) or \
          await db.sad_forms.find_one({"acid_number": acid_id, "is_active": True})
    if not sad:
        raise HTTPException(404, "لم يتم إنشاء SAD لهذا الطلب")
    sad["_id"] = str(sad["_id"])
    for k in ["created_at", "updated_at"]:
        if isinstance(sad.get(k), datetime):
            sad[k] = sad[k].isoformat()
    return sad


@router.put("/{sad_id}")
async def update_sad(sad_id: str, data: SADUpdate, current_user=Depends(require_approved_user)):
    update_data = {k: v for k, v in data.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)
    result = await db.sad_forms.update_one({"_id": ObjectId(sad_id)}, {"$set": update_data})
    if result.modified_count == 0:
        raise HTTPException(404, "نموذج SAD غير موجود")
    return {"message": "تم التحديث"}


@router.get("/{sad_id}/pdf")
async def download_sad_pdf(sad_id: str, current_user=Depends(get_current_user)):
    sad = await db.sad_forms.find_one({"_id": ObjectId(sad_id)}) if ObjectId.is_valid(sad_id) else None
    if not sad:
        raise HTTPException(404, "نموذج SAD غير موجود")
    acid = await db.acid_requests.find_one({"_id": ObjectId(sad["acid_id"])}) if ObjectId.is_valid(sad["acid_id"]) else None
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    for d in [sad, acid]:
        d["_id"] = str(d["_id"])
        for k in ["created_at", "updated_at"]:
            if isinstance(d.get(k), datetime):
                d[k] = d[k].isoformat()
    verify_url = f"{os.environ.get('FRONTEND_URL', 'https://libya-customs-acis.preview.emergentagent.com')}/verify"
    pdf_bytes = generate_jl159_pdf_bytes(
        receipt_no=sad.get("receipt_number", sad_id), sad=sad, acid=acid, verify_url=verify_url
    )
    fname = f"JL159_{sad.get('receipt_number', sad_id)}.pdf"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
                             headers={"Content-Disposition": f"attachment; filename={fname}"})


@router.get("/{sad_id}/jl119-pdf")
async def download_jl119_pdf(sad_id: str, current_user=Depends(get_current_user)):
    sad = await db.sad_forms.find_one({"_id": ObjectId(sad_id)}) if ObjectId.is_valid(sad_id) else None
    if not sad:
        raise HTTPException(404, "نموذج SAD غير موجود")
    acid = await db.acid_requests.find_one({"_id": ObjectId(sad["acid_id"])}) if ObjectId.is_valid(sad.get("acid_id", "")) else None
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    for d in [sad, acid]:
        d["_id"] = str(d["_id"])
        for k in ["created_at", "updated_at"]:
            if isinstance(d.get(k), datetime):
                d[k] = d[k].isoformat()
    verify_url = os.environ.get('FRONTEND_URL', 'https://libya-customs-acis.preview.emergentagent.com') + "/verify"
    pdf_bytes = generate_jl119_pdf_bytes(sad=sad, acid=acid, verify_url=verify_url)
    fname = f"JL119_{sad.get('sad_number', sad_id)}.pdf"
    await log_audit(
        action="jl119_pdf_downloaded", user_id=current_user["_id"],
        user_name=current_user.get("name_ar", ""), resource_type="sad_form",
        resource_id=sad_id, details={"sad_number": sad.get("sad_number")}
    )
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
                             headers={"Content-Disposition": f"attachment; filename={fname}"})
