"""Shipment tracking, dashboard stats, fees calculator"""
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from models import FeesCalculateInput
from database import db
from auth_utils import get_current_user
from helpers import format_doc
from constants import CURRENT_CBL_RATES, TIMELINE_STAGES, STATUS_ORDER
from datetime import datetime, timezone

router = APIRouter(tags=["dashboard"])


@router.get("/shipments")
async def list_shipments(current_user=Depends(get_current_user)):
    role = current_user["role"]
    query: Dict[str, Any] = {}
    if role in ["importer", "customs_broker"]:
        query["requester_id"] = current_user["_id"]
    elif role == "foreign_supplier":
        # Global Exporter Registry: البحث عن المصدر بالبريد الإلكتروني في مصفوفة emails
        exporter = await db.global_exporters.find_one({"emails": current_user["email"]})
        if exporter:
            # عرض جميع ACIDs المرتبطة بنفس الـ tax_id من جميع المستوردين
            query["exporter_tax_id"] = exporter["tax_id"]
        else:
            # Fallback: الدعم القديم للـ email المباشر (للبيانات التجريبية والإرث)
            query["$or"] = [
                {"exporter_email": current_user["email"]},
                {"supplier_email": current_user["email"]},
            ]
    requests = await db.acid_requests.find(query).sort("updated_at", -1).to_list(100)
    return [format_doc(r) for r in requests]


@router.get("/shipments/track/{identifier:path}")
async def track_shipment(identifier: str):
    req = await db.acid_requests.find_one({"acid_number": identifier})
    if not req and ObjectId.is_valid(identifier):
        req = await db.acid_requests.find_one({"_id": ObjectId(identifier)})
    if not req:
        raise HTTPException(status_code=404, detail="لم يتم العثور على شحنة")
    return format_doc(req)


@router.get("/dashboard/stats")
async def get_stats(current_user=Depends(get_current_user)):
    role = current_user["role"]
    uid = current_user["_id"]
    if role in ["importer", "customs_broker", "foreign_supplier"]:
        if role == "foreign_supplier":
            # Global Exporter Registry: نفس منطق list_shipments
            exporter = await db.global_exporters.find_one({"emails": current_user["email"]})
            if exporter:
                q = {"exporter_tax_id": exporter["tax_id"]}
            else:
                q = {"$or": [
                    {"exporter_email": current_user["email"]},
                    {"supplier_email": current_user["email"]},
                ]}
        else:
            q = {"requester_id": uid}
        return {
            "total": await db.acid_requests.count_documents(q),
            "pending": await db.acid_requests.count_documents({**q, "status": {"$in": ["submitted", "under_review"]}}),
            "approved": await db.acid_requests.count_documents({**q, "status": "approved"}),
            "rejected": await db.acid_requests.count_documents({**q, "status": "rejected"}),
        }
    elif role in ["acid_reviewer", "acid_risk_officer", "manifest_officer",
                   "customs_valuer", "inspector", "treasury_officer",
                   "gate_officer", "declaration_officer", "release_officer",
                   "pga_officer", "violations_officer"]:
        return {
            "total": await db.acid_requests.count_documents({}),
            "pending": await db.acid_requests.count_documents({"status": "submitted"}),
            "under_review": await db.acid_requests.count_documents({"status": "under_review"}),
            "approved": await db.acid_requests.count_documents({"status": "approved"}),
            "rejected": await db.acid_requests.count_documents({"status": "rejected"}),
            "high_risk": await db.acid_requests.count_documents({"risk_level": "high"}),
        }
    elif role == "admin":
        return {
            "total_users": await db.users.count_documents({}),
            "total_requests": await db.acid_requests.count_documents({}),
            "pending_requests": await db.acid_requests.count_documents({"status": {"$in": ["submitted", "under_review"]}}),
            "approved": await db.acid_requests.count_documents({"status": "approved"}),
            "high_risk": await db.acid_requests.count_documents({"risk_level": "high"}),
        }
    return {}


@router.post("/fees/calculate")
async def calculate_fees(data: FeesCalculateInput):
    value_usd = data.value_usd
    hs = data.hs_code.strip()
    rate_map = {
        "84": 0.05, "85": 0.05, "87": 0.25, "22": 0.30, "04": 0.10,
        "10": 0.05, "30": 0.05, "93": 0.30, "61": 0.25, "62": 0.25,
    }
    chapter = hs[:2]
    customs_rate = rate_map.get(chapter, 0.20)
    exchange_rate = CURRENT_CBL_RATES.get("USD", 4.87)
    customs_duty_usd = round(value_usd * customs_rate, 2)
    customs_duty_lyd = round(customs_duty_usd * exchange_rate, 2)
    vat_rate = 0.09
    vat_usd = round((value_usd + customs_duty_usd) * vat_rate, 2)
    vat_lyd = round(vat_usd * exchange_rate, 2)
    total_usd = round(customs_duty_usd + vat_usd, 2)
    total_lyd = round(customs_duty_lyd + vat_lyd, 2)
    return {
        "value_usd": value_usd, "value_lyd": round(value_usd * exchange_rate, 2),
        "hs_code": hs, "customs_rate_pct": f"{customs_rate * 100:.0f}%",
        "customs_duty_usd": customs_duty_usd, "customs_duty_lyd": customs_duty_lyd,
        "vat_rate_pct": f"{vat_rate * 100:.0f}%",
        "vat_usd": vat_usd, "vat_lyd": vat_lyd,
        "total_usd": total_usd, "total_lyd": total_lyd,
        "exchange_rate": exchange_rate
    }


@router.get("/public/verify/{acid_number:path}")
async def public_verify(acid_number: str):
    req = await db.acid_requests.find_one({"acid_number": acid_number})
    if not req and ObjectId.is_valid(acid_number):
        req = await db.acid_requests.find_one({"_id": ObjectId(acid_number)})
    if not req:
        raise HTTPException(404, "رقم ACID غير موجود أو غير صحيح")
    return {
        "acid_number": req.get("acid_number"),
        "status": req.get("status"),
        "goods_description": req.get("goods_description"),
        "port_of_entry": req.get("port_of_entry"),
        "transport_mode": req.get("transport_mode"),
        "supplier_country": req.get("supplier_country"),
        "created_at": req["created_at"].isoformat() if isinstance(req.get("created_at"), datetime) else req.get("created_at"),
        "updated_at": req["updated_at"].isoformat() if isinstance(req.get("updated_at"), datetime) else req.get("updated_at"),
        "risk_level": req.get("risk_level"),
        "verified": True
    }


@router.get("/public/track/{acid_number:path}")
async def public_track_shipment(acid_number: str):
    req = await db.acid_requests.find_one({"acid_number": acid_number.strip()})
    if not req:
        raise HTTPException(404, "رقم ACID غير موجود. تحقق من الرقم وأعد المحاولة.")
    current_status = req.get("status", "submitted")
    current_idx = STATUS_ORDER.get(current_status, 0)
    timeline_raw = req.get("timeline", [])
    timeline_events: dict = {}
    for ev in timeline_raw:
        k = ev.get("event", "")
        if k in STATUS_ORDER:
            timeline_events[k] = ev.get("timestamp", "")
    stages = []
    for i, stage in enumerate(TIMELINE_STAGES):
        key = stage["key"]
        ts = timeline_events.get(key)
        if not ts and key == current_status:
            ts_raw = req.get("updated_at") or req.get("created_at")
            ts = ts_raw.isoformat() if isinstance(ts_raw, datetime) else str(ts_raw or "")
        stages.append({
            "key": key, "label_ar": stage["label_ar"], "label_en": stage["label_en"],
            "status": "completed" if i < current_idx else ("current" if i == current_idx else "pending"),
            "timestamp": ts or None,
        })
    if current_status in ["amendment_required", "rejected"]:
        for s in stages:
            if s["key"] == "under_review":
                s["status"] = "current"
                s["label_ar"] += f" — {'يحتاج تعديل' if current_status == 'amendment_required' else 'مرفوض'}"
    return {
        "acid_id": str(req["_id"]),
        "acid_number": req.get("acid_number"),
        "status": current_status,
        "port_of_entry": req.get("port_of_entry"),
        "transport_mode": req.get("transport_mode"),
        "goods_category": req.get("goods_description", "")[:40] + "..." if len(req.get("goods_description","")) > 40 else req.get("goods_description",""),
        "supplier_country": req.get("supplier_country"),
        "estimated_arrival": req.get("estimated_arrival"),
        "jl38_number": req.get("jl38_number") if current_status == "gate_released" else None,
        "gate_released_at": req.get("gate_released_at").isoformat() if isinstance(req.get("gate_released_at"), datetime) else req.get("gate_released_at"),
        "timeline_stages": stages,
        "privacy_note": "تُعرض معلومات الحالة فقط — البيانات المالية والتجارية التفصيلية محمية",
        "tracked_at": datetime.now(timezone.utc).isoformat(),
    }
