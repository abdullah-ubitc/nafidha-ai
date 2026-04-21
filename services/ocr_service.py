"""
OCR Modular Service — النواة المركزية للفحص الذكي للمستندات
يمكن استدعاؤها من أي Controller في النظام.
الاستخدام: Inspector, Broker (SAD auto-fill), Importer (doc upload).

Models:
  api_usage_logs:          user_id, acid_id, service_type, doc_type, cost, matched, timestamp, result_summary
  ocr_wallets:             user_id, balance_usd, total_topups_usd, total_spent_usd
  system_pricing:          service_type, price_per_unit_usd, min_balance_usd, packages[]
  ocr_topup_transactions:  user_id, package_id, scans_added, amount_usd, balance_before, balance_after
"""
import os
import json
import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

from database import db
from services.ollama_client import ollama_chat_vision

# ── إعدادات الخدمة ───────────────────────────────────────────────────────────
_COST_PER_SCAN = 0.05          # USD — القيمة الافتراضية (تُستبدل بـ system_pricing)
_ALERT_LIMIT   = 2.00          # USD — تنبيه عند تجاوز $2 للشحنة الواحدة

# ── تعريف حقول كل نوع وثيقة وتعيينها على ACID ───────────────────────────────
DOC_SCHEMAS = {
    "invoice": {
        "name_ar": "فاتورة تجارية",
        "extract_fields": ["invoice_number", "total_value_usd", "supplier_name", "goods_description", "issue_date", "currency"],
        "acid_mapping": {
            "supplier_name":    "supplier_name",
            "total_value_usd":  "value_usd",
            "goods_description": "goods_description",
        },
        "prompt": """استخرج من الفاتورة التجارية:
{"invoice_number": null, "total_value_usd": null, "supplier_name": null, "goods_description": null, "issue_date": null, "currency": null, "confidence": 0.0}
الأرقام المالية بصيغة رقمية فقط (بدون عملة). الثقة بين 0 و 1. أجب بـ JSON فقط."""
    },
    "certificate_of_origin": {
        "name_ar": "شهادة المنشأ",
        "extract_fields": ["country_of_origin", "goods_description", "hs_code", "exporter_name", "issue_date"],
        "acid_mapping": {
            "country_of_origin": "supplier_country",
            "goods_description":  "goods_description",
            "hs_code":            "hs_code",
            "exporter_name":      "supplier_name",
        },
        "prompt": """استخرج من شهادة المنشأ:
{"country_of_origin": null, "goods_description": null, "hs_code": null, "exporter_name": null, "issue_date": null, "confidence": 0.0}
HS Code بصيغة XXXX.XX. أجب بـ JSON فقط."""
    },
    "passport": {
        "name_ar": "جواز السفر",
        "extract_fields": ["full_name", "passport_number", "nationality", "expiry_date", "date_of_birth"],
        "acid_mapping": {
            "nationality": "supplier_country",
        },
        "prompt": """استخرج من جواز السفر:
{"full_name": null, "passport_number": null, "nationality": null, "expiry_date": null, "date_of_birth": null, "confidence": 0.0}
التواريخ بصيغة YYYY-MM-DD. أجب بـ JSON فقط."""
    },
    "bill_of_lading": {
        "name_ar": "بوليصة الشحن",
        "extract_fields": ["bl_number", "vessel_name", "port_of_loading", "port_of_discharge", "goods_description", "total_weight"],
        "acid_mapping": {
            "port_of_discharge": "port_of_entry",
            "goods_description":  "goods_description",
        },
        "prompt": """استخرج من بوليصة الشحن (Bill of Lading):
{"bl_number": null, "vessel_name": null, "port_of_loading": null, "port_of_discharge": null, "goods_description": null, "total_weight": null, "confidence": 0.0}
أجب بـ JSON فقط."""
    },
}

SYSTEM_MSG = (
    "أنت خبير OCR متخصص في قراءة الوثائق الرسمية التجارية والجمركية (عربية وإنجليزية). "
    "مهمتك استخراج القيم المحددة بدقة عالية. أجب بـ JSON فقط بدون تفسيرات."
)


# ═══════════════════════════════════════════════════════════════
# get_dynamic_price — جلب سعر المسحة من system_pricing
# ═══════════════════════════════════════════════════════════════

async def get_dynamic_price() -> float:
    """يجلب سعر المسحة الحالي من system_pricing أو يُرجع القيمة الافتراضية."""
    try:
        pricing = await db.system_pricing.find_one({"service_type": "ocr_scan"})
        if pricing:
            return float(pricing.get("price_per_unit_usd", _COST_PER_SCAN))
    except Exception:
        pass
    return _COST_PER_SCAN


# ═══════════════════════════════════════════════════════════════
# check_and_deduct_balance — التحقق من رصيد المحفظة وخصم التكلفة
# ═══════════════════════════════════════════════════════════════

async def check_and_deduct_balance(user_id: str) -> Tuple[bool, str, float, float]:
    """
    عطّلت هذه الدالة لتعمل دائماً بنجاح (Public Access) بناءً على طلب المستخدم.
    كانت تتحقق سابقاً من رصيد محفظة OCR.
    """
    return True, "تم السماح بالوصول العام", 0.0, 0.0


async def _notify_low_balance(user_id: str, remaining: float, cost: float):
    """إرسال SMS تنبيه عند اقتراب نفاد رصيد OCR (أقل من 5 مسحات)."""
    try:
        from bson import ObjectId
        from services.notification_service import _send_twilio_sms
        user = await db.users.find_one({"_id": ObjectId(user_id)}, {"phone": 1})
        if user and user.get("phone"):
            scans_left = int(remaining / cost) if cost > 0 else 0
            msg = (
                f"تنبيه نافذة الجمارك: رصيد OCR منخفض — متبقٍ {scans_left} مسحة. "
                f"اشحن محفظتك الآن على بوابة نافذة الجمارك الليبية."
            )
            await _send_twilio_sms(user["phone"], msg)
    except Exception:
        pass  # SMS غير إلزامي


# ═══════════════════════════════════════════════════════════════
# parse_json_safe — تنظيف رد النموذج المحلي
# ═══════════════════════════════════════════════════════════════

def _parse_json(raw: str) -> dict:
    clean = re.sub(r"```(?:json)?", "", raw).strip(" \n`")
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', clean, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {}


# ═══════════════════════════════════════════════════════════════
# match_fields — مقارنة القيم المستخرجة مع بيانات ACID
# ═══════════════════════════════════════════════════════════════

def _match_fields(extracted: dict, acid_doc: dict, mapping: dict) -> dict:
    """
    Returns a dict of {field: {extracted, stored, match: True/False/None}}
    match=None عندما تكون القيمة غير متوفرة لإجراء المقارنة.
    """
    results = {}
    for doc_field, acid_field in mapping.items():
        ext_val   = extracted.get(doc_field)
        acid_val  = acid_doc.get(acid_field)
        if ext_val is None or acid_val is None:
            results[doc_field] = {"extracted": ext_val, "stored": acid_val, "match": None}
            continue
        # مقارنة مرنة: كلاهما str أو رقم
        ext_str  = str(ext_val).strip().lower()
        acid_str = str(acid_val).strip().lower()
        # للأرقام المالية: فرق ±5% مسموح
        try:
            e_f = float(ext_str.replace(",", ""))
            a_f = float(acid_str.replace(",", ""))
            match_ok = abs(e_f - a_f) / max(a_f, 0.01) <= 0.05
        except ValueError:
            match_ok = ext_str == acid_str or ext_str in acid_str or acid_str in ext_str
        results[doc_field] = {"extracted": ext_val, "stored": acid_val, "match": match_ok}
    return results


# ═══════════════════════════════════════════════════════════════
# log_usage — تسجيل التكلفة في api_usage_logs
# ═══════════════════════════════════════════════════════════════

async def log_usage(
    user_id: str,
    acid_id: Optional[str],
    service_type: str,
    doc_type: str,
    cost: float,
    matched: Optional[bool],
    result_summary: dict,
) -> float:
    """
    يسجّل العملية ويُرجع إجمالي تكلفة الشحنة بعد هذه العملية.
    """
    now = datetime.now(timezone.utc)
    await db.api_usage_logs.insert_one({
        "user_id":        user_id,
        "acid_id":        acid_id,
        "service_type":   service_type,
        "doc_type":       doc_type,
        "cost_usd":       cost,
        "matched":        matched,
        "result_summary": result_summary,
        "timestamp":      now,
    })
    # جلب إجمالي التكلفة للشحنة
    pipeline = [
        {"$match": {"acid_id": acid_id}},
        {"$group": {"_id": None, "total": {"$sum": "$cost_usd"}}},
    ]
    cur = db.api_usage_logs.aggregate(pipeline)
    rows = await cur.to_list(1)
    return rows[0]["total"] if rows else cost


# ═══════════════════════════════════════════════════════════════
# get_shipment_cost — إجمالي تكلفة الشحنة
# ═══════════════════════════════════════════════════════════════

async def get_shipment_cost(acid_id: str) -> dict:
    pipeline = [
        {"$match": {"acid_id": acid_id}},
        {"$group": {
            "_id": None,
            "total_cost": {"$sum": "$cost_usd"},
            "scan_count": {"$sum": 1},
        }},
    ]
    cur  = db.api_usage_logs.aggregate(pipeline)
    rows = await cur.to_list(1)
    if rows:
        return {"total_cost_usd": rows[0]["total_cost"], "scan_count": rows[0]["scan_count"]}
    return {"total_cost_usd": 0.0, "scan_count": 0}


# ═══════════════════════════════════════════════════════════════
# scan_and_match — الدالة الرئيسية
# ═══════════════════════════════════════════════════════════════

async def scan_and_match(
    image_base64: str,
    doc_type: str,
    acid_id: Optional[str],
    user_id: str,
    acid_doc: Optional[dict] = None,
) -> dict:
    """
    Core OCR function — قابلة للاستدعاء من أي controller.

    Returns:
      {
        extracted_fields,
        match_results,
        overall_match,
        confidence,
        cost_per_scan,
        shipment_total_cost,
        alert_triggered,
        doc_type,
        doc_name_ar,
        ocr_failed,      # True إذا فشل OCR (fallback يدوي)
        error_message,
      }
    """
    schema = DOC_SCHEMAS.get(doc_type)
    if not schema:
        return {
            "ocr_failed": True,
            "error_message": f"نوع وثيقة غير مدعوم: {doc_type}",
            "extracted_fields": {},
            "match_results": {},
        }

    # ── Ollama vision OCR (محلي) ───────────────────────────────
    extracted  = {}
    ocr_failed = False
    error_msg  = ""

    try:
        raw = await ollama_chat_vision(
            SYSTEM_MSG,
            schema["prompt"],
            image_base64,
        )
        extracted = _parse_json(raw)
    except Exception as e:
        ocr_failed = True
        error_msg = f"تعذّر الاتصال بخدمة OCR المحلية (Ollama): {str(e)[:200]}"

    confidence   = float(extracted.pop("confidence", 0.0)) if not ocr_failed else 0.0
    match_results = {}
    overall_match = None

    # ── مطابقة مع بيانات ACID ──────────────────────────────────
    if acid_doc and not ocr_failed:
        match_results = _match_fields(extracted, acid_doc, schema.get("acid_mapping", {}))
        # الإجمالي: match إذا كل الحقول المتوفرة matched
        checked = [v["match"] for v in match_results.values() if v["match"] is not None]
        if checked:
            overall_match = all(checked)

    # ── تسجيل التكلفة ─────────────────────────────────────────
    cost = (await get_dynamic_price()) if not ocr_failed else 0.0
    shipment_total = 0.0
    alert_triggered = False

    if acid_id:
        result_summary = {
            "confidence": confidence,
            "overall_match": overall_match,
            "fields_count": len(extracted),
        }
        shipment_total = await log_usage(
            user_id=user_id,
            acid_id=acid_id,
            service_type="Ollama_OCR",
            doc_type=doc_type,
            cost=cost,
            matched=overall_match,
            result_summary=result_summary,
        )
        alert_triggered = shipment_total >= _ALERT_LIMIT

    # ── حدث Timeline على الشحنة ────────────────────────────────
    if acid_id and not ocr_failed:
        from bson import ObjectId
        event_note = (
            f"[OCR] {schema['name_ar']} — "
            f"{'مطابق ✓' if overall_match else 'غير مطابق ✗' if overall_match is False else 'لا يوجد بيانات للمقارنة'} "
            f"(ثقة: {confidence:.0%})"
        )
        try:
            if ObjectId.is_valid(acid_id):
                await db.acid_requests.update_one(
                    {"_id": ObjectId(acid_id)},
                    {"$push": {"timeline": {
                        "event":     "ocr_scan",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "actor":     "النظام — OCR",
                        "notes":     event_note,
                    }}},
                )
        except Exception:
            pass  # لا نوقف العملية بسبب خطأ في timeline

    return {
        "extracted_fields":   extracted,
        "match_results":      match_results,
        "overall_match":      overall_match,
        "confidence":         confidence,
        "doc_type":           doc_type,
        "doc_name_ar":        schema["name_ar"],
        "cost_per_scan":      cost,
        "shipment_total_cost": shipment_total,
        "alert_triggered":    alert_triggered,
        "alert_message":      f"تجاوزت تكلفة المسح للشحنة الحد المسموح به (${_ALERT_LIMIT:.2f})" if alert_triggered else None,
        "ocr_failed":         ocr_failed,
        "error_message":      error_msg,
    }
