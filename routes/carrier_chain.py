"""Carrier chain: ACID Risk queue, Declaration queue, Release chain"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Form
from bson import ObjectId
from datetime import datetime, timezone
from models import DeclarationReviewInput, ReleaseApproveInput, UserRole
from database import db
from auth_utils import require_roles
from helpers import format_doc, log_audit
from ws_manager import ws_manager

router = APIRouter(tags=["carrier_chain"])


# ---- ACID Risk Officer ----
@router.get("/acid-risk/queue")
async def acid_risk_queue(current_user=Depends(require_roles(
    UserRole.ACID_RISK_OFFICER, UserRole.ACID_REVIEWER, UserRole.ADMIN
))):
    """قائمة طلبات ACID مع تقديم القناة الخضراء (Green Channel) أولاً — Phase K."""
    items = await db.acid_requests.find(
        {"status": {"$in": ["submitted", "under_review"]}}
    ).sort([("priority_score", -1), ("created_at", 1)]).to_list(200)
    return [format_doc(i) for i in items]


# ---- Declaration Officer ----
@router.get("/declaration/queue")
async def declaration_queue(current_user=Depends(require_roles(UserRole.DECLARATION_OFFICER, UserRole.ADMIN))):
    acid_ids_cursor = await db.acid_requests.find({"status": "approved"}, {"_id": 1, "acid_number": 1}).to_list(500)
    acid_id_map = {str(a["_id"]): a.get("acid_number", "") for a in acid_ids_cursor}
    sads = await db.sad_forms.find(
        {"acid_id": {"$in": list(acid_id_map.keys())}, "is_active": True,
         "status": {"$in": ["draft", "submitted", "pending_declaration"]}}
    ).sort("created_at", 1).to_list(200)
    result = []
    for sad in sads:
        acid = await db.acid_requests.find_one({"_id": ObjectId(sad["acid_id"])}) if ObjectId.is_valid(sad.get("acid_id", "")) else None
        sad["_id"] = str(sad["_id"])
        for k in ["created_at", "updated_at"]:
            if isinstance(sad.get(k), datetime):
                sad[k] = sad[k].isoformat()
        sad["acid_data"] = format_doc(acid) if acid else {}
        result.append(sad)
    return result


@router.put("/declaration/{sad_id}/review")
async def review_declaration(sad_id: str, data: DeclarationReviewInput,
                              current_user=Depends(require_roles(UserRole.DECLARATION_OFFICER, UserRole.ADMIN))):
    if data.action not in ["accept", "reject"]:
        raise HTTPException(400, "الإجراء يجب أن يكون accept أو reject")
    new_status = "declaration_accepted" if data.action == "accept" else "declaration_rejected"
    sad = await db.sad_forms.find_one({"_id": ObjectId(sad_id)}) if ObjectId.is_valid(sad_id) else None
    if not sad:
        raise HTTPException(404, "نموذج SAD غير موجود")
    await db.sad_forms.update_one(
        {"_id": ObjectId(sad_id)},
        {"$set": {"status": new_status, "declaration_officer_id": current_user["_id"],
                  "declaration_officer_name": current_user.get("name_ar", ""),
                  "declaration_notes": data.notes,
                  "declaration_reviewed_at": datetime.now(timezone.utc).isoformat(),
                  "updated_at": datetime.now(timezone.utc)}}
    )
    if data.action == "accept":
        await db.acid_requests.update_one(
            {"_id": ObjectId(sad["acid_id"])} if ObjectId.is_valid(sad.get("acid_id", "")) else {"acid_number": sad.get("acid_number")},
            {"$set": {"declaration_accepted": True, "declaration_officer_id": current_user["_id"],
                      "updated_at": datetime.now(timezone.utc)},
             "$push": {"timeline": {"event": "declaration_accepted",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "actor": current_user.get("name_ar", "")}}}
        )
    await log_audit(action=f"declaration_{data.action}d", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="sad_form",
                    resource_id=sad_id, details={"action": data.action, "notes": data.notes})
    return {"message": f"تم تحديث حالة البيان إلى {new_status}", "new_status": new_status}


# ---- Release Officer ----
@router.get("/release/queue")
async def release_queue(current_user=Depends(require_roles(UserRole.RELEASE_OFFICER, UserRole.ADMIN))):
    items = await db.acid_requests.find(
        {"treasury_paid": True, "gate_released": False}
    ).sort("treasury_paid_at", 1).to_list(200)
    return [format_doc(i) for i in items]


@router.post("/release/{acid_id}/approve")
async def approve_release(acid_id: str, data: ReleaseApproveInput,
                          current_user=Depends(require_roles(UserRole.RELEASE_OFFICER, UserRole.ADMIN))):
    acid = await db.acid_requests.find_one({"_id": ObjectId(acid_id)}) if ObjectId.is_valid(acid_id) else None
    if not acid:
        raise HTTPException(404, "طلب ACID غير موجود")
    if not acid.get("treasury_paid"):
        raise HTTPException(400, "لا يمكن إصدار الإفراج - لم يتم تأكيد دفع الخزينة بعد")
    # ── الخط الأحمر الإلكتروني: رسوم المنصة يجب أن تكون مدفوعة ──────
    if not acid.get("platform_fees_paid"):
        raise HTTPException(
            403,
            "مرفوض — الخط الأحمر: لم يتم سداد رسوم منصة نافذة التشغيلية. "
            "لا يمكن إصدار إذن الإفراج JL38 حتى يتم السداد الكامل لجميع الرسوم."
        )
    if acid.get("gate_released"):
        raise HTTPException(400, "صدر الإفراج مسبقاً لهذه الشحنة")

    # ── صمام الأمان الذكي: المعاينة الميدانية — القناة الخضراء الموسَّعة ──
    # القناة الخضراء تشمل: (1) مصدر موثَّق في السجل العالمي، أو (2) مخاطرة منخفضة
    is_green = acid.get("is_green_channel", False) or acid.get("risk_level") == "low"
    insp_status = acid.get("inspection_status")
    if not is_green and insp_status != "compliant":
        if insp_status == "non_compliant":
            raise HTTPException(
                400,
                "لا يمكن إصدار الإفراج — نتيجة المعاينة الميدانية: غير مطابق. "
                "يجب مراجعة المخالفة وإغلاقها أولاً."
            )
        raise HTTPException(
            400,
            "لا يمكن إصدار الإفراج — في انتظار تقرير المعاينة الميدانية من المفتش الجمركي. "
            "البضاعة ذات مخاطرة متوسطة أو عالية — يجب اكتمال المعاينة الميدانية أولاً."
        )
    year = datetime.now(timezone.utc).year
    r = await db.acid_counters.find_one_and_update(
        {"type": "jl38", "year": year}, {"$inc": {"count": 1}}, upsert=True, return_document=True
    )
    jl38_number = f"JL38/{year}/{r.get('count', 1):05d}"
    await db.acid_requests.update_one(
        {"_id": ObjectId(acid_id)},
        {"$set": {"gate_released": True, "gate_released_at": datetime.now(timezone.utc).isoformat(),
                  "gate_officer_id": current_user["_id"], "jl38_number": jl38_number,
                  "release_notes": data.notes, "updated_at": datetime.now(timezone.utc)},
         "$push": {"timeline": {"event": "release_issued", "timestamp": datetime.now(timezone.utc).isoformat(),
                                "actor": current_user.get("name_ar", ""), "jl38_number": jl38_number}}}
    )
    await log_audit(action="release_issued", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="acid_request",
                    resource_id=acid_id, details={"jl38_number": jl38_number, "notes": data.notes})
    await ws_manager.broadcast_all({
        "type": "notification",
        "message_ar": f"تم إصدار إذن الإفراج JL38 للشحنة {acid.get('acid_number', '')}",
        "acid_id": acid_id, "jl38_number": jl38_number
    })
    return {"message": "تم إصدار إذن الإفراج بنجاح", "jl38_number": jl38_number}


@router.get("/release/stats")
async def release_stats(current_user=Depends(require_roles(UserRole.RELEASE_OFFICER, UserRole.ADMIN))):
    return {
        "pending_release": await db.acid_requests.count_documents({"treasury_paid": True, "gate_released": False}),
        "released_today": await db.acid_requests.count_documents({
            "gate_released": True,
            "gate_released_at": {"$gte": datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()}
        }),
        "total_released": await db.acid_requests.count_documents({"gate_released": True}),
    }


# ---- Supplier Notify ----
@router.post("/supplier/notify-importer")
async def supplier_notify_importer(
    acid_id: str = Form(...), doc_type: str = Form(...),
    background_tasks: BackgroundTasks = None,
    current_user=Depends(require_roles(UserRole.FOREIGN_SUPPLIER, UserRole.ADMIN))
):
    acid_req = await db.acid_requests.find_one(
        {"_id": ObjectId(acid_id)} if ObjectId.is_valid(acid_id) else {"acid_number": acid_id}
    )
    if not acid_req:
        raise HTTPException(404, "طلب ACID غير موجود")
    from notifications import notify_user_whatsapp
    if background_tasks:
        background_tasks.add_task(notify_user_whatsapp, acid_req.get("requester_id", ""),
            f"رفع المورد مستنداً جديداً ({doc_type}) لشحنتك {acid_req.get('acid_number','')}. يُرجى المراجعة والتحقق.",
            "supplier_document_uploaded", acid_id)
    await log_audit(action="supplier_document_uploaded", user_id=current_user["_id"],
                    user_name=current_user.get("name_ar", ""), resource_type="acid_request",
                    resource_id=acid_id, details={"doc_type": doc_type, "supplier": current_user.get("name_ar", "")})
    return {"message": "تم إبلاغ المستورد بالمستند الجديد"}


# ---- Broker ----
@router.get("/broker/importers")
async def list_importers_for_broker(current_user=Depends(require_roles(UserRole.CUSTOMS_BROKER, UserRole.ADMIN))):
    importers = await db.users.find({"role": "importer", "is_active": True},
                                    {"_id": 1, "name_ar": 1, "name_en": 1, "email": 1, "company_name_ar": 1}).to_list(200)
    return [{"_id": str(u["_id"]), "name_ar": u.get("name_ar",""), "name_en": u.get("name_en",""),
             "email": u.get("email",""), "company_name_ar": u.get("company_name_ar","")} for u in importers]


@router.get("/broker/my-requests")
async def broker_requests(current_user=Depends(require_roles(UserRole.CUSTOMS_BROKER, UserRole.ADMIN))):
    reqs = await db.acid_requests.find({"broker_id": current_user["_id"]}).sort("created_at", -1).to_list(200)
    return [format_doc(r) for r in reqs]
