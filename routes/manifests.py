"""Manifest management routes + Manifest stats"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from bson import ObjectId
from datetime import datetime, timezone
from models import ManifestCreate, ManifestReviewInput, IssueDeliveryOrderInput, UserRole
from database import db
from auth_utils import get_current_user, require_roles
from helpers import format_doc, log_audit, generate_manifest_number
from ws_manager import ws_manager
from services.notification_service import notify_role_users

router = APIRouter(prefix="/manifests", tags=["manifests"])


@router.post("")
async def create_manifest(data: ManifestCreate, background_tasks: BackgroundTasks, current_user=Depends(require_roles(UserRole.CARRIER_AGENT, UserRole.ADMIN))):
    manifest_number = await generate_manifest_number()
    doc = {
        "manifest_number": manifest_number, "carrier_id": current_user["_id"],
        "carrier_name_ar": current_user.get("name_ar") or current_user.get("company_name_ar", ""),
        "carrier_name_en": current_user.get("name_en") or current_user.get("company_name_en", ""),
        "transport_mode": data.transport_mode.value, "port_of_entry": data.port_of_entry,
        "arrival_date": data.arrival_date,
        # Sea fields
        "vessel_name": data.vessel_name, "imo_number": data.imo_number,
        "voyage_id": data.voyage_id, "container_ids": data.container_ids,
        "container_seal": data.container_seal,
        # Air fields
        "flight_number": data.flight_number, "airline": data.airline, "awb": data.awb,
        # Land fields
        "truck_plate": data.truck_plate, "trailer_plate": data.trailer_plate,
        "driver_id": data.driver_id, "driver_passport": data.driver_passport,
        "delivery_order_status": data.delivery_order_status,
        "consignments": data.consignments, "notes": data.notes,
        "status": "submitted", "reviewer_id": None, "reviewer_notes": None, "reviewed_at": None,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    result = await db.manifests.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    doc["created_at"] = doc["created_at"].isoformat()
    doc["updated_at"] = doc["updated_at"].isoformat()
    await log_audit(action="manifest_submitted", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="manifest",
                    resource_id=str(result.inserted_id), details={"manifest_number": manifest_number})
    # ── إشعار مأموري المانيفست بوصول طلب جديد ─────────────────────
    background_tasks.add_task(
        notify_role_users,
        "manifest_officer",
        "task_manifest_submitted",
        {
            "manifest_number": manifest_number,
            "carrier_name": doc.get("carrier_name_ar") or doc.get("carrier_name_en", ""),
        },
        None,
        current_user["_id"],
    )
    return doc


@router.get("")
async def list_manifests(current_user=Depends(get_current_user)):
    role = current_user["role"]
    query = {"carrier_id": current_user["_id"]} if role in ["carrier_agent"] else {}
    items = await db.manifests.find(query).sort("created_at", -1).to_list(200)
    return [format_doc(m) for m in items]


@router.get("/queue")
async def manifest_queue(current_user=Depends(require_roles(UserRole.MANIFEST_OFFICER, UserRole.ADMIN))):
    items = await db.manifests.find({"status": {"$in": ["submitted", "under_review"]}}).sort("created_at", 1).to_list(200)
    return [format_doc(m) for m in items]


@router.get("/stats")
async def manifest_stats(current_user=Depends(require_roles(UserRole.MANIFEST_OFFICER, UserRole.CARRIER_AGENT, UserRole.ADMIN))):
    role = current_user["role"]
    base_q = {"carrier_id": current_user["_id"]} if role == "carrier_agent" else {}
    return {
        "total": await db.manifests.count_documents(base_q),
        "submitted": await db.manifests.count_documents({**base_q, "status": "submitted"}),
        "accepted": await db.manifests.count_documents({**base_q, "status": "accepted"}),
        "rejected": await db.manifests.count_documents({**base_q, "status": "rejected"}),
    }


# Legacy alias — frontend uses /manifest/stats (singular)
from fastapi import APIRouter as _APIRouter
legacy_router = _APIRouter(tags=["manifests"])

@legacy_router.get("/manifest/stats")
async def manifest_stats_legacy(current_user=Depends(require_roles(UserRole.MANIFEST_OFFICER, UserRole.CARRIER_AGENT, UserRole.ADMIN))):
    return await manifest_stats(current_user)


@router.get("/{manifest_id}")
async def get_manifest(manifest_id: str, current_user=Depends(get_current_user)):
    m = await db.manifests.find_one({"_id": ObjectId(manifest_id)}) if ObjectId.is_valid(manifest_id) else None
    if not m:
        m = await db.manifests.find_one({"manifest_number": manifest_id})
    if not m:
        raise HTTPException(404, "المانيفست غير موجود")
    return format_doc(m)


@router.put("/{manifest_id}/review")
async def review_manifest(manifest_id: str, data: ManifestReviewInput,
                          current_user=Depends(require_roles(UserRole.MANIFEST_OFFICER, UserRole.ADMIN))):
    if data.action not in ["accept", "reject"]:
        raise HTTPException(400, "الإجراء يجب أن يكون accept أو reject")
    new_status = "accepted" if data.action == "accept" else "rejected"
    m = await db.manifests.find_one({"_id": ObjectId(manifest_id)}) if ObjectId.is_valid(manifest_id) else None
    if not m:
        raise HTTPException(404, "المانيفست غير موجود")

    # ── التطهير الإلزامي للرحلة: التحقق من حالة جميع ACIDs في المانيفست ──
    if data.action == "accept":
        consignments = m.get("consignments") or []
        acid_numbers = [c.get("acid_number") for c in consignments if c.get("acid_number")]
        if acid_numbers:
            suspicious_acids = []
            for acid_num in acid_numbers:
                acid_doc = await db.acid_requests.find_one(
                    {"acid_number": acid_num}, {"_id": 0, "acid_number": 1, "status": 1, "risk_level": 1}
                )
                if not acid_doc:
                    suspicious_acids.append({"acid_number": acid_num, "reason": "غير موجود في النظام"})
                elif acid_doc.get("status") not in ["approved", "valued", "treasury_paid", "gate_released"]:
                    suspicious_acids.append({
                        "acid_number": acid_num,
                        "reason": f"الحالة: {acid_doc.get('status', 'غير معروفة')} — يجب أن يكون معتمداً",
                        "risk_level": acid_doc.get("risk_level", ""),
                    })
            if suspicious_acids:
                raise HTTPException(
                    400,
                    {
                        "code": "MANIFEST_CONTAINS_UNCLEARED_ACIDS",
                        "message": (
                            "لا يمكن قبول المانيفست — يحتوي على بضائع غير مُجازة جمركياً. "
                            "يجب تطهير جميع طلبات ACID في الرحلة قبل الدخول للمنفذ."
                        ),
                        "suspicious_acids": suspicious_acids,
                    }
                )
    await db.manifests.update_one(
        {"_id": ObjectId(manifest_id)},
        {"$set": {"status": new_status, "reviewer_id": current_user["_id"],
                  "reviewer_name": current_user.get("name_ar", ""), "reviewer_notes": data.notes,
                  "reviewed_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc)}}
    )
    await log_audit(action=f"manifest_{new_status}", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="manifest",
                    resource_id=manifest_id, details={"action": data.action, "notes": data.notes})
    if new_status == "accepted":
        await ws_manager.broadcast_user(m.get("carrier_id", ""), {
            "type": "manifest_approved",
            "message_ar": f"تم قبول المانيفست {m.get('manifest_number', '')} — يمكن الآن متابعة إجراءات التخليص",
            "manifest_id": manifest_id, "manifest_number": m.get("manifest_number", ""),
        })
    return {"message": f"تم تحديث حالة المانيفست إلى {new_status}", "new_status": new_status}


@router.put("/{manifest_id}/issue-do")
async def issue_delivery_order(manifest_id: str, data: IssueDeliveryOrderInput,
                               current_user=Depends(get_current_user)):
    """
    Phase F — Issue Delivery Order (أمر التسليم).
    Carrier must confirm freight_fees_paid before issuing DO.
    Once issued, delivery_order_status = True unlocks SAD creation for the broker.
    """
    if current_user["role"] not in ("carrier_agent", "admin"):
        raise HTTPException(403, "فقط وكيل النقل يمكنه إصدار أمر التسليم")
    if not data.freight_fees_paid:
        raise HTTPException(400, "يجب تأكيد سداد رسوم الشحن قبل إصدار أمر التسليم")

    m = await db.manifests.find_one({"_id": ObjectId(manifest_id)}) if ObjectId.is_valid(manifest_id) else None
    if not m:
        raise HTTPException(404, "المانيفست غير موجود")
    if m.get("status") != "accepted":
        raise HTTPException(400, "لا يمكن إصدار أمر التسليم إلا بعد قبول المانيفست من الموظف المختص")
    if m.get("delivery_order_status"):
        raise HTTPException(400, "تم إصدار أمر التسليم مسبقاً لهذا المانيفست")

    do_number = f"DO/{datetime.now(timezone.utc).strftime('%Y/%m%d')}/{manifest_id[-6:].upper()}"
    await db.manifests.update_one(
        {"_id": ObjectId(manifest_id)},
        {"$set": {
            "delivery_order_status": True,
            "do_number": do_number,
            "freight_fees_paid": data.freight_fees_paid,
            "do_issued_at": datetime.now(timezone.utc).isoformat(),
            "do_issued_by": current_user["_id"],
            "updated_at": datetime.now(timezone.utc),
        }}
    )

    # Phase F Workflow: unlock SAD creation for all linked ACID requests
    linked_acids = [c.get("acid_number") for c in (m.get("consignments") or []) if c.get("acid_number")]
    if linked_acids:
        await db.acid_requests.update_many(
            {"acid_number": {"$in": linked_acids}},
            {"$set": {"do_issued": True, "do_number": do_number,
                      "do_manifest_id": manifest_id,
                      "updated_at": datetime.now(timezone.utc)},
             "$push": {"timeline": {"event": "do_issued", "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "actor": current_user.get("name_ar", ""),
                                    "do_number": do_number}}}
        )
    # Notify (broadcast)
    await ws_manager.broadcast_all({
        "type": "do_issued",
        "message_ar": f"تم إصدار أمر التسليم {do_number} للمانيفست {m.get('manifest_number', '')}",
        "manifest_id": manifest_id,
        "do_number": do_number,
    })
    return {
        "message": "تم إصدار أمر التسليم بنجاح. يمكن للمخلص الجمركي الآن إنشاء البيان الجمركي.",
        "do_number": do_number,
        "linked_acid_count": len(linked_acids),
    }
