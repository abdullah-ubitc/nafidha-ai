"""Authentication utilities: JWT, password hashing, dependency injection"""
import os
import jwt
import bcrypt
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, Request, Depends
from bson import ObjectId
from models import UserRole
from database import db

JWT_ALGORITHM = "HS256"


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "type": "access"
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh"
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def format_user(user: dict) -> dict:
    user["_id"] = str(user["_id"])
    user.pop("password_hash", None)
    user.pop("email_verify_token", None)     # ✅ لا نُرسل التوكن في أي استجابة API
    # حقل صريح لتأكيد البريد — يُستخدم في frontend كـ Guard
    user["is_email_verified"] = bool(user.get("email_verified_at"))
    if "created_at" in user and isinstance(user["created_at"], datetime):
        user["created_at"] = user["created_at"].isoformat()
    if "email_verified_at" in user and isinstance(user.get("email_verified_at"), datetime):
        user["email_verified_at"] = user["email_verified_at"].isoformat()
    # ── Multi-Role Support: ضمان وجود roles array ──────────────────
    if not user.get("roles"):
        user["roles"] = [user["role"]] if user.get("role") else []
    # ── Active Status ────────────────────────────────────────────────
    if "is_active" not in user:
        user["is_active"] = True
    return user


# ── رسائل رفض KYC المركزية ────────────────────────────────────────
_KYC_MESSAGES = {
    "email_unverified": "يُرجى تأكيد بريدك الإلكتروني أولاً قبل استخدام هذه الميزة",
    "pending":          "حسابك قيد مراجعة مأمور التسجيل — يُرجى انتظار قرار الاعتماد",
    "docs_submitted":   "وثائقك قيد المراجعة — يُرجى انتظار قرار الاعتماد",
    "needs_correction": "يُرجى تصحيح وثائقك وإعادة تقديمها قبل استخدام هذه الميزة",
    "rejected":         "تم رفض طلب تسجيلك — يُرجى التواصل مع مصلحة الجمارك",
}

def _kyc_block(status: str):
    """يرفع HTTPException 403 مع رسالة عربية ملائمة."""
    raise HTTPException(
        status_code=403,
        detail={
            "code":    "KYC_NOT_APPROVED",
            "message": _KYC_MESSAGES.get(status, "حسابك غير معتمد بعد")
        }
    )


async def require_approved_user(request: Request):
    """
    Dependency: JWT + فحص KYC للأدوار التجارية.
    يُستخدم في الـ endpoints التي تستخدم Depends(get_current_user) مباشرة.
    """
    from models import KYC_REQUIRED_ROLES
    user = await get_current_user(request)
    if user["role"] in KYC_REQUIRED_ROLES:
        status = user.get("registration_status", "approved")
        if status != "approved":
            _kyc_block(status)
    return user


async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return format_user(user)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_roles(*roles: UserRole):
    """
    فحص الصلاحية + فحص KYC تلقائياً للأدوار التجارية.
    يدعم Multi-Role: يكفي أن يمتلك المستخدم أيٍّ من الأدوار المطلوبة.
    الأدوار الداخلية (admin, officers) تمر بدون قيد KYC.
    """
    async def checker(user=Depends(get_current_user)):
        required = [r.value for r in roles]
        # فحص Multi-Role: roles array أو role مفرد
        user_roles = user.get("roles") or [user.get("role", "")]
        if not any(r in required for r in user_roles):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        # ── فحص KYC للأدوار التجارية ─────────────────────────────
        from models import KYC_REQUIRED_ROLES
        if user["role"] in KYC_REQUIRED_ROLES:
            status = user.get("registration_status", "approved")
            if status != "approved":
                _kyc_block(status)
        return user
    return checker
