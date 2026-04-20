"""Registration documents upload endpoint"""
import uuid
import aiofiles
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from bson import ObjectId
from datetime import datetime, timezone
from database import db, ROOT_DIR
from auth_utils import get_current_user

router = APIRouter(prefix="/registration", tags=["registration"])

REG_UPLOAD_DIR = ROOT_DIR / "reg_uploads"
REG_UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_DOC_TYPES = {
    # ── Legacy doc types (backward compatibility) ─────────────────────
    "commercial_registry": "السجل التجاري",
    "national_id":        "البطاقة الوطنية للمفوّض",
    "tax_certificate":    "شهادة التسجيل الضريبي",
    "broker_license":     "ترخيص المخلص الجمركي",
    "carrier_license":    "ترخيص شركة النقل",
    "signature_sample":   "عينة التوقيع المعتمد",
    "stamp_sample":       "عينة الختم الرسمي",
    # ── Phase 2026: Front / Back splits ───────────────────────────────
    "commercial_registry_front": "السجل التجاري (الوجه الأمامي)",
    "commercial_registry_back":  "السجل التجاري (الوجه الخلفي)",
    "national_id_front":         "البطاقة الوطنية (الوجه الأمامي)",
    "national_id_back":          "البطاقة الوطنية (الوجه الخلفي)",
    "passport_image":            "جواز السفر (صورة كاملة)",
    "statistical_cert_front":    "الرمز الإحصائي (الوجه الأمامي)",
    "statistical_cert_back":     "الرمز الإحصائي (الوجه الخلفي)",
    "authorization_letter":      "خطاب التفويض",
    # ── Customs Broker License Documents ─────────────────────────────────────
    "broker_license_front":        "ترخيص المخلص (الوجه الأمامي)",
    "broker_license_back":         "ترخيص المخلص (الوجه الخلفي)",
    # ── Carrier Multi-Modal License Documents ────────────────────────────────
    "marine_license_front":        "الترخيص البحري (الوجه الأمامي)",
    "marine_license_back":         "الترخيص البحري (الوجه الخلفي)",
    "air_operator_cert_front":     "ترخيص التشغيل الجوي (الوجه الأمامي)",
    "air_operator_cert_back":      "ترخيص التشغيل الجوي (الوجه الخلفي)",
    "land_transport_permit_front": "ترخيص النقل البري (الوجه الأمامي)",
    "land_transport_permit_back":  "ترخيص النقل البري (الوجه الخلفي)",
}


@router.post("/docs/upload")
async def upload_registration_doc(
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    if doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(400, f"نوع الوثيقة غير صحيح. المسموح: {list(ALLOWED_DOC_TYPES.keys())}")
    ext = Path(file.filename).suffix.lower() if file.filename else ".bin"
    if ext not in ['.pdf', '.jpg', '.jpeg', '.png']:
        raise HTTPException(400, "نوع الملف غير مدعوم (PDF, JPG, PNG فقط)")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "حجم الملف يتجاوز 10 ميجابايت")
    user_dir = REG_UPLOAD_DIR / current_user["_id"]
    user_dir.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    saved_path = user_dir / f"{doc_type}_{file_id}{ext}"
    async with aiofiles.open(saved_path, 'wb') as f:
        await f.write(content)
    doc_meta = {
        "file_id": file_id, "user_id": current_user["_id"],
        "doc_type": doc_type, "doc_type_ar": ALLOWED_DOC_TYPES[doc_type],
        "original_filename": file.filename,
        "saved_path": str(saved_path), "file_size": len(content),
        "content_type": file.content_type,
        "uploaded_at": datetime.now(timezone.utc), "status": "pending_review"
    }
    await db.registration_docs.insert_one(doc_meta)
    # Phase L: حفظ تاريخ الرفع في reg_doc_* — يُستخدم لمقارنته بـ correction_requested_at لتحديد "مُحدث"
    # PRESERVE_STATUSES: لا نغير حالة Phase L (تبقى كما هي)
    current_status = current_user.get("registration_status", "")
    PRESERVE_STATUSES = {"email_unverified", "pending", "needs_correction", "approved", "rejected"}
    new_status = current_status if current_status in PRESERVE_STATUSES else "docs_submitted"
    uploaded_at_iso = datetime.now(timezone.utc).isoformat()
    await db.users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$set": {
            f"reg_doc_{doc_type}": {"file_id": file_id, "status": "uploaded", "uploaded_at": uploaded_at_iso},
            "registration_status": new_status,
            **({f"{doc_type}_file_id": file_id} if doc_type in ("signature_sample", "stamp_sample") else {})
        },
        "$push": {
            "status_history": {
                "action":     "doc_uploaded",
                "actor":      "user",
                "actor_name": current_user.get("name_ar") or current_user.get("legal_name_ar") or "",
                "timestamp":  uploaded_at_iso,
                "details":    {"doc_type": doc_type, "doc_type_ar": ALLOWED_DOC_TYPES[doc_type]},
            }
        }}
    )
    return {
        "message": "تم رفع الوثيقة بنجاح",
        "file_id": file_id, "doc_type": doc_type,
        "doc_type_ar": ALLOWED_DOC_TYPES[doc_type],
        "uploaded_at": doc_meta["uploaded_at"].isoformat()
    }


@router.get("/docs/my")
async def get_my_registration_docs(current_user=Depends(get_current_user)):
    docs = await db.registration_docs.find(
        {"user_id": current_user["_id"]}
    ).sort("uploaded_at", -1).to_list(20)
    result = []
    for d in docs:
        d["_id"] = str(d["_id"])
        if isinstance(d.get("uploaded_at"), datetime):
            d["uploaded_at"] = d["uploaded_at"].isoformat()
        result.append(d)
    return result


@router.get("/docs/{file_id}/serve")
async def serve_registration_doc(file_id: str, current_user=Depends(get_current_user)):
    """Stream a registration doc file (used for signature/stamp display in admin)"""
    doc = await db.registration_docs.find_one({"file_id": file_id})
    if not doc:
        raise HTTPException(404, "الملف غير موجود")
    # Allow owner OR officer/admin roles
    allowed_roles = {"admin", "registration_officer", "acid_reviewer", "acid_risk_officer",
                     "manifest_officer", "declaration_officer", "release_officer", "inspector"}
    is_owner = doc["user_id"] == current_user["_id"]
    is_officer = current_user.get("role") in allowed_roles
    if not (is_owner or is_officer):
        raise HTTPException(403, "غير مصرح")
    path = Path(doc["saved_path"])
    if not path.exists():
        raise HTTPException(404, "الملف المادي غير موجود")
    return FileResponse(str(path), media_type=doc.get("content_type", "application/octet-stream"))


@router.put("/complete-wizard")
async def complete_registration_wizard(
    data: dict,
    current_user=Depends(get_current_user)
):
    """Save delegate info from the 4-step wizard"""
    allowed_fields = {
        "delegate_name_ar", "delegate_name_en", "delegate_national_id",
        "delegate_phone", "delegate_email", "license_number", "license_expiry",
        "city", "phone"
    }
    update_data = {k: v for k, v in data.items() if k in allowed_fields and v}
    update_data["registration_wizard_completed"] = True
    update_data["wizard_completed_at"] = datetime.now(timezone.utc)
    if not update_data:
        raise HTTPException(400, "لا توجد بيانات للتحديث")
    await db.users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$set": update_data}
    )
    return {"message": "تم حفظ بيانات معالج التسجيل بنجاح"}
