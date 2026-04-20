"""All Pydantic models and Enums"""
from pydantic import BaseModel, BeforeValidator
from typing import Annotated, Optional, List
from bson import ObjectId
from enum import Enum


def validate_object_id(v):
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, str) and ObjectId.is_valid(v):
        return v
    raise ValueError(f"Invalid ObjectId: {v}")


PyObjectId = Annotated[str, BeforeValidator(validate_object_id)]


# ===== Enums =====
class UserRole(str, Enum):
    IMPORTER = "importer"
    FOREIGN_SUPPLIER = "foreign_supplier"
    CARRIER_AGENT = "carrier_agent"
    CUSTOMS_BROKER = "customs_broker"
    MANIFEST_OFFICER = "manifest_officer"
    ACID_RISK_OFFICER = "acid_risk_officer"
    DECLARATION_OFFICER = "declaration_officer"
    RELEASE_OFFICER = "release_officer"
    PGA_OFFICER = "pga_officer"
    VIOLATIONS_OFFICER = "violations_officer"
    ACID_REVIEWER = "acid_reviewer"
    CUSTOMS_VALUER = "customs_valuer"
    INSPECTOR = "inspector"
    TREASURY_OFFICER = "treasury_officer"
    GATE_OFFICER = "gate_officer"
    REGISTRATION_OFFICER = "registration_officer"   # Phase L — مأمور التسجيل / KYC
    ADMIN = "admin"


# الأدوار الداخلية — تُفعَّل تلقائياً بدون KYC (تُنشأ من Admin/System)
INTERNAL_CUSTOMS_ROLES = {
    "admin", "acid_reviewer", "acid_risk_officer", "customs_valuer",
    "inspector", "gate_officer", "manifest_officer", "declaration_officer",
    "release_officer", "pga_officer", "violations_officer", "treasury_officer",
    "registration_officer",
}
# الأدوار التجارية — تحتاج KYC من مأمور التسجيل
KYC_REQUIRED_ROLES = {"importer", "customs_broker", "carrier_agent", "foreign_supplier"}


class EntityType(str, Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"
    GOVERNMENT = "government"


class AcidStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    AMENDMENT_REQUIRED = "amendment_required"


class TransportMode(str, Enum):
    SEA = "sea"
    AIR = "air"
    LAND = "land"
    RAIL = "rail"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskChannel(str, Enum):
    """Customs risk channel (مسار المخاطر)"""
    GREEN  = "green"   # إفراج فوري
    YELLOW = "yellow"  # فحص وثائق
    RED    = "red"     # فحص مادي كامل


class PGADecision(str, Enum):
    """PGA regulatory decision"""
    APPROVE   = "approve"
    REJECT    = "reject"
    GUARANTEE = "guarantee"


# ===== Request Models =====
class UserCreate(BaseModel):
    email: str
    password: str
    role: UserRole
    name_ar: str
    name_en: str
    entity_type: Optional[str] = None        # نوع الكيان (free text — e.g. 'Individual', 'LLC', 'company')
    company_name_ar: Optional[str] = None
    company_name_en: Optional[str] = None
    commercial_registry_no: Optional[str] = None
    commercial_registry_expiry: Optional[str] = None
    tax_id_tin: Optional[str] = None
    manager_national_id: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    # Phase E — Sovereign Identity
    statistical_code: Optional[str] = None
    license_expiry_date: Optional[str] = None  # legacy alias
    # Registration wizard fields
    delegate_name_ar: Optional[str] = None
    delegate_name_en: Optional[str] = None
    delegate_national_id: Optional[str] = None
    delegate_phone: Optional[str] = None
    delegate_email: Optional[str] = None
    license_number: Optional[str] = None
    license_expiry: Optional[str] = None
    # ── Phase 2026 — Importer Re-engineering ──────────────────────────
    # Legal Entity
    legal_name_ar: Optional[str] = None            # الاسم القانوني بالعربية
    legal_name_en: Optional[str] = None            # الاسم القانوني بالإنجليزية
    cr_number: Optional[str] = None               # رقم السجل التجاري
    cr_expiry_date: Optional[str] = None          # تاريخ انتهاء السجل التجاري
    vat_number: Optional[str] = None              # الرقم الضريبي (اختياري)
    address_ar: Optional[str] = None              # العنوان بالعربية
    address_en: Optional[str] = None              # العنوان بالإنجليزية
    statistical_expiry_date: Optional[str] = None  # تاريخ انتهاء الرمز الإحصائي
    # Authorized Representative
    rep_full_name_ar: Optional[str] = None        # اسم المفوَّض بالعربية
    rep_full_name_en: Optional[str] = None        # اسم المفوَّض بالإنجليزية
    rep_id_type: Optional[str] = None             # نوع الهوية: national_id | passport
    rep_id_number: Optional[str] = None           # رقم الهوية
    rep_nationality: Optional[str] = None         # الجنسية
    rep_job_title: Optional[str] = None           # المنصب: owner | signing_manager | operations_manager
    rep_mobile: Optional[str] = None              # الهاتف المحمول (218XXXXXXXXXX)
    # ── Customs Broker Specific Fields ─────────────────────────────────────────
    broker_type: Optional[str] = None                  # "individual" | "company"
    customs_region: Optional[str] = None               # كود المنطقة الجمركية للمخلص الفردي
    broker_license_number: Optional[str] = None        # رقم ترخيص المخلص الجمركي
    broker_license_expiry: Optional[str] = None        # تاريخ انتهاء ترخيص المخلص
    issuing_customs_office: Optional[str] = None       # مكتب الجمارك مُصدِر الترخيص
    # ── Carrier Agent Multi-Modal Fields ──────────────────────────────────────────
    transport_modes: Optional[List[str]] = None        # ["sea", "air", "land"]
    agency_name_ar: Optional[str] = None               # اسم الوكالة بالعربية
    agency_name_en: Optional[str] = None               # اسم الوكالة بالإنجليزية
    agency_commercial_reg: Optional[str] = None        # رقم السجل التجاري للوكالة
    marine_license_number: Optional[str] = None        # رقم الترخيص البحري
    marine_license_expiry: Optional[str] = None        # تاريخ انتهاء الترخيص البحري
    air_operator_license: Optional[str] = None         # رقم ترخيص المشغل الجوي (AOC)
    air_license_expiry: Optional[str] = None           # تاريخ انتهاء الترخيص الجوي
    land_transport_license: Optional[str] = None       # رقم ترخيص النقل البري
    land_license_expiry: Optional[str] = None          # تاريخ انتهاء الترخيص البري


class UserLogin(BaseModel):
    email: str
    password: str


class AcidRequestCreate(BaseModel):
    supplier_name: str
    supplier_country: str
    supplier_address: Optional[str] = None
    goods_description: str
    hs_code: str
    quantity: float
    unit: str
    value_usd: float
    port_of_entry: str
    transport_mode: TransportMode
    carrier_name: Optional[str] = None
    bill_of_lading: Optional[str] = None
    estimated_arrival: Optional[str] = None
    on_behalf_of: Optional[str] = None
    # Phase E — Global Trade Flow
    exporter_email: Optional[str] = None    # للدعوة التلقائية للمصدر الدولي
    proforma_invoice: Optional[str] = None  # رابط الفاتورة المبدئية (بعد الرفع)
    # Global Exporter Registry — رقم الضريبة كمرجع قانوني
    exporter_tax_id: Optional[str] = None   # الربط بجدول global_exporters


class AcidReviewInput(BaseModel):
    action: str
    notes: Optional[str] = None


class FeesCalculateInput(BaseModel):
    value_usd: float
    hs_code: str
    quantity: Optional[float] = 1


class ManifestCreate(BaseModel):
    transport_mode: TransportMode
    port_of_entry: str
    arrival_date: str
    # Sea fields
    vessel_name: Optional[str] = None
    imo_number: Optional[str] = None
    voyage_id: Optional[str] = None
    container_ids: Optional[List[str]] = []
    container_seal: Optional[str] = None
    # Air fields
    flight_number: Optional[str] = None
    airline: Optional[str] = None
    awb: Optional[str] = None
    # Land fields
    truck_plate: Optional[str] = None
    trailer_plate: Optional[str] = None
    driver_id: Optional[str] = None
    driver_passport: Optional[str] = None
    # Phase E D.O. logic
    delivery_order_status: bool = False
    # Common
    consignments: List[dict] = []
    notes: Optional[str] = None


class ManifestReviewInput(BaseModel):
    action: str
    notes: Optional[str] = None


class DeclarationReviewInput(BaseModel):
    action: str
    notes: Optional[str] = None


class ReleaseApproveInput(BaseModel):
    notes: Optional[str] = None


class PGAReviewInput(BaseModel):
    action: str   # "approve" | "reject" | "guarantee"
    agency_name: str
    notes: Optional[str] = None
    reference_number: Optional[str] = None
    risk_channel: Optional[RiskChannel] = None   # Phase E — set risk channel
    pga_decision: Optional[PGADecision] = None   # Phase E — structured decision


class GuaranteeCreate(BaseModel):
    acid_id: str
    guarantee_type: str
    amount_lyd: float
    beneficiary: str
    description: Optional[str] = None
    expiry_date: Optional[str] = None


class GuaranteeReleaseInput(BaseModel):
    reason: str


class ViolationCreate(BaseModel):
    acid_id: str
    violation_type: str
    description_ar: str
    fine_amount_lyd: Optional[float] = None


class ViolationFineInput(BaseModel):
    fine_amount_lyd: float
    fine_reason: str


class SADCreate(BaseModel):
    acid_id: str
    cbl_bank_ref: Optional[str] = None
    customs_station: Optional[str] = "طرابلس البحري"
    declaration_type: str = "import"


class SADUpdate(BaseModel):
    cbl_bank_ref: Optional[str] = None
    customs_station: Optional[str] = None
    status: Optional[str] = None


class AIRiskInput(BaseModel):
    goods_description: str
    hs_code: str
    value_usd: float
    supplier_country: str


class BankVerifyInput(BaseModel):
    acid_number: str
    cbl_ref: str
    amount_lyd: float
    bank_name: str = "مصرف الوحدة"


class TariffValuationInput(BaseModel):
    goods_description: str
    hs_code: str
    declared_value_usd: float
    quantity: float
    unit: str
    supplier_country: str
    acid_id: Optional[str] = None


class ValuationInput(BaseModel):
    confirmed_value_usd: float
    valuation_notes: str = ""
    acid_id: str


class TreasuryPayInput(BaseModel):
    treasury_ref: str
    notes: str = ""


class GateReleaseInput(BaseModel):
    notes: str = ""


class HSSearchInput(BaseModel):
    query: str
    lang: str = "ar"


# ===== Phase T — Field Inspection (وحدة المعاينة الميدانية) =====

class SealStatus(str, Enum):
    INTACT  = "intact"    # سليم
    BROKEN  = "broken"    # مكسور
    MISSING = "missing"   # مفقود


class HSCodeMatch(str, Enum):
    MATCHING     = "matching"      # مطابق
    NOT_MATCHING = "not_matching"  # غير مطابق


class TrademarkStatus(str, Enum):
    GENUINE              = "genuine"              # أصلية
    SUSPECTED_COUNTERFEIT = "suspected_counterfeit" # مشتبه في تقليدها
    DAMAGED              = "damaged"              # تالفة


class InspectionResult(str, Enum):
    COMPLIANT        = "compliant"          # مطابق — يُفعِّل الإفراج
    NON_COMPLIANT    = "non_compliant"      # غير مطابق — يوقف الإفراج
    PENDING_ESCALATION = "pending_escalation"  # قيد التصعيد


class InspectionReportCreate(BaseModel):
    acid_id: str

    # القسم 1: التحقق من الحاوية
    seal_status: SealStatus
    new_seal_number: Optional[str] = None         # رقم الختم الجمركي الجديد
    container_integrity: bool                      # True = سليمة، False = آثار تلاعب
    container_integrity_notes: Optional[str] = None

    # القسم 2: المطابقة التقنية
    hs_code_match: HSCodeMatch
    suggested_hs_code: Optional[str] = None       # إلزامي إذا hs_code_match = not_matching
    origin_country_match: bool                     # True = مطابق
    actual_quantity: float
    actual_weight: float

    # القسم 3: الرقابة والمنع
    trademark_status: TrademarkStatus
    expiry_date: Optional[str] = None             # للمواد الغذائية / الطبية
    inspector_notes: Optional[str] = None

    # القسم 4: المواد الخطرة / المشعة
    dangerous_goods_flag: bool = False
    dangerous_goods_type: Optional[str] = None    # نوع الخطر (كيميائي / مشع / قابل للاشتعال...)

    # القسم 5: الأدلة البصرية (base64 JPEG)
    photos: List[str] = []                        # 3 صور كحد أدنى

    # توقيت
    inspection_started_at: str
    inspection_completed_at: str

    # النتيجة الإجمالية
    overall_result: InspectionResult


# ===== Phase E — Platform Fees =====
class PlatformFeeType(str, Enum):
    ANNUAL_SUBSCRIPTION  = "annual_subscription"
    ACID_TRANSACTION     = "acid_transaction"
    MANIFEST_TRANSACTION = "manifest_transaction"
    SAD_TRANSACTION      = "sad_transaction"
    AMENDMENT_FEE        = "amendment_fee"       # Phase F


class PlatformFeeCreate(BaseModel):
    fee_type: PlatformFeeType
    reference_id: str
    amount_lyd: float


class PlatformFeePayInput(BaseModel):
    payment_ref: str
    notes: str = ""
    use_wallet: bool = False   # Phase F — deduct from wallet balance


# ===== Phase F — Wallet =====
class WalletTransactionType(str, Enum):
    TOPUP  = "topup"
    DEDUCT = "deduct"
    REFUND = "refund"


class WalletTopUpInput(BaseModel):
    amount_lyd: float
    payment_ref: str
    notes: str = ""


class IssueDeliveryOrderInput(BaseModel):
    freight_fees_paid: bool
    notes: str = ""


# ===== Global Exporter Registry (Strategic Update) =====
class GlobalExporterCreate(BaseModel):
    tax_id: str                          # المفتاح الأساسي الفريد — رقم الضريبة / VAT
    company_name: str                    # اسم الشركة الدولية
    emails: Optional[List[str]] = []    # قائمة البريد الإلكتروني (يمكن أن يكون متعدداً)
    country: Optional[str] = None       # البلد
    address: Optional[str] = None       # العنوان


class GlobalExporterAddEmail(BaseModel):
    email: str                           # إضافة بريد إلكتروني ثانوي


class GlobalExporterVerifyInput(BaseModel):
    notes: Optional[str] = None          # ملاحظات التحقق (اختيارية)


class GlobalExporterResponse(BaseModel):
    tax_id: str
    company_name: str
    emails: List[str] = []
    country: Optional[str] = None
    address: Optional[str] = None
    is_verified: bool = False            # يُفعّل لاحقاً من Admin للقناة الخضراء
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ===== Exporter Self-Registration =====
class ExporterSelfRegisterInput(BaseModel):
    """مدخلات تسجيل المصدر الذاتي — Step 1/2 of wizard"""
    company_name: str
    email: str
    phone: str
    country: str                         # بلد الشركة
    address: str
    tax_id: str                          # VAT / رقم الضريبة — المفتاح الفريد
    exporter_type: str                   # "regional" | "global"
    password: str
    # Global-only
    duns_number: Optional[str] = None
    vat_registration: Optional[str] = None
    # Regional-only
    regional_country: Optional[str] = None   # مصر | تونس | الجزائر | المغرب


# ===== Stripe Payments =====
class VerificationCheckoutRequest(BaseModel):
    exporter_tax_id: str
    origin_url: str


class AcidFeeCheckoutRequest(BaseModel):
    acid_id: str
    origin_url: str


class AdminAcidFeeUpdate(BaseModel):
    amount_usd: float
