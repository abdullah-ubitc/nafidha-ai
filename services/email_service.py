"""
خدمة البريد الإلكتروني — SendGrid Integration
NAFIDHA — Libya National Single Window for Customs
قوالب HTML احترافية لكل حالات دورة العمل
"""
import os
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, From, To, Subject, Content

logger = logging.getLogger(__name__)

_SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "lybiacustoms@gmail.com")
_SENDER_NAME  = "مصلحة الجمارك الليبية | NAFIDHA Customs"
_FRONTEND_URL = os.environ.get("FRONTEND_BASE_URL", "https://libya-customs-acis.preview.emergentagent.com")


def _get_sg() -> SendGridAPIClient | None:
    key = os.environ.get("SENDGRID_API_KEY", "")
    if not key or key.startswith("SG.placeholder"):
        return None
    return SendGridAPIClient(key)


async def _dispatch(to_email: str, subject: str, html: str) -> bool:
    """الإرسال الفعلي عبر SendGrid."""
    sg = _get_sg()
    if not sg:
        logger.warning(f"[EMAIL MOCK] '{subject}' → {to_email}")
        return False
    try:
        msg = Mail(
            from_email=From(_SENDER_EMAIL, _SENDER_NAME),
            to_emails=To(to_email),
            subject=Subject(subject),
            html_content=Content("text/html", html),
        )
        resp = sg.send(msg)
        logger.info(f"[EMAIL OK] {resp.status_code} → {to_email}")
        return resp.status_code in (200, 202)
    except Exception as exc:
        logger.error(f"[EMAIL ERROR] {exc}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# المكوّن الأساسي لقوالب HTML — البصمة المرئية الموحّدة لمصلحة الجمارك
# ══════════════════════════════════════════════════════════════════════════════

def _base(
    status_label_ar: str,
    status_label_en: str,
    accent:          str,          # لون الهوية البصرية للحالة
    body_ar:         str,          # المحتوى العربي الرئيسي
    body_en:         str,          # المحتوى الإنجليزي الثانوي
    details_html:    str  = "",    # جدول التفاصيل (اختياري)
    cta_url:         str  = None,  # رابط زر الإجراء
    cta_label:       str  = None,  # نص زر الإجراء
    warning_html:    str  = "",    # تنبيه إضافي (اختياري)
) -> str:
    cta_block = ""
    if cta_url and cta_label:
        cta_block = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 8px;">
          <tr><td align="center">
            <a href="{cta_url}"
               style="display:inline-block;background:{accent};color:#fff;text-decoration:none;
                      padding:14px 44px;border-radius:12px;font-size:14px;font-weight:700;
                      letter-spacing:0.5px;box-shadow:0 4px 14px rgba(0,0,0,0.2);">
              {cta_label}
            </a>
          </td></tr>
        </table>"""

    warning_block = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:20px;">
          <tr><td style="background:#fefce8;border:1px solid #fde047;border-radius:10px;padding:14px 18px;">
            {warning_html}
          </td></tr>
        </table>""" if warning_html else ""

    return f"""<!DOCTYPE html>
<html lang="ar">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NAFIDHA — {status_label_en}</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Tahoma,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:36px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
       style="max-width:600px;width:100%;border-radius:18px;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,0.12);">

  <!-- ─── HEADER ──────────────────────────────────────────────── -->
  <tr>
    <td style="background:linear-gradient(135deg,#0f2644 0%,#1e3a5f 65%,#1a4a7a 100%);padding:32px 40px;text-align:center;">
      <div style="display:inline-block;background:rgba(212,160,23,0.18);border:1px solid rgba(212,160,23,0.45);
                  border-radius:9px;padding:6px 18px;margin-bottom:14px;">
        <span style="color:#d4a017;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;">
          الإدارة العامة للجمارك الليبية
        </span>
      </div>
      <h1 style="color:#fff;margin:0 0 5px;font-size:24px;font-weight:800;letter-spacing:-0.3px;">NAFIDHA Customs</h1>
      <p style="color:#93b8d8;margin:0;font-size:12px;">Libya National Single Window · منظومة التخليص الجمركي الرقمي</p>
    </td>
  </tr>

  <!-- ─── STATUS BANNER ───────────────────────────────────────── -->
  <tr>
    <td style="background:{accent};padding:10px 40px;text-align:center;">
      <span style="color:#fff;font-size:12px;font-weight:800;letter-spacing:1px;text-transform:uppercase;">
        {status_label_en} &nbsp;·&nbsp; {status_label_ar}
      </span>
    </td>
  </tr>

  <!-- ─── BODY ─────────────────────────────────────────────────── -->
  <tr>
    <td style="background:#fff;padding:32px 40px;" dir="rtl">
      <div style="color:#1f2937;font-size:15px;line-height:1.8;margin-bottom:16px;">{body_ar}</div>
      {details_html}
      {cta_block}
      {warning_block}
      <hr style="border:none;border-top:1px solid #f1f5f9;margin:24px 0 16px;">
      <p style="color:#9ca3af;font-size:12px;direction:ltr;text-align:left;">{body_en}</p>
    </td>
  </tr>

  <!-- ─── FOOTER ───────────────────────────────────────────────── -->
  <tr>
    <td style="background:#0f2644;padding:20px 40px;text-align:center;">
      <p style="color:#d4a017;font-size:12px;font-weight:700;margin:0 0 5px;">
        الجمهورية الليبية — الإدارة العامة للجمارك
      </p>
      <p style="color:#3d6185;font-size:11px;margin:0;">
        This is an automated message from NAFIDHA Digital Platform. Please do not reply to this email.
        &nbsp;·&nbsp; <a href="mailto:{_SENDER_EMAIL}" style="color:#5b87b5;">{_SENDER_EMAIL}</a>
      </p>
    </td>
  </tr>

</table>
</td></tr>
</table>
</body></html>"""


def _detail_row(label: str, value: str, color: str = "#1f2937") -> str:
    return f"""<tr style="border-bottom:1px solid #f8fafc;">
      <td style="padding:9px 0;color:#9ca3af;font-size:11px;font-weight:700;width:42%;text-transform:uppercase;letter-spacing:0.5px;">{label}</td>
      <td style="padding:9px 0;color:{color};font-size:13px;font-weight:600;">{value}</td>
    </tr>"""


def _details_table(*rows: str) -> str:
    return f"""<table width="100%" cellpadding="0" cellspacing="0"
               style="border-collapse:collapse;margin:16px 0 20px;background:#f8fafc;
                      border-radius:12px;overflow:hidden;padding:0 16px;">
               <tr><td colspan="2" style="padding:12px 16px 0;"></td></tr>
               {''.join(rows)}
               <tr><td colspan="2" style="padding:0 0 8px;"></td></tr>
             </table>"""


# ══════════════════════════════════════════════════════════════════════════════
# ① تأكيد البريد الإلكتروني (Email Verification)
# ══════════════════════════════════════════════════════════════════════════════
def _tpl_email_verification(ctx: dict):
    name        = ctx.get("name", "")
    verify_url  = ctx.get("verify_url", "#")
    subject = "[NAFIDHA] تأكيد بريدك الإلكتروني | Email Verification Required"
    html = _base(
        status_label_ar = "تأكيد الحساب",
        status_label_en = "Account Verification",
        accent          = "#1e3a5f",
        body_ar = f"""مرحباً <strong>{name}</strong>،<br><br>
شكراً لتسجيلك في منظومة <strong>نافذة الجمارك الليبية</strong>.<br>
لاستكمال طلب التسجيل وإدخاله دورة مراجعة مأمور التسجيل الجمركي،
يُرجى الضغط على الزر أدناه <strong>لتأكيد بريدك الإلكتروني</strong> خلال <u>24 ساعة</u> من استلام هذه الرسالة.""",
        body_en = f"Dear {name}, please verify your email to activate your NAFIDHA account and enter the KYC review process.",
        cta_url   = verify_url,
        cta_label = "✓ تأكيد بريدي الإلكتروني — Verify My Email",
        warning_html = f"""<p style="margin:0;color:#713f12;font-size:12px;line-height:1.6;">
          <strong>⚠ ملاحظة:</strong> إذا لم تقم بالتسجيل في منظومة نافذة الجمارك الليبية، يُرجى تجاهل هذه الرسالة.
          رابط التأكيد: <a href="{verify_url}" style="color:#b45309;word-break:break-all;">{verify_url}</a>
        </p>"""
    )
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
# ② KYC — قبول الحساب
# ══════════════════════════════════════════════════════════════════════════════
def _tpl_kyc_approved(ctx: dict):
    name     = ctx.get("name", "")
    login_url = f"{_FRONTEND_URL}/login"
    subject = f"[NAFIDHA] 🎉 تم اعتماد حسابك في منظومة الجمارك الليبية"
    html = _base(
        status_label_ar = "الحساب معتمد",
        status_label_en = "Account Approved",
        accent          = "#16a34a",
        body_ar = f"""تهانينا <strong>{name}</strong>! 🎉<br><br>
يسرّنا إعلامكم بأن مأمور التسجيل الجمركي قد <strong>اعتمد حسابكم</strong> في منظومة نافذة الجمارك الليبية (NAFIDHA).<br>
يمكنكم الآن تسجيل الدخول والبدء في تقديم طلبات التخليص الجمركي وإجراءات الاستيراد والتصدير.""",
        body_en = f"Congratulations {name}! Your NAFIDHA account has been approved. You can now log in and access all customs services.",
        cta_url   = login_url,
        cta_label = "تسجيل الدخول — Log In to NAFIDHA",
    )
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
# ③ KYC — رفض الحساب
# ══════════════════════════════════════════════════════════════════════════════
def _tpl_kyc_rejected(ctx: dict):
    name   = ctx.get("name", "")
    reason = ctx.get("reason", "لم يُذكر سبب محدد")
    subject = "[NAFIDHA] نتيجة طلب التسجيل — Registration Decision"
    html = _base(
        status_label_ar = "الطلب مرفوض",
        status_label_en = "Registration Rejected",
        accent          = "#dc2626",
        body_ar = f"""عزيزي {name}،<br><br>
نأسف لإبلاغكم بأن مأمور التسجيل الجمركي قد <strong>رفض طلب تسجيلكم</strong> في منظومة نافذة الجمارك الليبية.<br>
يمكنكم التواصل مع مصلحة الجمارك لمزيد من التوضيحات أو تقديم طلب جديد بوثائق مُحدَّثة.""",
        body_en = f"Dear {name}, your NAFIDHA registration request has been rejected.",
        details_html = _details_table(
            _detail_row("سبب الرفض / Reason", reason, "#dc2626"),
        ),
        warning_html = """<p style="margin:0;color:#713f12;font-size:12px;">
          للاستفسار أو الاعتراض، تواصل مع مصلحة الجمارك مباشرةً على:
          <a href="mailto:lybiacustoms@gmail.com" style="color:#b45309;">lybiacustoms@gmail.com</a>
        </p>"""
    )
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
# ④ KYC — طلب تصحيح الوثائق
# ══════════════════════════════════════════════════════════════════════════════
def _tpl_kyc_correction(ctx: dict):
    name   = ctx.get("name", "")
    notes  = ctx.get("notes", "")
    subject = "[NAFIDHA] ⚠️ مطلوب تصحيح وثائقك | Document Correction Required"
    html = _base(
        status_label_ar = "مطلوب تعديل",
        status_label_en = "Correction Required",
        accent          = "#d97706",
        body_ar = f"""عزيزي {name}،<br><br>
قام مأمور التسجيل الجمركي بمراجعة وثائقكم وطلب <strong>تصحيح بعض المستندات</strong>.
يُرجى تسجيل الدخول لمنظومة نافذة ورفع الوثائق الصحيحة.""",
        body_en = f"Dear {name}, document correction has been requested for your NAFIDHA account.",
        details_html = _details_table(
            _detail_row("ملاحظات المأمور / Officer Notes", notes, "#92400e"),
        ),
        cta_url   = f"{_FRONTEND_URL}/login",
        cta_label = "رفع الوثائق المصحَّحة — Upload Corrected Documents",
    )
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ ACID — تأكيد الاستلام للمستورد
# ══════════════════════════════════════════════════════════════════════════════
def _tpl_acid_submitted(ctx: dict):
    acid_number = ctx.get("acid_number", "")
    name        = ctx.get("name", "")
    subject = f"[NAFIDHA] تم استلام طلب ACID رقم {acid_number}"
    html = _base(
        status_label_ar = "تم الاستلام",
        status_label_en = "ACID Submitted",
        accent          = "#2563eb",
        body_ar = f"""عزيزي {name}،<br><br>
تم استلام طلب التصاريح المسبقة للبضائع (ACID) رقم <strong style="font-family:monospace;font-size:16px;">{acid_number}</strong>
وسيُراجَع قريباً من ضباط الجمارك المختصين.""",
        body_en = f"Dear {name}, your ACID request {acid_number} has been received and is pending review.",
        details_html = _details_table(
            _detail_row("رقم ACID", acid_number, "#1d4ed8"),
            _detail_row("الحالة / Status", "قيد المراجعة — Pending Review", "#6b7280"),
        ),
    )
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
# ⑥ ACID — الاعتماد
# ══════════════════════════════════════════════════════════════════════════════
def _tpl_acid_approved(ctx: dict):
    acid_number = ctx.get("acid_number", "")
    name        = ctx.get("name", "")
    subject = f"[NAFIDHA] ✅ تم اعتماد طلب ACID رقم {acid_number}"
    html = _base(
        status_label_ar = "ACID معتمد",
        status_label_en = "ACID Approved",
        accent          = "#16a34a",
        body_ar = f"""عزيزي {name}،<br><br>
يسرّنا إبلاغكم بأن طلب ACID رقم <strong style="font-family:monospace;font-size:16px;">{acid_number}</strong>
قد تم <strong>اعتماده بنجاح</strong>. يمكنكم الآن متابعة إجراءات التخليص الجمركي.""",
        body_en = f"Dear {name}, ACID request {acid_number} has been approved. Proceed to customs clearance.",
        details_html = _details_table(
            _detail_row("رقم ACID", acid_number, "#15803d"),
            _detail_row("الحالة / Status", "معتمد — Approved ✓", "#16a34a"),
        ),
        cta_url   = f"{_FRONTEND_URL}/dashboard",
        cta_label = "متابعة إجراءات التخليص — Continue Clearance",
    )
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
# ⑦ ACID — الرفض
# ══════════════════════════════════════════════════════════════════════════════
def _tpl_acid_rejected(ctx: dict):
    acid_number = ctx.get("acid_number", "")
    name        = ctx.get("name", "")
    reason      = ctx.get("reason", "")
    subject = f"[NAFIDHA] ❌ طلب ACID رقم {acid_number} — قرار الرفض"
    html = _base(
        status_label_ar = "ACID مرفوض",
        status_label_en = "ACID Rejected",
        accent          = "#dc2626",
        body_ar = f"""عزيزي {name}،<br><br>
نُفيدكم بأن طلب ACID رقم <strong style="font-family:monospace;">{acid_number}</strong> قد رُفض من قِبَل ضباط الجمارك.
يمكنكم تقديم طلب جديد بعد مراجعة الأسباب.""",
        body_en = f"Dear {name}, ACID request {acid_number} has been rejected.",
        details_html = _details_table(
            _detail_row("رقم ACID", acid_number),
            _detail_row("سبب الرفض / Reason", reason or "—", "#dc2626"),
        ),
    )
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
# ⑧ ACID — طلب تعديل
# ══════════════════════════════════════════════════════════════════════════════
def _tpl_acid_amendment(ctx: dict):
    acid_number = ctx.get("acid_number", "")
    name        = ctx.get("name", "")
    notes       = ctx.get("notes", "")
    subject = f"[NAFIDHA] ⚠️ طلب ACID رقم {acid_number} يحتاج تعديلات"
    html = _base(
        status_label_ar = "تعديل مطلوب",
        status_label_en = "Amendment Required",
        accent          = "#d97706",
        body_ar = f"""عزيزي {name}،<br><br>
طلب ACID رقم <strong style="font-family:monospace;">{acid_number}</strong>
يحتاج إلى <strong>تعديلات</strong> قبل المتابعة. راجع الملاحظات أدناه وأعد تقديم الطلب.""",
        body_en = f"Dear {name}, ACID request {acid_number} requires amendments.",
        details_html = _details_table(
            _detail_row("رقم ACID", acid_number),
            _detail_row("ملاحظات الضابط", notes or "—", "#92400e"),
        ),
        cta_url   = f"{_FRONTEND_URL}/dashboard",
        cta_label = "تعديل الطلب — Amend Request",
    )
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
# ⑨ المصدر الأجنبي — دعوة تأكيد الشحنة
# ══════════════════════════════════════════════════════════════════════════════
def _html_supplier_invitation(
    supplier_name: str, acid_number: str, importer_name: str,
    goods_desc: str, value_usd: float, hs_code: str, confirm_url: str,
) -> str:
    rows = "".join([
        _detail_row(label, value)
        for label, value in [
            ("Supplier / Exporter", supplier_name),
            ("Goods Description",   goods_desc[:80] + ("..." if len(goods_desc) > 80 else "")),
            ("HS Code",             hs_code or "—"),
            ("Declared Value",      f"USD {value_usd:,.2f}"),
            ("Importing Party",     importer_name),
        ]
    ])
    details = f"""<table width="100%" cellpadding="0" cellspacing="0"
              style="border-collapse:collapse;margin:16px 0 20px;background:#f8fafc;border-radius:12px;">
              <tr><td colspan="2" style="padding:12px 16px 0;"></td></tr>
              {rows}
              <tr><td colspan="2" style="padding:0 0 8px;"></td></tr>
            </table>"""
    html = _base(
        status_label_ar = "تأكيد بيانات الشحنة",
        status_label_en = "Shipment Confirmation Required",
        accent          = "#d4a017",
        body_ar = f"""Dear <strong>{supplier_name}</strong>,<br><br>
The Libyan importer <strong>{importer_name}</strong> has filed an <strong>ACID Declaration</strong>
with Libyan Customs referencing your shipment. Your confirmation is required to proceed.""",
        body_en = f"ACID Reference: {acid_number}  ·  Please review and confirm the shipment data.",
        details_html = details,
        cta_url   = confirm_url,
        cta_label = "✓ Confirm Shipment Data — تأكيد بيانات الشحنة",
        warning_html = f"""<p style="margin:0;color:#713f12;font-size:12px;">
          If you did not authorize this shipment, do <strong>not</strong> click confirm.
          Contact: <a href="mailto:{_SENDER_EMAIL}" style="color:#b45309;">{_SENDER_EMAIL}</a>
        </p>"""
    )
    return html


# ══════════════════════════════════════════════════════════════════════════════
# قوالب المصدر الأجنبي — إشعارات التوثيق وطلبات ACID
# ══════════════════════════════════════════════════════════════════════════════

def _tpl_exporter_verified(ctx: dict):
    """بريد تأكيد التوثيق — المصدر حصل على الشارة"""
    company  = ctx.get("company_name", "شركتكم")
    tax_id   = ctx.get("tax_id", "")
    expiry   = ctx.get("expires_at", "")
    email    = ctx.get("email", "")
    portal   = f"{_FRONTEND_URL}/dashboard/exporter"
    subject  = f"[NAFIDHA] ✅ تم توثيق حساب المصدر — {company}"
    details  = f"""<table width="100%" cellpadding="6" cellspacing="0">
      <tr><td style="color:#374151;font-size:13px;padding:6px 0;border-bottom:1px solid #f3f4f6">الشركة</td>
          <td style="font-weight:700;color:#1f2937;text-align:left">{company}</td></tr>
      <tr><td style="color:#374151;font-size:13px;padding:6px 0;border-bottom:1px solid #f3f4f6">رقم الضريبة</td>
          <td style="font-weight:700;color:#1f2937;font-family:monospace;text-align:left">{tax_id}</td></tr>
      <tr><td style="color:#374151;font-size:13px;padding:6px 0;border-bottom:1px solid #f3f4f6">البريد</td>
          <td style="font-weight:700;color:#1f2937;text-align:left">{email}</td></tr>
      <tr><td style="color:#374151;font-size:13px;padding:6px 0">صلاحية التوثيق</td>
          <td style="font-weight:700;color:#059669;text-align:left">{expiry[:10] if expiry else 'سنة واحدة'}</td></tr>
    </table>"""
    html = _base(
        status_label_ar = "تم التوثيق — شارة المصدر الموثّق",
        status_label_en = "Verified Exporter Badge Activated",
        accent          = "#059669",
        body_ar = f"""مبروك <strong>{company}</strong>!<br><br>
تم تفعيل حسابك في نظام NAFIDHA للجمارك الليبية وحصولك على <strong>شارة المصدر الموثّق</strong>.
يمكنك الآن تلقّي طلبات ACID ومتابعة شحناتك عبر بوابة المصدر.""",
        body_en = f"Your exporter account has been verified. Tax ID: {tax_id}",
        details_html = details,
        cta_url   = portal,
        cta_label = "🏛️ ادخل بوابة المصدر — Enter Exporter Portal",
    )
    return subject, html


def _tpl_acid_assigned_to_exporter(ctx: dict):
    """بريد إشعار للمصدر بوجود طلب ACID مرتبط بشركته"""
    company      = ctx.get("company_name", "شركتكم")
    acid_number  = ctx.get("acid_number", "")
    importer     = ctx.get("importer_name", "المستورد")
    port         = ctx.get("port_of_entry", "")
    goods        = ctx.get("goods_description", "")
    acid_id      = ctx.get("acid_id", "")
    acid_url     = f"{_FRONTEND_URL}/acid/{acid_id}"
    subject      = f"[NAFIDHA] 📦 طلب ACID جديد مرتبط بشركتكم — {acid_number}"
    details      = f"""<table width="100%" cellpadding="6" cellspacing="0">
      <tr><td style="color:#374151;font-size:13px;padding:6px 0;border-bottom:1px solid #f3f4f6">رقم ACID</td>
          <td style="font-weight:700;color:#1f2937;font-family:monospace;text-align:left">{acid_number}</td></tr>
      <tr><td style="color:#374151;font-size:13px;padding:6px 0;border-bottom:1px solid #f3f4f6">المستورد</td>
          <td style="font-weight:700;color:#1f2937;text-align:left">{importer}</td></tr>
      <tr><td style="color:#374151;font-size:13px;padding:6px 0;border-bottom:1px solid #f3f4f6">منفذ الدخول</td>
          <td style="font-weight:700;color:#1f2937;text-align:left">{port}</td></tr>
      <tr><td style="color:#374151;font-size:13px;padding:6px 0">البضاعة</td>
          <td style="color:#374151;text-align:left">{goods[:80] if goods else '—'}</td></tr>
    </table>"""
    html = _base(
        status_label_ar = "طلب ACID — يحتاج تأكيدكم",
        status_label_en = f"New ACID Request · {acid_number}",
        accent          = "#1e3a5f",
        body_ar = f"""عزيزي المصدر <strong>{company}</strong>،<br><br>
تم إنشاء طلب جمركي (ACID) في منظومة NAFIDHA يشير إلى شركتكم.
يمكنكم مراجعة البيانات وتأكيد صحة الشحنة عبر البوابة.""",
        body_en = f"A new ACID declaration {acid_number} references your company.",
        details_html = details,
        cta_url   = acid_url,
        cta_label = "📋 عرض طلب ACID — View ACID Declaration",
    )
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
# ⑩ إعادة تعيين كلمة المرور
# ══════════════════════════════════════════════════════════════════════════════
def _tpl_password_reset(ctx: dict):
    name       = ctx.get("name", "")
    reset_url  = ctx.get("reset_url", "#")
    subject = "[NAFIDHA] إعادة تعيين كلمة المرور | Password Reset Request"
    html = _base(
        status_label_ar = "إعادة كلمة المرور",
        status_label_en = "Password Reset",
        accent          = "#7c3aed",
        body_ar = f"""مرحباً <strong>{name}</strong>،<br><br>
تلقّينا طلباً لإعادة تعيين كلمة المرور المرتبطة بحسابك في منظومة <strong>نافذة الجمارك الليبية</strong>.<br>
اضغط على الزر أدناه لتعيين كلمة مرور جديدة. <strong>الرابط صالح لمدة ساعة واحدة</strong> فقط من وقت الطلب.""",
        body_en = f"Dear {name}, we received a request to reset your NAFIDHA account password. Click the button below. This link expires in 1 hour.",
        cta_url   = reset_url,
        cta_label = "🔐 إعادة تعيين كلمة المرور — Reset My Password",
        warning_html = f"""<p style="margin:0;color:#713f12;font-size:12px;line-height:1.6;">
          <strong>⚠ تنبيه أمني:</strong> إذا لم تطلب إعادة تعيين كلمة المرور، يُرجى تجاهل هذه الرسالة — حسابك آمن.<br>
          رابط إعادة التعيين: <a href="{reset_url}" style="color:#b45309;word-break:break-all;">{reset_url}</a>
        </p>"""
    )
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
# الدالة الرئيسية للإرسال الموحَّد — event dispatcher
# ══════════════════════════════════════════════════════════════════════════════
_DISPATCHERS = {
    "email_verification":          _tpl_email_verification,
    "kyc_approved":                _tpl_kyc_approved,
    "kyc_rejected":                _tpl_kyc_rejected,
    "kyc_correction_requested":    _tpl_kyc_correction,
    "acid_submitted":              _tpl_acid_submitted,
    "acid_approved":               _tpl_acid_approved,
    "acid_rejected":               _tpl_acid_rejected,
    "acid_amendment_required":     _tpl_acid_amendment,
    "exporter_verified":           _tpl_exporter_verified,
    "acid_assigned_to_exporter":   _tpl_acid_assigned_to_exporter,
    "password_reset":              _tpl_password_reset,
}


async def send_event_email(template_key: str, to_email: str, ctx: dict) -> bool:
    """
    إرسال إيميل HTML احترافي بناءً على مفتاح القالب.
    يُستدعى من notification_service و auth routes.
    """
    fn = _DISPATCHERS.get(template_key)
    if not fn:
        logger.debug(f"[EMAIL] No template for: {template_key}")
        return False
    try:
        subject, html = fn(ctx)
        return await _dispatch(to_email, subject, html)
    except Exception as exc:
        logger.error(f"[EMAIL ERROR] template={template_key}: {exc}")
        return False


async def send_supplier_invitation(
    to_email: str, supplier_name: str, acid_number: str,
    importer_name: str, goods_desc: str, value_usd: float,
    hs_code: str, confirm_url: str,
) -> bool:
    """إرسال دعوة تأكيد الشحنة للمصدر الأجنبي."""
    html    = _html_supplier_invitation(supplier_name, acid_number, importer_name,
                                        goods_desc, value_usd, hs_code, confirm_url)
    subject = f"[NAFIDHA Customs] Action Required — Shipment Confirmation · ACID {acid_number}"
    return await _dispatch(to_email, subject, html)


async def send_acid_status_update(
    to_email: str, name: str, acid_number: str, status: str, notes: str = "",
) -> bool:
    """تحديث حالة ACID للمستورد (يُستدعى من notifications.py)."""
    key_map = {
        "approved":           "acid_approved",
        "rejected":           "acid_rejected",
        "under_review":       None,
        "amendment_required": "acid_amendment_required",
    }
    key = key_map.get(status)
    if not key:
        return False
    return await send_event_email(key, to_email, {"name": name, "acid_number": acid_number, "reason": notes, "notes": notes})
