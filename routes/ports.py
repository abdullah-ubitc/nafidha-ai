"""
ports.py — إحصاءات المنافذ الحية لخريطة Admin Control Tower
GET /api/ports/stats — إجمالي النشاط لكل منفذ
"""
from fastapi import APIRouter, Depends
from database import db
from auth_utils import require_roles
from models import UserRole
from datetime import datetime, timezone

router = APIRouter(prefix="/ports", tags=["ports"])

_ACTIVE_ACID_STATUSES = ["submitted", "under_review", "pending", "approved"]


@router.get("/stats")
async def get_ports_stats(
    current_user=Depends(require_roles(UserRole.ADMIN, UserRole.MANIFEST_OFFICER))
):
    """
    يُرجع إحصاءات النشاط لكل منفذ دخول:
    - acid_count: عدد طلبات ACID النشطة
    - land_pending: رحلات برية معلقة
    - land_escalated: رحلات برية مصعَّدة
    - status: normal | caution | alert
    """
    # ── ACID per port ──────────────────────────────────────────
    acid_pipeline = [
        {"$match": {"status": {"$in": _ACTIVE_ACID_STATUSES}}},
        {"$group": {"_id": "$port_of_entry", "count": {"$sum": 1}}},
    ]
    acid_res = await db.acid_requests.aggregate(acid_pipeline).to_list(100)
    acid_map = {r["_id"]: r["count"] for r in acid_res if r["_id"]}

    # ── Land trips per port ────────────────────────────────────
    land_pipeline = [
        {"$group": {
            "_id":      {"port": "$port_of_entry", "status": "$status"},
            "count":    {"$sum": 1},
        }},
    ]
    land_res = await db.land_trips.aggregate(land_pipeline).to_list(200)
    land_pending:   dict[str, int] = {}
    land_escalated: dict[str, int] = {}
    for r in land_res:
        port   = r["_id"].get("port", "")
        status = r["_id"].get("status", "")
        if not port:
            continue
        if status == "pending":
            land_pending[port]   = land_pending.get(port, 0)   + r["count"]
        elif status == "escalated":
            land_escalated[port] = land_escalated.get(port, 0) + r["count"]

    # ── Total counters for summary ─────────────────────────────
    total_acids     = await db.acid_requests.count_documents({"status": {"$in": _ACTIVE_ACID_STATUSES}})
    total_escalated = await db.land_trips.count_documents({"status": "escalated"})
    total_pending   = await db.land_trips.count_documents({"status": "pending"})

    # ── Build port list ────────────────────────────────────────
    all_ports = [
        # Sea
        {"value": "طرابلس البحري",       "label_en": "Tripoli Sea Port",         "mode": "sea",  "region": "TRP", "lon": 13.18, "lat": 32.9},
        {"value": "بنغازي البحري",       "label_en": "Benghazi Sea Port",        "mode": "sea",  "region": "BNG", "lon": 20.07, "lat": 32.11},
        {"value": "مصراتة البحري",       "label_en": "Misrata Sea Port",         "mode": "sea",  "region": "MSR", "lon": 15.09, "lat": 32.37},
        {"value": "ميناء الخمس",         "label_en": "Khoms Sea Port",           "mode": "sea",  "region": "ZWT", "lon": 14.26, "lat": 32.64},
        {"value": "ميناء الزاوية",       "label_en": "Zawia Port",               "mode": "sea",  "region": "ZWT", "lon": 12.73, "lat": 32.75},
        {"value": "ميناء زوارة",         "label_en": "Zuara Port",               "mode": "sea",  "region": "ZWT", "lon": 12.08, "lat": 32.92},
        {"value": "ميناء راس لانوف",     "label_en": "Ras Lanuf Port",           "mode": "sea",  "region": "BNG", "lon": 18.57, "lat": 30.49},
        {"value": "ميناء درنة",          "label_en": "Derna Port",               "mode": "sea",  "region": "BNG", "lon": 22.64, "lat": 32.76},
        # Air
        {"value": "مطار طرابلس الدولي",  "label_en": "Tripoli Int'l Airport",   "mode": "air",  "region": "TRP", "lon": 13.16, "lat": 32.67},
        {"value": "مطار معيتيقة",        "label_en": "Mitiga Airport",           "mode": "air",  "region": "TRP", "lon": 13.28, "lat": 32.89},
        {"value": "مطار بنينة الدولي",   "label_en": "Benina Int'l Airport",    "mode": "air",  "region": "BNG", "lon": 20.27, "lat": 32.1},
        {"value": "مطار مصراتة",         "label_en": "Misrata Airport",          "mode": "air",  "region": "MSR", "lon": 15.06, "lat": 32.32},
        {"value": "مطار سبها",           "label_en": "Sabha Airport",            "mode": "air",  "region": "SBH", "lon": 14.47, "lat": 27.01},
        # Land
        {"value": "رأس جدير البري",      "label_en": "Ra's Ajdir Land Border",  "mode": "land", "region": "TRP", "lon": 11.58, "lat": 33.14},
        {"value": "أمبروزية البري",      "label_en": "Ambrosia Land Border",    "mode": "land", "region": "ZWT", "lon": 12.0,  "lat": 32.5},
        {"value": "منفذ مساعد",          "label_en": "Musaid Land Border",       "mode": "land", "region": "BNG", "lon": 25.1,  "lat": 31.88, "is_musaid": True},
        {"value": "منفذ أمساعد",         "label_en": "Amsaad Land Border",       "mode": "land", "region": "BNG", "lon": 24.9,  "lat": 31.8},
        {"value": "منفذ الوازن",         "label_en": "Al-Wazin Land Border",    "mode": "land", "region": "TRP", "lon": 10.74, "lat": 31.97},
        {"value": "منفذ الشورف",         "label_en": "Al-Shoruf Land Border",   "mode": "land", "region": "SBH", "lon": 14.0,  "lat": 24.0},
    ]

    def _status(port_name: str, acids: int, pending: int, escalated: int) -> str:
        if escalated > 0:
            return "alert"
        if pending >= 3 or acids >= 8:
            return "caution"
        if pending >= 1 or acids >= 1:
            return "active"
        return "idle"

    result = []
    for p in all_ports:
        name       = p["value"]
        acids      = acid_map.get(name, 0)
        pending    = land_pending.get(name, 0)
        escalated  = land_escalated.get(name, 0)
        result.append({
            **{k: v for k, v in p.items() if k not in ("lon", "lat")},
            "lon":          p["lon"],
            "lat":          p["lat"],
            "acid_count":   acids,
            "land_pending": pending,
            "land_escalated": escalated,
            "status":       _status(name, acids, pending, escalated),
        })

    return {
        "ports": result,
        "summary": {
            "total_active_acids":    total_acids,
            "total_land_pending":    total_pending,
            "total_land_escalated":  total_escalated,
            "alert_ports":           sum(1 for p in result if p["status"] == "alert"),
            "active_ports":          sum(1 for p in result if p["status"] in ("active", "caution", "alert")),
        },
    }



@router.get("/musaid-live")
async def get_musaid_live(
    current_user=Depends(require_roles(UserRole.ADMIN, UserRole.MANIFEST_OFFICER))
):
    """
    إحصاءات حية لمنفذ مساعد مع تفاصيل الرحلات المصعَّدة
    يُستخدم في Detail Panel عند النقر على ★ مساعد
    """
    now = datetime.now(timezone.utc)

    # جلب الرحلات المصعَّدة من منافذ مساعد وأمساعد
    musaid_ports = ["منفذ مساعد", "منفذ أمساعد"]
    escalated = await db.land_trips.find(
        {"port_of_entry": {"$in": musaid_ports}, "status": "escalated"},
        {"_id": 0, "truck_plate": 1, "acid_id": 1, "created_at": 1, "escalated_at": 1},
    ).sort("created_at", 1).to_list(50)

    trips = []
    for t in escalated:
        overdue_h = 0.0
        try:
            created = datetime.fromisoformat(str(t.get("created_at", "")))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            overdue_h = round((now - created).total_seconds() / 3600, 1)
        except Exception:
            pass

        acid_number = ""
        if t.get("acid_id"):
            from bson import ObjectId
            try:
                acid = await db.acid_requests.find_one(
                    {"_id": ObjectId(str(t["acid_id"]))}, {"_id": 0, "acid_number": 1}
                )
                acid_number = acid.get("acid_number", "") if acid else ""
            except Exception:
                pass

        trips.append({
            "truck_plate":   t.get("truck_plate", "—"),
            "acid_number":   acid_number,
            "overdue_hours": overdue_h,
            "escalated_at":  str(t.get("escalated_at", "")),
        })

    # إحصاءات عامة لمنفذ مساعد
    pending_count = await db.land_trips.count_documents(
        {"port_of_entry": {"$in": musaid_ports}, "status": "pending"}
    )
    total_today = await db.land_trips.count_documents(
        {"port_of_entry": {"$in": musaid_ports}}
    )

    return {
        "escalated_trips":  trips,
        "pending_count":    pending_count,
        "total_trips":      total_today,
        "escalated_count":  len(trips),
    }
