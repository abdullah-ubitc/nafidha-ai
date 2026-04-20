#!/usr/bin/env python3
"""
NAFIDHA — Seed Script
=====================
ينشئ بيانات اختبار كاملة للنظام:
  - جميع حسابات الأدوار (Admin + 14 دور)
  - طلبات تسجيل KYC (مستورد، مخلص، ناقل)
  - طلبات ACID بحالات مختلفة
  - مخالفات جمركية تجريبية
  - محافظ رقمية بأرصدة

الاستخدام:
    python seed.py                  # تشغيل عادي
    python seed.py --reset          # حذف البيانات القديمة وإعادة الزرع
    python seed.py --users-only     # أدوار المستخدمين فقط
"""

import asyncio
import argparse
import random
import sys
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from dotenv import load_dotenv
import os

load_dotenv()

# ── اتصال قاعدة البيانات ────────────────────────────────────────────────────
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME   = os.environ["DB_NAME"]

client = AsyncIOMotorClient(MONGO_URL)
db     = client[DB_NAME]

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_pw(password: str) -> str:
    return pwd_ctx.hash(password)

def now():
    return datetime.now(timezone.utc)

def days_ago(n): return now() - timedelta(days=n)
def days_from_now(n): return now() + timedelta(days=n)

# ════════════════════════════════════════════════════════════════════════════
#  1. المستخدمون
# ════════════════════════════════════════════════════════════════════════════

ACCOUNTS = [
    # ── المدير ──────────────────────────────────────────────────────────────
    {
        "email": "admin@customs.ly",
        "password": "Admin@2026!",
        "role": "admin",
        "name_ar": "مدير النظام",
        "name_en": "System Administrator",
        "status": "approved",
    },
    # ── الموظفون الداخليون ───────────────────────────────────────────────────
    {
        "email": "reg_officer@customs.ly",
        "password": "RegOfficer@2026!",
        "role": "registration_officer",
        "name_ar": "مأمور التسجيل الجمركي",
        "name_en": "Registration Officer",
    },
    {
        "email": "acidrisk@customs.ly",
        "password": "AcidRisk@2026!",
        "role": "acid_risk_officer",
        "name_ar": "موظف ACID والمخاطر",
        "name_en": "ACID & Risk Officer",
    },
    {
        "email": "declaration@customs.ly",
        "password": "Declaration@2026!",
        "role": "declaration_officer",
        "name_ar": "موظف البيان الجمركي",
        "name_en": "Customs Declaration Officer",
    },
    {
        "email": "release@customs.ly",
        "password": "Release@2026!",
        "role": "release_officer",
        "name_ar": "موظف الإفراج الجمركي",
        "name_en": "Customs Release Officer",
    },
    {
        "email": "inspector@customs.ly",
        "password": "Inspector@2026!",
        "role": "inspector",
        "name_ar": "مفتش جمركي",
        "name_en": "Customs Inspector",
    },
    {
        "email": "valuer@customs.ly",
        "password": "Valuer@2026!",
        "role": "customs_valuer",
        "name_ar": "موظف التقدير الجمركي",
        "name_en": "Customs Valuation Officer",
    },
    {
        "email": "manifest@customs.ly",
        "password": "Manifest@2026!",
        "role": "manifest_officer",
        "name_ar": "مراجع المانيفست",
        "name_en": "Manifest Review Officer",
    },
    {
        "email": "pga@customs.ly",
        "password": "PGA@2026!",
        "role": "pga_officer",
        "name_ar": "موظف الجهات الرقابية",
        "name_en": "PGA Officer",
        "agency_name_ar": "وزارة الصحة",
    },
    {
        "email": "violations@customs.ly",
        "password": "Violations@2026!",
        "role": "violations_officer",
        "name_ar": "موظف قسم المخالفات",
        "name_en": "Violations Officer",
    },
    {
        "email": "treasury@customs.ly",
        "password": "Treasury@2026!",
        "role": "treasury_officer",
        "name_ar": "أمين الخزينة الجمركية",
        "name_en": "Treasury Officer",
    },
    {
        "email": "gate@customs.ly",
        "password": "Gate@2026!",
        "role": "gate_officer",
        "name_ar": "أمين بوابة الميناء",
        "name_en": "Gate Officer",
    },
    # ── المستخدمون التجاريون (بعد KYC) ─────────────────────────────────────
    {
        "email": "importer@test.ly",
        "password": "Importer@2026!",
        "role": "importer",
        "name_ar": "شركة الأمل للاستيراد",
        "name_en": "Al Amal Import Co.",
        "company_name_ar": "شركة الأمل للاستيراد والتصدير",
        "company_name_en": "Al Amal Import & Export Co.",
        "statistical_code": "LY-IMP-001234",
        "status": "approved",
    },
    {
        "email": "broker@test.ly",
        "password": "Broker@2026!",
        "role": "customs_broker",
        "name_ar": "أحمد المخلص الجمركي",
        "name_en": "Ahmed Licensed Broker",
        "broker_license_number": "BRK-2026-0042",
        "status": "approved",
    },
    {
        "email": "carrier@test.ly",
        "password": "Carrier@2026!",
        "role": "carrier_agent",
        "name_ar": "وكالة الناقل الليبي",
        "name_en": "Libyan Carrier Agency",
        "company_name_ar": "شركة الناقل الليبي للشحن",
        "company_name_en": "Libyan Shipping Carrier Co.",
        "status": "approved",
    },
    {
        "email": "supplier@test.ly",
        "password": "Supplier@2026!",
        "role": "foreign_supplier",
        "name_ar": "مورد أجنبي - شركة الاختبار",
        "name_en": "Test Foreign Supplier Co.",
        "status": "approved",
    },
    # ── طلبات KYC معلّقة (للاختبار) ─────────────────────────────────────────
    {
        "email": "pending_importer@test.ly",
        "password": "Pending@2026!",
        "role": "importer",
        "name_ar": "مستورد جديد - طلب قيد المراجعة",
        "name_en": "New Importer - Under Review",
        "status": "pending",
    },
    {
        "email": "rejected_broker@test.ly",
        "password": "Rejected@2026!",
        "role": "customs_broker",
        "name_ar": "مخلص - طلب مرفوض للاختبار",
        "name_en": "Broker - Rejected Application Test",
        "status": "rejected",
    },
]


async def seed_users(reset: bool = False):
    print("\n[1/4] زرع المستخدمين...")
    if reset:
        non_admin = [a["email"] for a in ACCOUNTS if a["role"] != "admin"]
        result = await db.users.delete_many({"email": {"$in": non_admin}})
        print(f"  حُذف {result.deleted_count} مستخدم قديم")

    created = 0
    for acct in ACCOUNTS:
        existing = await db.users.find_one({"email": acct["email"]})
        if existing:
            print(f"  [موجود] {acct['email']}")
            continue

        status = acct.get("status", "approved")
        doc = {
            "email":               acct["email"],
            "password_hash":       hash_pw(acct["password"]),
            "role":                acct["role"],
            "roles":               [acct["role"]],
            "name_ar":             acct["name_ar"],
            "name_en":             acct["name_en"],
            "company_name_ar":     acct.get("company_name_ar", ""),
            "company_name_en":     acct.get("company_name_en", ""),
            "agency_name_ar":      acct.get("agency_name_ar", ""),
            "statistical_code":    acct.get("statistical_code", ""),
            "broker_license_number": acct.get("broker_license_number", ""),
            "is_verified":         True,
            "is_active":           status == "approved",
            "registration_status": status,
            "email_verified_at":   now(),
            "created_at":          now(),
        }
        await db.users.insert_one(doc)
        created += 1
        print(f"  [+] {acct['email']}  ({acct['role']}) — {status}")

    print(f"  تم إنشاء {created} حساب جديد")
    return created


# ════════════════════════════════════════════════════════════════════════════
#  2. طلبات KYC / التسجيل
# ════════════════════════════════════════════════════════════════════════════

KYC_REGISTRATIONS = [
    {
        "role": "importer",
        "email": "importer@test.ly",
        "status": "approved",
        "company_name_ar": "شركة الأمل للاستيراد والتصدير",
        "statistical_code": "LY-IMP-001234",
        "docs": ["commercial_registry_front", "commercial_registry_back",
                 "statistical_cert_front", "statistical_cert_back",
                 "rep_id_front", "rep_id_back"],
    },
    {
        "role": "customs_broker",
        "email": "broker@test.ly",
        "status": "approved",
        "company_name_ar": "مكتب أحمد للتخليص الجمركي",
        "broker_license_number": "BRK-2026-0042",
        "docs": ["broker_license_front", "broker_license_back",
                 "statistical_cert_front", "national_id_front", "national_id_back",
                 "signature_sample"],
    },
    {
        "role": "carrier_agent",
        "email": "carrier@test.ly",
        "status": "approved",
        "company_name_ar": "شركة الناقل الليبي للشحن",
        "docs": ["commercial_registry_front", "commercial_registry_back",
                 "marine_license_front", "rep_id_front"],
    },
    {
        "role": "importer",
        "email": "pending_importer@test.ly",
        "status": "pending",
        "company_name_ar": "مؤسسة الفجر الجديد للتجارة",
        "statistical_code": "LY-IMP-009988",
        "docs": ["commercial_registry_front", "statistical_cert_front", "rep_id_front"],
    },
    {
        "role": "customs_broker",
        "email": "rejected_broker@test.ly",
        "status": "rejected",
        "company_name_ar": "مكتب التخليص الجمركي - مرفوض",
        "rejection_reason": "الترخيص منتهي الصلاحية — يرجى تجديده وإعادة التقديم",
        "docs": ["broker_license_front"],
    },
]


async def seed_registrations(reset: bool = False):
    print("\n[2/4] زرع طلبات التسجيل KYC...")
    if reset:
        await db.registrations.delete_many(
            {"user_email": {"$in": [r["email"] for r in KYC_REGISTRATIONS]}}
        )

    created = 0
    for reg in KYC_REGISTRATIONS:
        user = await db.users.find_one({"email": reg["email"]})
        if not user:
            print(f"  [تخطي] المستخدم غير موجود: {reg['email']}")
            continue

        user_id = str(user["_id"])
        existing = await db.registrations.find_one({"user_id": user_id})
        if existing:
            print(f"  [موجود] طلب {reg['email']}")
            continue

        doc = {
            "user_id":           user_id,
            "user_email":        reg["email"],
            "role":              reg["role"],
            "status":            reg["status"],
            "company_name_ar":   reg.get("company_name_ar", ""),
            "statistical_code":  reg.get("statistical_code", ""),
            "broker_license_number": reg.get("broker_license_number", ""),
            "rejection_reason":  reg.get("rejection_reason", None),
            "docs": [
                {
                    "doc_type": d,
                    "url": f"/uploads/seed/{user_id}_{d}.jpg",
                    "uploaded_at": days_ago(random.randint(1, 30)).isoformat(),
                }
                for d in reg.get("docs", [])
            ],
            "submitted_at": days_ago(random.randint(5, 45)).isoformat(),
            "reviewed_at":  days_ago(random.randint(1, 4)).isoformat() if reg["status"] != "pending" else None,
            "reviewed_by":  "reg_officer@customs.ly" if reg["status"] != "pending" else None,
            "created_at":   days_ago(random.randint(5, 45)),
        }
        await db.registrations.insert_one(doc)
        created += 1
        print(f"  [+] طلب KYC {reg['email']} ({reg['status']})")

    print(f"  تم إنشاء {created} طلب تسجيل")
    return created


# ════════════════════════════════════════════════════════════════════════════
#  3. طلبات ACID
# ════════════════════════════════════════════════════════════════════════════

PORTS      = ["مصراتة البحري", "ميناء طرابلس", "مطار معيتيقة", "منفذ مساعد", "ميناء بنغازي"]
MODES      = {"مصراتة البحري": "sea", "ميناء طرابلس": "sea", "مطار معيتيقة": "air",
               "منفذ مساعد": "land", "ميناء بنغازي": "sea"}
COUNTRIES  = ["تركيا", "إيطاليا", "الصين", "ألمانيا", "الإمارات", "مصر", "كوريا الجنوبية"]
SUPPLIERS  = {
    "تركيا":       ["Istanbul Trading Co.", "Ankara Exports Ltd."],
    "إيطاليا":     ["Milano Industries SRL", "Roma Trade S.p.A"],
    "الصين":       ["Guangzhou Electronics Co.", "Shanghai Global Trade"],
    "ألمانيا":     ["Berlin Machinery GmbH", "Munich Auto Parts AG"],
    "الإمارات":    ["Dubai Wholesale LLC", "Abu Dhabi Trading"],
    "مصر":         ["Cairo Textiles Co.", "Alexandria Export"],
    "كوريا الجنوبية": ["Seoul Electronics Corp.", "Busan Shipping Ltd."],
}
GOODS = [
    {"desc": "أجهزة هواتف ذكية",     "hs": "8517", "range": (15000, 120000)},
    {"desc": "قطع غيار سيارات",       "hs": "8708", "range": (8000,  45000)},
    {"desc": "أثاث منزلي خشبي",       "hs": "9403", "range": (5000,  30000)},
    {"desc": "ملابس قطنية",           "hs": "6205", "range": (3000,  25000)},
    {"desc": "آلات ومعدات صناعية",    "hs": "8479", "range": (25000, 200000)},
    {"desc": "أدوية ومستحضرات طبية", "hs": "3004", "range": (5000,  60000)},
    {"desc": "مواد بناء سيراميك",     "hs": "6908", "range": (4000,  20000)},
    {"desc": "أجهزة كهربائية منزلية","hs": "8516", "range": (8000,  50000)},
    {"desc": "مواد غذائية معلبة",     "hs": "1602", "range": (2000,  15000)},
    {"desc": "لابتوب وحاسبات",        "hs": "8471", "range": (10000, 80000)},
]
STATUSES   = ["approved", "approved", "submitted", "under_review", "rejected", "amendment_required"]
RISK_LEVELS = ["low", "low", "medium", "medium", "high"]
REQUESTERS = [
    {"id": "req001", "name_ar": "شركة الأمل للاستيراد",    "name_en": "Al Amal Import Co."},
    {"id": "req002", "name_ar": "مؤسسة الخليج للتجارة",   "name_en": "Gulf Trade Est."},
    {"id": "req003", "name_ar": "شركة ليبيا التجارية",     "name_en": "Libya Commercial Co."},
    {"id": "req004", "name_ar": "مجموعة النجمة للاستيراد", "name_en": "Najma Import Group"},
]


async def _next_acid_number():
    count = await db.acid_requests.count_documents({})
    year  = datetime.now(timezone.utc).year
    return f"ACID-{year}-{str(count + 1).zfill(5)}"


async def seed_acid_requests(count: int = 60, reset: bool = False):
    print(f"\n[3/4] زرع {count} طلب ACID...")
    if reset:
        await db.acid_requests.delete_many({})
        print("  حُذفت جميع طلبات ACID القديمة")

    existing = await db.acid_requests.count_documents({})
    if existing >= count:
        print(f"  [تخطي] يوجد بالفعل {existing} طلب")
        return 0

    needed  = count - existing
    seeded  = 0
    for _ in range(needed):
        port     = random.choice(PORTS)
        country  = random.choice(COUNTRIES)
        supplier = random.choice(SUPPLIERS.get(country, ["Generic Supplier Ltd."]))
        good     = random.choice(GOODS)
        value    = round(random.uniform(*good["range"]), 2)
        status   = random.choice(STATUSES)
        risk     = "high" if (int(good["hs"][:2]) in [93, 36] or value > 100000) else random.choice(RISK_LEVELS)
        requester = random.choice(REQUESTERS)
        created  = days_ago(random.randint(1, 180))
        acid_num = await _next_acid_number()

        risk_channel = "green"
        if risk == "high":   risk_channel = "red"
        elif risk == "medium": risk_channel = "yellow"

        doc = {
            "acid_number":       acid_num,
            "requester_id":      requester["id"],
            "requester_name_ar": requester["name_ar"],
            "requester_name_en": requester["name_en"],
            "status":            status,
            "risk_level":        risk,
            "risk_channel":      risk_channel,
            "supplier_name":     supplier,
            "supplier_country":  country,
            "supplier_address":  f"P.O.Box {random.randint(100, 9999)}, {country}",
            "goods_description": good["desc"],
            "hs_code":           good["hs"],
            "quantity":          random.randint(10, 500),
            "unit":              random.choice(["قطعة", "كيلوغرام", "طن", "كرتون"]),
            "value_usd":         value,
            "port_of_entry":     port,
            "transport_mode":    MODES.get(port, "sea"),
            "carrier_name":      f"Carrier {random.randint(1, 5)} Ltd.",
            "bill_of_lading":    f"BL{random.randint(10000, 99999)}",
            "estimated_arrival": (created + timedelta(days=random.randint(5, 30))).strftime("%Y-%m-%d"),
            "reviewer_notes":    None,
            "on_behalf_of":      None,
            "created_at":        created,
            "updated_at":        created,
            "timeline": [
                {"event": "submitted", "timestamp": created.isoformat(), "actor": requester["name_ar"]}
            ],
        }
        if status in ("approved", "rejected"):
            reviewed = created + timedelta(days=random.randint(1, 5))
            doc["reviewed_at"] = reviewed.isoformat()
            doc["reviewed_by"] = "acidrisk@customs.ly"
            doc["timeline"].append(
                {"event": status, "timestamp": reviewed.isoformat(), "actor": "موظف المراجعة"}
            )

        try:
            await db.acid_requests.insert_one(doc)
            seeded += 1
        except Exception as e:
            print(f"  [خطأ] {e}")

    print(f"  تم إنشاء {seeded} طلب ACID")
    return seeded


# ════════════════════════════════════════════════════════════════════════════
#  4. مخالفات جمركية تجريبية
# ════════════════════════════════════════════════════════════════════════════

VIOLATION_TYPES = [
    {"type_ar": "تقليل قيمة البضائع",          "penalty_range": (500, 5000)},
    {"type_ar": "بيان جمركي غير مكتمل",        "penalty_range": (200, 1500)},
    {"type_ar": "استيراد بضائع محظورة",         "penalty_range": (5000, 50000)},
    {"type_ar": "تأخر في تقديم المستندات",      "penalty_range": (100, 800)},
    {"type_ar": "مخالفة شروط الترخيص التجاري", "penalty_range": (1000, 8000)},
    {"type_ar": "إخفاء بضائع داخل الشحنة",     "penalty_range": (10000, 100000)},
]

VIOLATION_STATUSES = ["open", "open", "under_investigation", "closed", "appealed"]


async def seed_violations(count: int = 20, reset: bool = False):
    print(f"\n[4/4] زرع {count} مخالفة جمركية...")
    if reset:
        await db.violations.delete_many({})

    existing = await db.violations.count_documents({})
    if existing >= count:
        print(f"  [تخطي] يوجد بالفعل {existing} مخالفة")
        return 0

    users = await db.users.find(
        {"role": {"$in": ["importer", "customs_broker", "carrier_agent"]}},
        {"_id": 1, "name_ar": 1, "email": 1}
    ).to_list(50)

    if not users:
        print("  [تخطي] لا يوجد مستخدمون تجاريون")
        return 0

    seeded  = 0
    needed  = count - existing
    for i in range(needed):
        vtype  = random.choice(VIOLATION_TYPES)
        user   = random.choice(users)
        status = random.choice(VIOLATION_STATUSES)
        penalty = round(random.uniform(*vtype["penalty_range"]), 2)
        created = days_ago(random.randint(1, 365))

        doc = {
            "violation_number": f"VIO-{datetime.now(timezone.utc).year}-{str(existing + i + 1).zfill(4)}",
            "user_id":          str(user["_id"]),
            "user_name_ar":     user.get("name_ar", ""),
            "user_email":       user.get("email", ""),
            "violation_type_ar": vtype["type_ar"],
            "penalty_usd":      penalty,
            "status":           status,
            "description_ar":   f"مخالفة {vtype['type_ar']} — بلاغ رقم {random.randint(1000, 9999)}",
            "port_ar":          random.choice(PORTS),
            "officer_email":    "violations@customs.ly",
            "created_at":       created,
            "updated_at":       created,
        }
        if status == "closed":
            doc["resolved_at"] = (created + timedelta(days=random.randint(3, 30))).isoformat()
            doc["resolution_notes"] = "تمت التسوية — سُدِّدت الغرامة كاملاً"

        await db.violations.insert_one(doc)
        seeded += 1

    print(f"  تم إنشاء {seeded} مخالفة")
    return seeded


# ════════════════════════════════════════════════════════════════════════════
#  تشغيل رئيسي
# ════════════════════════════════════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser(description="NAFIDHA Seed Script")
    parser.add_argument("--reset",       action="store_true", help="حذف البيانات القديمة قبل الزرع")
    parser.add_argument("--users-only",  action="store_true", help="إنشاء المستخدمين فقط")
    parser.add_argument("--acid-count",  type=int, default=60, help="عدد طلبات ACID (افتراضي: 60)")
    args = parser.parse_args()

    print("=" * 60)
    print("  NAFIDHA — نظام زرع البيانات")
    print(f"  قاعدة البيانات: {DB_NAME}")
    print("=" * 60)

    u = await seed_users(reset=args.reset)

    if not args.users_only:
        r  = await seed_registrations(reset=args.reset)
        a  = await seed_acid_requests(count=args.acid_count, reset=args.reset)
        v  = await seed_violations(reset=args.reset)
    else:
        r = a = v = 0

    print("\n" + "=" * 60)
    print("  ملخص الزرع:")
    print(f"  • مستخدمون جدد:   {u}")
    print(f"  • طلبات KYC:       {r}")
    print(f"  • طلبات ACID:      {a}")
    print(f"  • مخالفات:         {v}")
    print("=" * 60)

    print("\n  بيانات الدخول:")
    print("  ┌─────────────────────────────────┬──────────────────┬──────────────────────┐")
    print("  │ الدور                           │ البريد           │ كلمة المرور          │")
    print("  ├─────────────────────────────────┼──────────────────┼──────────────────────┤")
    print("  │ مدير النظام                     │ admin@customs.ly │ Admin@2026!          │")
    print("  │ مأمور التسجيل                   │ reg_officer@...  │ RegOfficer@2026!     │")
    print("  │ مستورد معتمد                    │ importer@test.ly │ Importer@2026!       │")
    print("  │ مخلص جمركي معتمد               │ broker@test.ly   │ Broker@2026!         │")
    print("  │ وكيل ناقل معتمد                │ carrier@test.ly  │ Carrier@2026!        │")
    print("  │ مستورد (طلب معلّق)             │ pending_importer │ Pending@2026!        │")
    print("  └─────────────────────────────────┴──────────────────┴──────────────────────┘")
    print("\n  اكتمل الزرع بنجاح ✓")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
