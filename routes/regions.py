"""
Regions & Ports Configurator — Admin API
نظام المناطق الجمركية والمنافذ المرتبطة بها
GET  /regions/public          — قائمة المناطق العامة للـ wizard
GET  /regions                 — قائمة المناطق (admin)
POST /regions                 — إنشاء منطقة (admin)
PUT  /regions/{id}            — تعديل منطقة (admin)
DELETE /regions/{id}          — حذف منطقة (admin)
POST /regions/{id}/ports      — إضافة منفذ (admin)
DELETE /regions/{id}/ports/{port_code} — حذف منفذ (admin)
"""
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from database import db
from auth_utils import require_roles
from models import UserRole

router = APIRouter(prefix="/regions", tags=["Regions"])

_ADMINS = (UserRole.ADMIN,)

# ── البيانات الأولية للمناطق الليبية ──────────────────────────────────────────
DEFAULT_REGIONS = [
    {
        "region_code": "TRP",
        "region_name_ar": "طرابلس الكبرى",
        "region_name_en": "Greater Tripoli",
        "ports": [
            {"port_code": "TRP_SEA", "port_name_ar": "ميناء طرابلس البحري", "port_name_en": "Tripoli Sea Port", "transport_mode": "sea"},
            {"port_code": "TRP_AIR", "port_name_ar": "مطار طرابلس الدولي (معيتيقة)", "port_name_en": "Tripoli Intl Airport (Mitiga)", "transport_mode": "air"},
            {"port_code": "TRP_RAS", "port_name_ar": "معبر رأس اجدير البري", "port_name_en": "Ras Ajdir Land Border", "transport_mode": "land"},
        ],
        "is_active": True,
    },
    {
        "region_code": "BNG",
        "region_name_ar": "بنغازي والشرق",
        "region_name_en": "Benghazi & East",
        "ports": [
            {"port_code": "BNG_SEA", "port_name_ar": "ميناء بنغازي البحري", "port_name_en": "Benghazi Sea Port", "transport_mode": "sea"},
            {"port_code": "BNG_AIR", "port_name_ar": "مطار بنينا الدولي", "port_name_en": "Benina International Airport", "transport_mode": "air"},
            {"port_code": "BNG_SAL", "port_name_ar": "معبر السلوم البري", "port_name_en": "Sallum Land Border", "transport_mode": "land"},
        ],
        "is_active": True,
    },
    {
        "region_code": "MSR",
        "region_name_ar": "مصراتة والوسط",
        "region_name_en": "Misrata & Center",
        "ports": [
            {"port_code": "MSR_FREE", "port_name_ar": "ميناء مصراتة الحر", "port_name_en": "Misrata Free Port", "transport_mode": "sea"},
            {"port_code": "MSR_AIR",  "port_name_ar": "مطار مصراتة الدولي", "port_name_en": "Misrata International Airport", "transport_mode": "air"},
        ],
        "is_active": True,
    },
    {
        "region_code": "ZWT",
        "region_name_ar": "الزاوية والغرب",
        "region_name_en": "Zawiya & West",
        "ports": [
            {"port_code": "ZWT_SEA", "port_name_ar": "ميناء الخمس البحري", "port_name_en": "Khoms Sea Port", "transport_mode": "sea"},
            {"port_code": "ZWT_ZUW", "port_name_ar": "معبر الذهيبة البري", "port_name_en": "Dheiba Land Border", "transport_mode": "land"},
        ],
        "is_active": True,
    },
    {
        "region_code": "SBH",
        "region_name_ar": "سبها والجنوب",
        "region_name_en": "Sabha & South",
        "ports": [
            {"port_code": "SBH_AIR", "port_name_ar": "مطار سبها الدولي", "port_name_en": "Sabha International Airport", "transport_mode": "air"},
        ],
        "is_active": True,
    },
]


def _region_to_dict(r: dict) -> dict:
    d = dict(r)
    d["_id"] = str(d["_id"])
    return d


async def seed_default_regions():
    """يُزرع عند الإقلاع إذا كانت المجموعة فارغة"""
    count = await db.regions.count_documents({})
    if count == 0:
        now = datetime.now(timezone.utc).isoformat()
        for reg in DEFAULT_REGIONS:
            reg["created_at"] = now
        await db.regions.insert_many(DEFAULT_REGIONS)


# ── GET /regions/public ─────────────────────────────────────────────────────────
@router.get("/public")
async def get_public_regions():
    """قائمة المناطق العامة للـ Wizard (لا تتطلب مصادقة)"""
    cursor = db.regions.find({"is_active": True}, {"_id": 1, "region_code": 1, "region_name_ar": 1, "region_name_en": 1, "ports": 1})
    regions = [_region_to_dict(r) async for r in cursor]
    return regions


# ── GET /regions ────────────────────────────────────────────────────────────────
@router.get("")
async def list_regions(current_user=Depends(require_roles(*_ADMINS))):
    cursor = db.regions.find({}).sort("region_code", 1)
    return [_region_to_dict(r) async for r in cursor]


# ── POST /regions ───────────────────────────────────────────────────────────────
class RegionCreate(BaseModel):
    region_code: str
    region_name_ar: str
    region_name_en: str
    is_active: Optional[bool] = True


@router.post("")
async def create_region(data: RegionCreate, current_user=Depends(require_roles(*_ADMINS))):
    existing = await db.regions.find_one({"region_code": data.region_code.upper()})
    if existing:
        raise HTTPException(409, f"كود المنطقة {data.region_code} موجود مسبقاً")
    doc = {
        "region_code":    data.region_code.upper(),
        "region_name_ar": data.region_name_ar,
        "region_name_en": data.region_name_en,
        "ports":          [],
        "is_active":      data.is_active,
        "created_at":     datetime.now(timezone.utc).isoformat(),
        "created_by":     current_user.get("name_ar", ""),
    }
    result = await db.regions.insert_one(doc)
    return {"message": "تم إنشاء المنطقة", "_id": str(result.inserted_id)}


# ── PUT /regions/{id} ───────────────────────────────────────────────────────────
class RegionUpdate(BaseModel):
    region_name_ar: Optional[str] = None
    region_name_en: Optional[str] = None
    is_active:      Optional[bool] = None


@router.put("/{region_id}")
async def update_region(region_id: str, data: RegionUpdate, current_user=Depends(require_roles(*_ADMINS))):
    if not ObjectId.is_valid(region_id):
        raise HTTPException(400, "معرّف غير صالح")
    upd = {k: v for k, v in data.model_dump().items() if v is not None}
    if not upd:
        raise HTTPException(400, "لا يوجد شيء للتحديث")
    upd["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.regions.update_one({"_id": ObjectId(region_id)}, {"$set": upd})
    return {"message": "تم التحديث"}


# ── DELETE /regions/{id} ────────────────────────────────────────────────────────
@router.delete("/{region_id}")
async def delete_region(region_id: str, current_user=Depends(require_roles(*_ADMINS))):
    if not ObjectId.is_valid(region_id):
        raise HTTPException(400, "معرّف غير صالح")
    await db.regions.delete_one({"_id": ObjectId(region_id)})
    return {"message": "تم الحذف"}


# ── POST /regions/{id}/ports ────────────────────────────────────────────────────
class PortCreate(BaseModel):
    port_code:    str
    port_name_ar: str
    port_name_en: str
    transport_mode: Optional[str] = "sea"  # sea | air | land


@router.post("/{region_id}/ports")
async def add_port(region_id: str, data: PortCreate, current_user=Depends(require_roles(*_ADMINS))):
    if not ObjectId.is_valid(region_id):
        raise HTTPException(400, "معرّف غير صالح")
    region = await db.regions.find_one({"_id": ObjectId(region_id)})
    if not region:
        raise HTTPException(404, "المنطقة غير موجودة")
    # تحقق من عدم التكرار
    existing_codes = [p["port_code"] for p in region.get("ports", [])]
    if data.port_code in existing_codes:
        raise HTTPException(409, f"كود المنفذ {data.port_code} موجود مسبقاً في هذه المنطقة")
    new_port = {
        "port_code":      data.port_code,
        "port_name_ar":   data.port_name_ar,
        "port_name_en":   data.port_name_en,
        "transport_mode": data.transport_mode,
    }
    await db.regions.update_one({"_id": ObjectId(region_id)}, {"$push": {"ports": new_port}})
    return {"message": "تم إضافة المنفذ"}


# ── DELETE /regions/{id}/ports/{port_code} ──────────────────────────────────────
@router.delete("/{region_id}/ports/{port_code}")
async def remove_port(region_id: str, port_code: str, current_user=Depends(require_roles(*_ADMINS))):
    if not ObjectId.is_valid(region_id):
        raise HTTPException(400, "معرّف غير صالح")
    await db.regions.update_one(
        {"_id": ObjectId(region_id)},
        {"$pull": {"ports": {"port_code": port_code}}}
    )
    return {"message": "تم حذف المنفذ"}
