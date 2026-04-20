"""AI HS Code search + admin seed data + WhatsApp logs"""
import random
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends
from models import HSSearchInput, UserRole
from database import db
from auth_utils import get_current_user, require_roles
from helpers import generate_acid_number
from constants import TARIFF_2022
from services.ollama_client import ollama_chat_text, parse_json_response

router = APIRouter(tags=["admin"])
logger = logging.getLogger(__name__)


@router.post("/hs/search")
async def hs_ai_search(data: HSSearchInput, current_user=Depends(get_current_user)):
    tariff_context = "\n".join([f"الفصل {ch}: {info['desc_ar']} ({info['desc_en']}) — معدل الرسوم: {int(info['rate']*100)}%" for ch, info in TARIFF_2022.items()])
    system_prompt = f"""أنت خبير تصنيف جمركي متخصص في التعريفة الجمركية الليبية 2022.
مهمتك: تحديد رمز HS المناسب بناءً على وصف البضاعة بالعربية أو الإنجليزية.

التعريفة الجمركية الليبية 2022 - فهرس الفصول:
{tariff_context}

قواعد الإجابة:
1. اقترح 3-5 رموز HS محتملة مع معدل الرسوم المقابل
2. رتّب النتائج من الأكثر احتمالاً إلى الأقل
3. أجب بـ JSON صحيح فقط، بدون أي نص إضافي"""
    user_msg = f"""ابحث عن رمز HS للبضاعة: "{data.query}"

أجب بـ JSON:
{{"results": [
  {{"hs_code": "<رمز HS 4-10 أرقام>", "chapter": "<رقم الفصل 2 رقم>", "description_ar": "<الوصف العربي>", "description_en": "<English description>", "duty_rate_pct": "<معدل الرسوم %>", "vat_rate_pct": "9%", "confidence": <85-100>, "notes_ar": "<ملاحظة إضافية>"}},
  ...
], "search_query": "{data.query}", "source": "التعريفة الجمركية الليبية 2022"}}"""
    try:
        resp_text = await ollama_chat_text(system_prompt, user_msg, json_mode=True)
        ai_result = parse_json_response(resp_text)
        if not ai_result:
            raise ValueError("empty or non-JSON model response")
        results = ai_result.get("results", [])
        for r in results:
            ch = r.get("chapter", r.get("hs_code", "")[:2])
            tariff = TARIFF_2022.get(ch, {})
            if tariff:
                r["duty_rate"] = tariff["rate"]
                r["duty_rate_pct"] = f"{int(tariff['rate'] * 100)}%"
                r["chapter_desc_ar"] = tariff["desc_ar"]
        return {"results": results, "search_query": data.query,
                "source": "التعريفة الجمركية الليبية 2022", "total": len(results),
                "searched_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.error(f"HS search error: {e}")
        raise HTTPException(500, f"خطأ في البحث: {str(e)}")


@router.post("/admin/seed-data")
async def seed_realistic_data(current_user=Depends(require_roles(UserRole.ADMIN))):
    existing = await db.acid_requests.count_documents({})
    if existing >= 55:
        return {"message": f"البيانات موجودة مسبقاً ({existing} طلب)", "seeded": 0}
    PORTS = [
        {"name": "مصراتة البحري", "mode": "sea"}, {"name": "ميناء طرابلس", "mode": "sea"},
        {"name": "مطار معيتيقة", "mode": "air"}, {"name": "منفذ مساعد", "mode": "land"},
        {"name": "ميناء بنغازي", "mode": "sea"}, {"name": "ميناء الزاوية", "mode": "sea"},
        {"name": "منفذ أمساعد", "mode": "land"},
    ]
    COUNTRIES = ["تركيا", "إيطاليا", "الصين", "ألمانيا", "الإمارات", "مصر", "كوريا الجنوبية", "فرنسا", "الهند", "اليابان"]
    SUPPLIERS = {
        "تركيا": ["Istanbul Trading Co.", "Ankara Exports Ltd."],
        "إيطاليا": ["Milano Industries SRL", "Roma Trade S.p.A"],
        "الصين": ["Guangzhou Electronics Co.", "Shanghai Global Trade"],
        "ألمانيا": ["Berlin Machinery GmbH", "Munich Auto Parts AG"],
        "الإمارات": ["Dubai Wholesale LLC", "Abu Dhabi Trading"],
        "مصر": ["Cairo Textiles Co.", "Alexandria Export"],
        "كوريا الجنوبية": ["Seoul Electronics Corp.", "Busan Shipping Ltd."],
        "فرنسا": ["Paris Luxury Goods", "Lyon Chemical SA"],
        "الهند": ["Mumbai Pharmaceuticals", "Delhi Textiles Pvt"],
        "اليابان": ["Tokyo Motors Corp.", "Osaka Electronics"],
    }
    GOODS = [
        {"desc": "أجهزة هواتف ذكية", "hs": "8517", "val_range": (15000, 120000)},
        {"desc": "قطع غيار سيارات", "hs": "8708", "val_range": (8000, 45000)},
        {"desc": "أثاث منزلي خشبي", "hs": "9403", "val_range": (5000, 30000)},
        {"desc": "ملابس قطنية", "hs": "6205", "val_range": (3000, 25000)},
        {"desc": "آلات ومعدات صناعية", "hs": "8479", "val_range": (25000, 200000)},
        {"desc": "أدوية ومستحضرات طبية", "hs": "3004", "val_range": (5000, 60000)},
        {"desc": "مواد بناء (سيراميك)", "hs": "6908", "val_range": (4000, 20000)},
        {"desc": "أجهزة كهربائية منزلية", "hs": "8516", "val_range": (8000, 50000)},
        {"desc": "مواد غذائية معلبة", "hs": "1602", "val_range": (2000, 15000)},
        {"desc": "لابتوب وحاسبات", "hs": "8471", "val_range": (10000, 80000)},
    ]
    STATUSES = ["approved", "approved", "approved", "submitted", "under_review", "rejected", "amendment_required"]
    RISKS = ["low", "low", "medium", "medium", "high"]
    REQUESTERS = [
        {"id": "req001", "name_ar": "شركة الأمل للاستيراد", "name_en": "Al Amal Import Co."},
        {"id": "req002", "name_ar": "مؤسسة الخليج للتجارة", "name_en": "Gulf Trade Est."},
        {"id": "req003", "name_ar": "شركة ليبيا التجارية", "name_en": "Libya Commercial Co."},
        {"id": "req004", "name_ar": "مجموعة النجمة للاستيراد", "name_en": "Najma Import Group"},
    ]
    now = datetime.now(timezone.utc)
    seeded = 0
    for i in range(55):
        port = random.choice(PORTS); country = random.choice(COUNTRIES)
        supplier_name = random.choice(SUPPLIERS.get(country, ["Generic Supplier Ltd."]))
        good = random.choice(GOODS); value = round(random.uniform(*good["val_range"]), 2)
        status = random.choice(STATUSES); risk = random.choice(RISKS)
        if int(good["hs"][:2]) in [93, 36] or value > 100000:
            risk = "high"
        requester = random.choice(REQUESTERS)
        days_ago = random.randint(1, 180); created = now - timedelta(days=days_ago)
        acid_num = await generate_acid_number()
        doc = {
            "acid_number": acid_num, "requester_id": requester["id"],
            "requester_name_ar": requester["name_ar"], "requester_name_en": requester["name_en"],
            "status": status, "risk_level": risk, "supplier_name": supplier_name, "supplier_country": country,
            "supplier_address": f"P.O.Box {random.randint(100,9999)}, {country}",
            "goods_description": good["desc"], "hs_code": good["hs"], "quantity": random.randint(10, 500),
            "unit": random.choice(["قطعة", "كيلوغرام", "طن", "كرتون"]),
            "value_usd": value, "port_of_entry": port["name"], "transport_mode": port["mode"],
            "carrier_name": f"Carrier {random.randint(1,5)} Ltd.", "bill_of_lading": f"BL{random.randint(10000,99999)}",
            "estimated_arrival": (created + timedelta(days=random.randint(5,30))).strftime("%Y-%m-%d"),
            "reviewer_notes": None, "on_behalf_of": None, "created_at": created, "updated_at": created,
            "timeline": [{"event": "submitted", "timestamp": created.isoformat(), "actor": requester["name_ar"]}]
        }
        try:
            await db.acid_requests.insert_one(doc); seeded += 1
        except Exception:
            pass
    return {"message": f"تم إنشاء {seeded} طلب ACID بنجاح", "seeded": seeded,
            "total_after": await db.acid_requests.count_documents({})}


@router.get("/admin/whatsapp/logs")
async def get_whatsapp_logs(current_user=Depends(require_roles(UserRole.ADMIN)), page: int = 1, limit: int = 50):
    skip = (page - 1) * limit
    logs = await db.whatsapp_logs.find({}).sort("sent_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.whatsapp_logs.count_documents({})
    for log in logs:
        log["_id"] = str(log["_id"])
        if isinstance(log.get("sent_at"), datetime):
            log["sent_at"] = log["sent_at"].isoformat()
    return {"logs": logs, "total": total, "page": page}


@router.post("/admin/demo-seed")
async def seed_demo_golden_path(current_user=Depends(require_roles(UserRole.ADMIN))):
    """
    Phase H — Seamless Demo Mode.
    Creates a clean, high-quality presentation dataset:
      1. ACID submitted (just created — review stage)
      2. ACID approved + DO issued (broker can submit SAD)
      3. ACID gate_released (full lifecycle complete)
      4. Platform fees paid → Executive Dashboard shows revenue
      5. Demo importer wallet with balance
    """
    # Find the demo importer
    demo_importer = await db.users.find_one({"email": "importer@customs.ly"})
    if not demo_importer:
        return {"message": "Demo importer account not found. Create importer@customs.ly first.", "created": 0}

    demo_id = str(demo_importer["_id"])
    now = datetime.now(timezone.utc)
    created_count = 0

    # ── ACID 1: Just submitted (ACID review stage) ──
    existing_demo = await db.acid_requests.count_documents({"requester_id": demo_id, "acid_number": {"$regex": "DEMO"}})
    if existing_demo == 0:
        acid1_num = f"DEMO/ACID/2026/00101"
        acid2_num = f"DEMO/ACID/2026/00102"
        acid3_num = f"DEMO/ACID/2026/00103"

        # ACID 1 — Submitted / Under Review
        await db.acid_requests.insert_one({
            "acid_number": acid1_num,
            "requester_id": demo_id,
            "requester_name_ar": "شركة الأمل للاستيراد — حساب تجريبي",
            "status": "submitted",
            "risk_level": "medium",
            "supplier_name": "Istanbul Textiles Ltd.",
            "supplier_country": "تركيا",
            "supplier_email": "supplier@customs.ly",
            "goods_description": "ملابس قطنية وبوليستر (حوالي 500 كرتون)",
            "hs_code": "6205",
            "quantity": 500,
            "unit": "كرتون",
            "value_usd": 28500.00,
            "port_of_entry": "ميناء طرابلس",
            "transport_mode": "sea",
            "carrier_name": "Mediterranean Shipping Co.",
            "bill_of_lading": "MSC-BL-20260401",
            "estimated_arrival": (now + timedelta(days=7)).strftime("%Y-%m-%d"),
            "created_at": now - timedelta(hours=3),
            "updated_at": now - timedelta(hours=3),
            "timeline": [{"event": "submitted", "timestamp": (now - timedelta(hours=3)).isoformat(), "actor": "شركة الأمل"}],
        })
        created_count += 1

        # ACID 2 — Approved + DO issued (ready for SAD)
        acid2_id = await db.acid_requests.insert_one({
            "acid_number": acid2_num,
            "requester_id": demo_id,
            "requester_name_ar": "شركة الأمل للاستيراد — حساب تجريبي",
            "status": "approved",
            "risk_level": "low",
            "do_issued": True,
            "do_number": f"DO/TRB/2026/0089",
            "supplier_name": "Berlin Machinery GmbH",
            "supplier_country": "ألمانيا",
            "supplier_email": "supplier@customs.ly",
            "goods_description": "آلات تصنيع صناعية — خط إنتاج بلاستيك",
            "hs_code": "8479",
            "quantity": 12,
            "unit": "وحدة",
            "value_usd": 145000.00,
            "port_of_entry": "مصراتة البحري",
            "transport_mode": "sea",
            "carrier_name": "Libya Maritime Services",
            "bill_of_lading": "LMS-BL-20260315",
            "estimated_arrival": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
            "reviewer_notes": "تم التحقق من الوثائق، المنشأ صحيح",
            "created_at": now - timedelta(days=14),
            "updated_at": now - timedelta(days=1),
            "timeline": [
                {"event": "submitted", "timestamp": (now - timedelta(days=14)).isoformat()},
                {"event": "approved", "timestamp": (now - timedelta(days=10)).isoformat()},
                {"event": "do_issued", "timestamp": (now - timedelta(days=1)).isoformat()},
            ],
        })
        created_count += 1

        # ACID 3 — Full lifecycle complete (gate_released)
        await db.acid_requests.insert_one({
            "acid_number": acid3_num,
            "requester_id": demo_id,
            "requester_name_ar": "شركة الأمل للاستيراد — حساب تجريبي",
            "status": "gate_released",
            "risk_level": "low",
            "do_issued": True,
            "do_number": "DO/TRB/2026/0067",
            "treasury_paid": True,
            "platform_fees_status": "paid",
            "supplier_name": "Shanghai Global Trade",
            "supplier_country": "الصين",
            "supplier_email": "supplier@customs.ly",
            "goods_description": "أجهزة هواتف ذكية — iPhone 15 Series (200 قطعة)",
            "hs_code": "8517",
            "quantity": 200,
            "unit": "قطعة",
            "value_usd": 96000.00,
            "port_of_entry": "ميناء طرابلس",
            "transport_mode": "sea",
            "carrier_name": "COSCO Shipping Lines",
            "bill_of_lading": "COSCO-BL-20260201",
            "estimated_arrival": (now - timedelta(days=20)).strftime("%Y-%m-%d"),
            "gate_release_number": f"REL/TRB/2026/0211",
            "gate_released_at": (now - timedelta(days=5)).isoformat(),
            "reviewer_notes": "إفراج نهائي — جميع الرسوم مسددة",
            "created_at": now - timedelta(days=45),
            "updated_at": now - timedelta(days=5),
            "timeline": [
                {"event": "submitted", "timestamp": (now - timedelta(days=45)).isoformat()},
                {"event": "approved", "timestamp": (now - timedelta(days=38)).isoformat()},
                {"event": "do_issued", "timestamp": (now - timedelta(days=25)).isoformat()},
                {"event": "sad_submitted", "timestamp": (now - timedelta(days=22)).isoformat()},
                {"event": "valued", "timestamp": (now - timedelta(days=18)).isoformat()},
                {"event": "treasury_paid", "timestamp": (now - timedelta(days=12)).isoformat()},
                {"event": "gate_released", "timestamp": (now - timedelta(days=5)).isoformat()},
            ],
        })
        created_count += 1

    # ── Platform Fees (show revenue on Executive Dashboard) ──
    demo_fees_exist = await db.platform_fees.count_documents({"entity_id": demo_id, "is_demo": True})
    if demo_fees_exist == 0:
        fee_types = [
            {"fee_type": "annual_subscription", "amount_lyd": 450.0, "early_bird_discount": True,
             "description": "اشتراك سنوي — خصم 10% للمبكرين", "status": "paid"},
            {"fee_type": "acid_fee", "amount_lyd": 150.0, "description": f"رسوم ACID — DEMO/ACID/2026/00102", "status": "paid"},
            {"fee_type": "acid_fee", "amount_lyd": 150.0, "description": f"رسوم ACID — DEMO/ACID/2026/00103", "status": "paid"},
            {"fee_type": "amendment_fee", "amount_lyd": 25.0, "description": "رسوم تعديل — المرة الثانية", "status": "paid"},
        ]
        for fee in fee_types:
            await db.platform_fees.insert_one({
                **fee,
                "entity_id": demo_id,
                "is_demo": True,
                "paid_at": (now - timedelta(days=random.randint(5, 30))).isoformat(),
                "created_at": now - timedelta(days=35),
                "qr_data": f"NAFIDHA-FEE-DEMO-{fee['fee_type'].upper()}-{demo_id[:8]}",
            })
        created_count += len(fee_types)

    # ── Demo Wallet Balance ──
    wallet_exists = await db.wallets.find_one({"entity_id": demo_id})
    if wallet_exists:
        if wallet_exists.get("balance_lyd", 0) < 500:
            await db.wallets.update_one(
                {"entity_id": demo_id},
                {"$set": {"balance_lyd": 1500.0, "total_topup": 2000.0, "total_spent": 500.0}}
            )
    else:
        await db.wallets.insert_one({
            "entity_id": demo_id,
            "balance_lyd": 1500.0,
            "total_topup": 2000.0,
            "total_spent": 500.0,
            "transactions": [
                {"type": "topup", "amount": 2000.0, "ref": "DEMO-TOPUP-001", "timestamp": (now - timedelta(days=30)).isoformat()},
                {"type": "payment", "amount": -500.0, "ref": "DEMO-FEE-PAY", "timestamp": (now - timedelta(days=20)).isoformat()},
            ],
        })
        created_count += 1

    return {
        "message": f"تم تجهيز بيانات العرض التقديمي بنجاح ({created_count} عنصر)",
        "demo_accounts": {
            "importer": "importer@customs.ly / Importer@2026!",
            "admin_dashboard": "admin@customs.ly / Admin@2026!",
            "carrier": "carrier@customs.ly / Carrier@2026!",
            "broker": "broker@customs.ly / Broker@2026!",
        },
        "demo_acids": [
            {"num": "DEMO/ACID/2026/00101", "stage": "تقديم ACID — مرحلة المراجعة"},
            {"num": "DEMO/ACID/2026/00102", "stage": "DO صادر — جاهز لتقديم SAD"},
            {"num": "DEMO/ACID/2026/00103", "stage": "إفراج نهائي — دورة كاملة"},
        ],
        "created": created_count,
    }
