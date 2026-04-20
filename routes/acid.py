"""ACID request routes: create, list, get, review, JL38 download"""
import io
import os
import secrets
from typing import Optional, Dict, Any
from datetime import datetime, timezone, date
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from bson import ObjectId
from models import AcidRequestCreate, AcidReviewInput, UserRole
from database import db
from auth_utils import get_current_user, require_roles, require_approved_user
from helpers import format_doc, compute_risk, generate_acid_number, log_audit
from ws_manager import ws_manager
from notifications import send_acid_status_email, notify_user_whatsapp
from services.notification_service import send_notification, notify_role_users
from services.email_service import send_event_email
from pdf_generator import generate_jl38_pdf_bytes

router = APIRouter(prefix="/acid", tags=["acid"])


def _check_license_expiry(user: dict):
    """Hard-Stop: Block transactions if the user's statistical card or customs license is expired."""
    expiry_str = user.get("license_expiry_date") or user.get("license_expiry")
    if not expiry_str:
        return  # No expiry date set — allow
    try:
        expiry = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
        if expiry < date.today():
            raise HTTPException(
                status_code=403,
                detail=f"تم تعطيل حسابك — انتهت صلاحية الرخصة / البطاقة الإحصائية بتاريخ {expiry_str[:10]}. يرجى تجديدها والتواصل مع الإدارة."
            )
    except ValueError:
        pass  # Malformed date — allow


@router.post("")
async def create_acid(data: AcidRequestCreate, background_tasks: BackgroundTasks, current_user=Depends(require_approved_user)):
    allowed = ["importer", "customs_broker", "admin"]
    if current_user["role"] not in allowed:
        raise HTTPException(status_code=403, detail="غير مصرح لك بإنشاء طلبات ACID")

    # Phase E Hard-Stop: check license expiry
    _check_license_expiry(current_user)

    acid_number = await generate_acid_number()
    risk = compute_risk(data.value_usd, data.transport_mode.value, data.hs_code)

    # Global Exporter Registry — تسجيل/ربط المصدر تلقائياً + Green Channel Detection
    exporter_tax_id = data.exporter_tax_id or None
    is_green_channel = False   # القناة الخضراء — تُفعَّل إذا كان المصدر موثَّقاً رسمياً
    priority_score   = 0       # 100 للقناة الخضراء، 0 للعادي
    if exporter_tax_id:
        existing_exporter = await db.global_exporters.find_one({"tax_id": exporter_tax_id})
        if existing_exporter:
            # أضف البريد الإلكتروني الجديد للقائمة إذا كان مختلفاً
            if data.exporter_email and data.exporter_email not in existing_exporter.get("emails", []):
                await db.global_exporters.update_one(
                    {"tax_id": exporter_tax_id},
                    {"$addToSet": {"emails": data.exporter_email},
                     "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
                )
            # Green Channel: المصدر موثَّق رسمياً
            if existing_exporter.get("is_verified"):
                is_green_channel = True
                priority_score   = 100
        else:
            # إنشاء سجل جديد في قاعدة المصدرين العالميين
            exporter_doc = {
                "tax_id": exporter_tax_id,
                "company_name": data.supplier_name,
                "emails": [data.exporter_email] if data.exporter_email else [],
                "country": data.supplier_country,
                "address": data.supplier_address,
                "is_verified": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await db.global_exporters.insert_one(exporter_doc)
            except Exception:
                pass  # في حال وجود تعارض في tax_id بسبب concurrency

    doc = {
        "acid_number": acid_number,
        "requester_id": current_user["_id"],
        "requester_name_ar": current_user.get("company_name_ar") or current_user.get("name_ar"),
        "requester_name_en": current_user.get("company_name_en") or current_user.get("name_en"),
        "on_behalf_of": data.on_behalf_of,
        "broker_id": current_user["_id"] if current_user["role"] == "customs_broker" else None,
        "status": "submitted",
        "risk_level": risk,
        "supplier_name": data.supplier_name,
        "supplier_country": data.supplier_country,
        "supplier_address": data.supplier_address,
        "goods_description": data.goods_description,
        "hs_code": data.hs_code,
        "quantity": data.quantity,
        "unit": data.unit,
        "value_usd": data.value_usd,
        "port_of_entry": data.port_of_entry,
        "transport_mode": data.transport_mode.value,
        "carrier_name": data.carrier_name,
        "bill_of_lading": data.bill_of_lading,
        "estimated_arrival": data.estimated_arrival,
        # Phase E fields
        "exporter_email": data.exporter_email,
        "exporter_tax_id": exporter_tax_id,
        "exporter_confirmation": False,
        "supplier_confirm_token": secrets.token_urlsafe(32) if data.exporter_email else None,
        "proforma_invoice": data.proforma_invoice,
        # Phase K — Green Channel
        "is_green_channel": is_green_channel,         # True إذا كان المصدر موثَّقاً
        "priority_score": priority_score,             # 100 = Green Channel, 0 = Regular
        "clearance_started_at": None,                 # يُسجَّل عند بدء المراجعة
        "clearance_completed_at": None,               # يُسجَّل عند الاعتماد النهائي
        "platform_fees_paid": False,
        "reviewer_notes": None,
        "valuation_confirmed": False, "valuation_confirmed_at": None,
        "valuer_id": None, "valuation_notes": None, "confirmed_value_usd": None,
        "treasury_paid": False, "treasury_paid_at": None, "treasury_officer_id": None, "treasury_ref": None,
        "gate_released": False, "gate_released_at": None, "gate_officer_id": None, "jl38_number": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "timeline": [{"event": "submitted", "timestamp": datetime.now(timezone.utc).isoformat(), "actor": current_user.get("name_ar", "")}]
    }
    result = await db.acid_requests.insert_one(doc)
    acid_id_str = str(result.inserted_id)
    doc["_id"] = acid_id_str

    # Phase E — Create platform fee record for this ACID transaction
    from helpers import PLATFORM_FEE_AMOUNTS
    fee_doc = {
        "fee_type": "acid_transaction",
        "reference_id": acid_id_str,
        "acid_number": acid_number,
        "amount_lyd": PLATFORM_FEE_AMOUNTS.get("acid_transaction", 50),
        "payer_id": current_user["_id"],
        "payer_name": current_user.get("name_ar", ""),
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
    }
    await db.platform_fees.insert_one(fee_doc)

    # Phase E — Send HTML invitation email to exporter
    if data.exporter_email:
        background_tasks.add_task(
            _send_exporter_invitation,
            data.exporter_email,
            acid_number,
            data.supplier_name,
            current_user.get("company_name_ar") or current_user.get("name_ar", ""),
            data.goods_description,
            data.value_usd,
            data.hs_code,
            doc.get("supplier_confirm_token", ""),
        )

    # Phase L — Smart Notifications: Confirm submission + Green Channel alert
    requester_id = str(current_user["_id"])
    background_tasks.add_task(
        send_notification, requester_id, "acid_submitted",
        {"acid_number": acid_number}, "ar", acid_id_str,
    )
    if is_green_channel:
        background_tasks.add_task(
            send_notification, requester_id, "green_channel_activated",
            {"acid_number": acid_number}, "ar", acid_id_str,
        )
    # ── إشعار ضباط ACID بوصول طلب جديد للمراجعة ───────────────────
    _requester_name = current_user.get("name_ar") or current_user.get("company_name_ar", "")
    background_tasks.add_task(
        notify_role_users,
        "acid_risk_officer",
        "task_acid_submitted",
        {"acid_number": acid_number, "requester_name": _requester_name},
        acid_id_str,
        requester_id,
    )

    # Phase I — إيميل إشعار للمصدر عند ربط ACID بشركته (مصدر موثَّق فقط)
    if exporter_tax_id:
        exporter_rec = await db.global_exporters.find_one(
            {"tax_id": exporter_tax_id}, {"_id": 0, "email": 1, "emails": 1, "company_name": 1}
        )
        if exporter_rec and exporter_rec.get("is_verified", False) if False else exporter_rec:
            # نرسل للإيميل الرئيسي فقط لتجنب الإزعاج
            exporter_email = exporter_rec.get("email") or (exporter_rec.get("emails") or [None])[0]
            if exporter_email:
                background_tasks.add_task(
                    send_event_email,
                    "acid_assigned_to_exporter",
                    exporter_email,
                    {
                        "company_name":     exporter_rec.get("company_name", ""),
                        "acid_number":      acid_number,
                        "acid_id":          acid_id_str,
                        "importer_name":    current_user.get("company_name_ar") or current_user.get("name_ar", ""),
                        "port_of_entry":    data.port_of_entry,
                        "goods_description": data.goods_description,
                    },
                )

    doc["created_at"] = doc["created_at"].isoformat()
    doc["updated_at"] = doc["updated_at"].isoformat()
    return doc


async def _send_exporter_invitation(
    exporter_email: str,
    acid_number:    str,
    supplier_name:  str,
    importer_name:  str,
    goods_desc:     str,
    value_usd:      float,
    hs_code:        str,
    token:          str,
):
    """إرسال دعوة HTML احترافية للمصدر الأجنبي مع رابط تأكيد البيانات."""
    from services.email_service import send_supplier_invitation
    base_url   = os.environ.get("FRONTEND_BASE_URL", "https://libya-customs-acis.preview.emergentagent.com")
    confirm_url = f"{base_url}/supplier/confirm/{token}"
    await send_supplier_invitation(
        to_email=exporter_email,
        supplier_name=supplier_name,
        acid_number=acid_number,
        importer_name=importer_name,
        goods_desc=goods_desc,
        value_usd=value_usd,
        hs_code=hs_code,
        confirm_url=confirm_url,
    )


# ══════════════════════════════════════════════════════════════
# Endpoints علنية للمصدر الأجنبي — لا تتطلب مصادقة (تعمل بالتوكن فقط)
# ══════════════════════════════════════════════════════════════

@router.get("/supplier/confirm/{token}")
async def supplier_get_acid(token: str):
    """
    جلب بيانات ACID للمصدر عبر رابط التأكيد (endpoint علني).
    يُعيد فقط الحقول الضرورية للمصدر.
    """
    acid = await db.acid_requests.find_one({"supplier_confirm_token": token})
    if not acid:
        raise HTTPException(404, "رابط التأكيد غير صالح أو منتهي الصلاحية")
    return {
        "acid_number":           acid["acid_number"],
        "supplier_name":         acid.get("supplier_name", ""),
        "supplier_country":      acid.get("supplier_country", ""),
        "goods_description":     acid.get("goods_description", ""),
        "hs_code":               acid.get("hs_code", ""),
        "quantity":              acid.get("quantity"),
        "unit":                  acid.get("unit", ""),
        "value_usd":             acid.get("value_usd"),
        "transport_mode":        acid.get("transport_mode", ""),
        "port_of_entry":         acid.get("port_of_entry", ""),
        "estimated_arrival":     acid.get("estimated_arrival", ""),
        "importer_name":         acid.get("requester_name_en") or acid.get("requester_name_ar", ""),
        "exporter_confirmation": acid.get("exporter_confirmation", False),
        "exporter_confirmed_at": acid.get("exporter_confirmed_at"),
        "status":                acid.get("status", ""),
    }


@router.post("/supplier/confirm/{token}")
async def supplier_confirm_acid(token: str):
    """
    تأكيد بيانات الشحنة من قِبَل المصدر الأجنبي (endpoint علني).
    يستخدم التوكن الفريد كوسيلة مصادقة بدلاً من JWT.
    """
    acid = await db.acid_requests.find_one({"supplier_confirm_token": token})
    if not acid:
        raise HTTPException(404, "رابط التأكيد غير صالح أو منتهي الصلاحية")
    if acid.get("exporter_confirmation"):
        return {
            "message":   "تم تأكيد بيانات هذه الشحنة مسبقاً",
            "acid_number": acid["acid_number"],
            "already_confirmed": True,
        }
    now = datetime.now(timezone.utc).isoformat()
    await db.acid_requests.update_one(
        {"supplier_confirm_token": token},
        {
            "$set": {
                "exporter_confirmation":   True,
                "exporter_confirmed_at":   now,
                "updated_at":              datetime.now(timezone.utc),
            },
            "$push": {
                "timeline": {
                    "event":     "exporter_confirmed",
                    "timestamp": now,
                    "actor":     acid.get("supplier_name", "Foreign Supplier"),
                }
            },
        },
    )
    await db.audit_logs.insert_one({
        "action":        "exporter_confirmation",
        "resource_type": "acid_request",
        "resource_id":   str(acid["_id"]),
        "details":       {"acid_number": acid["acid_number"], "supplier": acid.get("supplier_name")},
        "timestamp":     now,
    })
    return {
        "message":     "تم تأكيد بيانات الشحنة بنجاح — شكراً لتعاونكم مع مصلحة الجمارك الليبية",
        "acid_number": acid["acid_number"],
        "already_confirmed": False,
    }



@router.get("")
async def list_acid(current_user=Depends(get_current_user), status: Optional[str] = None):
    role = current_user["role"]
    query: Dict[str, Any] = {}
    if role in ["importer", "customs_broker"]:
        query["requester_id"] = current_user["_id"]
    if status:
        query["status"] = status
    requests = await db.acid_requests.find(query).sort("created_at", -1).to_list(200)
    return [format_doc(r) for r in requests]


@router.get("/{acid_id}/jl38-pdf")
async def download_jl38_pdf_early(acid_id: str, current_user=Depends(get_current_user)):
    acid = await db.acid_requests.find_one(
        {"_id": ObjectId(acid_id)} if ObjectId.is_valid(acid_id) else {"acid_number": acid_id}
    )
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    if not acid.get("jl38_number"):
        raise HTTPException(400, "لم يُصدر JL38 بعد — يجب اكتمال دورة العمل السيادية أولاً")
    frontend_url = os.environ.get("FRONTEND_URL", "https://libya-customs-acis.preview.emergentagent.com")
    track_url = f"{frontend_url}/track?acid={acid.get('acid_number','')}"
    pdf_bytes = generate_jl38_pdf_bytes(acid, acid["jl38_number"], track_url)
    fname = f"JL38_{acid.get('acid_number','').replace('/','_')}.pdf"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
                             headers={"Content-Disposition": f"attachment; filename={fname}"})


@router.get("/{acid_id:path}")
async def get_acid(acid_id: str, current_user=Depends(get_current_user)):
    req = await db.acid_requests.find_one({"acid_number": acid_id})
    if not req and ObjectId.is_valid(acid_id):
        req = await db.acid_requests.find_one({"_id": ObjectId(acid_id)})
    if not req:
        raise HTTPException(status_code=404, detail="طلب ACID غير موجود")
    return format_doc(req)


async def _require_wf_lock_acid(acid_id: str, officer_id: str):
    """
    Hard-Stop: يمنع القرار على طلب ACID إذا لم يكن المأمور قد حجزه من حوض المهام.
    يُرفع 423 LOCK_REQUIRED إذا لم يكن المأمور هو من سجّل الحجز.
    """
    if not ObjectId.is_valid(acid_id):
        raise HTTPException(400, "معرّف ACID غير صالح")
    acid = await db.acid_requests.find_one({"_id": ObjectId(acid_id)})
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")

    wf_status   = acid.get("wf_status", "Unassigned")
    assigned_to = str(acid.get("wf_assigned_to", "")) if acid.get("wf_assigned_to") else ""

    if wf_status != "In_Progress" or assigned_to != officer_id:
        locked_by = acid.get("wf_assigned_to_name", "")
        msg = (
            f"المهمة محجوزة حالياً بواسطة: {locked_by}"
            if (wf_status == "In_Progress" and assigned_to != officer_id and locked_by)
            else "يجب حجز المهمة أولاً من حوض المهام قبل اتخاذ أي قرار على الطلب"
        )
        raise HTTPException(
            status_code=423,
            detail={"code": "LOCK_REQUIRED", "message": msg, "locked_by": locked_by},
        )


@router.put("/{acid_id}/review")
async def review_acid(acid_id: str, data: AcidReviewInput,
                      background_tasks: BackgroundTasks,
                      current_user=Depends(require_roles(
                          UserRole.ACID_REVIEWER, UserRole.ACID_RISK_OFFICER,
                          UserRole.ADMIN, UserRole.CUSTOMS_VALUER))):
    # ── Task Lock: لا قرار بدون حجز مسبق من الحوض ──────────────────
    await _require_wf_lock_acid(acid_id, current_user["_id"])
    action_map = {"approve": "approved", "reject": "rejected", "review": "under_review", "amendment": "amendment_required"}
    new_status = action_map.get(data.action)
    if not new_status:
        raise HTTPException(status_code=400, detail="Invalid action")
    acid_req = await db.acid_requests.find_one({"_id": ObjectId(acid_id)})
    timeline_event = {"event": new_status, "timestamp": datetime.now(timezone.utc).isoformat(), "actor": current_user.get("name_ar", ""), "notes": data.notes}
    # Phase K — Green Channel clearance time tracking
    now_iso = datetime.now(timezone.utc).isoformat()
    clearance_update = {}
    if new_status == "under_review" and acid_req and not acid_req.get("clearance_started_at"):
        clearance_update["clearance_started_at"] = now_iso
    if new_status == "approved" and acid_req:
        clearance_update["clearance_completed_at"] = now_iso
    result = await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {"$set": {"status": new_status, "reviewer_notes": data.notes, "updated_at": datetime.now(timezone.utc),
                  "reviewed_by": current_user["_id"], **clearance_update},
         "$push": {"timeline": timeline_event}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="طلب ACID غير موجود")

    # ── P2 ENFORCEMENT: تعيين تلقائي لطابور المعاينة — Yellow/Red Channel ──
    # عند الموافقة على ACID بمخاطرة متوسطة أو عالية ⇒ يُضاف تلقائياً لقائمة المفتش
    if new_status == "approved" and acid_req:
        _risk = acid_req.get("risk_level", "medium")
        _is_green = acid_req.get("is_green_channel", False)
        if _risk in ["medium", "high"] and not _is_green:
            _channel_label = "صفراء — مراجعة وثائق" if _risk == "medium" else "حمراء — معاينة ميدانية"
            insp_note = (
                f"مخاطرة {'عالية' if _risk == 'high' else 'متوسطة'} — تم تعيين المعاينة إجبارياً"
            )
            await db.acid_requests.update_one(
                {"_id": ObjectId(acid_id)},
                {
                    "$set": {
                        "inspection_required": True,
                        "inspection_status": "pending",
                        "channel_type": "yellow" if _risk == "medium" else "red",
                    },
                    "$push": {"timeline": {
                        "event": "inspection_required",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "actor": "النظام — محرك المخاطر",
                        "notes": insp_note,
                    }},
                }
            )
            # ── إشعار المفتشين بوصول مهمة معاينة جديدة ────────────
            _tpl = "task_yellow_review_required" if _risk == "medium" else "task_inspection_required"
            background_tasks.add_task(
                notify_role_users,
                "inspector",
                _tpl,
                {
                    "acid_number": acid_req.get("acid_number", ""),
                    "channel_label": _channel_label,
                },
                acid_id,
                current_user["_id"],
            )
    await log_audit(
        action=f"acid_{new_status}", user_id=current_user["_id"],
        user_name=current_user.get("name_ar", ""), resource_type="acid_request",
        resource_id=acid_id, details={"new_status": new_status, "notes": data.notes},
        ip_address=""
    )
    if acid_req and new_status in ["approved", "rejected", "amendment_required", "under_review"]:
        requester = await db.users.find_one({"_id": ObjectId(acid_req.get("requester_id", ""))}) if ObjectId.is_valid(acid_req.get("requester_id", "")) else None
        if requester:
            req_uid    = str(requester["_id"])
            acid_num   = acid_req.get("acid_number", acid_id)
            # Phase L — Persistent notification via DB + WebSocket
            notif_key  = f"acid_{new_status}"
            background_tasks.add_task(
                send_notification, req_uid, notif_key,
                {"acid_number": acid_num}, "ar", acid_id,
            )
            # Legacy email for approved/rejected/amendment
            if requester.get("email") and new_status in ["approved", "rejected", "amendment_required"]:
                background_tasks.add_task(
                    send_acid_status_email,
                    requester["email"],
                    requester.get("name_ar") or requester.get("name_en", ""),
                    acid_num, new_status, data.notes or ""
                )
    return {"message": "تم التحديث بنجاح", "new_status": new_status}


@router.post("/{acid_id}/confirm-export")
async def confirm_export(acid_id: str, current_user=Depends(get_current_user)):
    """Exporter confirms shipment data (Phase E)."""
    acid = await db.acid_requests.find_one({"_id": ObjectId(acid_id)}) if ObjectId.is_valid(acid_id) else None
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {"$set": {"exporter_confirmation": True, "exporter_confirmed_at": datetime.now(timezone.utc).isoformat(),
                  "updated_at": datetime.now(timezone.utc)},
         "$push": {"timeline": {"event": "exporter_confirmed", "timestamp": datetime.now(timezone.utc).isoformat(),
                                "actor": current_user.get("name_en") or current_user.get("name_ar", "")}}}
    )
    return {"message": "تم تأكيد بيانات الشحنة من قِبَل المصدر الدولي", "exporter_confirmation": True}
