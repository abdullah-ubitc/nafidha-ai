"""
OCR Route — استخراج النصوص الذكي بواسطة نموذج رؤية محلي (Ollama: llava / qwen-vl)
POST /ocr/extract-cr        — استخراج رقم السجل التجاري وتاريخ انتهائه
POST /ocr/extract-container — استخراج رمز/رقم الحاوية من صورة الكاميرا
POST /ocr/scan-document     — الفحص الذكي للمستندات الجمركية + مطابقة + عداد التكلفة
GET  /ocr/usage/{acid_id}   — إجمالي تكلفة الشحنة
GET  /ocr/usage/summary     — ملخص التكاليف للمدير
"""
import json
import re
import base64
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

from database import db
from helpers import format_doc
from services.ocr_service import scan_and_match, get_shipment_cost, DOC_SCHEMAS
from services.ollama_client import ollama_chat_vision

router = APIRouter(prefix="/ocr", tags=["ocr"])


# ── POST /ocr/extract-cr ──────────────────────────────────────────────────────

@router.post("/extract-cr")
async def extract_cr(
    file: UploadFile = File(...),
):
    """
    استخراج رقم السجل التجاري وتاريخ انتهاء الصلاحية من صورة مرفوعة.
    يدعم PDF (أول صفحة) وصور JPG/PNG.
    """
    # No balance check required for public access

    content = await file.read()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()

    if ext == "pdf":
        # استخرج الصورة الأولى من PDF
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=content, filetype="pdf")
            page = doc[0]
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("jpeg")
            img_b64 = base64.b64encode(img_bytes).decode()
        except Exception:
            # fallback: أرسل كـ binary مباشرةً
            img_b64 = base64.b64encode(content).decode()
    else:
        img_b64 = base64.b64encode(content).decode()

    system_msg = (
        "أنت خبير OCR متخصص في قراءة الوثائق الرسمية الليبية والعربية. "
        "مهمتك استخراج المعلومات المحددة فقط. أجِب بـ JSON بدون تفسيرات."
    )
    prompt = """استخرج من هذه الوثيقة (سجل تجاري أو شهادة تسجيل):
1. رقم السجل التجاري (Commercial Registry Number) — الرقم الفريد للشركة
2. تاريخ انتهاء الصلاحية (Expiry Date) — بصيغة YYYY-MM-DD

أجب بـ JSON حرفياً دون أي نص إضافي:
{"cr_number": "XXXXX", "cr_expiry": "YYYY-MM-DD", "confidence": 0.95, "notes": ""}

إذا لم تجد القيمة أجب بـ null. اقرأ العربي والإنجليزي. الثقة بين 0 و 1."""

    try:
        raw = await ollama_chat_vision(system_msg, prompt, img_b64)
    except Exception as e:
        raise HTTPException(503, f"خدمة OCR المحلية غير متوفرة (Ollama): {str(e)[:200]}")

    # نظّف الـ JSON من markdown code fences
    clean = re.sub(r"```(?:json)?", "", raw).strip(" \n`")
    try:
        result = json.loads(clean)
    except json.JSONDecodeError:
        # محاولة أخيرة: اجتياز regex
        m = re.search(r'\{.*\}', clean, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group())
            except Exception:
                result = {"cr_number": None, "cr_expiry": None, "confidence": 0, "notes": raw[:200]}
        else:
            result = {"cr_number": None, "cr_expiry": None, "confidence": 0, "notes": raw[:200]}

    return {
        "cr_number":  result.get("cr_number"),
        "cr_expiry":  result.get("cr_expiry"),
        "confidence": result.get("confidence", 0),
        "notes":      result.get("notes", ""),
    }


# ── POST /ocr/extract-container ───────────────────────────────────────────────

@router.post("/extract-container")
async def extract_container_code(
    file: UploadFile = File(...),
):
    """
    استخراج رمز/رقم الحاوية من صورة التقطتها كاميرا المفتش.
    رمز الحاوية: 4 أحرف + 7 أرقام (مثال: ABCD1234567) وفق معيار ISO 6346.
    """
    # No balance check required for public access

    content = await file.read()
    img_b64 = base64.b64encode(content).decode()

    system_msg = (
        "أنت خبير قراءة رموز حاويات شحن. "
        "رمز الحاوية ISO 6346 يتكون من: 4 أحرف لاتينية ثم 7 أرقام (مثال: ABCD1234567). "
        "أجِب بـ JSON فقط."
    )
    prompt = """ابحث في هذه الصورة عن رمز الحاوية وفق معيار ISO 6346.

الرمز يظهر عادةً على الجانب الأمامي أو الجانبي للحاوية بخط كبير.
الشكل: 4 أحرف + مسافة/شرطة + 7 أرقام (مثال: MSCU1234567 أو TEXU 1234567-8)

أجب بـ JSON حرفياً:
{"container_code": "XXXX1234567", "confidence": 0.9, "raw_text": "النص الذي وجدته"}

إذا لم تجد رمز الحاوية: {"container_code": null, "confidence": 0, "raw_text": ""}"""

    try:
        raw = await ollama_chat_vision(system_msg, prompt, img_b64)
    except Exception as e:
        raise HTTPException(503, f"خدمة OCR المحلية غير متوفرة (Ollama): {str(e)[:200]}")

    clean = re.sub(r"```(?:json)?", "", raw).strip(" \n`")
    try:
        result = json.loads(clean)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', clean, re.DOTALL)
        result = json.loads(m.group()) if m else {"container_code": None, "confidence": 0, "raw_text": ""}

    # نظّف الرمز — احذف المسافات والشرطات
    code = result.get("container_code")
    if code:
        code = re.sub(r'[\s\-]', '', code).upper()
        # تحقق: 4 أحرف + 7 أرقام
        if not re.match(r'^[A-Z]{4}\d{7}$', code):
            code = code  # أبقه كما هو حتى لو لم يطابق تماماً

    return {
        "container_code": code,
        "confidence":     result.get("confidence", 0),
        "raw_text":       result.get("raw_text", ""),
    }


# ═══════════════════════════════════════════════════════════════
# POST /ocr/scan-document — الفحص الذكي + مطابقة + عداد التكلفة
# ═══════════════════════════════════════════════════════════════

@router.post("/scan-document")
async def scan_document(
    file:      UploadFile = File(...),
    doc_type:  str        = Form(...),   # invoice | certificate_of_origin | passport | bill_of_lading
    acid_id:   str        = Form(""),    # لربط النتيجة بالشحنة
):
    """
    Core OCR endpoint — يقرأ الوثيقة ويطابق القيم مع بيانات ACID في DB.
    في حال فشل OCR، تُعاد رسالة واضحة مع إبقاء المراجعة اليدوية ممكنة.

    Supported doc_types: invoice | certificate_of_origin | passport | bill_of_lading
    """
    if doc_type not in DOC_SCHEMAS:
        raise HTTPException(400, f"نوع وثيقة غير مدعوم. القيم المقبولة: {list(DOC_SCHEMAS.keys())}")

    # ── قراءة الصورة ──────────────────────────────────────────
    content = await file.read()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()

    if ext == "pdf":
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            page = doc[0]
            pix  = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("jpeg")
            img_b64 = base64.b64encode(img_bytes).decode()
        except Exception:
            img_b64 = base64.b64encode(content).decode()
    else:
        img_b64 = base64.b64encode(content).decode()

    # ── جلب بيانات ACID للمطابقة ──────────────────────────────
    acid_doc = None
    if acid_id and ObjectId.is_valid(acid_id):
        acid_doc = await db.acid_requests.find_one(
            {"_id": ObjectId(acid_id)},
            {"_id": 0, "supplier_name": 1, "supplier_country": 1, "value_usd": 1,
             "goods_description": 1, "hs_code": 1, "port_of_entry": 1, "transport_mode": 1}
        )

    # ── فحص رصيد محفظة OCR وخصم التكلفة (Public Access) ──────────
    user_id_str = "public"
    cost_usd = 0.0
    remaining_balance = 0.0

    # ── استدعاء الخدمة المركزية (التكلفة مخصومة مسبقاً) ────────
    result = await scan_and_match(
        image_base64=img_b64,
        doc_type=doc_type,
        acid_id=acid_id or None,
        user_id=user_id_str,
        acid_doc=acid_doc,
    )

    # أضف معلومات الرصيد المتبقي للاستجابة
    result["remaining_balance_usd"] = remaining_balance - cost_usd
    result["cost_usd"]              = cost_usd

    # في حال فشل OCR لا نُرجع 5xx — المراجعة اليدوية لا تزال ممكنة
    return JSONResponse(status_code=200, content=result)


# ═══════════════════════════════════════════════════════════════
# GET /ocr/usage/{acid_id} — تكاليف الشحنة
# ═══════════════════════════════════════════════════════════════

@router.get("/usage/{acid_id}")
async def shipment_ocr_usage(
    acid_id: str,
):
    """إجمالي تكاليف عمليات OCR لشحنة محددة."""
    if not ObjectId.is_valid(acid_id):
        raise HTTPException(400, "معرّف الشحنة غير صالح")
    summary = await get_shipment_cost(acid_id)
    logs    = await db.api_usage_logs.find(
        {"acid_id": acid_id},
        {"_id": 0, "service_type": 1, "doc_type": 1, "cost_usd": 1,
         "matched": 1, "timestamp": 1, "result_summary": 1}
    ).sort("timestamp", -1).to_list(50)
    for log in logs:
        if hasattr(log.get("timestamp"), "isoformat"):
            log["timestamp"] = log["timestamp"].isoformat()
    return {"summary": summary, "logs": logs}


# ═══════════════════════════════════════════════════════════════
# GET /ocr/usage/summary — ملخص إداري
# ═══════════════════════════════════════════════════════════════

@router.get("/usage-summary")
async def ocr_usage_summary():
    """ملخص إداري لتكاليف الـ OCR حسب الشحنة ونوع الوثيقة."""
    pipeline = [
        {"$group": {
            "_id":         "$acid_id",
            "total_cost":  {"$sum": "$cost_usd"},
            "scan_count":  {"$sum": 1},
            "last_scan":   {"$max": "$timestamp"},
        }},
        {"$sort": {"total_cost": -1}},
        {"$limit": 100},
    ]
    rows = await db.api_usage_logs.aggregate(pipeline).to_list(100)
    for r in rows:
        if hasattr(r.get("last_scan"), "isoformat"):
            r["last_scan"] = r["last_scan"].isoformat()

    total_all = await db.api_usage_logs.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$cost_usd"}, "count": {"$sum": 1}}}
    ]).to_list(1)

    return {
        "total_cost_usd": total_all[0]["total"] if total_all else 0,
        "total_scans":    total_all[0]["count"]  if total_all else 0,
        "by_shipment":    rows,
    }


# ═══════════════════════════════════════════════════════════════
# POST /ocr/kyc-scan — مسح وثائق KYC والتسجيل بدون خصم من المحفظة
# مخصص لنموذج التسجيل فقط (passport, national_id, commercial_registry)
# ═══════════════════════════════════════════════════════════════

@router.post("/kyc-scan")
async def kyc_scan_document(
    file:     UploadFile = File(...),
    doc_type: str        = Form(...),   # passport | national_id | commercial_registry
):
    """
    مسح وثيقة KYC أثناء التسجيل — مجاني (بدون خصم من محفظة OCR).
    يعمل فقط مع: passport, national_id, commercial_registry.
    يُستخدم حصراً في نموذج تسجيل المستورد.
    """
    allowed_types = {"passport", "national_id", "commercial_registry"}
    if doc_type not in allowed_types:
        raise HTTPException(400, f"نوع الوثيقة '{doc_type}' غير مدعوم في مسح KYC")

    content = await file.read()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            page = doc[0]
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("jpeg")
            img_b64 = base64.b64encode(img_bytes).decode()
        except Exception:
            img_b64 = base64.b64encode(content).decode()
    else:
        img_b64 = base64.b64encode(content).decode()

    # ── بناء الـ prompt حسب نوع الوثيقة ──
    if doc_type == "passport":
        prompt = """استخرج من جواز السفر هذا بالضبط:
{"full_name_ar": "الاسم الكامل بالعربي", "full_name_en": "FULL NAME IN ENGLISH", "passport_number": "رقم الجواز", "nationality": "الجنسية", "date_of_birth": "YYYY-MM-DD", "expiry_date": "YYYY-MM-DD", "gender": "M/F", "confidence": 0.95}
أجب بـ JSON فقط. إذا لم تجد قيمة استخدم null."""
    elif doc_type == "national_id":
        prompt = """استخرج من بطاقة الهوية الوطنية الليبية:
{"full_name_ar": "الاسم بالعربي", "national_id_number": "رقم الهوية", "date_of_birth": "YYYY-MM-DD", "expiry_date": "YYYY-MM-DD", "confidence": 0.95}
أجب بـ JSON فقط."""
    else:  # commercial_registry
        prompt = """استخرج من السجل التجاري:
{"cr_number": "رقم السجل", "company_name": "اسم الشركة", "cr_expiry": "YYYY-MM-DD", "confidence": 0.95}
أجب بـ JSON فقط."""

    system_msg = "أنت خبير OCR متخصص في الوثائق الرسمية. أجب بـ JSON دون شرح."
    try:
        raw = await ollama_chat_vision(system_msg, prompt, img_b64)
    except Exception as e:
        return JSONResponse(status_code=200, content={"ocr_failed": True, "error": str(e)[:200], "fields": {}})

    # تنظيف JSON
    clean = re.sub(r"```(?:json)?", "", raw).strip(" \n`")
    try:
        extracted = json.loads(clean)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', clean, re.DOTALL)
        extracted = json.loads(m.group()) if m else {}

    return JSONResponse(status_code=200, content={
        "ocr_failed":  not bool(extracted),
        "doc_type":    doc_type,
        "fields":      extracted,
        "cost_usd":    0.0,
        "note":        "مسح مجاني — التسجيل والتوثيق",
    })
