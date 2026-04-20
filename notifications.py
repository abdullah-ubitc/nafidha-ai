"""Email (SendGrid) and WhatsApp (Mock) notification services"""
import os
import logging
from datetime import datetime, timezone
from bson import ObjectId
from database import db
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, To, From, Content, Subject

logger = logging.getLogger(__name__)


async def send_whatsapp(to_number: str, recipient_name: str, message_ar: str,
                        event_type: str, acid_id: str = ""):
    """Mock WhatsApp notification — logs to whatsapp_logs"""
    await db.whatsapp_logs.insert_one({
        "to_number": to_number or "N/A",
        "recipient_name": recipient_name,
        "message_ar": message_ar,
        "event_type": event_type,
        "acid_id": acid_id,
        "status": "mock_sent",
        "sent_at": datetime.now(timezone.utc)
    })
    logger.info(f"[WHATSAPP MOCK] {event_type} → {recipient_name}: {message_ar[:80]}")


async def notify_user_whatsapp(user_id: str, message_ar: str, event_type: str, acid_id: str = ""):
    if not user_id or not ObjectId.is_valid(user_id):
        return
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if user:
        phone = user.get("phone") or user.get("mobile") or "N/A"
        await send_whatsapp(phone, user.get("name_ar", ""), message_ar, event_type, acid_id)


async def send_acid_status_email(recipient_email: str, recipient_name: str, acid_number: str,
                                  new_status: str, notes: str = ""):
    sg_key = os.environ.get("SENDGRID_API_KEY", "")
    sender_email = os.environ.get("SENDER_EMAIL", "lybiacustoms@gmail.com")
    if not sg_key or sg_key.startswith("SG.placeholder"):
        logger.info(f"[EMAIL MOCK] Would send {new_status} email to {recipient_email} for {acid_number}")
        return False
    status_labels = {
        "approved": {"ar": "معتمد ✓", "en": "Approved ✓", "color": "#22c55e"},
        "rejected": {"ar": "مرفوض ✗", "en": "Rejected ✗", "color": "#ef4444"},
        "under_review": {"ar": "قيد المراجعة", "en": "Under Review", "color": "#f59e0b"},
        "amendment_required": {"ar": "يحتاج تعديل", "en": "Amendment Required", "color": "#8b5cf6"},
    }
    lbl = status_labels.get(new_status, {"ar": new_status, "en": new_status, "color": "#1e3a5f"})
    next_steps = {
        "approved": {"ar": "يمكنك الآن إنشاء نموذج SAD وتقديم مرجع التحويل المصرفي CBL.", "en": "You can now create a SAD form and submit the CBL bank transfer reference."},
        "rejected": {"ar": "يُرجى مراجعة الملاحظات والتواصل مع مكتب الجمارك.", "en": "Please review the notes and contact the customs office."},
        "amendment_required": {"ar": "يُرجى تعديل طلبك وإعادة تقديمه.", "en": "Please amend your request and resubmit."},
        "under_review": {"ar": "سيتم إخطارك فور اتخاذ قرار.", "en": "You will be notified once a decision is made."},
    }
    step = next_steps.get(new_status, {"ar": "", "en": ""})
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f8f9fa;margin:0;padding:20px;">
<div style="max-width:600px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.1);">
<div style="background:#1e3a5f;padding:24px;text-align:center;">
  <h1 style="color:white;margin:0;font-size:22px;">نافذة الجمارك الليبية</h1>
  <p style="color:#d4a017;margin:4px 0 0;font-size:13px;">NAFIDHA — Libya Customs Digital Single Window</p>
</div>
<div style="padding:28px;">
  <div style="text-align:right;direction:rtl;margin-bottom:24px;">
    <h2 style="color:#1e3a5f;margin:0 0 8px;">تحديث حالة طلب ACID</h2>
    <p style="color:#555;margin:0;">عزيزي {recipient_name}،</p>
    <p style="color:#555;">تم تحديث حالة طلبك رقم <strong style="color:#1e3a5f;font-family:monospace;">{acid_number}</strong> إلى:</p>
    <div style="background:{lbl['color']}15;border:2px solid {lbl['color']};border-radius:8px;padding:12px;text-align:center;margin:16px 0;">
      <span style="font-size:20px;font-weight:bold;color:{lbl['color']};">{lbl['ar']}</span>
    </div>
    {f'<p style="color:#555;background:#fff3cd;padding:12px;border-radius:8px;border-right:4px solid #f59e0b;"><strong>ملاحظة:</strong> {notes}</p>' if notes else ''}
    <p style="color:#555;"><strong>الخطوات التالية:</strong><br>{step['ar']}</p>
  </div>
</div>
<div style="background:#1e3a5f;padding:16px;text-align:center;">
  <p style="color:#aab;font-size:11px;margin:0;">الجمهورية الليبية — الإدارة العامة للجمارك</p>
</div>
</div>
</body></html>"""
    try:
        message = Mail(
            from_email=From(sender_email, "نافذة الجمارك الليبية NAFIDHA"),
            to_emails=To(recipient_email),
            subject=Subject(f"[NAFIDHA] طلب ACID {acid_number} — {lbl['ar']} | {lbl['en']}"),
            html_content=Content("text/html", html)
        )
        sg = SendGridAPIClient(sg_key)
        resp = sg.send(message)
        logger.info(f"Email sent to {recipient_email}: {resp.status_code}")
        return True
    except Exception as e:
        logger.error(f"SendGrid error: {e}")
        return False
