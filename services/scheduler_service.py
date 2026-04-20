"""
scheduler_service.py — خدمة المهام الآلية (Automated CRON Jobs)
════════════════════════════════════════════════════════════════
المهمة الأساسية:
  • كل يوم الساعة 9:00 صباحاً: يقرأ نطاق التنبيه من system_settings (أو LICENSE_EXPIRY_WARN_DAYS env)
  • يفحص قاعدة البيانات للرخص في النطاق، ويُرسل إشعارات التجديد
  • يسجّل النتيجة في Audit Log بـ user_name = "النظام الآلي"
  • كل خميس 17:00 UTC: يُولِّد PDF أسبوعي + يُرسله بالبريد لجميع المدراء
"""
import os
import base64
import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import db
from services.notification_service import send_notification

logger = logging.getLogger("scheduler")

_DEFAULT_WARN_DAYS  = int(os.environ.get("LICENSE_EXPIRY_WARN_DAYS", "30"))
_SETTINGS_DOC_ID    = "kyc_settings"
_DEFAULT_HOUR       = 9
_DEFAULT_MINUTE     = 0

_COMMERCIAL_ROLES = [
    "importer", "customs_broker", "carrier_agent", "foreign_supplier"
]

_ACID_STATUSES = ["submitted", "pending", "under_review"]
_KYC_ROLES     = _COMMERCIAL_ROLES

_scheduler: AsyncIOScheduler | None = None

# ─────────────────────────────────────────────────────────────────
# قراءة نطاق التنبيه الديناميكي
# ─────────────────────────────────────────────────────────────────

async def _fetch_warn_days() -> int:
    """يقرأ LICENSE_EXPIRY_WARN_DAYS من system_settings (DB → env var fallback)."""
    try:
        doc = await db.system_settings.find_one({"_id": _SETTINGS_DOC_ID})
        if doc and isinstance(doc.get("license_expiry_warn_days"), int):
            return doc["license_expiry_warn_days"]
    except Exception:
        pass
    return _DEFAULT_WARN_DAYS


# ─────────────────────────────────────────────────────────────────
# المهمة الأساسية
# ─────────────────────────────────────────────────────────────────

async def run_license_expiry_check(days: int | None = None) -> dict:
    """
    يفحص الرخص التجارية ويُرسل إشعارات التجديد.
    إذا لم يُمرَّر days، يُجلَب من DB تلقائياً.
    """
    if days is None:
        days = await _fetch_warn_days()

    run_start = datetime.now(timezone.utc)
    today     = run_start.date().isoformat()
    cutoff    = (run_start.date() + timedelta(days=days)).isoformat()

    logger.info(f"[CRON] بدء الفحص — نطاق: {days} يوم | {today} → {cutoff}")

    query = {
        "role":                {"$in": _COMMERCIAL_ROLES},
        "registration_status": "approved",
        "license_expiry_date": {
            "$exists": True, "$ne": None,
            "$gte": today, "$lte": cutoff,
        },
    }
    users = await db.users.find(query).to_list(500)

    sent = errors = 0
    notified = []

    for user in users:
        try:
            uid       = str(user["_id"])
            name      = user.get("name_ar") or user.get("name_en") or user.get("email", "")
            expiry    = user.get("license_expiry_date", "")
            days_left = (datetime.fromisoformat(expiry).date() - run_start.date()).days
            await send_notification(
                uid, "license_expiry_reminder",
                {"name": name, "days": str(days_left), "expiry": expiry},
                "ar",
            )
            sent += 1
            notified.append({"email": user.get("email"), "days_left": days_left})
        except Exception as exc:
            logger.error(f"[CRON] خطأ: {user.get('email')} — {exc}")
            errors += 1

    run_end  = datetime.now(timezone.utc)
    duration = round((run_end - run_start).total_seconds(), 2)

    summary = {
        "job":          "license_expiry_check",
        "triggered_at": run_start.isoformat(),
        "finished_at":  run_end.isoformat(),
        "duration_sec": duration,
        "days_window":  days,
        "total_found":  len(users),
        "sent":         sent,
        "errors":       errors,
        "notified":     notified,
    }

    await db.audit_logs.insert_one({
        "action":        "cron_license_expiry_check",
        "user_id":       "SYSTEM",
        "user_name":     "النظام الآلي",
        "resource_type": "scheduler",
        "resource_id":   "license_expiry_check",
        "details":       summary,
        "timestamp":     run_end.isoformat(),
    })

    _last_run_result.update(summary)
    logger.info(f"[CRON] انتهى — أُرسِل: {sent} | أخطاء: {errors} | {duration}ث")
    return summary


# ─────────────────────────────────────────────────────────────────
# SLA Breach Check — تنبيه المدير عند تجاوز المهمة موعدها
# ─────────────────────────────────────────────────────────────────

async def run_sla_breach_check() -> dict:
    """
    يعمل كل 15 دقيقة:
    1. يبحث عن مهام In_Progress تجاوزت wf_sla_deadline
    2. يُصعِّدها إلى Escalated ويضع علامة wf_sla_breach_notified=True
    3. يُرسل إشعار WebSocket لجميع مستخدمي admin
    4. يُسجِّل في Audit Log
    """
    now     = datetime.now(timezone.utc).isoformat()
    breach_query = {
        "wf_status":               "In_Progress",
        "wf_sla_deadline":         {"$lt": now},
        "wf_sla_breach_notified":  {"$ne": True},
    }

    kyc_breached  = await db.users.find({
        **breach_query,
        "role": {"$in": _KYC_ROLES},
    }).to_list(200)
    acid_breached = await db.acid_requests.find(breach_query).to_list(200)

    all_breached = [("kyc_review", "مراجعة KYC", db.users, d) for d in kyc_breached] + \
                   [("acid_review", "مراجعة ACID", db.acid_requests, d) for d in acid_breached]

    if not all_breached:
        return {"breaches_found": 0, "notifications_sent": 0}

    # Get all admin user IDs
    admins = await db.users.find({"role": "admin"}, {"_id": 1}).to_list(20)
    admin_ids = [str(a["_id"]) for a in admins]

    notified = 0
    for task_type, type_label, col, task in all_breached:
        task_id    = task["_id"]
        title      = task.get("name_ar") or task.get("acid_number") or str(task_id)[:8]
        assigned   = task.get("wf_assigned_to_name", "—")
        deadline   = task.get("wf_sla_deadline", now)
        try:
            dl = datetime.fromisoformat(deadline)
            if dl.tzinfo is None:
                dl = dl.replace(tzinfo=timezone.utc)
            overdue_h  = round((datetime.now(timezone.utc) - dl).total_seconds() / 3600, 1)
        except Exception:
            overdue_h = 0

        # Escalate
        await col.update_one(
            {"_id": task_id},
            {"$set": {"wf_status": "Escalated", "wf_sla_breach_notified": True,
                      "wf_escalated_at": now}},
        )

        # Notify all admins
        for admin_id in admin_ids:
            try:
                await send_notification(
                    admin_id,
                    "wf_sla_breached",
                    {
                        "task_title":       title,
                        "task_type_label":  type_label,
                        "overdue_hours":    str(overdue_h),
                        "assigned_to":      assigned,
                    },
                    "ar",
                )
                notified += 1
            except Exception as exc:
                logger.error(f"[SLA] خطأ إشعار admin: {exc}")

    # Audit Log
    await db.audit_logs.insert_one({
        "action":        "cron_sla_breach_check",
        "user_id":       "SYSTEM",
        "user_name":     "النظام الآلي",
        "resource_type": "scheduler",
        "resource_id":   "sla_breach_check",
        "details":       {
            "breaches_found":       len(all_breached),
            "notifications_sent":   notified,
            "kyc_breached":         len(kyc_breached),
            "acid_breached":        len(acid_breached),
        },
        "timestamp": now,
    })

    logger.info(f"[SLA] تحقق اكتمل — خروقات: {len(all_breached)} | إشعارات: {notified}")
    return {"breaches_found": len(all_breached), "notifications_sent": notified}


# ─────────────────────────────────────────────────────────────────
# حالة آخر تشغيل
# ─────────────────────────────────────────────────────────────────

_last_run_result: dict = {
    "job":          "license_expiry_check",
    "triggered_at": None,
    "sent":         0,
    "errors":       0,
    "status":       "waiting_for_first_run",
}


def get_last_run() -> dict:
    return dict(_last_run_result)


def get_next_run_time() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("license_expiry_check")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def get_sla_job_next_run() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("sla_breach_check")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def get_report_job_next_run() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("weekly_report_email")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def get_land_trip_escalation_next_run() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job("land_trip_escalation")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


# ─────────────────────────────────────────────────────────────────
# التقرير الأسبوعي — إرسال تلقائي كل خميس
# ─────────────────────────────────────────────────────────────────

async def run_weekly_report_email() -> dict:
    """
    يعمل كل خميس الساعة 17:00 UTC:
    1. يُولِّد تقرير PDF أسبوعي باستخدام report_service
    2. يُرسل الـ PDF عبر SendGrid لجميع مستخدمي admin (عند توفر المفاتيح)
    3. يُرسل إشعار WebSocket للمدير بجاهزية التقرير
    4. يُسجِّل في Audit Log
    """
    from services.report_service import generate_weekly_report
    now = datetime.now(timezone.utc).isoformat()
    logger.info("[RPT] بدء إنتاج التقرير الأسبوعي...")

    try:
        pdf_bytes = await generate_weekly_report(week_offset=0)
        size_kb   = round(len(pdf_bytes) / 1024, 1)
        logger.info(f"[RPT] تقرير PDF جاهز — الحجم: {size_kb} KB")
    except Exception as exc:
        logger.error(f"[RPT] خطأ في توليد التقرير: {exc}")
        return {"status": "error", "message": str(exc)}

    # إشعار WebSocket للمدراء
    admins = await db.users.find({"role": "admin"}, {"_id": 1, "email": 1}).to_list(20)
    from services.notification_service import send_notification
    notified = 0
    for admin in admins:
        try:
            await send_notification(
                str(admin["_id"]),
                "weekly_report_ready",
                {"date": datetime.now(timezone.utc).strftime("%Y/%m/%d"), "size_kb": str(size_kb)},
                "ar",
            )
            notified += 1
        except Exception as exc:
            logger.error(f"[RPT] خطأ إشعار: {exc}")

    # إرسال PDF بالبريد الإلكتروني لجميع المدراء عبر SendGrid
    emailed = 0
    for admin in admins:
        admin_email = admin.get("email")
        if admin_email:
            ok = await _send_report_email(admin_email, pdf_bytes)
            if ok:
                emailed += 1
    if emailed:
        logger.info(f"[RPT] تم إرسال التقرير بالبريد لـ {emailed} مدير(ين)")

    await db.audit_logs.insert_one({
        "action":        "cron_weekly_report",
        "user_id":       "SYSTEM",
        "user_name":     "النظام الآلي",
        "resource_type": "scheduler",
        "resource_id":   "weekly_report_email",
        "details":       {"pdf_size_kb": size_kb, "admins_notified": notified},
        "timestamp":     now,
    })

    logger.info(f"[RPT] اكتمل — حجم: {size_kb} KB | إشعارات: {notified}")
    return {"status": "ok", "pdf_size_kb": size_kb, "notifications_sent": notified}


async def _send_report_email(to_email: str, pdf_bytes: bytes) -> bool:
    """
    يُرسل تقرير PDF الأسبوعي كمرفق عبر SendGrid.
    يُرجع True عند النجاح، False عند الفشل أو غياب المفتاح.
    """
    import os
    sg_key = os.environ.get("SENDGRID_API_KEY", "")
    if not sg_key or sg_key.startswith("SG.placeholder"):
        logger.warning(f"[RPT EMAIL MOCK] → {to_email} (لا يوجد SENDGRID_API_KEY)")
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            Mail, From, To, Subject, Content,
            Attachment, FileContent, FileName, FileType, Disposition,
        )

        sender_email = os.environ.get("SENDER_EMAIL", "lybiacustoms@gmail.com")
        sender_name  = "مصلحة الجمارك الليبية | NAFIDHA Customs"
        report_date  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        subject      = f"التقرير الأسبوعي الآلي — نافذة | {report_date}"

        html_body = f"""
        <div dir="rtl" style="font-family:Tajawal,Arial,sans-serif;max-width:600px;margin:auto;color:#1e3a5f;">
          <div style="background:#1e3a5f;padding:24px 32px;border-radius:12px 12px 0 0;">
            <h1 style="color:#d4a017;margin:0;font-size:22px;">نافذة — البوابة الجمركية الوطنية</h1>
            <p style="color:#a8c4e0;margin:4px 0 0;font-size:13px;">NAFIDHA Libya National Single Window</p>
          </div>
          <div style="background:#f8fafc;padding:28px 32px;border:1px solid #e2e8f0;border-top:none;">
            <h2 style="font-size:17px;margin:0 0 12px;">التقرير الأسبوعي الآلي</h2>
            <p style="color:#475569;font-size:14px;line-height:1.7;margin:0 0 16px;">
              مرفق طيّه التقرير الأسبوعي الآلي الصادر عن منظومة نافذة للجمارك الليبية بتاريخ <strong>{report_date}</strong>.
              يحتوي التقرير على إحصاءات أداء الأسبوع الكامل: KYC، طلبات ACID، المدفوعات، وبيانات الموظفين.
            </p>
            <div style="background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:16px 20px;margin-bottom:20px;">
              <p style="color:#64748b;font-size:13px;margin:0;">يتم إرسال هذا التقرير تلقائياً كل <strong>خميس الساعة 17:00 UTC</strong> لجميع مستخدمي الإدارة.</p>
            </div>
            <p style="color:#94a3b8;font-size:12px;margin:0;">هذا بريد تلقائي — لا تردّ عليه مباشرةً.</p>
          </div>
          <div style="background:#1e3a5f;padding:14px 32px;border-radius:0 0 12px 12px;text-align:center;">
            <p style="color:#a8c4e0;font-size:12px;margin:0;">© 2026 مصلحة الجمارك الليبية — جميع الحقوق محفوظة</p>
          </div>
        </div>
        """

        encoded_pdf = base64.b64encode(pdf_bytes).decode()
        attachment  = Attachment(
            file_content  = FileContent(encoded_pdf),
            file_name     = FileName(f"nafidha_weekly_report_{report_date}.pdf"),
            file_type     = FileType("application/pdf"),
            disposition   = Disposition("attachment"),
        )

        msg = Mail(
            from_email   = From(sender_email, sender_name),
            to_emails    = To(to_email),
            subject      = Subject(subject),
            html_content = Content("text/html", html_body),
        )
        msg.attachment = attachment

        sg   = SendGridAPIClient(sg_key)
        resp = sg.send(msg)
        logger.info(f"[RPT EMAIL OK] {resp.status_code} → {to_email}")
        return resp.status_code in (200, 202)

    except Exception as exc:
        logger.error(f"[RPT EMAIL ERROR] {to_email}: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────
# Land Trip 24h Escalation — تصعيد رحلات مساعد المتأخرة
# ─────────────────────────────────────────────────────────────────

_LAND_TRIP_SLA_HOURS = int(os.environ.get("LAND_TRIP_SLA_HOURS", "24"))

async def run_land_trip_escalation() -> dict:
    """
    يعمل كل ساعة:
    1. يبحث عن رحلات برية في حالة 'pending' منذ أكثر من 24 ساعة
    2. يُحدِّثها إلى 'escalated' ويُسجِّل وقت التصعيد
    3. يُرسل إشعار WebSocket للمأمورين المختصين (manifest_officer + admin)
    4. يُسجِّل في Audit Log
    """
    now     = datetime.now(timezone.utc)
    cutoff  = (now - timedelta(hours=_LAND_TRIP_SLA_HOURS)).isoformat()
    now_iso = now.isoformat()

    stale_trips = await db.land_trips.find({
        "status":     "pending",
        "created_at": {"$lt": cutoff},
        "escalated":  {"$ne": True},
    }).to_list(200)

    if not stale_trips:
        return {"escalated": 0}

    # جلب معرّفات المسؤولين
    reviewers = await db.users.find(
        {"role": {"$in": ["manifest_officer", "admin"]}, "is_active": True},
        {"_id": 1},
    ).to_list(50)
    reviewer_ids = [str(r["_id"]) for r in reviewers]

    escalated_count = 0
    for trip in stale_trips:
        trip_id = trip["_id"]
        acid_id = str(trip.get("acid_id", ""))
        plate   = trip.get("truck_plate", "—")
        port    = trip.get("port_of_entry", "—")

        # الحساب الدقيق للساعات المتأخرة
        try:
            created = datetime.fromisoformat(str(trip["created_at"]))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            overdue_h = round((now - created).total_seconds() / 3600, 1)
        except Exception:
            overdue_h = _LAND_TRIP_SLA_HOURS

        await db.land_trips.update_one(
            {"_id": trip_id},
            {"$set": {
                "status":            "escalated",
                "escalated":         True,
                "escalated_at":      now_iso,
                "escalation_reason": f"تجاوزت الرحلة {overdue_h} ساعة دون معالجة",
            }}
        )

        # تحديث حالة land_trip_status في acid_requests
        if acid_id:
            from bson import ObjectId
            try:
                await db.acid_requests.update_one(
                    {"_id": ObjectId(acid_id)},
                    {"$set": {"land_trip_status": "escalated"}}
                )
            except Exception:
                pass

        # إشعار المسؤولين
        for rid in reviewer_ids:
            try:
                await send_notification(
                    rid, "land_trip_escalated",
                    {
                        "truck_plate":   plate,
                        "port":          port,
                        "overdue_hours": str(overdue_h),
                    },
                    "ar",
                )
            except Exception as exc:
                logger.error(f"[LAND_ESC] خطأ إشعار {rid}: {exc}")

        escalated_count += 1
        logger.warning(
            f"[LAND_ESC] تصعيد رحلة: {plate} | منفذ: {port} | تأخير: {overdue_h}h"
        )

    await db.audit_logs.insert_one({
        "action":        "cron_land_trip_escalation",
        "user_id":       "SYSTEM",
        "user_name":     "النظام الآلي",
        "resource_type": "scheduler",
        "resource_id":   "land_trip_escalation",
        "details":       {
            "escalated":         escalated_count,
            "sla_hours":         _LAND_TRIP_SLA_HOURS,
            "checked_at":        now_iso,
        },
        "timestamp": now_iso,
    })

    logger.info(f"[LAND_ESC] اكتمل — تم تصعيد: {escalated_count} رحلة")
    return {"escalated": escalated_count, "sla_hours": _LAND_TRIP_SLA_HOURS}


# ─────────────────────────────────────────────────────────────────
# دورة حياة الـ scheduler
# ─────────────────────────────────────────────────────────────────

def startup_scheduler() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        run_license_expiry_check,
        trigger=CronTrigger(hour=_DEFAULT_HOUR, minute=_DEFAULT_MINUTE),
        id="license_expiry_check",
        name="فحص انتهاء الرخص التجارية",
        replace_existing=True,
    )
    # مهمة SLA Breach — كل 15 دقيقة
    from apscheduler.triggers.interval import IntervalTrigger
    _scheduler.add_job(
        run_sla_breach_check,
        trigger=IntervalTrigger(minutes=15),
        id="sla_breach_check",
        name="فحص تجاوز مهل SLA",
        replace_existing=True,
    )
    # تقرير PDF الأسبوعي — كل خميس الساعة 17:00 UTC
    _scheduler.add_job(
        run_weekly_report_email,
        trigger=CronTrigger(day_of_week="thu", hour=17, minute=0),
        id="weekly_report_email",
        name="تقرير الأداء الأسبوعي — البريد الإلكتروني",
        replace_existing=True,
    )
    # تصعيد الرحلات البرية المتأخرة — كل ساعة
    _scheduler.add_job(
        run_land_trip_escalation,
        trigger=IntervalTrigger(hours=1),
        id="land_trip_escalation",
        name="تصعيد رحلات مساعد المتأخرة (SLA 24h)",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        f"[CRON] نشط — 09:00 UTC يومياً | "
        f"نطاق افتراضي: {_DEFAULT_WARN_DAYS} يوم\n"
        f"[SLA]  فحص تجاوز المهل كل 15 دقيقة — تصعيد + إشعار المدير\n"
        f"[RPT]  تقرير PDF الأسبوعي — كل خميس 17:00 UTC\n"
        f"[LAND] تصعيد رحلات مساعد المتأخرة كل ساعة (SLA: {_LAND_TRIP_SLA_HOURS}h)"
    )


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[CRON] تم الإيقاف")
    _scheduler = None

