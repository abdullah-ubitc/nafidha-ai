"""
Land Trip (Manifest Terrestre) — رحلات المنافذ البرية
POST /land-trip/submit            — إرسال بيانات الرحلة البرية (multipart)
GET  /land-trip/by-acid/{acid_id} — جلب بيانات الرحلة المرتبطة بـ ACID
GET  /land-trip/{trip_id}         — جلب رحلة واحدة
POST /land-trip/{trip_id}/approve — مأمور يعتمد الرحلة (مع Musaid validation)
POST /land-trip/{trip_id}/reject  — مأمور يرفض الرحلة
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from bson import ObjectId
from typing import Optional
from datetime import datetime, timezone
import os, shutil

from database import db
from auth_utils import get_current_user, require_roles
from models import UserRole

router = APIRouter(prefix="/land-trip", tags=["Land Trip"])

_UPLOAD_DIR = "/app/uploads/land_trips"

# ── المنافذ البرية — تتطلب وثائق الشاحنة/السائق ──────────────────────────────
LAND_PORTS = {
    "منفذ مساعد", "منفذ أمساعد", "رأس جدير البري", "منفذ الوازن",
    "أمبروزية البري", "منفذ الشورف",
}
# هذه المنافذ تتطلب التحقق الصارم من صورة وثيقة السائق قبل الاعتماد
MUSAID_STRICT_PORTS = {"منفذ مساعد", "منفذ أمساعد"}

_REVIEWERS = (UserRole.ADMIN, UserRole.REGISTRATION_OFFICER, UserRole.MANIFEST_OFFICER)
_SUBMITTERS = (UserRole.IMPORTER, UserRole.CUSTOMS_BROKER, UserRole.CARRIER_AGENT, UserRole.ADMIN)


def _trip_to_dict(t: dict) -> dict:
    d = dict(t)
    d["_id"]       = str(d["_id"])
    d["acid_id"]   = str(d.get("acid_id", ""))
    if d.get("reviewed_by"):
        d["reviewed_by"] = str(d["reviewed_by"])
    return d


# ── POST /land-trip/submit ─────────────────────────────────────────────────────
@router.post("/submit")
async def submit_land_trip(
    acid_id:            str           = Form(...),
    truck_license_plate: str          = Form(...),
    truck_nationality:  str           = Form(...),
    driver_name:        str           = Form(...),
    driver_id_type:     str           = Form("license"),   # "license" | "passport"
    estimated_arrival:  Optional[str] = Form(None),
    trailer_plate:      Optional[str] = Form(None),
    notes:              Optional[str] = Form(None),
    driver_id_photo:    UploadFile    = File(...),
    current_user=Depends(require_roles(*_SUBMITTERS)),
):
    """إرسال بيانات الرحلة البرية مع صورة وثيقة السائق"""

    if not ObjectId.is_valid(acid_id):
        raise HTTPException(400, "معرّف طلب ACID غير صالح")

    # جلب طلب ACID للتحقق من وجوده وأن منفذه بري
    acid = await db.acid_requests.find_one({"_id": ObjectId(acid_id)})
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")

    port_of_entry = acid.get("port_of_entry", "")
    if acid.get("transport_mode", "").lower() != "land" and port_of_entry not in LAND_PORTS:
        raise HTTPException(400, "هذا الطلب ليس برياً — بيانات الرحلة البرية تنطبق فقط على منافذ النقل البري")

    # منع التكرار — رحلة واحدة فقط لكل طلب ACID
    existing = await db.land_trips.find_one({"acid_id": ObjectId(acid_id), "status": {"$ne": "rejected"}})
    if existing:
        raise HTTPException(409, "يوجد رحلة برية مقدَّمة لهذا الطلب — يمكنك التعديل عليها أو الانتظار لنتيجة المراجعة")

    # حفظ الصورة
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    ts        = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = f"{acid_id}_{ts}_{driver_id_photo.filename}"
    file_path = os.path.join(_UPLOAD_DIR, safe_name)
    with open(file_path, "wb") as fh:
        shutil.copyfileobj(driver_id_photo.file, fh)

    now = datetime.now(timezone.utc).isoformat()
    is_musaid = port_of_entry in MUSAID_STRICT_PORTS

    trip_doc = {
        "acid_id":              ObjectId(acid_id),
        "acid_number":          acid.get("acid_number", ""),
        "port_of_entry":        port_of_entry,
        "is_musaid_port":       is_musaid,
        "submitted_by":         current_user["_id"],
        "submitted_by_name":    current_user.get("name_ar", ""),
        "truck_license_plate":  truck_license_plate.strip().upper(),
        "truck_nationality":    truck_nationality.strip(),
        "driver_name":          driver_name.strip(),
        "driver_id_type":       driver_id_type,
        "driver_id_photo_path": file_path,
        "driver_id_photo_name": driver_id_photo.filename,
        "trailer_plate":        (trailer_plate or "").strip().upper() or None,
        "estimated_arrival":    estimated_arrival,
        "notes":                notes,
        "status":               "pending",
        "officer_confirmed_photo_clarity": False,
        "reviewed_by":          None,
        "reviewed_at":          None,
        "rejection_reason":     None,
        "created_at":           now,
    }
    result   = await db.land_trips.insert_one(trip_doc)
    trip_id  = str(result.inserted_id)

    # ربط الـ ACID بالرحلة البرية
    await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {"$set": {"land_trip_id": trip_id, "land_trip_status": "pending"}}
    )

    # Timeline
    await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {"$push": {"timeline": {
            "event":     "land_trip_submitted",
            "actor":     current_user.get("name_ar", ""),
            "role":      current_user.get("role", ""),
            "timestamp": now,
            "details": {
                "truck_license_plate": truck_license_plate,
                "truck_nationality":   truck_nationality,
                "driver_name":         driver_name,
                "is_musaid_port":      is_musaid,
            },
        }}}
    )

    msg = "تم تقديم بيانات الرحلة البرية بنجاح"
    if is_musaid:
        msg += " — منفذ مساعد يتطلب التحقق الصارم من وثيقة السائق قبل الاعتماد"
    return {"message": msg, "trip_id": trip_id, "is_musaid_port": is_musaid}


# ── GET /land-trip/by-acid/{acid_id} ──────────────────────────────────────────
@router.get("/by-acid/{acid_id}")
async def get_land_trip_by_acid(acid_id: str, current_user=Depends(get_current_user)):
    if not ObjectId.is_valid(acid_id):
        raise HTTPException(400, "معرّف غير صالح")
    trip = await db.land_trips.find_one({"acid_id": ObjectId(acid_id)}, {"driver_id_photo_path": 0})
    if not trip:
        raise HTTPException(404, "لا توجد رحلة برية مرتبطة بهذا الطلب")
    return _trip_to_dict(trip)


# ── GET /land-trip/{trip_id} ───────────────────────────────────────────────────
@router.get("/{trip_id}")
async def get_land_trip(trip_id: str, current_user=Depends(get_current_user)):
    if not ObjectId.is_valid(trip_id):
        raise HTTPException(400, "معرّف غير صالح")
    trip = await db.land_trips.find_one({"_id": ObjectId(trip_id)}, {"driver_id_photo_path": 0})
    if not trip:
        raise HTTPException(404, "الرحلة البرية غير موجودة")
    return _trip_to_dict(trip)


# ── POST /land-trip/{trip_id}/approve ─────────────────────────────────────────
@router.post("/{trip_id}/approve")
async def approve_land_trip(
    trip_id:                  str,
    photo_clarity_confirmed:  bool = Form(True),
    notes:                    Optional[str] = Form(None),
    current_user=Depends(require_roles(*_REVIEWERS)),
):
    """
    مأمور يعتمد الرحلة البرية.
    - المنافذ العادية: يمكن الاعتماد مباشرةً
    - منفذ مساعد/أمساعد (Musaid Strict): يجب تأكيد وضوح صورة الوثيقة
    """
    if not ObjectId.is_valid(trip_id):
        raise HTTPException(400, "معرّف غير صالح")
    trip = await db.land_trips.find_one({"_id": ObjectId(trip_id)})
    if not trip:
        raise HTTPException(404, "الرحلة البرية غير موجودة")
    if trip["status"] != "pending":
        raise HTTPException(409, "تم معالجة هذه الرحلة مسبقاً")

    # ── Musaid Strict Validation ────────────────────────────────────────────────
    if trip.get("is_musaid_port") and not photo_clarity_confirmed:
        raise HTTPException(422, {
            "code":    "MUSAID_PHOTO_REQUIRED",
            "message": "منفذ مساعد يتطلب التأكيد الصريح بوضوح صورة وثيقة السائق قبل الاعتماد"
        })

    # تحقق من وجود الصورة على الـ disk
    photo_path = trip.get("driver_id_photo_path")
    if trip.get("is_musaid_port") and (not photo_path or not os.path.exists(photo_path)):
        raise HTTPException(422, {
            "code":    "MUSAID_PHOTO_MISSING",
            "message": "صورة وثيقة السائق غير موجودة — لا يمكن اعتماد رحلة منفذ مساعد بدون وثيقة واضحة"
        })

    now = datetime.now(timezone.utc).isoformat()
    await db.land_trips.update_one(
        {"_id": ObjectId(trip_id)},
        {"$set": {
            "status":                         "approved",
            "reviewed_by":                    ObjectId(current_user["_id"]),
            "reviewed_by_name":               current_user.get("name_ar", ""),
            "reviewed_at":                    now,
            "officer_confirmed_photo_clarity": photo_clarity_confirmed,
            "officer_notes":                  notes,
        }}
    )

    # تحديث ACID
    acid_id = trip["acid_id"]
    await db.acid_requests.update_one(
        {"_id": acid_id},
        {"$set":  {"land_trip_status": "approved"},
         "$push": {"timeline": {
            "event":     "land_trip_approved",
            "actor":     current_user.get("name_ar", ""),
            "role":      current_user.get("role", ""),
            "timestamp": now,
            "details":   {"trip_id": trip_id, "truck_plate": trip["truck_license_plate"],
                          "driver": trip["driver_name"], "musaid_confirmed": photo_clarity_confirmed},
         }}}
    )
    return {"message": f"تم اعتماد الرحلة البرية للشاحنة {trip['truck_license_plate']}", "auto_cleared": True}


# ── POST /land-trip/{trip_id}/reject ──────────────────────────────────────────
@router.post("/{trip_id}/reject")
async def reject_land_trip(
    trip_id: str,
    reason:  str = Form(...),
    current_user=Depends(require_roles(*_REVIEWERS)),
):
    """مأمور يرفض بيانات الرحلة البرية مع ذكر السبب"""
    if not ObjectId.is_valid(trip_id):
        raise HTTPException(400, "معرّف غير صالح")
    trip = await db.land_trips.find_one({"_id": ObjectId(trip_id)})
    if not trip:
        raise HTTPException(404, "الرحلة البرية غير موجودة")
    if trip["status"] != "pending":
        raise HTTPException(409, "تم معالجة هذه الرحلة مسبقاً")

    now = datetime.now(timezone.utc).isoformat()
    await db.land_trips.update_one(
        {"_id": ObjectId(trip_id)},
        {"$set": {
            "status":           "rejected",
            "reviewed_by":      ObjectId(current_user["_id"]),
            "reviewed_by_name": current_user.get("name_ar", ""),
            "reviewed_at":      now,
            "rejection_reason": reason,
        }}
    )
    await db.acid_requests.update_one(
        {"_id": trip["acid_id"]},
        {"$set":  {"land_trip_status": "rejected"},
         "$push": {"timeline": {
            "event":     "land_trip_rejected",
            "actor":     current_user.get("name_ar", ""),
            "role":      current_user.get("role", ""),
            "timestamp": now,
            "details":   {"trip_id": trip_id, "reason": reason},
         }}}
    )
    return {"message": "تم رفض بيانات الرحلة البرية"}


# ── GET /land-trip/queue (للمراجعين) ─────────────────────────────────────────
@router.get("/queue/pending")
async def get_pending_land_trips(current_user=Depends(require_roles(*_REVIEWERS))):
    """قائمة الرحلات البرية المعلقة للمراجعة"""
    trips = await db.land_trips.find(
        {"status": "pending"},
        {"driver_id_photo_path": 0}
    ).sort("created_at", 1).to_list(100)
    return [_trip_to_dict(t) for t in trips]
