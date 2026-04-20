"""Global Exporter Registry — CRUD + Verification + Public Stats + Self-Registration
سجل المصدرين العالميين: بحث، تسجيل ذاتي، توثيق، إحصاءات عامة
"""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File, Form, Request
from database import db
from auth_utils import get_current_user, require_roles, hash_password
from models import GlobalExporterCreate, GlobalExporterAddEmail, GlobalExporterVerifyInput, UserRole
import os, shutil

router = APIRouter(prefix="/exporters", tags=["exporters"])

_UPLOAD_DIR = "/app/uploads/exporter_docs"


# ───────────── Public Stats (no auth) ─────────────────────────────────────────

@router.get("/public/stats")
async def public_exporter_stats():
    """إحصاءات عامة للمصدرين — تُستخدم في صفحة اللاندينج (بدون توثيق)."""
    total = await db.global_exporters.count_documents({})
    verified = await db.global_exporters.count_documents({"is_verified": True})
    # احتساب عدد الدول الفريدة
    countries_pipeline = [
        {"$match": {"country": {"$exists": True, "$nin": [None, ""]}}},
        {"$group": {"_id": "$country"}},
        {"$count": "unique_countries"},
    ]
    countries_result = await db.global_exporters.aggregate(countries_pipeline).to_list(1)
    unique_countries = countries_result[0]["unique_countries"] if countries_result else 0
    return {
        "total_exporters": total,
        "verified_exporters": verified,
        "unique_countries": unique_countries,
    }


# ───────────── Search (authenticated) ─────────────────────────────────────────

@router.get("/search")
async def search_exporters(
    q: str = Query(default="", min_length=0),
    current_user=Depends(get_current_user),
):
    """بحث جزئي عن المصدرين بالاسم أو رقم الضريبة — يُستخدم في الـ Autocomplete."""
    if not q or len(q.strip()) < 2:
        return []
    clean_q = q.strip()
    query = {
        "$or": [
            {"tax_id":       {"$regex": clean_q, "$options": "i"}},
            {"company_name": {"$regex": clean_q, "$options": "i"}},
        ]
    }
    results = await db.global_exporters.find(query, {"_id": 0}).limit(15).to_list(15)
    return results


# ───────────── Admin: List All ─────────────────────────────────────────────────

@router.get("")
async def list_exporters(
    verified: Optional[bool] = None,
    country: Optional[str] = None,
    q: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current_user=Depends(require_roles(UserRole.ADMIN)),
):
    """قائمة جميع المصدرين — للمدير فقط مع خيارات الفلترة."""
    filter_q: dict = {}
    if verified is not None:
        filter_q["is_verified"] = verified
    if country:
        filter_q["country"] = {"$regex": country, "$options": "i"}
    if q:
        filter_q["$or"] = [
            {"tax_id":       {"$regex": q, "$options": "i"}},
            {"company_name": {"$regex": q, "$options": "i"}},
        ]
    total = await db.global_exporters.count_documents(filter_q)
    results = await db.global_exporters.find(filter_q, {"_id": 0}).skip(skip).limit(limit).sort("created_at", -1).to_list(limit)
    return {"total": total, "exporters": results}


# ───────────── Get By Tax ID ───────────────────────────────────────────────────

@router.get("/{tax_id}")
async def get_exporter(tax_id: str, current_user=Depends(get_current_user)):
    """جلب بيانات مصدر محدد بواسطة رقم الضريبة."""
    exporter = await db.global_exporters.find_one({"tax_id": tax_id}, {"_id": 0})
    if not exporter:
        raise HTTPException(status_code=404, detail="المصدر غير موجود في السجل العالمي")
    return exporter


# ───────────── Create ─────────────────────────────────────────────────────────

@router.post("")
async def create_exporter(
    data: GlobalExporterCreate,
    current_user=Depends(get_current_user),
):
    """
    تسجيل مصدر جديد في السجل العالمي.
    - إذا كان الـ tax_id موجوداً: يُعيد بياناته مع علامة exists=True
    - إذا كان جديداً: ينشئ السجل مع is_verified=False افتراضياً
    """
    existing = await db.global_exporters.find_one({"tax_id": data.tax_id}, {"_id": 0})
    if existing:
        return {"exists": True, "exporter": existing}

    doc = {
        "tax_id": data.tax_id,
        "company_name": data.company_name,
        "emails": list(set(data.emails or [])),
        "country": data.country,
        "address": data.address,
        "is_verified": False,
        "verified_by_id": None,
        "verified_by_name": None,
        "verified_at": None,
        "verification_notes": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.global_exporters.insert_one(doc)
    doc.pop("_id", None)
    return {"exists": False, "exporter": doc}


# ───────────── Add Secondary Email ────────────────────────────────────────────

@router.post("/{tax_id}/emails")
async def add_exporter_email(
    tax_id: str,
    data: GlobalExporterAddEmail,
    current_user=Depends(get_current_user),
):
    """إضافة بريد إلكتروني ثانوي لمصدر موجود."""
    exporter = await db.global_exporters.find_one({"tax_id": tax_id})
    if not exporter:
        raise HTTPException(status_code=404, detail="المصدر غير موجود في السجل العالمي")

    if data.email in exporter.get("emails", []):
        return {
            "message": "البريد الإلكتروني مسجل مسبقاً",
            "emails": exporter["emails"],
            "already_exists": True,
        }

    await db.global_exporters.update_one(
        {"tax_id": tax_id},
        {
            "$addToSet": {"emails": data.email},
            "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    updated = await db.global_exporters.find_one({"tax_id": tax_id}, {"_id": 0})
    return {
        "message": "تم إضافة البريد الإلكتروني كجهة اتصال ثانوية بنجاح",
        "emails": updated["emails"],
        "already_exists": False,
    }


# ───────────── Verify (Admin) ──────────────────────────────────────────────────

@router.patch("/{tax_id}/verify")
async def verify_exporter(
    tax_id: str,
    data: GlobalExporterVerifyInput = GlobalExporterVerifyInput(),
    current_user=Depends(require_roles(UserRole.ADMIN)),
):
    """
    اعتماد المصدر كمُوثَّق (Admin فقط) مع تسجيل مسار التدقيق الكامل.
    يُمكّن خاصية القناة الخضراء في المستقبل.
    """
    exporter = await db.global_exporters.find_one({"tax_id": tax_id})
    if not exporter:
        raise HTTPException(status_code=404, detail="المصدر غير موجود في السجل العالمي")

    now = datetime.now(timezone.utc).isoformat()
    await db.global_exporters.update_one(
        {"tax_id": tax_id},
        {
            "$set": {
                "is_verified": True,
                "verified_by_id": current_user["_id"],
                "verified_by_name": current_user.get("name_ar") or current_user.get("name_en", ""),
                "verified_at": now,
                "verification_notes": data.notes,
                "updated_at": now,
            }
        },
    )
    # تسجيل في سجل التدقيق
    await db.audit_logs.insert_one({
        "action": "exporter_verified",
        "user_id": current_user["_id"],
        "user_name": current_user.get("name_ar", ""),
        "resource_type": "global_exporter",
        "resource_id": tax_id,
        "details": {
            "company_name": exporter.get("company_name"),
            "notes": data.notes,
        },
        "timestamp": now,
    })
    return {
        "message": f"تم توثيق المصدر {tax_id} بنجاح",
        "is_verified": True,
        "verified_by": current_user.get("name_ar", ""),
        "verified_at": now,
    }


# ───────────── Unverify (Admin) ────────────────────────────────────────────────

@router.patch("/{tax_id}/unverify")
async def unverify_exporter(
    tax_id: str,
    current_user=Depends(require_roles(UserRole.ADMIN)),
):
    """إلغاء توثيق المصدر (Admin فقط) — مع تسجيل المسؤول والتوقيت."""
    exporter = await db.global_exporters.find_one({"tax_id": tax_id})
    if not exporter:
        raise HTTPException(status_code=404, detail="المصدر غير موجود في السجل العالمي")

    now = datetime.now(timezone.utc).isoformat()
    await db.global_exporters.update_one(
        {"tax_id": tax_id},
        {
            "$set": {
                "is_verified": False,
                "unverified_by_id": current_user["_id"],
                "unverified_by_name": current_user.get("name_ar", ""),
                "unverified_at": now,
                "updated_at": now,
            }
        },
    )
    await db.audit_logs.insert_one({
        "action": "exporter_unverified",
        "user_id": current_user["_id"],
        "user_name": current_user.get("name_ar", ""),
        "resource_type": "global_exporter",
        "resource_id": tax_id,
        "details": {"company_name": exporter.get("company_name")},
        "timestamp": now,
    })
    return {"message": f"تم إلغاء توثيق المصدر {tax_id}", "is_verified": False}


# ───────────── Self-Registration (Public) ─────────────────────────────────────

@router.post("/self-register")
async def self_register_exporter(
    company_name:      str           = Form(...),
    email:             str           = Form(...),
    phone:             str           = Form(...),
    country:           str           = Form(...),
    address:           str           = Form(...),
    tax_id:            str           = Form(...),
    exporter_type:     str           = Form(...),  # "regional" | "global"
    password:          str           = Form(...),
    duns_number:       Optional[str] = Form(None),
    vat_registration:  Optional[str] = Form(None),
    regional_country:  Optional[str] = Form(None),
    business_license:  UploadFile    = File(...),
):
    """
    تسجيل ذاتي للمصدر الأجنبي.
    - ينشئ سجل في global_exporters بحالة pending_payment
    - يحفظ وثيقة الترخيص التجاري
    - يخزّن هاش كلمة المرور مؤقتاً (تُستخدم لإنشاء users بعد الدفع)
    """
    email = email.lower().strip()
    tax_id = tax_id.strip().upper()

    # التحقق من عدم التكرار
    existing = await db.global_exporters.find_one({"$or": [{"tax_id": tax_id}, {"email": email}]})
    if existing:
        if existing.get("account_status") == "approved":
            raise HTTPException(409, "البريد الإلكتروني أو رقم الضريبة مسجّل مسبقاً وحسابك نشط")
        # إعادة الـ tax_id للمواصلة بالدفع
        return {
            "tax_id":         existing["tax_id"],
            "account_status": existing.get("account_status", "pending_payment"),
            "message":        "الحساب مسجّل مسبقاً — يمكنك إتمام الدفع",
        }

    # حفظ ملف الترخيص التجاري
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe = f"{tax_id}_{ts}_{business_license.filename}"
    file_path = os.path.join(_UPLOAD_DIR, safe)
    with open(file_path, "wb") as fh:
        shutil.copyfileobj(business_license.file, fh)

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "tax_id":                     tax_id,
        "company_name":               company_name.strip(),
        "email":                      email,
        "phone":                      phone.strip(),
        "country":                    country.strip(),
        "address":                    address.strip(),
        "exporter_type":              exporter_type,      # regional | global
        "regional_country":           regional_country,
        "duns_number":                duns_number,
        "vat_registration":           vat_registration,
        "emails":                     [email],
        "business_license_path":      file_path,
        "business_license_filename":  business_license.filename,
        "is_verified":                False,
        "account_status":             "pending_payment",   # يتغير → approved بعد الدفع
        "user_id":                    None,
        "_password_hash":             hash_password(password),
        "verified_by_id":             None,
        "verified_by_name":           None,
        "verified_at":                None,
        "verification_notes":         None,
        "verification_fee_paid_at":   None,
        "verification_fee_expires_at": None,
        "created_at":                 now,
        "updated_at":                 now,
    }
    await db.global_exporters.insert_one(doc)

    return {
        "tax_id":         tax_id,
        "account_status": "pending_payment",
        "message":        "تم تسجيل بياناتك — أكمل الدفع للحصول على شارة التوثيق",
    }


# ───────────── Exporter ACID View (for logged-in foreign_supplier) ────────────

@router.get("/my-acids")
async def my_acids(current_user=Depends(get_current_user)):
    """جلب طلبات ACID المرتبطة بالمصدر الحالي"""
    if current_user["role"] != "foreign_supplier":
        raise HTTPException(403, "هذا المسار مخصص للمصدرين فقط")
    email = current_user.get("email", "")
    tax_id = current_user.get("tax_id_tin", "")
    query = {"$or": []}
    if email:
        query["$or"].append({"exporter_email": email})
    if tax_id:
        query["$or"].append({"exporter_tax_id": tax_id})
    if not query["$or"]:
        return []
    from helpers import format_doc
    acids = await db.acid_requests.find(query).sort("created_at", -1).to_list(100)
    return [format_doc(a) for a in acids]
