"""
Notification Service — نظام الإشعارات الذكي (Phase L)
يعمل داخلياً مع hooks جاهزة للتكامل مع Twilio/SendGrid
"""
from datetime import datetime, timezone
from typing import Optional
from bson import ObjectId
from database import db
from ws_manager import ws_manager

# ═══════════════════════════════════════════════════════════════
# قوالب الرسائل — Arabic & English
# ═══════════════════════════════════════════════════════════════
TEMPLATES = {
    # ── القناة الخضراء ─────────────────────────────────────────
    "green_channel_activated": {
        "ar": "🟢 شحنتك {acid_number} دخلت الممر السريع — التخليص المتوقع خلال ساعتين",
        "en": "🟢 Your shipment {acid_number} has been fast-tracked — Expected clearance within 2 hours",
        "type": "green_channel",
        "icon": "zap",
    },
    # ── تحديثات حالة ACID ──────────────────────────────────────
    "acid_submitted": {
        "ar": "📋 تم استلام طلبك {acid_number} وسيُراجَع قريباً من الضباط المختصين",
        "en": "📋 Your ACID request {acid_number} has been received and is pending officer review",
        "type": "info",
        "icon": "file",
    },
    "acid_under_review": {
        "ar": "🔍 طلبك {acid_number} تحت المراجعة من ضابط المخاطر الجمركي",
        "en": "🔍 Your ACID request {acid_number} is currently under customs risk review",
        "type": "info",
        "icon": "search",
    },
    "acid_approved": {
        "ar": "✅ تم اعتماد طلب ACID رقم {acid_number} بنجاح — يمكنك متابعة إجراءات التخليص",
        "en": "✅ ACID request {acid_number} has been approved — Proceed to customs clearance",
        "type": "success",
        "icon": "check",
    },
    "acid_rejected": {
        "ar": "❌ تم رفض طلب {acid_number} — يُرجى مراجعة أسباب الرفض والتقديم من جديد",
        "en": "❌ ACID request {acid_number} was rejected — Please review the reasons and resubmit",
        "type": "error",
        "icon": "x",
    },
    "acid_amendment_required": {
        "ar": "⚠️ طلب {acid_number} يحتاج إلى تعديلات — راجع ملاحظات الضابط وأعد الإرسال",
        "en": "⚠️ ACID request {acid_number} requires amendments — Review officer notes and resubmit",
        "type": "warning",
        "icon": "alert",
    },
    # ── سجل المصدرين ──────────────────────────────────────────
    "exporter_verified": {
        "ar": "🏆 تهانينا! شركتك {company_name} حصلت على شارة 'مصدر موثَّق' في سجل نافذة الجمارك الليبية",
        "en": "🏆 Congratulations! {company_name} has been granted 'Verified Exporter' status in NAFIDHA registry",
        "type": "success",
        "icon": "shield",
    },
    # ── KYC — Phase L ─────────────────────────────────────────
    "kyc_approved": {
        "ar": "🎉 مبروك {name}! تم اعتماد حسابك في منظومة نافذة الجمارك — يمكنك الآن الدخول وبدء العمل",
        "en": "🎉 Congratulations {name}! Your account has been approved in NAFIDHA — You can now log in and start",
        "type": "success",
        "icon": "check",
    },
    # ── Renewal Engine ─────────────────────────────────────────
    "renewal_approved": {
        "ar": "✅ {name} — تم اعتماد تجديد وثيقتك '{doc_label}'. تاريخ الانتهاء الجديد: {new_expiry}. حسابك نشط الآن.",
        "en": "✅ {name} — Your document '{doc_label}' renewal has been approved. New expiry: {new_expiry}. Account is now active.",
        "type": "success",
        "icon": "check",
    },
    "renewal_rejected": {
        "ar": "❌ {name} — تم رفض تجديد وثيقتك '{doc_label}'. السبب: {reason}. يُرجى إعادة الرفع.",
        "en": "❌ {name} — Your document '{doc_label}' renewal was rejected. Reason: {reason}. Please resubmit.",
        "type": "error",
        "icon": "x",
    },
    "kyc_rejected": {
        "ar": "❌ {name} — تم رفض طلب تسجيلك في المنظومة. السبب: {reason} — يمكن التواصل مع مصلحة الجمارك للاستفسار",
        "en": "❌ {name} — Your registration request was rejected. Reason: {reason}",
        "type": "error",
        "icon": "x",
    },
    # ── انتهاء الرخص — Phase M ────────────────────────────────
    "license_expiry_reminder": {
        "ar": "⚠️ تنبيه تجديد الرخصة — {name}، رخصتك التجارية ستنتهي خلال {days} يوم ({expiry}). يُرجى التجديد لضمان استمرار الخدمة",
        "en": "⚠️ License Renewal Alert — {name}, your trade license expires in {days} days ({expiry}). Please renew to avoid service interruption",
        "type": "warning",
        "icon": "alert",
    },
    # ── Workflow SLA — Phase Q ─────────────────────────────────
    "wf_sla_breached": {
        "ar": "🔴 تنبيه تجاوز SLA — المهمة \"{task_title}\" ({task_type_label}) تجاوزت موعدها الإلزامي بـ {overdue_hours} ساعة. المحجوز بواسطة: {assigned_to}",
        "en": "🔴 SLA Breach Alert — Task \"{task_title}\" ({task_type_label}) is overdue by {overdue_hours} hours. Claimed by: {assigned_to}",
        "type": "error",
        "icon": "alert",
    },
    # ── تصعيد الرحلات البرية — Phase LAND ──────────────────────
    "land_trip_escalated": {
        "ar": "🚨 رحلة برية متأخرة — لوحة: {truck_plate} | منفذ: {port} | تأخير: {overdue_hours} ساعة — يحتاج مراجعة فورية",
        "en": "🚨 Land trip overdue — Plate: {truck_plate} | Port: {port} | Overdue: {overdue_hours}h — Immediate review required",
        "type": "error",
        "icon": "alert",
    },
    # ── التقرير الأسبوعي — Phase R ────────────────────────────
    "weekly_report_ready": {
        "ar": "📊 تقرير الأداء الأسبوعي جاهز ({date}) — حجم الملف: {size_kb} KB. يمكن تحميله من برج المراقبة.",
        "en": "📊 Weekly Performance Report ready ({date}) — File size: {size_kb} KB. Download from Admin Control Tower.",
        "type": "info",
        "icon": "chart",
    },
    # ── إعادة تقديم الوثائق — Phase N ─────────────────────────
    "kyc_resubmitted": {
        "ar": "✅ {name} أعاد رفع وثائقه — طلبه الآن في حوض المراجعة مرة ثانية (مراجعة ثانية #{count})",
        "en": "✅ {name} has resubmitted documents — request is back in review pool (Review #{count})",
        "type": "info",
        "icon": "refresh",
    },
    "kyc_docs_returned_to_officer": {
        "ar": "📋 {applicant_name} أعاد رفع وثائقه — الملف عاد إلى قائمتك لاستكمال المراجعة",
        "en": "📋 {applicant_name} resubmitted documents — file is back in your queue",
        "type": "info",
        "icon": "refresh",
    },
    # ── تصحيح KYC — Phase N ─────────────────────────────────
    "kyc_correction_requested": {
        "ar": "⚠️ {name} — طُلب تصحيح وثائقك في منظومة نافذة. ملاحظات المأمور: {notes} — يُرجى مراجعة حسابك لإعادة رفع الوثائق المطلوبة",
        "en": "⚠️ {name} — Document corrections requested for your NAFIDHA account. Officer notes: {notes}",
        "type": "warning",
        "icon": "alert",
    },
    # ── المعاينة الميدانية — Phase T ────────────────────────
    "dangerous_goods_detected": {
        "ar": "🚨 تنبيه طارئ — مواد خطرة في الشحنة {acid_number} | النوع: {goods_type} | المفتش: {inspector_name}",
        "en": "🚨 CRITICAL ALERT — Dangerous goods in shipment {acid_number} | Type: {goods_type} | Inspector: {inspector_name}",
        "type": "error",
        "icon": "alert",
    },
    # ── الإفراج الجمركي ────────────────────────────────────────────
    "gate_released": {
        "ar": "🎉 تم الإفراج النهائي عن شحنتك {acid_number} — رقم وثيقة JL38: {jl38_number}",
        "en": "🎉 Final release issued for your shipment {acid_number} — JL38 Document: {jl38_number}",
        "type": "success",
        "icon": "check",
    },
    # ── التنبيهات الدورية للضباط (task_arrival) ────────────────────
    "task_acid_submitted": {
        "ar": "📋 طلب ACID جديد [{acid_number}] في انتظار المراجعة — المستورد: {requester_name}",
        "en": "📋 New ACID request [{acid_number}] awaiting review — Importer: {requester_name}",
        "type": "info",
        "icon": "file",
    },
    "task_manifest_submitted": {
        "ar": "🚢 مانيفست جديد [{manifest_number}] في انتظار الموافقة — الناقل: {carrier_name}",
        "en": "🚢 New manifest [{manifest_number}] awaiting approval — Carrier: {carrier_name}",
        "type": "info",
        "icon": "package",
    },
    "task_sad_submitted": {
        "ar": "📄 بيان جمركي جديد [{sad_number}] — ACID: {acid_number} — في انتظار مراجعة مأمور البيان",
        "en": "📄 New SAD [{sad_number}] — ACID: {acid_number} — Awaiting declaration officer review",
        "type": "info",
        "icon": "file",
    },
    "task_inspection_required": {
        "ar": "🔍 شحنة [{acid_number}] تحتاج معاينة ميدانية — قناة: {channel_label} — يُرجى المراجعة",
        "en": "🔍 Shipment [{acid_number}] requires field inspection — Channel: {channel_label}",
        "type": "warning",
        "icon": "search",
    },
    "task_yellow_review_required": {
        "ar": "📑 شحنة [{acid_number}] في القناة الصفراء — مراجعة وثائق فقط (بدون معاينة ميدانية)",
        "en": "📑 Shipment [{acid_number}] in Yellow Channel — Documents review only (no field inspection)",
        "type": "warning",
        "icon": "file",
    },
    "task_ready_for_valuation": {
        "ar": "💰 شحنة [{acid_number}] جاهزة للتقييم الجمركي — بيانها مقبول من مأمور البيان",
        "en": "💰 Shipment [{acid_number}] ready for customs valuation — Declaration accepted",
        "type": "info",
        "icon": "chart",
    },
    "task_ready_for_treasury": {
        "ar": "🏦 شحنة [{acid_number}] جاهزة لتأكيد السداد — القيمة الجمركية: {confirmed_value} USD",
        "en": "🏦 Shipment [{acid_number}] ready for treasury confirmation — Customs value: {confirmed_value} USD",
        "type": "info",
        "icon": "package",
    },
    "task_ready_for_gate": {
        "ar": "🚦 شحنة [{acid_number}] جاهزة للإفراج النهائي — تم تأكيد السداد من الخزينة",
        "en": "🚦 Shipment [{acid_number}] ready for final release — Treasury payment confirmed",
        "type": "success",
        "icon": "check",
    },
}


# ═══════════════════════════════════════════════════════════════
# الدالة الرئيسية لإرسال الإشعار
# ═══════════════════════════════════════════════════════════════
async def send_notification(
    user_id: str,
    template_key: str,
    context: dict,
    lang: str = "ar",
    acid_id: Optional[str] = None,
):
    """
    إرسال إشعار داخلي + حفظه في DB + بث عبر WebSocket.
    جاهز للتوسع: أضف send_twilio_sms() أو send_sendgrid_email() هنا.
    """
    tmpl = TEMPLATES.get(template_key)
    if not tmpl:
        return

    msg_ar = tmpl["ar"].format(**{k: v or "" for k, v in context.items()})
    msg_en = tmpl["en"].format(**{k: v or "" for k, v in context.items()})
    now    = datetime.now(timezone.utc).isoformat()

    # ── 1. حفظ في قاعدة البيانات ──────────────────────────────
    doc = {
        "user_id":    user_id,
        "template":   template_key,
        "message_ar": msg_ar,
        "message_en": msg_en,
        "type":       tmpl["type"],       # success | error | warning | info | green_channel
        "icon":       tmpl["icon"],
        "acid_id":    acid_id,
        "context":    context,
        "is_read":    False,
        "created_at": now,
    }
    result = await db.notifications.insert_one(doc)
    notif_id = str(result.inserted_id)

    # ── 2. بث WebSocket فوري ──────────────────────────────────
    await ws_manager.broadcast_user(user_id, {
        "type":       "notification",
        "notif_id":   notif_id,
        "message_ar": msg_ar,
        "message_en": msg_en,
        "notif_type": tmpl["type"],
        "icon":       tmpl["icon"],
        "created_at": now,
        "is_read":    False,
    })

    # ── 3. Hook للـ Twilio SMS — سيُرسَل بعد جلب بيانات المستخدم في الخطوة 5 ──

    # ── 4 + 5. جلب بيانات المستخدم مرة واحدة (Email + SMS) ──────
    recipient = None
    try:
        recipient = await db.users.find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(str(user_id)) else None
    except Exception:
        pass

    # ── 4. SendGrid Email — قوالب HTML احترافية ──────────────────
    if recipient and recipient.get("email") and tmpl.get("type") not in ("green_channel",):
        try:
            from services.email_service import send_event_email
            await send_event_email(template_key, recipient["email"], context)
        except Exception:
            pass  # البريد الإلكتروني غير إلزامي — لا يوقف تسليم الإشعار الداخلي

    # ── 5. Twilio SMS — (ينتظر بيانات الربط) ──────────────────
    if recipient and recipient.get("phone"):
        try:
            await _send_twilio_sms(recipient["phone"], msg_ar)
        except Exception:
            pass  # SMS غير إلزامي

    return notif_id


# ═══════════════════════════════════════════════════════════════
# Stub Functions — جاهزة للربط الخارجي
# ═══════════════════════════════════════════════════════════════

import os
import asyncio
import logging
from functools import partial

_sms_logger = logging.getLogger(__name__)


def _normalize_phone(phone: str) -> str:
    """تحويل الأرقام الليبية إلى صيغة E.164 (+218...)"""
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("0") and len(phone) >= 9:
        phone = "+218" + phone[1:]
    elif phone.startswith("218") and not phone.startswith("+"):
        phone = "+" + phone
    elif not phone.startswith("+"):
        phone = "+218" + phone
    return phone


async def _send_twilio_sms(phone: str, message: str):
    """
    Twilio SMS — إرسال رسالة نصية.
    يتطلب: TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_FROM_NUMBER في .env
    إذا لم تُضبط المتغيرات يتحول تلقائياً لـ Mock Mode (يسجّل فقط بدون إرسال).
    """
    sid   = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_ = os.environ.get("TWILIO_FROM_NUMBER", "")

    if not all([sid, token, from_]):
        _sms_logger.info(f"[SMS MOCK] → {phone}: {message[:60]}...")
        return

    try:
        from twilio.rest import Client as TwilioClient
        normalized = _normalize_phone(phone)
        # Twilio SDK هو Synchronous — نُشغِّله في thread pool لعدم حجب event loop
        loop = asyncio.get_event_loop()
        func = partial(_do_twilio_send, sid, token, from_, normalized, message)
        await loop.run_in_executor(None, func)
        _sms_logger.info(f"[SMS OK] → {normalized}")
    except ImportError:
        _sms_logger.error("[SMS ERROR] مكتبة twilio غير مثبتة. شغّل: pip install twilio")
    except Exception as exc:
        _sms_logger.error(f"[SMS ERROR] {exc}")


def _do_twilio_send(sid: str, token: str, from_: str, to: str, body: str):
    """الإرسال الفعلي في thread منفصل."""
    from twilio.rest import Client as TwilioClient
    client = TwilioClient(sid, token)
    client.messages.create(body=body, from_=from_, to=to)


async def _send_twilio_whatsapp(phone: str, message: str):
    """
    Twilio WhatsApp Hook — سيُفعَّل عند توفر المفاتيح.
    Required env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER
    """
    sid   = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_wa = os.environ.get("TWILIO_WHATSAPP_NUMBER", "")

    if not all([sid, token, from_wa]):
        _sms_logger.info(f"[WHATSAPP MOCK] → {phone}: {message[:60]}...")
        return

    try:
        normalized = _normalize_phone(phone)
        loop = asyncio.get_event_loop()
        func = partial(_do_twilio_send, sid, token, f"whatsapp:{from_wa}", f"whatsapp:{normalized}", message)
        await loop.run_in_executor(None, func)
        _sms_logger.info(f"[WHATSAPP OK] → {normalized}")
    except Exception as exc:
        _sms_logger.error(f"[WHATSAPP ERROR] {exc}")


async def _send_sendgrid_email(to_email: str, subject: str, body_html: str):
    """
    SendGrid Email Hook — مُفعَّل عبر email_service.py
    Required env vars: SENDGRID_API_KEY, SENDGRID_FROM_EMAIL
    """
    try:
        from services.email_service import _dispatch
        await _dispatch(to_email, subject, body_html)
    except Exception as exc:
        _sms_logger.error(f"[EMAIL ERROR] {exc}")



# ═══════════════════════════════════════════════════════════════
# notify_role_users — إشعار جميع مستخدمي دور معين
# ═══════════════════════════════════════════════════════════════

async def notify_role_users(
    role: str,
    template_key: str,
    context: dict,
    acid_id: Optional[str] = None,
    exclude_user_id: Optional[str] = None,
) -> int:
    """
    يُرسل إشعاراً لجميع المستخدمين النشطين بدور معين.
    يُستخدم لإشعار الضباط عند وصول مهمة جديدة لطابورهم.

    Returns: عدد المستخدمين الذين أُرسل لهم الإشعار
    """
    users = await db.users.find(
        {"role": role, "is_active": True, "account_status": "approved"},
        {"_id": 1},
    ).to_list(200)

    sent = 0
    for u in users:
        uid = str(u["_id"])
        if exclude_user_id and uid == exclude_user_id:
            continue
        try:
            await send_notification(uid, template_key, context, acid_id=acid_id)
            sent += 1
        except Exception:
            pass
    return sent
