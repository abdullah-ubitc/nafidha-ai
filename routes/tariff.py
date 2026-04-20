"""Tariff lookup + AI valuation + exchange rates"""
import logging
from fastapi import APIRouter, HTTPException, Request, Depends
from datetime import datetime, timezone
from models import TariffValuationInput
from database import db
from auth_utils import get_current_user
from helpers import log_audit, get_tariff_rate
from constants import TARIFF_2022, CURRENT_CBL_RATES
from services.ollama_client import ollama_chat_text, parse_json_response

router = APIRouter(tags=["tariff"])
logger = logging.getLogger(__name__)


@router.get("/exchange-rates")
async def get_exchange_rates_hyphen():
    return {"rates": CURRENT_CBL_RATES, "base": "LYD",
            "updated_at": datetime.now(timezone.utc).isoformat(), "source": "مصرف ليبيا المركزي CBL"}


@router.get("/exchange/rates")
async def get_exchange_rates():
    return {"rates": CURRENT_CBL_RATES, "base": "LYD",
            "updated_at": datetime.now(timezone.utc).isoformat(), "source": "مصرف ليبيا المركزي CBL"}


@router.get("/tariff/lookup")
async def lookup_tariff(hs_code: str, current_user=Depends(get_current_user)):
    tariff = get_tariff_rate(hs_code)
    return {
        "hs_code": hs_code, "chapter": hs_code[:2] if hs_code else "",
        "duty_rate": tariff["rate"], "duty_rate_pct": f"{tariff['rate'] * 100:.0f}%",
        "description_ar": tariff["desc_ar"], "description_en": tariff["desc_en"],
        "source": "التعريفة الجمركية الليبية 2022", "vat_rate": 0.09, "vat_rate_pct": "9%"
    }


@router.post("/tariff/ai-valuate")
async def ai_tariff_valuate(data: TariffValuationInput, request: Request, current_user=Depends(get_current_user)):
    tariff = get_tariff_rate(data.hs_code)
    exch = CURRENT_CBL_RATES.get("USD", 4.87)
    system_prompt = """أنت خبير تقييم جمركي متخصص في كشف التلاعب بالقيم الجمركية وفق التعريفة الجمركية الليبية 2022.
مهمتك: تقدير سعر السوق الدولي العادل للبضاعة، ثم مقارنة القيمة المُعلنة:
- التهرب الجمركي: القيمة المُعلنة < 50% من سعر السوق
- تهريب العملة: القيمة المُعلنة > 200% من سعر السوق
أجب بـ JSON صحيح فقط، بدون أي نص إضافي."""
    user_msg = f"""قيّم البضاعة:
وصف: {data.goods_description} | رمز HS: {data.hs_code} ({tariff['desc_ar']})
القيمة المُعلنة: ${data.declared_value_usd:,.2f} للشحنة كاملة ({data.quantity} {data.unit})
سعر الوحدة المُعلن: ${data.declared_value_usd / max(data.quantity, 1):,.2f}
بلد المورد: {data.supplier_country} | معدل الرسوم: {tariff['rate'] * 100:.0f}% | سعر الصرف: {exch} د.ل/دولار

أجب بـ JSON:
{{"estimated_market_value_usd": <السعر العادل للشحنة>, "price_per_unit_usd": <سعر الوحدة المقدر>,
"declared_vs_market_ratio": <نسبة المعلن/السوق مئوية>,
"alert_type": "<none|customs_evasion|currency_smuggling>",
"alert_severity": "<none|low|medium|high|critical>",
"alert_ar": "<رسالة التنبيه>", "analysis_ar": "<التحليل التفصيلي>",
"duty_on_declared_lyd": <الرسوم على القيمة المعلنة>, "duty_on_market_lyd": <الرسوم على قيمة السوق>,
"revenue_leakage_lyd": <تسرب الإيرادات = الفرق في الرسوم>, "recommendation_ar": "<التوصية>"}}"""
    try:
        resp_text = await ollama_chat_text(system_prompt, user_msg, json_mode=True)
        ai = parse_json_response(resp_text)
        if not ai:
            raise ValueError("empty or non-JSON model response")
        result = {
            "goods_description": data.goods_description, "hs_code": data.hs_code,
            "declared_value_usd": data.declared_value_usd,
            "estimated_market_value_usd": ai.get("estimated_market_value_usd", data.declared_value_usd),
            "price_per_unit_usd": ai.get("price_per_unit_usd", 0),
            "declared_vs_market_ratio": ai.get("declared_vs_market_ratio", 100),
            "alert_type": ai.get("alert_type", "none"), "alert_severity": ai.get("alert_severity", "none"),
            "alert_ar": ai.get("alert_ar", ""), "analysis_ar": ai.get("analysis_ar", ""),
            "duty_rate_pct": f"{tariff['rate'] * 100:.0f}%",
            "duty_on_declared_lyd": ai.get("duty_on_declared_lyd", 0),
            "duty_on_market_lyd": ai.get("duty_on_market_lyd", 0),
            "revenue_leakage_lyd": ai.get("revenue_leakage_lyd", 0),
            "recommendation_ar": ai.get("recommendation_ar", ""),
            "tariff_source": "التعريفة الجمركية الليبية 2022",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "engine": "Ollama (local) — Libya Customs Tariff Valuation Engine v1"
        }
        if ai.get("alert_type") != "none":
            await log_audit(
                action=f"tariff_alert_{ai.get('alert_type')}",
                user_id=current_user["_id"], user_name=current_user.get("name_ar", ""),
                resource_type="acid_request", resource_id=data.acid_id or "",
                details={"alert_type": ai.get("alert_type"), "declared_value": data.declared_value_usd,
                         "market_value": ai.get("estimated_market_value_usd"),
                         "revenue_leakage_lyd": ai.get("revenue_leakage_lyd", 0)},
                ip_address=request.client.host if request.client else ""
            )
        return result
    except Exception as e:
        logger.error(f"Tariff valuation error: {e}")
        raise HTTPException(500, f"خطأ في تقييم التعريفة: {str(e)}")
