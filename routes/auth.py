"""Auth routes: register, login, logout, me, refresh, email-verify"""
import os
import time
import secrets
from collections import defaultdict
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Response, Depends
from bson import ObjectId
from datetime import datetime, timezone
from models import UserCreate, UserLogin, INTERNAL_CUSTOMS_ROLES, KYC_REQUIRED_ROLES
from database import db
from auth_utils import (
    hash_password, verify_password, create_access_token,
    create_refresh_token, format_user, get_current_user, JWT_ALGORITHM, get_jwt_secret
)
import jwt

# ── عنوان الواجهة الأمامية من متغيرات البيئة ─────────────────────────────────
_FRONTEND_URL = os.environ.get("FRONTEND_BASE_URL", "https://libya-customs-acis.preview.emergentagent.com")

router = APIRouter(prefix="/auth", tags=["auth"])


# ══════════════════════════════════════════════════════════════════════════════
# مُقيِّد معدل الطلبات (Rate Limiter) — حماية من هجمات Brute-Force/Spam
# ══════════════════════════════════════════════════════════════════════════════
class _RateLimiter:
    """
    مُقيِّد معدل الطلبات في الذاكرة.
    يسمح بـ [limit] طلبات خلال [window_seconds] لكل عنوان IP.
    """
    def __init__(self, limit: int, window_seconds: int):
        self._limit  = limit
        self._window = window_seconds
        self._store: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now    = time.time()
        bucket = [t for t in self._store[key] if now - t < self._window]
        self._store[key] = bucket
        if len(bucket) >= self._limit:
            return False
        self._store[key].append(now)
        return True

    def seconds_until_reset(self, key: str) -> int:
        now    = time.time()
        bucket = [t for t in self._store[key] if now - t < self._window]
        if not bucket:
            return 0
        return max(0, int(self._window - (now - min(bucket))))


# 3 طلبات / ساعة لكل IP على forgot-password
_forgot_pwd_limiter = _RateLimiter(limit=3, window_seconds=3600)

# 5 محاولات / 10 دقائق لكل IP على login — حماية من Brute-Force
_login_limiter = _RateLimiter(limit=5, window_seconds=600)


def _check_stat_expiry(statistical_expiry_date: str | None) -> str:
    """يُرجع 'suspended' إذا كانت البطاقة الإحصائية منتهية، وإلا 'active'"""
    if not statistical_expiry_date:
        return "active"
    today = datetime.now(timezone.utc).date().isoformat()
    return "suspended" if statistical_expiry_date < today else "active"


@router.get("/check-email")
async def check_email(email: str):
    """يتحقق فوريًا إن كان البريد الإلكتروني مسجلًا مسبقًا (يُستخدم في معالجات التسجيل)"""
    email_clean = email.lower().strip()
    in_users     = await db.users.find_one({"email": email_clean}, {"_id": 1})
    in_exporters = await db.global_exporters.find_one({"email": email_clean}, {"_id": 1})
    return {"available": (in_users is None and in_exporters is None)}


@router.post("/register")
async def register(data: UserCreate, response: Response, background_tasks: BackgroundTasks):
    email = data.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="البريد الإلكتروني مسجل مسبقاً")
    user_doc = {
        "email": email,
        "password_hash": hash_password(data.password),
        "role": data.role.value,
        "name_ar": data.name_ar,
        "name_en": data.name_en,
        "entity_type": data.entity_type if data.entity_type else None,
        "company_name_ar": data.company_name_ar,
        "company_name_en": data.company_name_en,
        "commercial_registry_no": data.commercial_registry_no,
        "commercial_registry_expiry": data.commercial_registry_expiry,
        "tax_id_tin": data.tax_id_tin,
        "manager_national_id": data.manager_national_id,
        "phone": data.phone,
        "city": data.city,
        # Registration wizard extended fields
        "delegate_name_ar": data.delegate_name_ar,
        "delegate_name_en": data.delegate_name_en,
        "delegate_national_id": data.delegate_national_id,
        "delegate_phone": data.delegate_phone,
        "delegate_email": data.delegate_email,
        "license_number": data.license_number,
        "license_expiry": data.license_expiry,
        # Phase E — Sovereign Identity
        "statistical_code": data.statistical_code,
        "license_expiry_date": data.license_expiry_date,
        "is_verified": False,
        "is_active": True,
        # ── Phase 2026 — Importer Re-engineering ──────────────────
        "legal_name_ar":          data.legal_name_ar,
        "legal_name_en":          data.legal_name_en,
        "cr_number":              data.cr_number,
        "cr_expiry_date":         data.cr_expiry_date,
        "vat_number":             data.vat_number,
        "address_ar":             data.address_ar,
        "address_en":             data.address_en,
        "statistical_expiry_date":data.statistical_expiry_date,
        "rep_full_name_ar":       data.rep_full_name_ar,
        "rep_full_name_en":       data.rep_full_name_en,
        "rep_id_type":            data.rep_id_type,
        "rep_id_number":          data.rep_id_number,
        "rep_nationality":        data.rep_nationality,
        "rep_job_title":          data.rep_job_title,
        "rep_mobile":             data.rep_mobile,
        # ── Customs Broker Specific Fields ──────────────────────────────────────────
        "broker_type":              data.broker_type,
        "customs_region":           data.customs_region,
        "broker_license_number":    data.broker_license_number,
        "broker_license_expiry":    data.broker_license_expiry,
        "issuing_customs_office":   data.issuing_customs_office,
        # ── Carrier Agent Multi-Modal Fields ──────────────────────────────────────
        "transport_modes":        data.transport_modes,
        "agency_name_ar":         data.agency_name_ar,
        "agency_name_en":         data.agency_name_en,
        "agency_commercial_reg":  data.agency_commercial_reg,
        "marine_license_number":  data.marine_license_number,
        "marine_license_expiry":  data.marine_license_expiry,
        "air_operator_license":   data.air_operator_license,
        "air_license_expiry":     data.air_license_expiry,
        "land_transport_license": data.land_transport_license,
        "land_license_expiry":    data.land_license_expiry,
        # Phase L KYC — الأدوار الداخلية تُفعَّل تلقائياً، التجارية تمر بتحقق البريد ثم KYC
        "registration_status": (
            "approved" if data.role.value in INTERNAL_CUSTOMS_ROLES else "email_unverified"
        ),
        "email_verify_token": (
            None if data.role.value in INTERNAL_CUSTOMS_ROLES else secrets.token_urlsafe(32)
        ),
        # Auto-freeze إذا كانت البطاقة الإحصائية منتهية عند التسجيل
        "account_status": _check_stat_expiry(data.statistical_expiry_date),
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)

    # ── Phase F: Auto-create annual subscription fee for commercial entities ──
    if data.role.value in ["importer", "customs_broker", "carrier_agent"]:
        sub_count = await db.platform_fees.count_documents({"fee_type": "annual_subscription"})
        early_bird = sub_count < 100
        amount = round(500.0 * 0.9, 2) if early_bird else 500.0
        await db.platform_fees.insert_one({
            "payer_id": user_id,                    # string — matches platform_fees.py filter
            "entity_id": user_id,                    # string — for cross-reference
            "fee_type": "annual_subscription",
            "amount_lyd": amount,
            "early_bird_discount": early_bird,
            "description": f"اشتراك سنوي في منصة نافذة {'— خصم 10% للمبكرين (أول 100 كيان)' if early_bird else ''}",
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "due_date": (datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1)).isoformat(),
        })
        # Auto-create wallet for new entity
        wallet_exists = await db.wallets.find_one({"entity_id": user_id})
        if not wallet_exists:
            await db.wallets.insert_one({
                "entity_id": user_id,
                "balance_lyd": 0.0,
                "total_topup": 0.0,
                "total_spent": 0.0,
                "transactions": [],
                "created_at": datetime.now(timezone.utc),
            })
    access_token = create_access_token(user_id, email, data.role.value)
    refresh_token = create_refresh_token(user_id)
    response.set_cookie("access_token", access_token, httponly=True, secure=False, samesite="lax", max_age=86400, path="/")
    response.set_cookie("refresh_token", refresh_token, httponly=True, secure=False, samesite="lax", max_age=604800, path="/")
    user_doc["_id"] = user_id
    user_doc.pop("password_hash")
    user_doc["created_at"] = user_doc["created_at"].isoformat()

    # ── إضافة البريد الإلكتروني لقائمة التاريخ ──────────────────
    await db.users.update_one(
        {"_id": result.inserted_id},
        {"$push": {"status_history": {
            "action":     "registered",
            "actor_name": user_doc.get("name_ar") or user_doc.get("name_en") or email,
            "actor_role": data.role.value,
            "timestamp":  user_doc["created_at"],
            "details":    {},
        }}}
    )

    # ── إرسال إيميل تأكيد البريد للأدوار التجارية ───────────
    verify_token = user_doc.pop("email_verify_token", None)   # ✅ إخفاء التوكن عن الاستجابة
    if data.role.value not in INTERNAL_CUSTOMS_ROLES and verify_token:
        frontend = _FRONTEND_URL
        verify_url = f"{frontend}/verify-email/{verify_token}"
        background_tasks.add_task(
            _send_verify_email,
            email=email,
            name=data.name_ar or data.name_en or email,
            verify_url=verify_url,
        )
    return {"user": format_user(user_doc), "access_token": access_token}


@router.post("/login")
async def login(request: Request, data: UserLogin, response: Response):
    # ── Rate Limiting — حماية من هجمات Brute-Force ──────────────
    # نستخدم X-Forwarded-For أولاً (يُضبط من K8s/Nginx proxy) للحصول على IP الحقيقي
    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    if not _login_limiter.is_allowed(client_ip):
        wait_secs = _login_limiter.seconds_until_reset(client_ip)
        wait_mins = max(1, (wait_secs + 59) // 60)
        raise HTTPException(
            status_code=429,
            detail=f"تجاوزت الحد المسموح به من محاولات تسجيل الدخول (5 محاولات/10 دقائق). يُرجى الانتظار {wait_mins} دقيقة."
        )
    email = data.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(data.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="بريد إلكتروني أو كلمة مرور غير صحيحة")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="الحساب موقوف")
    # Phase L KYC — فقط البريد غير الموثَّق وحسابات الرفض تُمنع من الدخول
    # pending و needs_correction مسموح لهم بالدخول — الـ ProtectedRoute يُوجِّههم لـ /kyc-pending
    reg_status = user.get("registration_status", "approved")
    if reg_status == "rejected":
        reason = user.get("rejection_reason", "لم يُذكر سبب")
        raise HTTPException(
            status_code=403,
            detail={"code": "KYC_REJECTED", "message": f"تم رفض طلب تسجيلك: {reason}"}
        )
    user_id = str(user["_id"])
    access_token = create_access_token(user_id, email, user["role"])
    refresh_token = create_refresh_token(user_id)
    response.set_cookie("access_token", access_token, httponly=True, secure=False, samesite="lax", max_age=86400, path="/")
    response.set_cookie("refresh_token", refresh_token, httponly=True, secure=False, samesite="lax", max_age=604800, path="/")
    return {"user": format_user(user), "access_token": access_token}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"message": "Logged out successfully"}


@router.get("/me")
async def get_me(current_user=Depends(get_current_user)):
    return current_user


@router.post("/refresh")
async def refresh_token_route(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user_id = str(user["_id"])
        new_token = create_access_token(user_id, user["email"], user["role"])
        response.set_cookie("access_token", new_token, httponly=True, secure=False, samesite="lax", max_age=86400, path="/")
        return {"access_token": new_token}
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ══════════════════════════════════════════════════════════════
# Email Verification Endpoints
# ══════════════════════════════════════════════════════════════


async def _send_verify_email(email: str, name: str, verify_url: str):
    """إرسال إيميل التحقق في background task."""
    try:
        from services.email_service import send_event_email
        await send_event_email("email_verification", email, {"name": name, "verify_url": verify_url})
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(f"[VERIFY EMAIL] {exc}")


@router.get("/verify-email/{token}")
async def verify_email(token: str, response: Response):
    """
    تأكيد البريد الإلكتروني — يُحوِّل الحالة من email_unverified إلى pending.
    يُستدعى من رابط في الإيميل الذي يُرسَل عند التسجيل.
    
    السلوك:
    - أول ضغطة: يُحوِّل الحالة → pending ويضع email_verified_at + يضبط access_token cookie
    - ضغطة ثانية بنفس التوكن: يُرجع already_verified=True بدلاً من خطأ
    - توكن مجهول تماماً: يُرجع 400 INVALID_TOKEN
    """
    user = await db.users.find_one({"email_verify_token": token})
    if not user:
        raise HTTPException(400, detail={"code": "INVALID_TOKEN", "message": "رابط التحقق غير صالح أو منتهي الصلاحية"})
    # ── الحالة: تم التحقق مسبقاً (ضغطة ثانية على نفس الرابط أو حالة غير قابلة للتحقق) ──
    # القبول: email_unverified أو docs_submitted بدون email_verified_at (حالة legacy)
    is_unverified = (
        user.get("registration_status") == "email_unverified"
        or (user.get("registration_status") == "docs_submitted" and not user.get("email_verified_at"))
    )
    if not is_unverified:
        # مستخدم موثَّق مسبقاً — نضبط الـ cookie لتفعيل الجلسة التلقائية أيضاً
        user_id = str(user["_id"])
        access_token = create_access_token(user_id, user["email"], user["role"])
        refresh_token = create_refresh_token(user_id)
        response.set_cookie("access_token", access_token, httponly=True, secure=False, samesite="lax", max_age=86400, path="/")
        response.set_cookie("refresh_token", refresh_token, httponly=True, secure=False, samesite="lax", max_age=604800, path="/")
        return {"message": "تم تأكيد بريدك الإلكتروني مسبقاً — طلبك الآن قيد مراجعة مأمور التسجيل", "already_verified": True}
    # ── الحالة: تحقق جديد — تحديث الحالة إلى pending ──
    now = datetime.now(timezone.utc).isoformat()
    await db.users.update_one(
        {"email_verify_token": token},
        {"$set": {
            "registration_status": "pending",
            "email_verified_at":   now,
            # ملاحظة: نُبقي email_verify_token في DB لإتاحة already_verified على الضغطات اللاحقة
        }, "$push": {"status_history": {
            "action":     "email_verified",
            "actor_name": user.get("name_ar") or user.get("email", ""),
            "actor_role": user.get("role", ""),
            "timestamp":  now,
            "details":    {},
        }}}
    )
    # ── ضبط الـ cookies لإتاحة Auto-Login بعد التحقق (يعمل حتى من متصفح مختلف) ──
    user_id = str(user["_id"])
    access_token = create_access_token(user_id, user["email"], user["role"])
    refresh_token = create_refresh_token(user_id)
    response.set_cookie("access_token", access_token, httponly=True, secure=False, samesite="lax", max_age=86400, path="/")
    response.set_cookie("refresh_token", refresh_token, httponly=True, secure=False, samesite="lax", max_age=604800, path="/")
    return {"message": "تم تأكيد بريدك الإلكتروني بنجاح — طلبك الآن قيد مراجعة مأمور التسجيل", "verified": True}


@router.post("/resend-verification")
async def resend_verification(
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
):
    """إعادة إرسال إيميل التحقق للمستخدمين في حالة email_unverified."""
    if current_user.get("registration_status") != "email_unverified":
        raise HTTPException(400, "حسابك لا يحتاج إعادة إرسال رابط التحقق")
    # إنشاء توكن جديد
    new_token = secrets.token_urlsafe(32)
    await db.users.update_one(
        {"_id": ObjectId(current_user["_id"])},
        {"$set": {"email_verify_token": new_token}}
    )
    frontend  = _FRONTEND_URL
    verify_url = f"{frontend}/verify-email/{new_token}"
    background_tasks.add_task(
        _send_verify_email,
        email=current_user["email"],
        name=current_user.get("name_ar", current_user.get("name_en", "")),
        verify_url=verify_url,
    )
    return {"message": "تم إرسال رابط التحقق من جديد — تحقق من صندوق الوارد"}


# ══════════════════════════════════════════════════════════════════════════════
# Password Reset — إعادة تعيين كلمة المرور
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/forgot-password")
async def forgot_password(request: Request, background_tasks: BackgroundTasks):
    """
    طلب إعادة تعيين كلمة المرور — يُرسل رابطاً آمناً للبريد المُسجَّل.
    لا يكشف إن كان البريد مُسجَّلاً أم لا (حماية خصوصية).
    Rate limit: 3 طلبات/ساعة لكل IP.
    """
    # ── Rate Limiting ──
    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    if not _forgot_pwd_limiter.is_allowed(client_ip):
        wait_secs = _forgot_pwd_limiter.seconds_until_reset(client_ip)
        wait_mins = max(1, (wait_secs + 59) // 60)
        raise HTTPException(
            status_code=429,
            detail=f"تجاوزت الحد المسموح به من الطلبات (3 محاولات/ساعة). يُرجى الانتظار {wait_mins} دقيقة قبل المحاولة مجدداً."
        )

    body = await request.json()
    email = (body.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(400, detail="البريد الإلكتروني مطلوب")

    user = await db.users.find_one({"email": email})
    # نُرجع نجاح دائماً حتى لا يُكشف إن كان البريد مُسجَّلاً
    if user:
        reset_token  = secrets.token_urlsafe(32)
        now          = datetime.now(timezone.utc)
        expires_at   = (now.timestamp() + 3600)  # ساعة واحدة
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "reset_password_token":   reset_token,
                "reset_password_expires": expires_at,
            }}
        )
        frontend   = _FRONTEND_URL
        reset_url  = f"{frontend}/reset-password/{reset_token}"
        name       = user.get("name_ar") or user.get("name_en") or email
        background_tasks.add_task(_send_reset_email, email, name, reset_url)

    return {"message": "إذا كان البريد مُسجَّلاً، ستصلك رسالة خلال دقائق — تحقق من صندوق الوارد"}


@router.post("/reset-password")
async def reset_password(request: Request):
    """
    تعيين كلمة مرور جديدة باستخدام الرمز المُرسَل بالبريد.
    """
    body        = await request.json()
    token       = (body.get("token") or "").strip()
    new_password = (body.get("new_password") or "").strip()

    if not token:
        raise HTTPException(400, detail="الرمز مطلوب")
    if len(new_password) < 8:
        raise HTTPException(400, detail="كلمة المرور يجب أن تكون 8 أحرف على الأقل")

    user = await db.users.find_one({"reset_password_token": token})
    if not user:
        raise HTTPException(400, detail={"code": "INVALID_RESET_TOKEN", "message": "رابط إعادة التعيين غير صالح أو منتهي الصلاحية"})

    # التحقق من انتهاء الصلاحية
    expires_at = user.get("reset_password_expires", 0)
    if datetime.now(timezone.utc).timestamp() > expires_at:
        raise HTTPException(400, detail={"code": "RESET_TOKEN_EXPIRED", "message": "انتهت صلاحية الرابط — يُرجى طلب رابط جديد"})

    new_hash = hash_password(new_password)
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": new_hash}, "$unset": {"reset_password_token": "", "reset_password_expires": ""}}
    )
    return {"message": "تم تغيير كلمة المرور بنجاح — يمكنك تسجيل الدخول الآن"}


async def _send_reset_email(email: str, name: str, reset_url: str):
    """إرسال إيميل إعادة التعيين في background task."""
    try:
        from services.email_service import send_event_email
        await send_event_email("password_reset", email, {"name": name, "reset_url": reset_url})
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(f"[RESET EMAIL] {exc}")
