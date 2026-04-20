"""
reports.py — نقاط نهاية تقارير الأداء
"""
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse, HTMLResponse
import io

from auth_utils import require_roles
from models import UserRole
from services.report_service import generate_weekly_report

router = APIRouter(prefix="/reports", tags=["reports"])

_ADMIN = UserRole.ADMIN

_DELIVERY_PATH = Path(__file__).parent.parent.parent / "memory" / "DELIVERY.html"


@router.get("/handoff", response_class=HTMLResponse, include_in_schema=False)
async def view_handoff_doc():
    """
    عرض وثيقة التسليم الرسمية — لا تحتاج مصادقة (للعرض التوضيحي).
    الرابط: /api/reports/handoff
    """
    if _DELIVERY_PATH.exists():
        return HTMLResponse(content=_DELIVERY_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>الملف غير موجود</h1>", status_code=404)


@router.get("/weekly-performance")
async def download_weekly_report(
    week_offset: int = 0,
    current_user=Depends(require_roles(_ADMIN)),
):
    """
    يولِّد تقرير PDF للأداء الأسبوعي ويُرسله مباشرة للمتصفح.
    week_offset=0 → الأسبوع الحالي | week_offset=1 → الأسبوع الماضي
    """
    pdf_bytes = await generate_weekly_report(week_offset=week_offset)
    now       = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename  = f"nafidha_weekly_report_{now}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length":      str(len(pdf_bytes)),
        },
    )
