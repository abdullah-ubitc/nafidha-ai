"""Risk analysis routes: static + local LLM (Ollama)"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from datetime import datetime, timezone
from models import AIRiskInput
from database import db
from auth_utils import get_current_user
from constants import LIBYA_PROHIBITED_ITEMS
from services.ollama_client import ollama_chat_text, parse_json_response

router = APIRouter(prefix="/risk", tags=["risk"])
logger = logging.getLogger(__name__)


@router.get("/analyze/{acid_id}")
async def analyze_risk(acid_id: str):
    req = await db.acid_requests.find_one({"_id": ObjectId(acid_id)}) if ObjectId.is_valid(acid_id) else None
    if not req:
        req = await db.acid_requests.find_one({"acid_number": acid_id})
    if not req:
        raise HTTPException(status_code=404, detail="ACID request not found")
    factors = []
    score = 0
    if req.get("value_usd", 0) > 100000:
        factors.append({"factor": "high_value", "label_ar": "قيمة مرتفعة جداً", "weight": 30})
        score += 30
    if req.get("transport_mode") == "land":
        factors.append({"factor": "land_transport", "label_ar": "نقل بري - مخاطر أعلى", "weight": 20})
        score += 20
    suspicious = ["93", "36", "28", "29"]
    if any(req.get("hs_code", "").startswith(p) for p in suspicious):
        factors.append({"factor": "sensitive_hs", "label_ar": "رمز HS حساس", "weight": 50})
        score += 50
    level = "high" if score >= 50 else ("medium" if score >= 20 else "low")
    return {
        "acid_id": acid_id, "acid_number": req.get("acid_number"),
        "risk_score": score, "risk_level": level,
        "risk_factors": factors,
        "recommendation_ar": "فحص مادي مطلوب" if level == "high" else ("مراجعة وثائق مطلوبة" if level == "medium" else "مراجعة اعتيادية"),
        "analyzed_at": datetime.now(timezone.utc).isoformat()
    }


@router.post("/ai-analyze")
async def ai_analyze_risk(data: AIRiskInput):
    system_prompt = f"""أنت خبير تقييم مخاطر الجمارك الليبية. تحلل طلبات الاستيراد وتقيّم مستوى المخاطر.
قائمة البضائع المحظورة والمقيدة في ليبيا:
{LIBYA_PROHIBITED_ITEMS}
قواعد تصنيف المسار:
- الخط الأحمر (red): بضائع محظورة كلياً أو أسلحة أو مواد كيميائية خطرة أو كحول
- الخط الأصفر (yellow): بضائع مقيدة أو قيمة عالية (>100,000 USD) أو مواد ذات استخدام مزدوج
- الخط الأخضر (green): بضائع عادية لا مخاطر
أجب بـ JSON صحيح فقط، بدون أي نص إضافي."""
    user_msg = f"""حلل طلب الاستيراد:
وصف البضاعة: {data.goods_description}
رمز HS: {data.hs_code}
القيمة: ${data.value_usd:,.2f}
بلد المورد: {data.supplier_country}

أجب بـ JSON:
{{"risk_score": <0-100>, "route": "<green|yellow|red>", "risk_factors_ar": ["عامل1"], "recommendation_ar": "<توصية>", "is_prohibited": <true|false>, "prohibition_reason_ar": "<سبب أو null>", "suggested_action_ar": "<إجراء>"}}"""
    try:
        resp_text = await ollama_chat_text(system_prompt, user_msg, json_mode=True)
        ai_result = parse_json_response(resp_text)
        if not ai_result:
            raise ValueError("empty or non-JSON model response")
        return {
            "goods_description": data.goods_description, "hs_code": data.hs_code,
            "value_usd": data.value_usd, "supplier_country": data.supplier_country,
            "risk_score": ai_result.get("risk_score", 50),
            "route": ai_result.get("route", "yellow"),
            "risk_factors_ar": ai_result.get("risk_factors_ar", []),
            "recommendation_ar": ai_result.get("recommendation_ar", ""),
            "is_prohibited": ai_result.get("is_prohibited", False),
            "prohibition_reason_ar": ai_result.get("prohibition_reason_ar"),
            "suggested_action_ar": ai_result.get("suggested_action_ar", ""),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "engine": "Ollama (local) — Libya Customs Risk Engine v2"
        }
    except Exception as e:
        logger.error(f"AI error: {e}")
        raise HTTPException(500, f"خطأ في تحليل المخاطر: {str(e)}")
