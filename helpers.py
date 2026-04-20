"""Shared helper functions: format_doc, log_audit, generate_*_number, compute_risk"""
from datetime import datetime, timezone
from bson import ObjectId
from database import db
import arabic_reshaper
from bidi.algorithm import get_display

# Phase E — Platform fee amounts in LYD
PLATFORM_FEE_AMOUNTS = {
    "annual_subscription":  500,
    "acid_transaction":      50,
    "manifest_transaction":  30,
    "sad_transaction":       40,
}


def format_doc(doc: dict) -> dict:
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    for key in ["created_at", "updated_at"]:
        if key in doc and isinstance(doc[key], datetime):
            doc[key] = doc[key].isoformat()
    return doc


def compute_risk(value_usd: float, transport_mode: str, hs_code: str) -> str:
    score = 0
    if value_usd > 100000:
        score += 30
    elif value_usd > 50000:
        score += 15
    if transport_mode == "land":
        score += 20
    suspicious = ["93", "36", "28", "29", "30"]
    if any(hs_code.startswith(p) for p in suspicious):
        score += 50
    if score >= 50:
        return "high"
    elif score >= 20:
        return "medium"
    return "low"


def ar(text: str) -> str:
    try:
        reshaped = arabic_reshaper.reshape(str(text or ""))
        return get_display(reshaped)
    except Exception:
        return str(text or "")


async def log_audit(action: str, user_id: str, user_name: str, resource_type: str,
                    resource_id: str, details: dict, ip_address: str = ""):
    """Immutable audit log - APPEND ONLY. No DELETE or UPDATE permitted."""
    await db.audit_logs.insert_one({
        "action": action, "user_id": user_id, "user_name": user_name,
        "resource_type": resource_type, "resource_id": resource_id,
        "details": details, "ip_address": ip_address,
        "timestamp": datetime.now(timezone.utc), "immutable": True
    })


async def generate_acid_number() -> str:
    year = datetime.now(timezone.utc).year
    result = await db.acid_counters.find_one_and_update(
        {"year": year},
        {"$inc": {"count": 1}},
        upsert=True,
        return_document=True
    )
    count = result.get("count", 1)
    return f"ACID/{year}/{count:05d}"


async def generate_sad_number() -> str:
    year = datetime.now(timezone.utc).year
    result = await db.sad_counters.find_one_and_update(
        {"year": year}, {"$inc": {"count": 1}}, upsert=True, return_document=True
    )
    return f"SAD/{year}/{result.get('count', 1):05d}"


async def generate_jl159_number() -> str:
    year = datetime.now(timezone.utc).year
    result = await db.jl159_counters.find_one_and_update(
        {"year": year}, {"$inc": {"count": 1}}, upsert=True, return_document=True
    )
    return f"JL159/{year}/{result.get('count', 1):05d}"


async def generate_manifest_number() -> str:
    year = datetime.now(timezone.utc).year
    result = await db.manifest_counters.find_one_and_update(
        {"year": year}, {"$inc": {"count": 1}}, upsert=True, return_document=True
    )
    return f"MNF/{year}/{result.get('count', 1):05d}"


async def generate_release_number() -> str:
    year = datetime.now(timezone.utc).year
    result = await db.release_counters.find_one_and_update(
        {"year": year}, {"$inc": {"count": 1}}, upsert=True, return_document=True
    )
    return f"REL/{year}/{result.get('count', 1):05d}"


async def generate_jl38_number() -> str:
    year = datetime.now(timezone.utc).year
    result = await db.jl38_counters.find_one_and_update(
        {"year": year}, {"$inc": {"seq": 1}},
        upsert=True, return_document=True
    )
    seq = result.get("seq", 1)
    return f"JL38/{year}/{seq:05d}"


async def generate_guarantee_number() -> str:
    year = datetime.now(timezone.utc).year
    r = await db.guarantee_counters.find_one_and_update(
        {"year": year}, {"$inc": {"count": 1}}, upsert=True, return_document=True
    )
    return f"GUA/{year}/{r.get('count', 1):05d}"


async def generate_violation_number() -> str:
    year = datetime.now(timezone.utc).year
    r = await db.violation_counters.find_one_and_update(
        {"year": year}, {"$inc": {"count": 1}}, upsert=True, return_document=True
    )
    return f"VIO/{year}/{r.get('count', 1):05d}"


def get_tariff_rate(hs_code: str) -> dict:
    from constants import TARIFF_2022
    chapter = (hs_code.strip() if hs_code else "")[:2]
    return TARIFF_2022.get(chapter, {"rate": 0.20, "desc_ar": "بضائع متنوعة", "desc_en": "Miscellaneous goods"})
