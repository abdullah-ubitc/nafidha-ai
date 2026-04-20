"""PDF generation: JL159, JL119, JL38, Dashboard PDF"""
import io
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
import qrcode
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).parent

_fonts_registered = False


def ensure_fonts():
    global _fonts_registered
    if not _fonts_registered:
        fonts_dir = ROOT_DIR / "fonts"
        try:
            pdfmetrics.registerFont(TTFont('Amiri', str(fonts_dir / 'Amiri-Regular.ttf')))
            pdfmetrics.registerFont(TTFont('AmiriBold', str(fonts_dir / 'Amiri-Bold.ttf')))
            _fonts_registered = True
        except Exception as e:
            logger.warning(f"Font registration failed: {e}")


def ar(text: str) -> str:
    try:
        reshaped = arabic_reshaper.reshape(str(text or ""))
        return get_display(reshaped)
    except Exception:
        return str(text or "")


def generate_jl159_pdf_bytes(receipt_no: str, sad: dict, acid: dict, verify_url: str) -> bytes:
    ensure_fonts()
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    NAVY = HexColor("#1e3a5f")
    GOLD = HexColor("#d4a017")

    c.setFillColor(NAVY)
    c.rect(0, H - 72 * mm, W, 72 * mm, fill=True, stroke=False)
    c.setFillColor(GOLD)
    c.rect(0, H - 74 * mm, W, 2 * mm, fill=True, stroke=False)
    c.setFillColor(colors.white)
    c.setFont('AmiriBold', 15)
    c.drawCentredString(W / 2, H - 18 * mm, ar("الجمهورية الليبية - الإدارة العامة للجمارك"))
    c.setFont('Helvetica-Bold', 9)
    c.drawCentredString(W / 2, H - 25 * mm, "GREAT STATE OF LIBYA - GENERAL ADMINISTRATION OF CUSTOMS")
    c.setFont('AmiriBold', 19)
    c.drawCentredString(W / 2, H - 40 * mm, ar("إيصال الخزينة الجمركية"))
    c.setFont('Helvetica-Bold', 13)
    c.drawCentredString(W / 2, H - 50 * mm, "CUSTOMS TREASURY RECEIPT  (JL 159 / ج ل 159)")
    c.setFont('AmiriBold', 9)
    c.drawCentredString(W / 2, H - 60 * mm, ar("النموذج: ج ل 159  |  Form: JL 159"))

    y = H - 82 * mm
    c.setFillColor(HexColor("#eaf0fa"))
    c.rect(10 * mm, y - 10 * mm, W - 20 * mm, 18 * mm, fill=True, stroke=False)
    c.setFillColor(NAVY)
    c.setFont('AmiriBold', 9)
    c.drawRightString(W - 14 * mm, y, ar(f"رقم الإيصال: {receipt_no}"))
    c.drawRightString(W - 14 * mm, y - 6 * mm, ar(f"التاريخ: {datetime.now(timezone.utc).strftime('%d/%m/%Y')}"))
    c.setFont('Helvetica-Bold', 9)
    c.drawString(14 * mm, y, f"Receipt No: {receipt_no}")
    c.drawString(14 * mm, y - 6 * mm, f"Date: {datetime.now(timezone.utc).strftime('%d/%m/%Y')}")

    y -= 16 * mm
    c.setFillColor(GOLD)
    c.rect(10 * mm, y - 2 * mm, W - 20 * mm, 9 * mm, fill=True, stroke=False)
    c.setFillColor(NAVY)
    c.setFont('AmiriBold', 9)
    c.drawCentredString(W / 2, y + 2 * mm, ar(f"رقم ACID: {acid.get('acid_number', '')}     |     رقم SAD: {sad.get('sad_number', '')}"))

    def draw_sec(cy, title_ar, title_en):
        c.setFillColor(NAVY)
        c.rect(10 * mm, cy - 1 * mm, W - 20 * mm, 8 * mm, fill=True, stroke=False)
        c.setFillColor(colors.white)
        c.setFont('AmiriBold', 10)
        c.drawCentredString(W / 2, cy + 1 * mm, ar(f"{title_ar}  /  {title_en}"))

    def draw_row(cy, la, va, le, ve):
        c.setFillColor(HexColor("#f7f9fc"))
        c.setStrokeColor(HexColor("#dde5f0"))
        c.rect(10 * mm, cy - 1.5 * mm, W - 20 * mm, 7.5 * mm, fill=True, stroke=True)
        c.setFillColor(NAVY)
        c.setFont('AmiriBold', 8)
        c.drawRightString(W - 13 * mm, cy + 1.5 * mm, ar(str(la)))
        c.setFont('Amiri', 8)
        c.drawRightString(W - 55 * mm, cy + 1.5 * mm, ar(str(va)[:40]))
        c.setFont('Helvetica-Bold', 8)
        c.drawString(13 * mm, cy + 1.5 * mm, f"{le}:")
        c.setFont('Helvetica', 8)
        c.drawString(50 * mm, cy + 1.5 * mm, str(ve)[:38])

    y -= 14 * mm
    draw_sec(y, "بيانات المستورد", "Importer Details")
    y -= 10 * mm
    for la, va, le, ve in [
        ("المستورد", acid.get('requester_name_ar', ''), "Importer", acid.get('requester_name_ar', '')),
        ("المورد", acid.get('supplier_name', ''), "Supplier", acid.get('supplier_name', '')),
        ("بلد المورد", acid.get('supplier_country', ''), "Origin Country", acid.get('supplier_country', '')),
        ("منفذ الدخول", acid.get('port_of_entry', ''), "Port of Entry", acid.get('port_of_entry', '')),
    ]:
        draw_row(y, la, va, le, ve)
        y -= 9 * mm

    y -= 5 * mm
    draw_sec(y, "بيانات البضاعة", "Goods Details")
    y -= 10 * mm
    for la, va, le, ve in [
        ("وصف البضاعة", str(acid.get('goods_description', ''))[:40], "Description", str(acid.get('goods_description', ''))[:40]),
        ("رمز HS", acid.get('hs_code', ''), "HS Code", acid.get('hs_code', '')),
        ("الكمية", f"{acid.get('quantity', '')} {acid.get('unit', '')}", "Quantity", f"{acid.get('quantity', '')} {acid.get('unit', '')}"),
        ("القيمة CIF", f"USD {acid.get('value_usd', 0):,.2f}", "CIF Value", f"USD {acid.get('value_usd', 0):,.2f}"),
    ]:
        draw_row(y, la, va, le, ve)
        y -= 9 * mm

    y -= 5 * mm
    draw_sec(y, "حساب الرسوم الجمركية", "Duties Calculation")
    exch = sad.get('exchange_rate', 4.87)
    crate = sad.get('customs_rate_pct', '20%')
    y -= 10 * mm
    for la, va, le, ve in [
        (f"القيمة الجمركية (×{exch})", f"LYD {acid.get('value_usd', 0) * exch:,.2f}", f"Customs Value (×{exch})", f"LYD {acid.get('value_usd', 0) * exch:,.2f}"),
        (f"رسوم جمركية ({crate})", f"LYD {sad.get('customs_duty_lyd', 0):,.2f}", f"Customs Duty ({crate})", f"LYD {sad.get('customs_duty_lyd', 0):,.2f}"),
        ("ضريبة القيمة المضافة (9%)", f"LYD {sad.get('vat_lyd', 0):,.2f}", "VAT (9%)", f"LYD {sad.get('vat_lyd', 0):,.2f}"),
    ]:
        draw_row(y, la, va, le, ve)
        y -= 9 * mm

    y -= 5 * mm
    c.setFillColor(GOLD)
    c.rect(10 * mm, y - 3 * mm, W - 20 * mm, 12 * mm, fill=True, stroke=False)
    c.setFillColor(NAVY)
    c.setFont('AmiriBold', 13)
    c.drawRightString(W - 14 * mm, y + 2 * mm, ar(f"الإجمالي المستحق: {sad.get('total_lyd', 0):,.2f} د.ل"))
    c.setFont('Helvetica-Bold', 13)
    c.drawString(14 * mm, y + 2 * mm, f"TOTAL DUE:  LYD {sad.get('total_lyd', 0):,.2f}")

    if sad.get('cbl_bank_ref'):
        y -= 14 * mm
        c.setFillColor(HexColor("#e8f5e9"))
        c.rect(10 * mm, y - 2 * mm, W - 20 * mm, 9 * mm, fill=True, stroke=False)
        c.setFillColor(HexColor("#1b5e20"))
        c.setFont('AmiriBold', 9)
        c.drawRightString(W - 14 * mm, y + 2 * mm, ar(f"مرجع مصرف ليبيا المركزي: {sad.get('cbl_bank_ref', '')}"))
        c.setFont('Helvetica-Bold', 9)
        c.drawString(14 * mm, y + 2 * mm, f"CBL Ref: {sad.get('cbl_bank_ref', '')}")

    qr_data = f"{verify_url}?acid={acid.get('acid_number', '')}&receipt={receipt_no}"
    qr_obj = qrcode.QRCode(version=1, box_size=3, border=2)
    qr_obj.add_data(qr_data)
    qr_obj.make(fit=True)
    qr_img = qr_obj.make_image(fill_color="black", back_color="white")
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format='PNG')
    qr_buf.seek(0)
    qr_y = 18 * mm
    c.drawImage(ImageReader(qr_buf), 10 * mm, qr_y, 28 * mm, 28 * mm)
    c.setFont('Helvetica', 7)
    c.drawString(10 * mm, qr_y - 4 * mm, "Scan to verify")
    c.setFont('Amiri', 7)
    c.drawRightString(W - 10 * mm, qr_y - 4 * mm, ar("للتحقق الإلكتروني"))
    c.setFont('AmiriBold', 8)
    c.drawRightString(W - 14 * mm, qr_y + 20 * mm, ar("توقيع المخلص الجمركي"))
    c.drawRightString(W - 14 * mm, qr_y + 10 * mm, ar("............................"))
    c.setFont('Helvetica-Bold', 8)
    c.drawString(50 * mm, qr_y + 20 * mm, "Customs Broker Signature")
    c.drawString(50 * mm, qr_y + 10 * mm, "...............................")

    c.setFillColor(NAVY)
    c.rect(0, 0, W, 14 * mm, fill=True, stroke=False)
    c.setFillColor(colors.white)
    c.setFont('Amiri', 7)
    c.drawCentredString(W / 2, 6 * mm, ar("هذا الإيصال وثيقة رسمية صادرة عن الإدارة العامة للجمارك - جمهورية ليبيا"))
    c.setFont('Helvetica', 7)
    c.drawCentredString(W / 2, 2 * mm, "Official document - General Administration of Customs - Libya")
    c.save()
    buf.seek(0)
    return buf.getvalue()


def generate_jl38_pdf_bytes(acid: dict, jl38_number: str, track_url: str) -> bytes:
    ensure_fonts()
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    NAVY = HexColor("#1e3a5f"); GOLD = HexColor("#d4a017"); GREEN = HexColor("#22c55e")
    c.setFillColor(NAVY); c.rect(0, H - 50*mm, W, 50*mm, fill=True, stroke=False)
    c.setFillColor(GOLD); c.rect(0, H - 52*mm, W, 2*mm, fill=True, stroke=False)
    c.setFillColor(colors.white); c.setFont('AmiriBold', 14)
    c.drawCentredString(W/2, H - 16*mm, ar("الجمهورية الليبية — الإدارة العامة للجمارك"))
    c.setFont('Helvetica-Bold', 9); c.setFillColor(HexColor("#aab"))
    c.drawCentredString(W/2, H - 24*mm, "Great State of Libya — General Administration of Customs")
    c.setFont('AmiriBold', 11); c.setFillColor(GOLD)
    c.drawCentredString(W/2, H - 35*mm, ar("وثيقة الإفراج الجمركي النهائي"))
    c.setFont('Helvetica-Bold', 9); c.setFillColor(HexColor("#cce")); c.drawCentredString(W/2, H - 43*mm, "FINAL CUSTOMS RELEASE DOCUMENT")
    c.setFillColor(GREEN); c.setStrokeColor(GREEN); c.setLineWidth(2)
    c.roundRect(W - 55*mm, H - 80*mm, 45*mm, 20*mm, 3, fill=True, stroke=False)
    c.setFillColor(colors.white); c.setFont('AmiriBold', 13)
    c.drawCentredString(W - 32.5*mm, H - 73*mm, ar("مُفرَج عنه"))
    c.setFont('Helvetica-Bold', 8); c.drawCentredString(W - 32.5*mm, H - 78*mm, "RELEASED")
    c.setFillColor(NAVY); c.setFont('AmiriBold', 13)
    c.drawRightString(W - 10*mm, H - 63*mm, ar(f"رقم وثيقة الإفراج: {jl38_number}"))
    c.setFont('Helvetica', 9); c.setFillColor(HexColor("#555"))
    c.drawString(10*mm, H - 63*mm, f"Release Doc No.: {jl38_number}")
    issued_at = acid.get("gate_released_at")
    if isinstance(issued_at, datetime):
        issued_str = issued_at.strftime("%d/%m/%Y %H:%M")
    else:
        issued_str = str(issued_at or datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M"))
    c.setFillColor(HexColor("#333")); c.setFont('AmiriBold', 9)
    c.drawRightString(W - 10*mm, H - 70*mm, ar(f"تاريخ الإصدار: {issued_str}"))
    c.setFont('Helvetica', 8); c.setFillColor(HexColor("#555"))
    c.drawString(10*mm, H - 70*mm, f"Issued: {issued_str} UTC")
    c.setStrokeColor(HexColor("#e2e8f0")); c.setLineWidth(1)
    c.line(10*mm, H - 75*mm, W - 10*mm, H - 75*mm)
    fields = [
        (ar("رقم ACID"), "ACID Number", acid.get("acid_number",""), True),
        (ar("البضاعة"), "Goods Description", (acid.get("goods_description","") or "")[:60], True),
        (ar("رمز HS"), "HS Code", acid.get("hs_code",""), False),
        (ar("منفذ الدخول"), "Port of Entry", acid.get("port_of_entry",""), False),
        (ar("وسيلة النقل"), "Transport Mode", acid.get("transport_mode",""), False),
        (ar("بلد المنشأ"), "Origin Country", acid.get("supplier_country",""), False),
        (ar("مرجع الخزينة"), "Treasury Ref", acid.get("treasury_ref",""), False),
    ]
    y = H - 82*mm
    row_h = 12*mm
    col_w = (W - 20*mm) / 2
    for i, (la, en, val, full) in enumerate(fields):
        row = i // (1 if full else 2)
        col = 0 if full else i % 2
        x = 10*mm + col * col_w
        bg = HexColor("#f8f9fa") if i % 2 == 0 else HexColor("#ffffff")
        c.setFillColor(bg); c.rect(x, y - row_h * (i if full else row), col_w if full else col_w, row_h, fill=True, stroke=False)
        c.setFillColor(NAVY); c.setFont('AmiriBold', 8)
        c.drawRightString(x + (col_w if full else col_w) - 3*mm, y - row_h * (i if full else row) + 7*mm, la)
        c.setFillColor(HexColor("#444")); c.setFont('Helvetica', 7)
        c.drawString(x + 2*mm, y - row_h * (i if full else row) + 7*mm, f"{en}:")
        c.setFillColor(HexColor("#1e3a5f")); c.setFont('AmiriBold', 9)
        c.drawCentredString(x + (col_w if full else col_w) / 2, y - row_h * (i if full else row) + 2*mm, str(val or "—"))
        if i == 0:
            y -= row_h
    qr = qrcode.QRCode(version=1, box_size=4, border=2)
    qr.add_data(track_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#1e3a5f", back_color="white")
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format="PNG"); qr_buf.seek(0)
    qr_y = 40*mm
    c.drawImage(ImageReader(qr_buf), W/2 - 20*mm, qr_y, 40*mm, 40*mm)
    c.setFillColor(HexColor("#555")); c.setFont('Helvetica', 7)
    c.drawCentredString(W/2, qr_y - 4*mm, "Scan to verify | امسح للتحقق")
    c.setFont('Helvetica', 6); c.setFillColor(HexColor("#888"))
    c.drawCentredString(W/2, qr_y - 8*mm, track_url[:70])
    c.setFillColor(NAVY); c.rect(0, 0, W, 12*mm, fill=True, stroke=False)
    c.setFillColor(GOLD); c.rect(0, 12*mm, W, 1*mm, fill=True, stroke=False)
    c.setFillColor(colors.white); c.setFont('Amiri', 7)
    c.drawCentredString(W/2, 4*mm, ar(f"وثيقة رسمية — نافذة الجمارك الليبية NAFIDHA | {jl38_number}"))
    c.save()
    buf.seek(0)
    return buf.getvalue()


def generate_jl119_pdf_bytes(sad: dict, acid: dict, verify_url: str) -> bytes:
    ensure_fonts()
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    def rtxt(x, y, text, font="AmiriBold", size=9, color=(0, 0, 0)):
        c.setFont(font, size)
        c.setFillColorRGB(*color)
        reshaped = arabic_reshaper.reshape(str(text)) if text else ""
        bidi_text = get_display(reshaped)
        c.drawRightString(x, y, bidi_text)

    def ltxt(x, y, text, font="Helvetica", size=9, color=(0, 0, 0)):
        c.setFont(font, size)
        c.setFillColorRGB(*color)
        c.drawString(x, y, str(text))

    def box(x, y, bw, bh, label_ar="", label_en="", value="", fill_rgb=(1, 1, 1)):
        c.setFillColorRGB(*fill_rgb)
        c.setStrokeColorRGB(0.4, 0.4, 0.4)
        c.rect(x, y, bw, bh, fill=1)
        if label_ar:
            rtxt(x + bw - 3, y + bh - 11, label_ar, size=7, color=(0.4, 0.4, 0.5))
        if label_en:
            ltxt(x + 3, y + bh - 11, label_en, size=6, color=(0.4, 0.4, 0.5))
        if value:
            rtxt(x + bw - 4, y + bh / 2 - 4, str(value), size=9)

    c.setFillColorRGB(0.12, 0.23, 0.37)
    c.rect(0, h - 60, w, 60, fill=1)
    rtxt(w - 15, h - 22, "مصلحة الجمارك الليبية", "AmiriBold", 14, (1, 1, 1))
    rtxt(w - 15, h - 38, "الجمهورية الليبية", "Amiri", 10, (0.83, 0.63, 0.09))
    ltxt(15, h - 22, "LIBYAN CUSTOMS AUTHORITY", "Helvetica-Bold", 10, (1, 1, 1))
    ltxt(15, h - 36, "Great State of Libya", "Helvetica", 8, (0.83, 0.63, 0.09))
    c.setFillColorRGB(0.83, 0.63, 0.09)
    c.rect(w / 2 - 80, h - 55, 160, 44, fill=1)
    rtxt(w / 2 + 78, h - 26, "نموذج البيان الجمركي", "AmiriBold", 12, (0.12, 0.23, 0.37))
    rtxt(w / 2 + 78, h - 41, "ج.ل.119", "AmiriBold", 11, (0.12, 0.23, 0.37))
    ltxt(w / 2 - 78, h - 26, "Customs Declaration", "Helvetica-Bold", 9, (0.12, 0.23, 0.37))
    ltxt(w / 2 - 78, h - 41, "Form JL.119", "Helvetica", 8, (0.12, 0.23, 0.37))

    y0 = h - 100
    box(10, y0, 100, 36, "رقم البيان", "Declaration No.", sad.get("sad_number", ""), (0.97, 0.97, 1))
    box(115, y0, 100, 36, "تاريخ التسجيل", "Date", sad.get("created_at", "")[:10], (0.97, 0.97, 1))
    box(220, y0, 80, 36, "نوع الإجراء", "Procedure", "استيراد / Import", (0.97, 0.97, 1))
    box(305, y0, 90, 36, "رقم ACID", "ACID No.", acid.get("acid_number", ""), (0.97, 0.97, 1))
    box(400, y0, 90, 36, "مركز الجمارك", "Customs Station", sad.get("customs_station", ""), (0.97, 0.97, 1))
    box(495, y0, 90, 36, "رقم الإيصال", "Receipt No.", sad.get("receipt_number", ""), (0.97, 0.97, 1))

    y0 -= 80
    box(10, y0, 280, 75, "المستورد / Importer", "", "", (0.95, 0.98, 1))
    importer_name = acid.get("company_name_ar") or acid.get("importer_name_ar") or acid.get("company_name_en", "")
    rtxt(285, y0 + 60, importer_name, size=9)
    rtxt(285, y0 + 45, acid.get("commercial_registry_no", ""), size=8, color=(0.3, 0.3, 0.3))
    rtxt(285, y0 + 30, acid.get("tax_id_tin", ""), size=8, color=(0.3, 0.3, 0.3))
    rtxt(285, y0 + 15, acid.get("city", ""), size=8, color=(0.3, 0.3, 0.3))
    box(295, y0, 280, 75, "المُصرِّح / المخلص  Declarant", "", "", (0.95, 0.98, 1))
    declarant = sad.get("declarant_name", "")
    rtxt(570, y0 + 60, declarant, size=9)
    rtxt(570, y0 + 45, sad.get("cbl_bank_ref", ""), size=8, color=(0.3, 0.3, 0.3))

    y0 -= 50
    box(10, y0, 140, 45, "وسيلة النقل", "Transport Mode", acid.get("transport_mode", ""), (0.97, 1, 0.97))
    box(155, y0, 140, 45, "بلد المنشأ", "Country of Origin", acid.get("supplier_country", ""), (0.97, 1, 0.97))
    box(300, y0, 140, 45, "منفذ الدخول", "Port of Entry", acid.get("port_of_entry", ""), (0.97, 1, 0.97))
    box(445, y0, 140, 45, "مرجع التحويل CBL", "CBL Reference", sad.get("cbl_bank_ref", ""), (0.97, 1, 0.97))

    y0 -= 70
    c.setFillColorRGB(0.12, 0.23, 0.37)
    c.rect(10, y0 + 58, 575, 14, fill=1)
    rtxt(580, y0 + 62, "31 — وصف البضاعة / Description of Goods", "AmiriBold", 9, (1, 1, 1))
    box(10, y0, 575, 55, "", "", "", (0.98, 0.98, 1))
    goods_ar = acid.get("goods_description_ar") or acid.get("goods_description", "")
    goods_en = acid.get("goods_description_en", "")
    rtxt(580, y0 + 38, goods_ar, "Amiri", 10)
    if goods_en:
        ltxt(14, y0 + 38, goods_en, "Helvetica", 9, (0.4, 0.4, 0.4))

    y0 -= 50
    box(10, y0, 90, 44, "33 — رمز البضاعة", "HS Code", acid.get("hs_code", ""), (0.97, 0.97, 1))
    box(105, y0, 100, 44, "35 — الوزن الإجمالي", "Gross Weight (KG)", str(acid.get("gross_weight", "")), (0.97, 0.97, 1))
    box(210, y0, 100, 44, "36 — الوزن الصافي", "Net Weight (KG)", str(acid.get("net_weight", "")), (0.97, 0.97, 1))
    box(315, y0, 100, 44, "37 — عدد الطرود", "No. of Packages", str(acid.get("num_packages", "")), (0.97, 0.97, 1))
    box(420, y0, 80, 44, "العملة", "Currency", "USD", (0.97, 0.97, 1))
    box(505, y0, 90, 44, "42 — قيمة البضاعة", "Goods Value", f"${acid.get('value_usd', 0):,.2f}", (0.97, 0.97, 1))

    y0 -= 15
    c.setFillColorRGB(0.12, 0.23, 0.37)
    c.rect(10, y0 - 5, 575, 14, fill=1)
    rtxt(580, y0, "47 — حساب الرسوم والضرائب / Duties & Taxes Calculation", "AmiriBold", 9, (1, 1, 1))

    y0 -= 130
    c.setFillColorRGB(0.25, 0.41, 0.63)
    c.rect(10, y0 + 120, 575, 18, fill=1)
    headers = [("البيان / Description", 580), ("القيمة بالدولار", 490), ("سعر الصرف", 390), ("القيمة بالدينار", 290), ("النسبة", 200), ("النوع", 100)]
    for lbl, xp in headers:
        rtxt(xp, y0 + 126, lbl, "AmiriBold", 8, (1, 1, 1))

    rows = [
        ("القيمة الجمركية / Customs Value", f"${sad.get('value_usd', 0):,.2f}", f"{sad.get('exchange_rate', 4.87)}", f"{sad.get('value_lyd', 0):,.2f} LYD", "", ""),
        ("الرسوم الجمركية / Customs Duty", f"${sad.get('customs_duty_usd', 0):,.2f}", f"{sad.get('exchange_rate', 4.87)}", f"{sad.get('customs_duty_lyd', 0):,.2f} LYD", sad.get("customs_rate_pct", ""), "CD"),
        ("ضريبة القيمة المضافة / VAT", f"${sad.get('vat_usd', 0):,.2f}", f"{sad.get('exchange_rate', 4.87)}", f"{sad.get('vat_lyd', 0):,.2f} LYD", "9%", "VAT"),
        ("الإجمالي المستحق / Total Due", f"${sad.get('total_usd', 0):,.2f}", "", f"{sad.get('total_lyd', 0):,.2f} LYD", "", "TOTAL"),
    ]
    for i, (desc, usd, exch, lyd, pct, typ) in enumerate(rows):
        row_y = y0 + 100 - (i * 22)
        row_fill = (0.97, 0.99, 0.97) if i % 2 == 0 else (1, 1, 1)
        if i == 3:
            row_fill = (0.93, 0.97, 0.93)
        c.setFillColorRGB(*row_fill)
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.rect(10, row_y - 5, 575, 20, fill=1)
        rtxt(580, row_y + 5, desc, "Amiri" if i < 3 else "AmiriBold", 8)
        ltxt(395, row_y + 5, usd, "Helvetica-Bold" if i == 3 else "Helvetica", 8)
        ltxt(300, row_y + 5, lyd, "Helvetica-Bold" if i == 3 else "Helvetica", 8, (0.12, 0.23, 0.37) if i == 3 else (0, 0, 0))
        ltxt(205, row_y + 5, pct, "Helvetica", 8)
        ltxt(105, row_y + 5, typ, "Helvetica-Bold", 8, (0.83, 0.63, 0.09) if typ == "TOTAL" else (0, 0, 0))

    y0 -= 20
    c.setFillColorRGB(0.12, 0.23, 0.37)
    c.rect(10, y0 - 30, 575, 28, fill=1)
    rtxt(580, y0 - 10, f"الإجمالي المستحق:  {sad.get('total_lyd', 0):,.3f}  دينار ليبي", "AmiriBold", 11, (0.83, 0.63, 0.09))
    ltxt(14, y0 - 10, f"Total Due:  LYD {sad.get('total_lyd', 0):,.3f}", "Helvetica-Bold", 9, (1, 1, 1))

    y0 -= 70
    try:
        qr = qrcode.QRCode(version=1, box_size=3, border=2)
        qr.add_data(f"{verify_url}?n={sad.get('sad_number', '')}")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#1e3a5f", back_color="white")
        qr_buf = io.BytesIO(); qr_img.save(qr_buf, format='PNG')
        qr_buf.seek(0)
        c.drawImage(ImageReader(qr_buf), 10, y0 - 20, width=60, height=60)
    except Exception:
        pass
    rtxt(580, y0 + 25, "54 — المكان والتاريخ والتوقيع", "AmiriBold", 9)
    rtxt(580, y0 + 10, f"طرابلس  —  {sad.get('created_at', '')[:10]}", "Amiri", 9, (0.3, 0.3, 0.3))
    c.setStrokeColorRGB(0.4, 0.4, 0.4)
    c.line(85, y0, 300, y0)
    rtxt(300, y0 - 12, "توقيع المُصرِّح / Declarant Signature", "Amiri", 8, (0.5, 0.5, 0.5))
    c.line(340, y0, 580, y0)
    rtxt(580, y0 - 12, "ختم وتوقيع الجمارك / Customs Stamp & Signature", "Amiri", 8, (0.5, 0.5, 0.5))

    c.setFillColorRGB(0.93, 0.93, 0.93)
    c.rect(0, 0, w, 22, fill=1)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    ltxt(10, 7, f"NAFIDHA Digital Single Window | {verify_url}", "Helvetica", 7)
    rtxt(w - 10, 7, f"نافذة — النافذة الوطنية الواحدة للجمارك الليبية", "Amiri", 7)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
