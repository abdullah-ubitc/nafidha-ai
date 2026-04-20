"""
report_service.py — محرك التقارير السيادية (Sovereign Reporting Engine)
═══════════════════════════════════════════════════════════════════════════
يولِّد تقارير PDF باللغة العربية تحتوي على:
  • ملخص KPIs الأسبوعية (مكتملة / SLA / متوسط الإنجاز)
  • جدول الأداء حسب القسم (KYC / ACID)
  • Leaderboard أفضل الموظفين
  • تفاصيل خروقات SLA
مكتبات: reportlab + arabic_reshaper + python-bidi
"""

import os
import io
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Table, TableStyle
from reportlab.lib.colors import HexColor

import arabic_reshaper
from bidi.algorithm import get_display

from database import db

logger = logging.getLogger("report_service")

# ─── مسارات الخطوط ────────────────────────────────────────────────
_FONTS_DIR   = Path(__file__).parent.parent / "assets" / "fonts"
_FONT_REG    = str(_FONTS_DIR / "Amiri-Regular.ttf")
_FONT_BOLD   = str(_FONTS_DIR / "Amiri-Bold.ttf")

_FONTS_REGISTERED = False

def _ensure_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    try:
        pdfmetrics.registerFont(TTFont("Amiri",     _FONT_REG))
        pdfmetrics.registerFont(TTFont("AmiriBold", _FONT_BOLD))
        _FONTS_REGISTERED = True
    except Exception as exc:
        logger.error(f"[PDF] خطأ في تحميل الخطوط: {exc}")
        raise


# ─── ثوابت التصميم ────────────────────────────────────────────────
NAVY    = HexColor("#1e3a5f")
GOLD    = HexColor("#d4a017")
LIGHT   = HexColor("#f8fafc")
GRAY    = HexColor("#64748b")
GREEN   = HexColor("#16a34a")
RED     = HexColor("#dc2626")
AMBER   = HexColor("#d97706")
WHITE   = colors.white

PAGE_W, PAGE_H = A4  # 595 × 842 pt


# ─── مساعد النص العربي ────────────────────────────────────────────
def ar(text: str) -> str:
    """تحويل النص العربي ليُعرض صحيحاً في PDF (reshaping + bidi)."""
    try:
        reshaped = arabic_reshaper.reshape(str(text))
        return get_display(reshaped)
    except Exception:
        return str(text)


# ─── مساعدات الرسم ────────────────────────────────────────────────
def _draw_rtl_text(c: canvas.Canvas, text: str, x: float, y: float,
                   font: str = "Amiri", size: int = 11, color=NAVY):
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawRightString(x, y, ar(text))


def _draw_ltr_text(c: canvas.Canvas, text: str, x: float, y: float,
                   font: str = "Amiri", size: int = 11, color=NAVY):
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawString(x, y, str(text))


def _draw_centered(c: canvas.Canvas, text: str, y: float,
                   font: str = "Amiri", size: int = 12, color=NAVY):
    c.setFont(font, size)
    c.setFillColor(color)
    text_ar = ar(text)
    w = c.stringWidth(text_ar, font, size)
    c.drawString((PAGE_W - w) / 2, y, text_ar)


def _draw_rect(c, x, y, w, h, fill_color, radius=4):
    c.setFillColor(fill_color)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=0)


# ─── جمع البيانات ─────────────────────────────────────────────────
_KYC_ROLES    = ["importer", "customs_broker", "carrier_agent", "foreign_supplier"]
_ACID_STATUSES = ["submitted", "pending", "under_review"]


async def _gather_report_data(week_start: datetime, week_end: datetime) -> dict:
    ws  = week_start.isoformat()
    we  = week_end.isoformat()
    now = datetime.now(timezone.utc)

    # إنجاز أسبوعي — KYC
    kyc_week = await db.users.count_documents({
        "wf_status": "Completed",
        "wf_completed_at": {"$gte": ws, "$lt": we},
    })
    # إنجاز أسبوعي — ACID
    acid_week = await db.acid_requests.count_documents({
        "wf_status": "Completed",
        "wf_completed_at": {"$gte": ws, "$lt": we},
    })

    # إنجاز اليوم
    today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    kyc_today  = await db.users.count_documents({"wf_status": "Completed", "wf_completed_at": {"$gte": today}})
    acid_today = await db.acid_requests.count_documents({"wf_status": "Completed", "wf_completed_at": {"$gte": today}})

    # خروقات SLA — هذا الأسبوع
    sla_kyc  = await db.users.count_documents({
        "role": {"$in": _KYC_ROLES},
        "wf_status": {"$in": ["Escalated", "Completed"]},
        "wf_sla_breach_notified": True,
        "wf_escalated_at": {"$gte": ws, "$lt": we},
    })
    sla_acid = await db.acid_requests.count_documents({
        "wf_status": {"$in": ["Escalated", "Completed"]},
        "wf_sla_breach_notified": True,
        "wf_escalated_at": {"$gte": ws, "$lt": we},
    })

    # Leaderboard — أفضل الموظفين هذا الأسبوع
    pipeline = [
        {"$match": {"wf_status": "Completed", "wf_completed_at": {"$gte": ws, "$lt": we}}},
        {"$group": {"_id": "$wf_completed_by_name", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 8},
    ]
    kyc_officers  = await db.users.aggregate(pipeline).to_list(8)
    acid_officers = await db.acid_requests.aggregate(pipeline).to_list(8)

    # دمج الموظفين
    officers_map: dict = {}
    for o in kyc_officers:
        n = o["_id"] or "—"
        officers_map.setdefault(n, {"kyc": 0, "acid": 0})
        officers_map[n]["kyc"] = o["count"]
    for o in acid_officers:
        n = o["_id"] or "—"
        officers_map.setdefault(n, {"kyc": 0, "acid": 0})
        officers_map[n]["acid"] = o["count"]
    officers = sorted(
        [{"name": k, "kyc": v["kyc"], "acid": v["acid"], "total": v["kyc"] + v["acid"]}
         for k, v in officers_map.items()],
        key=lambda x: x["total"], reverse=True,
    )[:8]

    # حوض المهام الحالي
    pool_kyc  = await db.users.count_documents({
        "role": {"$in": _KYC_ROLES},
        "registration_status": "pending",
        "$or": [{"wf_status": {"$exists": False}}, {"wf_status": "Unassigned"}],
    })
    pool_acid = await db.acid_requests.count_documents({
        "status": {"$in": _ACID_STATUSES},
        "$or": [{"wf_status": {"$exists": False}}, {"wf_status": "Unassigned"}],
    })
    inprog_kyc  = await db.users.count_documents({"role": {"$in": _KYC_ROLES}, "wf_status": "In_Progress"})
    inprog_acid = await db.acid_requests.count_documents({"status": {"$in": _ACID_STATUSES}, "wf_status": "In_Progress"})

    return {
        "period":       {"start": week_start.strftime("%Y/%m/%d"), "end": week_end.strftime("%Y/%m/%d")},
        "kyc_week":     kyc_week,
        "acid_week":    acid_week,
        "total_week":   kyc_week + acid_week,
        "kyc_today":    kyc_today,
        "acid_today":   acid_today,
        "sla_kyc":      sla_kyc,
        "sla_acid":     sla_acid,
        "sla_total":    sla_kyc + sla_acid,
        "officers":     officers,
        "pool_kyc":     pool_kyc,
        "pool_acid":    pool_acid,
        "inprog_kyc":   inprog_kyc,
        "inprog_acid":  inprog_acid,
    }


# ─── رسم الـ PDF ───────────────────────────────────────────────────
def _build_pdf(data: dict) -> bytes:
    _ensure_fonts()
    buf = io.BytesIO()
    c   = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("تقرير الأداء الأسبوعي — نافذة الجمارك الليبية")

    y = PAGE_H - 1.5 * cm  # نبدأ من الأعلى

    # ── Header شريط أزرق داكن ─────────────────────────────────────
    _draw_rect(c, 0, PAGE_H - 3.2 * cm, PAGE_W, 3.2 * cm, NAVY)

    # اسم المنظومة
    c.setFont("AmiriBold", 22)
    c.setFillColor(WHITE)
    title_ar = ar("نافذة الجمارك الليبية")
    tw = c.stringWidth(title_ar, "AmiriBold", 22)
    c.drawString((PAGE_W - tw) / 2, PAGE_H - 1.6 * cm, title_ar)

    c.setFont("Amiri", 11)
    sub_ar = ar("NAFIDHA — National Single Window")
    sw = c.stringWidth(sub_ar, "Amiri", 11)
    c.drawString((PAGE_W - sw) / 2, PAGE_H - 2.4 * cm, sub_ar)

    y = PAGE_H - 3.6 * cm

    # ── شريط ذهبي التاريخ ─────────────────────────────────────────
    _draw_rect(c, 0, y - 0.6 * cm, PAGE_W, 0.7 * cm, GOLD)
    report_title = f"تقرير الأداء الأسبوعي | {data['period']['start']} — {data['period']['end']}"
    c.setFont("AmiriBold", 10)
    c.setFillColor(WHITE)
    rt = ar(report_title)
    rw = c.stringWidth(rt, "AmiriBold", 10)
    c.drawString((PAGE_W - rw) / 2, y - 0.45 * cm, rt)
    y -= 1.4 * cm

    # ── قسم KPIs الرئيسية ──────────────────────────────────────────
    _draw_centered(c, "ملخص الأداء", y, "AmiriBold", 14, NAVY)
    y -= 0.5 * cm

    kpis = [
        ("المهام المُنجزة هذا الأسبوع", str(data["total_week"]), GREEN,  HexColor("#f0fdf4")),
        ("طلبات KYC مُنجزة",            str(data["kyc_week"]),   NAVY,   HexColor("#eff6ff")),
        ("طلبات ACID مُنجزة",           str(data["acid_week"]),  HexColor("#7e22ce"), HexColor("#faf5ff")),
        ("خروقات SLA هذا الأسبوع",      str(data["sla_total"]), RED if data["sla_total"] > 0 else GREEN, HexColor("#fef2f2") if data["sla_total"] > 0 else HexColor("#f0fdf4")),
    ]

    card_w = (PAGE_W - 2 * cm) / 4
    card_h = 2.2 * cm
    for i, (label, val, vcolor, bg_color) in enumerate(kpis):
        cx = 1 * cm + i * card_w
        # بطاقة
        _draw_rect(c, cx, y - card_h, card_w - 0.3 * cm, card_h, bg_color)
        c.setStrokeColor(HexColor("#e2e8f0"))
        c.setLineWidth(0.5)
        c.roundRect(cx, y - card_h, card_w - 0.3 * cm, card_h, 4)
        # الرقم
        c.setFont("AmiriBold", 22)
        c.setFillColor(vcolor)
        vw = c.stringWidth(val, "AmiriBold", 22)
        c.drawString(cx + (card_w - 0.3 * cm - vw) / 2, y - 0.9 * cm, val)
        # التسمية
        c.setFont("Amiri", 8)
        c.setFillColor(GRAY)
        lbl = ar(label)
        lw = c.stringWidth(lbl, "Amiri", 8)
        c.drawString(cx + (card_w - 0.3 * cm - lw) / 2, y - 1.7 * cm, lbl)

    y -= card_h + 0.8 * cm

    # ── جدول إنجاز القسمين ───────────────────────────────────────
    _draw_centered(c, "الإنجاز حسب القسم", y, "AmiriBold", 13, NAVY)
    y -= 0.5 * cm

    table_data = [
        [ar("هذا الأسبوع (ACID)"), ar("اليوم (ACID)"), ar("هذا الأسبوع (KYC)"), ar("اليوم (KYC)"), ar("القسم / البيان")],
        [str(data["acid_week"]),  str(data["acid_today"]), str(data["kyc_week"]), str(data["kyc_today"]), ar("المهام المُنجزة")],
        [str(data["sla_acid"]),   "—",                     str(data["sla_kyc"]),  "—",                   ar("خروقات SLA")],
        [str(data["pool_acid"]),  str(data["inprog_acid"]),str(data["pool_kyc"]), str(data["inprog_kyc"]), ar("الحالة الراهنة")],
    ]

    col_widths = [3.2 * cm, 2.5 * cm, 3.2 * cm, 2.5 * cm, 4.8 * cm]
    tbl = Table(table_data, colWidths=col_widths, rowHeights=[0.7 * cm] * 4)
    tbl.setStyle(TableStyle([
        # Header
        ("BACKGROUND",   (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",    (0, 0), (-1, 0), WHITE),
        ("FONTNAME",     (0, 0), (-1, 0), "AmiriBold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 9),
        ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        # Rows
        ("FONTNAME",     (0, 1), (-1, -1), "Amiri"),
        ("FONTSIZE",     (0, 1), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, HexColor("#f8fafc")]),
        ("TEXTCOLOR",    (0, 1), (-1, -1), NAVY),
        # Last column (label) gold background
        ("BACKGROUND",   (-1, 1), (-1, -1), HexColor("#fffbeb")),
        ("FONTNAME",     (-1, 1), (-1, -1), "AmiriBold"),
        ("TEXTCOLOR",    (-1, 1), (-1, -1), HexColor("#92400e")),
        # Grid
        ("GRID",         (0, 0), (-1, -1), 0.5, HexColor("#e2e8f0")),
        ("LINEABOVE",    (0, 0), (-1, 0), 1.5, NAVY),
        ("LINEBELOW",    (0, -1), (-1, -1), 1.5, NAVY),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))

    tbl_w = sum(col_widths)
    tbl.wrapOn(c, PAGE_W - 2 * cm, PAGE_H)
    tbl_h = tbl._height
    tbl.drawOn(c, (PAGE_W - tbl_w) / 2, y - tbl_h)
    y -= tbl_h + 1 * cm

    # ── Leaderboard الموظفين ──────────────────────────────────────
    _draw_centered(c, "أداء الموظفين — الأسبوع الحالي", y, "AmiriBold", 13, NAVY)
    y -= 0.5 * cm

    if data["officers"]:
        lb_data = [[ar("المجموع"), ar("ACID"), ar("KYC"), ar("اسم الموظف"), ar("#")]]
        for i, off in enumerate(data["officers"]):
            lb_data.append([
                str(off["total"]),
                str(off["acid"]),
                str(off["kyc"]),
                ar(off["name"]),
                str(i + 1),
            ])

        lb_col_widths = [2.5 * cm, 2.5 * cm, 2.5 * cm, 7.5 * cm, 1.2 * cm]
        lb_tbl = Table(lb_data, colWidths=lb_col_widths, rowHeights=[0.65 * cm] * len(lb_data))
        lb_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), HexColor("#1e3a5f")),
            ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "AmiriBold"),
            ("FONTSIZE",      (0, 0), (-1, 0), 9),
            ("FONTNAME",      (0, 1), (-1, -1), "Amiri"),
            ("FONTSIZE",      (0, 1), (-1, -1), 10),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, HexColor("#f8fafc")]),
            ("TEXTCOLOR",     (0, 1), (-1, -1), NAVY),
            # أعلى موظف — ذهبي
            ("BACKGROUND",    (0, 1), (-1, 1), HexColor("#fffbeb")),
            ("FONTNAME",      (0, 1), (-1, 1), "AmiriBold"),
            ("GRID",          (0, 0), (-1, -1), 0.5, HexColor("#e2e8f0")),
            ("LINEABOVE",     (0, 0), (-1, 0), 1.5, NAVY),
            ("LINEBELOW",     (0, -1), (-1, -1), 1.5, NAVY),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        lb_w = sum(lb_col_widths)
        lb_tbl.wrapOn(c, PAGE_W - 2 * cm, PAGE_H)
        lb_h = lb_tbl._height
        lb_tbl.drawOn(c, (PAGE_W - lb_w) / 2, y - lb_h)
        y -= lb_h + 1 * cm
    else:
        _draw_centered(c, "لا توجد بيانات للموظفين في هذه الفترة", y - 0.5 * cm, "Amiri", 10, GRAY)
        y -= 1.5 * cm

    # ── خط فاصل ──────────────────────────────────────────────────
    c.setStrokeColor(HexColor("#e2e8f0"))
    c.setLineWidth(1)
    c.line(1 * cm, y, PAGE_W - 1 * cm, y)
    y -= 0.5 * cm

    # ── تذييل ─────────────────────────────────────────────────────
    _draw_rect(c, 0, 0, PAGE_W, 1 * cm, NAVY)
    gen_time = datetime.now(timezone.utc).strftime("%Y/%m/%d — %H:%M UTC")
    footer_text = f"تم الإصدار آلياً بواسطة منظومة نافذة الجمارك الليبية | {gen_time}"
    c.setFont("Amiri", 8)
    c.setFillColor(WHITE)
    ft = ar(footer_text)
    fw = c.stringWidth(ft, "Amiri", 8)
    c.drawString((PAGE_W - fw) / 2, 0.3 * cm, ft)

    c.save()
    return buf.getvalue()


# ─── الدالة العامة ────────────────────────────────────────────────
async def generate_weekly_report(
    week_offset: int = 0,   # 0 = الأسبوع الحالي، 1 = الأسبوع الماضي
) -> bytes:
    """
    يجمع البيانات من Workflow Engine ويولِّد ملف PDF.
    يُرجع محتوى الـ PDF كـ bytes.
    """
    now       = datetime.now(timezone.utc)
    days_back = now.weekday() + 7 * week_offset   # يبدأ أسبوع العمل من الاثنين
    week_start = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    week_end   = week_start + timedelta(days=7)

    data = await _gather_report_data(week_start, week_end)
    return _build_pdf(data)
