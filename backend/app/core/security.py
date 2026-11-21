import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    return pwd_context.verify(plain_password, hashed_password)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hmac_sha256_hex(secret: str, value: str) -> str:
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(target: str, purpose: str, code: str) -> str:
    return hmac_sha256_hex(settings.SECRET_KEY, f"{purpose}:{target}:{code}")


def create_access_token(
    subject: str,
    session_id: str,
    roles: List[str],
    permissions: List[str],
    expires_delta: Optional[timedelta] = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload: Dict[str, Any] = {
        "sub": subject,
        "sid": session_id,
        "roles": roles,
        "perms": permissions,
        "type": "access",
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    subject: str,
    session_id: str,
    jti: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    token_jti = jti or str(uuid4())
    payload: Dict[str, Any] = {
        "sub": subject,
        "sid": session_id,
        "type": "refresh",
        "jti": token_jti,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, token_jti, expire


def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def generate_signed_qr_token() -> tuple[str, str]:
    """Generate a high-entropy HMAC-signed pickup QR token and its storage hash."""
    raw = secrets.token_urlsafe(24)
    sig = hmac_sha256_hex(settings.QR_SIGNING_SECRET, raw)[:24]
    token = f"CBQR.{raw}.{sig}"
    return token, sha256_hex(token)


def verify_signed_qr_token_format(token: str) -> bool:
    """Verify cryptographic signature of an order QR token before database lookup."""
    parts = token.strip().split(".")
    if len(parts) != 3 or parts[0] != "CBQR":
        return False
    raw, sig = parts[1], parts[2]
    if not raw or not sig:
        return False
    expected = hmac_sha256_hex(settings.QR_SIGNING_SECRET, raw)[:24]
    return hmac.compare_digest(sig, expected)


def generate_location_qr_code_slug(prefix: str = "CBLOC") -> str:
    return f"{prefix}-{secrets.token_urlsafe(9)}"


def generate_guest_access_token() -> tuple[str, str]:
    token = f"CBG.{secrets.token_urlsafe(24)}"
    return token, sha256_hex(token)


def mask_mobile(mobile: Optional[str]) -> str:
    if not mobile:
        return "N/A"
    cleaned = "".join(ch for ch in mobile if ch.isdigit())
    if len(cleaned) <= 4:
        return "*" * len(cleaned)
    return ("*" * (len(cleaned) - 4)) + cleaned[-4:]
