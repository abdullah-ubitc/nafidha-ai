"""
NAFIDHA — Libya Customs National Single Window
FastAPI entry point: includes all modular routers
"""
from dotenv import load_dotenv
load_dotenv()

import os
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware

# Shared modules
from database import db, client
from auth_utils import hash_password, verify_password
from ws_manager import ws_manager

# Route modules
from routes.auth import router as auth_router
from routes.users import router as users_router
from routes.acid import router as acid_router
from routes.dashboard import router as dashboard_router
from routes.documents import router as documents_router
from routes.sad import router as sad_router
from routes.risk import router as risk_router
from routes.bank import router as bank_router
from routes.audit import router as audit_router
from routes.tariff import router as tariff_router
from routes.executive import router as executive_router, export_router as export_legacy_router
from routes.admin import router as admin_router
from routes.valuer import router as valuer_router
from routes.treasury import router as treasury_router
from routes.gate import router as gate_router
from routes.pga import router as pga_router
from routes.violations import router as violations_router
from routes.manifests import router as manifests_router, legacy_router as manifest_legacy_router
from routes.carrier_chain import router as carrier_chain_router
from routes.registration import router as registration_router
from routes.platform_fees import router as platform_fees_router
from routes.renewal      import router as renewal_router
from routes.wallet import router as wallet_router
from routes.exporters import router as exporters_router
from routes.notifications import router as notifications_router
from routes.kyc import router as kyc_router
from routes.workflow import router as workflow_router
from routes.reports import router as reports_router
from routes.inspections import router as inspections_router
from routes.employees import router as employees_router
from routes.regions import router as regions_router, seed_default_regions
from routes.land_trip import router as land_trip_router
from routes.payments import router as payments_router
from routes.ocr import router as ocr_router
from routes.ports import router as ports_router
from routes.ocr_wallet import router as ocr_wallet_router
from routes.service_pricing import router as service_pricing_router
from services.scheduler_service import startup_scheduler, shutdown_scheduler

from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="NAFIDHA — Libya Customs National Single Window", version="3.0.0")

# CORS — يقرأ القائمة من CORS_ORIGINS في .env (مفصولة بفاصلة)
# مثال:  CORS_ORIGINS=https://your-domain.com,http://localhost:3000
# إذا كانت القائمة فارغة تُستخدَم FRONTEND_BASE_URL + localhost كقيمة افتراضية آمنة
_raw_cors      = os.environ.get("CORS_ORIGINS", "").strip()
_frontend_url  = os.environ.get("FRONTEND_BASE_URL", "http://localhost:3000").strip()

if _raw_cors and _raw_cors != "*":
    # قائمة محددة من .env — النمط الصحيح للإنتاج
    _cors_origins: list[str] = [o.strip() for o in _raw_cors.split(",") if o.strip()]
else:
    # Fallback آمن: Preview URL + localhost (لا wildcard في أي حالة)
    _cors_origins = [_frontend_url, "http://localhost:3000", "http://127.0.0.1:3000"]

# ضمان عدم وجود مسافات زائدة أو قيم فارغة
_cors_origins = list(dict.fromkeys(o for o in _cors_origins if o))

logger.info(f"[CORS] Allowed origins ({len(_cors_origins)}): {_cors_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers under /api prefix
API_PREFIX = "/api"
app.include_router(auth_router,         prefix=API_PREFIX)
app.include_router(users_router,        prefix=API_PREFIX)
app.include_router(acid_router,         prefix=API_PREFIX)
app.include_router(dashboard_router,    prefix=API_PREFIX)
app.include_router(documents_router,    prefix=API_PREFIX)
app.include_router(sad_router,          prefix=API_PREFIX)
app.include_router(risk_router,         prefix=API_PREFIX)
app.include_router(bank_router,         prefix=API_PREFIX)
app.include_router(audit_router,        prefix=API_PREFIX)
app.include_router(tariff_router,       prefix=API_PREFIX)
app.include_router(executive_router,    prefix=API_PREFIX)
app.include_router(export_legacy_router, prefix=API_PREFIX)
app.include_router(admin_router,        prefix=API_PREFIX)
app.include_router(valuer_router,       prefix=API_PREFIX)
app.include_router(treasury_router,     prefix=API_PREFIX)
app.include_router(gate_router,         prefix=API_PREFIX)
app.include_router(pga_router,          prefix=API_PREFIX)
app.include_router(violations_router,   prefix=API_PREFIX)
app.include_router(manifests_router,    prefix=API_PREFIX)
app.include_router(manifest_legacy_router, prefix=API_PREFIX)
app.include_router(carrier_chain_router, prefix=API_PREFIX)
app.include_router(registration_router,  prefix=API_PREFIX)
app.include_router(platform_fees_router, prefix=API_PREFIX)
app.include_router(wallet_router,        prefix=API_PREFIX)
app.include_router(exporters_router,     prefix=API_PREFIX)
app.include_router(notifications_router, prefix=API_PREFIX)
app.include_router(kyc_router,           prefix=API_PREFIX)
app.include_router(workflow_router,      prefix=API_PREFIX)
app.include_router(reports_router,       prefix=API_PREFIX)
app.include_router(inspections_router,   prefix=API_PREFIX)
app.include_router(employees_router,     prefix=API_PREFIX)
app.include_router(regions_router,       prefix=API_PREFIX)
app.include_router(land_trip_router,     prefix=API_PREFIX)
app.include_router(renewal_router,       prefix=API_PREFIX)
app.include_router(payments_router,      prefix=API_PREFIX)
app.include_router(ocr_router,           prefix=API_PREFIX)
app.include_router(ports_router,         prefix=API_PREFIX)
app.include_router(ocr_wallet_router,    prefix=API_PREFIX)
app.include_router(service_pricing_router, prefix=API_PREFIX)

@app.get("/api/ping")
async def ping_test_debug():
    return {"status": "ok", "message": "Server is running latest code (Neutered OCR Auth/Balance)"}


# ── Stripe Webhook Endpoint ────────────────────────────────────────────────────
@app.post("/api/webhook/stripe")
async def stripe_webhook_handler(request: Request):
    """Stripe Webhook — معالجة أحداث الدفع الواردة من Stripe"""
    import os
    from emergentintegrations.payments.stripe.checkout import StripeCheckout
    api_key = os.environ.get("STRIPE_API_KEY", "")
    host_url = str(request.base_url).rstrip("/")
    webhook_url = f"{host_url}/api/webhook/stripe"
    sc = StripeCheckout(api_key=api_key, webhook_url=webhook_url)

    body = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        event = await sc.handle_webhook(body, sig)
        if event.payment_status == "paid":
            from routes.payments import _activate_exporter, _activate_acid_fee
            session_id = event.session_id
            from database import db as _db
            tx = await _db.payment_transactions.find_one({"session_id": session_id})
            if tx and tx.get("payment_status") != "paid":
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).isoformat()
                await _db.payment_transactions.update_one(
                    {"session_id": session_id},
                    {"$set": {"status": "complete", "payment_status": "paid", "updated_at": now}},
                )
                if tx.get("payment_type") == "verification":
                    await _activate_exporter(tx, now)
                elif tx.get("payment_type") == "acid_fee":
                    await _activate_acid_fee(tx, now)
    except Exception:
        pass
    return {"status": "ok"}


@app.websocket("/api/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await ws_manager.connect(websocket, user_id)
    try:
        await websocket.send_json({"type": "connected", "message_ar": "متصل بنظام الإشعارات الفورية"})
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, user_id)


@app.on_event("startup")
async def startup():
    # Create indexes
    await db.users.create_index("email", unique=True)
    await db.acid_requests.create_index("acid_number", unique=True)
    await db.acid_requests.create_index("requester_id")
    await db.acid_requests.create_index("status")
    await db.acid_requests.create_index([("created_at", -1)])
    # Global Exporter Registry indexes
    await db.global_exporters.create_index("tax_id", unique=True)
    await db.global_exporters.create_index("emails")
    await db.global_exporters.create_index("company_name")
    # Notifications index
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.notifications.create_index([("user_id", 1), ("is_read", 1)])

    # Phase T — Field Inspection
    await db.inspections.create_index("acid_id", unique=True)
    await db.inspections.create_index("inspector_id")
    await db.inspections.create_index("overall_result")
    await db.inspections.create_index([("submitted_at", -1)])

    # Seed admin
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@customs.ly")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@2026!")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "email": admin_email, "password_hash": hash_password(admin_password),
            "role": "admin", "name_ar": "مدير النظام", "name_en": "System Administrator",
            "is_verified": True, "is_active": True, "created_at": datetime.now(timezone.utc),
            "email_verified_at": datetime.now(timezone.utc), "registration_status": "approved"
        })
        logger.info(f"Admin created: {admin_email}")
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})
    # Ensure admin always has email verified
    await db.users.update_one(
        {"email": admin_email, "email_verified_at": None},
        {"$set": {"email_verified_at": datetime.now(timezone.utc), "registration_status": "approved"}}
    )

    # Seed role accounts
    SEED_ACCOUNTS = [
        {"email": "broker@customs.ly",       "password": "Broker@2026!",      "role": "customs_broker",    "name_ar": "مخلص جمركي معتمد",         "name_en": "Licensed Customs Broker",       "company_name_ar": "شركة التخليص الجمركي"},
        {"email": "valuer@customs.ly",        "password": "Valuer@2026!",       "role": "customs_valuer",    "name_ar": "موظف التقدير الجمركي",       "name_en": "Customs Valuation Officer"},
        {"email": "inspector@customs.ly",     "password": "Inspector@2026!",    "role": "inspector",         "name_ar": "مفتش جمركي",                 "name_en": "Customs Inspector"},
        {"email": "treasury@customs.ly",      "password": "Treasury@2026!",     "role": "treasury_officer",  "name_ar": "أمين الخزينة الجمركية",      "name_en": "Treasury Officer"},
        {"email": "gate@customs.ly",          "password": "Gate@2026!",         "role": "gate_officer",      "name_ar": "أمين بوابة الميناء",          "name_en": "Gate Officer"},
        {"email": "supplier@customs.ly",      "password": "Supplier@2026!",     "role": "foreign_supplier",  "name_ar": "مورد أجنبي - شركة الاختبار", "name_en": "Test Foreign Supplier Co."},
        {"email": "carrier@customs.ly",       "password": "Carrier@2026!",      "role": "carrier_agent",     "name_ar": "وكيل شحن وتخليص",            "name_en": "Freight & Customs Agent",       "company_name_ar": "شركة الناقل الليبي للشحن"},
        {"email": "manifest@customs.ly",      "password": "Manifest@2026!",     "role": "manifest_officer",  "name_ar": "مراجع المانيفست",             "name_en": "Manifest Review Officer"},
        {"email": "acidrisk@customs.ly",      "password": "AcidRisk@2026!",     "role": "acid_risk_officer", "name_ar": "موظف ACID والمخاطر",          "name_en": "ACID & Risk Officer"},
        {"email": "declaration@customs.ly",   "password": "Declaration@2026!",  "role": "declaration_officer","name_ar": "موظف البيان الجمركي",        "name_en": "Customs Declaration Officer"},
        {"email": "release@customs.ly",       "password": "Release@2026!",      "role": "release_officer",   "name_ar": "موظف الإفراج الجمركي",       "name_en": "Customs Release Officer"},
        {"email": "pga@customs.ly",           "password": "PGA@2026!",          "role": "pga_officer",       "name_ar": "موظف الجهات الرقابية",       "name_en": "PGA Officer",                   "agency_name_ar": "وزارة الصحة"},
        {"email": "violations@customs.ly",    "password": "Violations@2026!",   "role": "violations_officer","name_ar": "موظف قسم المخالفات",         "name_en": "Violations Officer"},
        {"email": "reg_officer@customs.ly",   "password": "RegOfficer@2026!",   "role": "registration_officer","name_ar": "مأمور التسجيل الجمركي",      "name_en": "Registration Officer"},
    ]
    for acct in SEED_ACCOUNTS:
        if not await db.users.find_one({"email": acct["email"]}):
            await db.users.insert_one({
                "email": acct["email"], "password_hash": hash_password(acct["password"]),
                "role": acct["role"], "name_ar": acct["name_ar"], "name_en": acct["name_en"],
                "company_name_ar": acct.get("company_name_ar", ""),
                "company_name_en": acct.get("company_name_en", ""),
                "is_verified": True, "is_active": True,
                "registration_status": "approved",
                "email_verified_at": datetime.now(timezone.utc),
                "created_at": datetime.now(timezone.utc)
            })
            logger.info(f"Seeded: {acct['email']} ({acct['role']})")

    logger.info("NAFIDHA v3.0 startup complete — modular architecture active")
    # زرع المناطق الجمركية الافتراضية
    await seed_default_regions()
    # فهارس نظام المدفوعات
    await db.payment_transactions.create_index("session_id", unique=True)
    await db.payment_transactions.create_index("exporter_tax_id")
    await db.payment_transactions.create_index("acid_id")
    await db.payment_transactions.create_index([("created_at", -1)])
    await db.admin_config.create_index("key", unique=True)
    # إنشاء إعداد رسوم ACID الافتراضي إن لم يوجد
    await db.admin_config.update_one(
        {"key": "acid_fee_usd"},
        {"$setOnInsert": {"key": "acid_fee_usd", "value": 50.0, "created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    # بدء الـ scheduler التلقائي (فحص الرخص يومياً الساعة 9:00 صباحاً)
    startup_scheduler()
    # تهيئة حقول الـ Workflow للبيانات الموجودة (إضافة wf_sla_deadline للسجلات القديمة)
    await _migrate_workflow_fields()
    # ترقية الحالات القديمة (docs_submitted → pending)
    await _migrate_legacy_statuses()
    # ترقية المستخدمين لدعم roles array متعددة
    await _migrate_roles_array()
    # تهيئة إعدادات تسعير OCR الافتراضية
    await _seed_system_pricing()


async def _seed_system_pricing():
    """زرع إعدادات تسعير OCR الافتراضية إن لم تكن موجودة."""
    existing = await db.system_pricing.find_one({"service_type": "ocr_scan"})
    if not existing:
        await db.system_pricing.insert_one({
            "service_type":       "ocr_scan",
            "service_name_ar":    "مسح OCR الذكي",
            "price_per_unit_usd": 0.05,
            "min_balance_usd":    0.05,
            "packages": [
                {"id": "starter",  "name_ar": "الباقة الأساسية",   "scans": 20,  "price_usd": 1.00},
                {"id": "standard", "name_ar": "الباقة القياسية",   "scans": 100, "price_usd": 4.00},
                {"id": "pro",      "name_ar": "الباقة الاحترافية", "scans": 500, "price_usd": 15.00},
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("[Seed] system_pricing (ocr_scan) created with default packages")
    # فهارس OCR Wallet
    await db.ocr_wallets.create_index("user_id", unique=True)
    await db.ocr_topup_transactions.create_index("user_id")
    await db.ocr_topup_transactions.create_index([("created_at", -1)])
    await db.api_usage_logs.create_index("user_id")
    await db.api_usage_logs.create_index("acid_id")
    await db.system_pricing.create_index("service_type", unique=True)


async def _migrate_workflow_fields():
    """يُضيف wf_sla_deadline للسجلات القديمة التي لا تملكها."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    # KYC tasks migration
    kyc_docs = await db.users.find({
        "role": {"$in": ["importer", "customs_broker", "carrier_agent", "foreign_supplier"]},
        "registration_status": "pending",
        "wf_sla_deadline": {"$exists": False},
    }).to_list(500)
    for u in kyc_docs:
        created = u.get("created_at", now)
        if hasattr(created, "tzinfo") and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        deadline = (created + timedelta(hours=72)).isoformat()
        await db.users.update_one({"_id": u["_id"]}, {"$set": {"wf_sla_deadline": deadline}})
    # ACID tasks migration
    acid_docs = await db.acid_requests.find({
        "status": {"$in": ["submitted", "pending", "under_review"]},
        "wf_sla_deadline": {"$exists": False},
    }).to_list(500)
    for a in acid_docs:
        created = a.get("created_at", now)
        if hasattr(created, "tzinfo") and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        deadline = (created + timedelta(hours=48)).isoformat()
        await db.acid_requests.update_one({"_id": a["_id"]}, {"$set": {"wf_sla_deadline": deadline}})
    if kyc_docs or acid_docs:
        logger.info(f"[Workflow Migration] KYC: {len(kyc_docs)} | ACID: {len(acid_docs)}")


async def _migrate_legacy_statuses():
    """
    ترقية الحالات القديمة — آمن للتكرار (idempotent).

    docs_submitted + email_verified_at مضبوط  → pending   (البريد مُوثَّق، بانتظار KYC)
    docs_submitted + email_verified_at فارغ   → email_unverified (لم يُوثَّق البريد بعد)
    pending/needs_correction + email_verified_at فارغ → تعيين email_verified_at (حسابات قبل Phase L)
    """
    # الحالة 1: docs_submitted + بريد موثَّق → pending
    r1 = await db.users.update_many(
        {"registration_status": "docs_submitted",
         "email_verified_at": {"$nin": [None, ""], "$exists": True}},
        {"$set": {"registration_status": "pending"}}
    )
    # الحالة 2: docs_submitted + بريد غير موثَّق → email_unverified (يحتاج تأكيد بريد)
    r2 = await db.users.update_many(
        {"registration_status": "docs_submitted",
         "$or": [{"email_verified_at": None}, {"email_verified_at": {"$exists": False}}]},
        {"$set": {"registration_status": "email_unverified"}}
    )
    # الحالة 3: pending/needs_correction بدون email_verified_at (وُجدت قبل Phase L)
    # نعتبرهم موثّقي البريد تلقائياً لأنهم تجاوزوا مرحلة التسجيل
    now_iso = datetime.now(timezone.utc).isoformat()
    r3 = await db.users.update_many(
        {
            "registration_status": {"$in": ["pending", "needs_correction"]},
            "$or": [{"email_verified_at": None}, {"email_verified_at": {"$exists": False}}]
        },
        {"$set": {"email_verified_at": now_iso}}
    )
    if r1.modified_count:
        logger.info(f"[Status Migration] docs_submitted+verified → pending: {r1.modified_count} accounts")
    if r2.modified_count:
        logger.info(f"[Status Migration] docs_submitted+unverified → email_unverified: {r2.modified_count} accounts")
    if r3.modified_count:
        logger.info(f"[Status Migration] pending+no-email-verified → email_verified_at set: {r3.modified_count} accounts")


async def _migrate_roles_array():
    """
    ترقية المستخدمين القدامى لدعم حقل roles[] — آمن للتكرار.
    كل مستخدم بدون roles يحصل على [role] تلقائياً.
    """
    result = await db.users.update_many(
        {"$or": [{"roles": {"$exists": False}}, {"roles": []}]},
        [{"$set": {"roles": ["$role"]}}]  # MongoDB Aggregation Pipeline Update
    )
    if result.modified_count:
        logger.info(f"[Roles Migration] {result.modified_count} users upgraded to roles[] array")




@app.on_event("shutdown")
async def shutdown():
    shutdown_scheduler()
    client.close()
