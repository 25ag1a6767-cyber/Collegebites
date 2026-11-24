import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import (
    ALL_ROLES,
    ROLE_CUSTOMER,
    load_user_roles_and_permissions,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_otp_code,
    hash_otp,
    hash_password,
    sha256_hex,
    verify_password,
)
from app.integrations.email_provider import deliver_otp_email, resolve_email_otp_provider
from app.integrations.sms_provider import deliver_otp_sms, resolve_sms_otp_provider
from app.models.auth import (
    CustomerProfile,
    OTPVerification,
    RefreshToken,
    Role,
    SessionRecord,
    StaffProfile,
    User,
    UserRole,
)
from app.models.promotion import LoyaltyAccount, LoyaltyTransaction
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    OTPLoginRequest,
    OTPRequest,
    OTPRequestResponse,
    OTPVerifyRequest,
    OTPVerifyResponse,
    PasswordResetConfirmRequest,
    RegisterCustomerRequest,
    StaffCreateRequest,
    TokenResponse,
    UserOut,
    UserRoleAssignRequest,
)
from app.services.audit_service import record_audit_log


def recompute_loyalty_tier(acct: LoyaltyAccount) -> None:
    if acct.lifetime_points >= 1000:
        acct.tier_level = "PLATINUM"
    elif acct.lifetime_points >= 500:
        acct.tier_level = "GOLD"
    elif acct.lifetime_points >= 200:
        acct.tier_level = "SILVER"
    else:
        acct.tier_level = "BRONZE"


def build_user_out(db: Session, user: User) -> UserOut:
    roles, perms, assigned_canteen_id = load_user_roles_and_permissions(db, user.id)
    return UserOut(
        id=user.id,
        email=user.email,
        phone=user.phone,
        full_name=user.full_name,
        user_kind=user.user_kind,
        is_active=user.is_active,
        is_verified=user.is_verified,
        roles=sorted(roles),
        permissions=sorted(perms),
        assigned_canteen_id=assigned_canteen_id,
        created_at=user.created_at,
    )


def _issue_session_tokens(
    db: Session, user: User, device_info: Optional[str] = None, ip_address: Optional[str] = None
) -> TokenResponse:
    now = datetime.now(timezone.utc)
    session_rec = SessionRecord(
        user_id=user.id,
        device_info=device_info,
        ip_address=ip_address,
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session_rec)
    db.flush()

    roles, perms, _ = load_user_roles_and_permissions(db, user.id)
    access_token = create_access_token(
        subject=str(user.id),
        session_id=str(session_rec.id),
        roles=sorted(roles),
        permissions=sorted(perms),
    )
    refresh_jwt, jti, refresh_exp = create_refresh_token(
        subject=str(user.id),
        session_id=str(session_rec.id),
    )
    db.add(
        RefreshToken(
            session_id=session_rec.id,
            user_id=user.id,
            jti=jti,
            token_hash=sha256_hex(refresh_jwt),
            expires_at=refresh_exp,
        )
    )
    user.last_login_at = now
    db.commit()
    db.refresh(user)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_jwt,
        expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=build_user_out(db, user),
    )


def register_customer(
    db: Session, data: RegisterCustomerRequest, ip_address: Optional[str] = None
) -> TokenResponse:
    conditions = []
    if data.email:
        conditions.append(User.email == data.email.lower())
    if data.phone:
        conditions.append(User.phone == data.phone.strip())

    existing = db.scalar(select(User).where(or_(*conditions))) if conditions else None
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email or phone already exists",
        )

    customer_role = db.scalar(select(Role).where(Role.name == ROLE_CUSTOMER))
    if not customer_role:
        raise HTTPException(status_code=500, detail="System roles not initialized")

    pre_verified = False
    if data.otp_verification_token:
        email_ok = bool(
            data.email
            and validate_otp_verification_token(
                db,
                target=str(data.email),
                purpose="register",
                raw_verification_token=data.otp_verification_token,
                consume=True,
            )
        )
        phone_ok = bool(
            not email_ok
            and data.phone
            and validate_otp_verification_token(
                db,
                target=data.phone,
                purpose="register",
                raw_verification_token=data.otp_verification_token,
                consume=True,
            )
        )
        if not (email_ok or phone_ok):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid, expired, or already-used registration OTP verification token",
            )
        pre_verified = True

    user = User(
        email=data.email.lower() if data.email else None,
        phone=data.phone.strip() if data.phone else None,
        full_name=data.full_name.strip(),
        password_hash=hash_password(data.password),
        user_kind="customer",
        is_active=True,
        is_verified=pre_verified,
    )
    db.add(user)
    db.flush()

    db.add(UserRole(user_id=user.id, role_id=customer_role.id))
    db.add(
        CustomerProfile(
            user_id=user.id,
            college_id_number=data.college_id_number,
            department=data.department,
            dietary_preference=data.dietary_preference,
        )
    )
    my_loyalty = LoyaltyAccount(
        user_id=user.id,
        referral_code=f"CB{secrets.token_hex(4).upper()}",
        points_balance=0,
        lifetime_points=0,
    )
    if data.referral_code:
        ref_code = data.referral_code.strip().upper()
        referrer = db.scalar(
            select(LoyaltyAccount).where(LoyaltyAccount.referral_code == ref_code).with_for_update()
        )
        if referrer and referrer.user_id != user.id:
            my_loyalty.referred_by_user_id = referrer.user_id
            my_loyalty.points_balance += 50
            my_loyalty.lifetime_points += 50
            recompute_loyalty_tier(my_loyalty)
            referrer.points_balance += 50
            referrer.lifetime_points += 50
            recompute_loyalty_tier(referrer)
            db.add(my_loyalty)
            db.flush()
            db.add_all([
                LoyaltyTransaction(
                    loyalty_account_id=my_loyalty.id,
                    points_delta=50,
                    transaction_type="referral_bonus",
                    description=f"Welcome referral bonus ({ref_code})",
                ),
                LoyaltyTransaction(
                    loyalty_account_id=referrer.id,
                    points_delta=50,
                    transaction_type="referral_bonus",
                    description=f"Referred {user.full_name}",
                ),
            ])
        else:
            db.add(my_loyalty)
    else:
        db.add(my_loyalty)
    record_audit_log(
        db,
        action="customer.registered",
        entity_type="user",
        entity_id=str(user.id),
        actor_user_id=user.id,
        actor_role=ROLE_CUSTOMER,
        ip_address=ip_address,
        details={"email": user.email, "phone": user.phone},
    )
    return _issue_session_tokens(db, user, ip_address=ip_address)


def login_user(db: Session, data: LoginRequest, ip_address: Optional[str] = None) -> TokenResponse:
    ident = data.identifier.strip()
    digits = "".join(ch for ch in ident if ch.isdigit())
    phone_candidates = {ident}
    if len(digits) == 10:
        phone_candidates.add(digits)
        phone_candidates.add(f"+91{digits}")
        phone_candidates.add(f"91{digits}")
    elif len(digits) == 12 and digits.startswith("91"):
        phone_candidates.add(f"+{digits}")
        phone_candidates.add(digits[-10:])
    user = db.scalar(
        select(User).where(or_(User.email == ident.lower(), User.phone.in_(phone_candidates)))
    )
    pw_ok = bool(
        user
        and user.password_hash
        and (
            verify_password(data.password, user.password_hash)
            or (data.password != data.password.strip() and verify_password(data.password.strip(), user.password_hash))
        )
    )
    if not user or not pw_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    record_audit_log(
        db,
        action="user.login",
        entity_type="user",
        entity_id=str(user.id),
        actor_user_id=user.id,
        actor_role=user.user_kind,
        ip_address=ip_address,
    )
    return _issue_session_tokens(db, user, device_info=data.device_info, ip_address=ip_address)


def refresh_user_session(db: Session, raw_refresh_token: str, ip_address: Optional[str] = None) -> TokenResponse:
    try:
        payload = decode_token(raw_refresh_token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token") from exc

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    token_hash = sha256_hex(raw_refresh_token)
    token_rec = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update())
    if not token_rec:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not recognized")

    now = datetime.now(timezone.utc)
    if token_rec.revoked_at is not None:
        # Refresh token reuse detected -> revoke entire session family
        session_rec = db.get(SessionRecord, token_rec.session_id)
        if session_rec and session_rec.revoked_at is None:
            session_rec.revoked_at = now
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token reuse detected; session revoked")

    if (_as_utc(token_rec.expires_at) or now) <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    session_rec = db.get(SessionRecord, token_rec.session_id)
    user = db.get(User, token_rec.user_id)
    if not session_rec or session_rec.revoked_at is not None or not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalid")

    new_refresh_jwt, new_jti, new_exp = create_refresh_token(subject=str(user.id), session_id=str(session_rec.id))
    token_rec.revoked_at = now
    token_rec.replaced_by_jti = new_jti
    db.add(
        RefreshToken(
            session_id=session_rec.id,
            user_id=user.id,
            jti=new_jti,
            token_hash=sha256_hex(new_refresh_jwt),
            expires_at=new_exp,
        )
    )
    roles, perms, _ = load_user_roles_and_permissions(db, user.id)
    access_token = create_access_token(
        subject=str(user.id),
        session_id=str(session_rec.id),
        roles=sorted(roles),
        permissions=sorted(perms),
    )
    db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_jwt,
        expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=build_user_out(db, user),
    )


def logout_session(db: Session, session_id: UUID, user_id: UUID, ip_address: Optional[str] = None) -> None:
    now = datetime.now(timezone.utc)
    session_rec = db.get(SessionRecord, session_id)
    if session_rec and session_rec.revoked_at is None:
        session_rec.revoked_at = now
    tokens = db.scalars(
        select(RefreshToken).where(RefreshToken.session_id == session_id, RefreshToken.revoked_at.is_(None))
    ).all()
    for t in tokens:
        t.revoked_at = now
    record_audit_log(
        db,
        action="user.logout",
        entity_type="session",
        entity_id=str(session_id),
        actor_user_id=user_id,
        ip_address=ip_address,
    )
    db.commit()
    from app.core.cache import invalidate_auth_session

    invalidate_auth_session(session_id)


_EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _normalize_otp_target(raw_target: str) -> tuple[str, str]:
    clean = (raw_target or "").strip()
    if "@" in clean:
        norm_email = clean.lower()
        if not _EMAIL_RX.match(norm_email):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a valid email address")
        return norm_email, "email"

    digits = "".join(ch for ch in clean if ch.isdigit())
    if len(digits) == 10:
        return f"+91{digits}", "sms"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}", "sms"
    if clean.startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}", "sms"
    if 8 <= len(digits) <= 15:
        return f"+{digits}", "sms"
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a valid email address or mobile number")


def _mask_otp_destination(dest: str) -> str:
    if "@" in dest:
        local, dom = dest.split("@", 1)
        head = local[:2] if len(local) > 2 else local[:1]
        return f"{head}***@{dom}"
    if len(dest) <= 4:
        return "***"
    return f"{'*' * (len(dest) - 4)}{dest[-4:]}"


def _find_user_by_identifier(db: Session, target: str) -> Optional[User]:
    ident = target.strip()
    if "@" in ident:
        return db.scalar(select(User).where(User.email == ident.lower()))
    digits = "".join(ch for ch in ident if ch.isdigit())
    candidates = {ident}
    if len(digits) == 10:
        candidates.update({digits, f"+91{digits}", f"91{digits}"})
    elif len(digits) == 12 and digits.startswith("91"):
        candidates.update({f"+{digits}", digits, digits[-10:]})
    elif digits:
        candidates.update({digits, f"+{digits}"})
    return db.scalar(select(User).where(User.phone.in_(candidates)))


def request_otp(
    db: Session,
    data: OTPRequest,
    *,
    ip_address: Optional[str] = None,
    actor_user_id: Optional[UUID] = None,
) -> OTPRequestResponse:
    norm_target, channel = _normalize_otp_target(data.target)
    now = datetime.now(timezone.utc)
    expiry_secs = settings.effective_otp_expiry_seconds
    cooldown_secs = max(0, int(settings.OTP_RESEND_COOLDOWN_SECONDS))

    matched_user = _find_user_by_identifier(db, norm_target)
    resolved_user_id = actor_user_id or (matched_user.id if matched_user else None)

    if data.purpose in ("login", "password_reset"):
        if not matched_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No registered account found for this email or mobile number",
            )
        if not matched_user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
    elif data.purpose == "register" and matched_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email or mobile number already exists",
        )

    # 1. Enforce resend cooldown on active / recently issued OTP for (target, purpose)
    latest_rec = db.scalar(
        select(OTPVerification)
        .where(OTPVerification.target == norm_target, OTPVerification.purpose == data.purpose)
        .order_by(OTPVerification.created_at.desc())
    )
    if latest_rec and cooldown_secs > 0:
        avail_at = _as_utc(latest_rec.resend_available_at) or (
            (_as_utc(latest_rec.created_at) or now) + timedelta(seconds=cooldown_secs)
        )
        if avail_at > now and latest_rec.verified_at is None:
            wait_secs = max(1, int((avail_at - now).total_seconds() + 0.999))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Please wait {wait_secs}s before requesting another OTP.",
                headers={"Retry-After": str(wait_secs)},
            )

    # 2. Enforce 15-minute sliding window rate limits by destination, IP, and account
    window_since = now - timedelta(minutes=15)
    dest_count = (
        db.scalar(
            select(func.count(OTPVerification.id)).where(
                OTPVerification.target == norm_target,
                OTPVerification.created_at >= window_since,
            )
        )
        or 0
    )
    if dest_count >= settings.OTP_RATE_LIMIT_PER_DEST_15M:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many OTP requests for this destination. Please wait 15 minutes before trying again.",
        )

    if ip_address and ip_address not in ("unknown", ""):
        ip_count = (
            db.scalar(
                select(func.count(OTPVerification.id)).where(
                    OTPVerification.ip_address == ip_address,
                    OTPVerification.created_at >= window_since,
                )
            )
            or 0
        )
        if ip_count >= settings.OTP_RATE_LIMIT_PER_IP_15M:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many OTP requests from this network address. Please try again later.",
            )

    if resolved_user_id:
        user_count = (
            db.scalar(
                select(func.count(OTPVerification.id)).where(
                    OTPVerification.user_id == resolved_user_id,
                    OTPVerification.created_at >= window_since,
                )
            )
            or 0
        )
        if user_count >= settings.OTP_RATE_LIMIT_PER_USER_15M:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many OTP requests for this account. Please try again later.",
            )

    # 3. Verify live provider configuration BEFORE generating or storing an OTP
    if channel == "email":
        active_provider = resolve_email_otp_provider()
        if not active_provider:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Email OTP delivery is temporarily unavailable because no transactional email provider is configured.",
            )
    else:
        active_provider = resolve_sms_otp_provider()
        if not active_provider:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SMS OTP delivery is currently disabled. Please use your email address for verification.",
            )

    # 4. Generate cryptographically secure 6-digit OTP and deliver via real provider
    code = generate_otp_code()
    expiry_mins_display = max(1, round(expiry_secs / 60))
    purpose_label = data.purpose.replace("_", " ")

    if channel == "email":
        subject = "CollegeBites Verification Code (OTP)"
        body = (
            f"Your CollegeBites verification code for {purpose_label} is: {code}\n\n"
            f"This one-time code expires in {expiry_mins_display} minute(s). "
            "Never share this verification code with anyone."
        )
        delivered, provider_detail = deliver_otp_email(norm_target, subject, body)
    else:
        sms_text = (
            f"Your CollegeBites verification code for {purpose_label} is {code}. "
            f"Valid for {expiry_mins_display} min. Do not share."
        )
        delivered, provider_detail = deliver_otp_sms(norm_target, sms_text)

    masked = _mask_otp_destination(norm_target)
    if not delivered:
        record_audit_log(
            db,
            action="otp.delivery_failed",
            entity_type="otp_verification",
            entity_id=masked,
            actor_user_id=resolved_user_id,
            ip_address=ip_address,
            details={"purpose": data.purpose, "channel": channel, "reason": provider_detail},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not deliver verification code via provider. Please verify the address or try again shortly.",
        )

    # 5. Invalidate any previous active unverified OTPs for this (target, purpose)
    prior_unverified = db.scalars(
        select(OTPVerification).where(
            OTPVerification.target == norm_target,
            OTPVerification.purpose == data.purpose,
            OTPVerification.verified_at.is_(None),
            OTPVerification.invalidated_at.is_(None),
        )
    ).all()
    for prev in prior_unverified:
        prev.invalidated_at = now

    otp_rec = OTPVerification(
        user_id=resolved_user_id,
        target=norm_target,
        purpose=data.purpose,
        channel=channel,
        provider=provider_detail,
        ip_address=ip_address,
        otp_hash=hash_otp(norm_target, data.purpose, code),
        attempts=0,
        max_attempts=settings.OTP_MAX_ATTEMPTS,
        resend_available_at=now + timedelta(seconds=cooldown_secs),
        expires_at=now + timedelta(seconds=expiry_secs),
    )
    db.add(otp_rec)
    record_audit_log(
        db,
        action="otp.sent",
        entity_type="otp_verification",
        entity_id=masked,
        actor_user_id=resolved_user_id,
        ip_address=ip_address,
        details={"purpose": data.purpose, "channel": channel, "provider": provider_detail},
    )
    db.commit()

    return OTPRequestResponse(
        message=f"Verification code sent via {channel.upper()} to {masked}",
        expires_in_seconds=expiry_secs,
        resend_cooldown_seconds=cooldown_secs,
        delivery_channel=channel,
        masked_destination=masked,
    )


def verify_otp(
    db: Session,
    data: OTPVerifyRequest,
    *,
    consume_immediately: bool = False,
    actor_user_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
) -> OTPVerifyResponse:
    norm_target, _channel = _normalize_otp_target(data.target)
    now = datetime.now(timezone.utc)
    masked = _mask_otp_destination(norm_target)

    otp_rec = db.scalar(
        select(OTPVerification)
        .where(
            OTPVerification.target == norm_target,
            OTPVerification.purpose == data.purpose,
        )
        .order_by(OTPVerification.created_at.desc())
        .with_for_update()
    )
    if (
        not otp_rec
        or otp_rec.verified_at is not None
        or otp_rec.consumed_at is not None
        or otp_rec.invalidated_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active pending OTP found or code was already used. Please request a new OTP.",
        )

    exp_at = _as_utc(otp_rec.expires_at)
    if exp_at is not None and exp_at <= now:
        otp_rec.invalidated_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP has expired. Please request a new verification code.",
        )

    if otp_rec.attempts >= otp_rec.max_attempts:
        otp_rec.invalidated_at = otp_rec.invalidated_at or now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Maximum OTP verification attempts exceeded. Please request a new code.",
        )

    if otp_rec.user_id and actor_user_id and otp_rec.user_id != actor_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="OTP does not belong to this account")

    otp_rec.attempts += 1
    expected_hash = hash_otp(norm_target, data.purpose, data.code.strip())
    if not hmac.compare_digest(otp_rec.otp_hash, expected_hash):
        exhausted = otp_rec.attempts >= otp_rec.max_attempts
        if exhausted:
            otp_rec.invalidated_at = now
        record_audit_log(
            db,
            action="otp.verify_failed",
            entity_type="otp_verification",
            entity_id=masked,
            actor_user_id=actor_user_id or otp_rec.user_id,
            ip_address=ip_address,
            details={"purpose": data.purpose, "attempts": otp_rec.attempts, "exhausted": exhausted},
        )
        db.commit()
        if exhausted:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Maximum OTP verification attempts exceeded. Code invalidated; please request a new OTP.",
            )
        remaining = max(0, otp_rec.max_attempts - otp_rec.attempts)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid OTP code ({remaining} attempt(s) remaining).",
        )

    otp_rec.verified_at = now
    if actor_user_id and not otp_rec.user_id:
        otp_rec.user_id = actor_user_id

    if consume_immediately:
        otp_rec.consumed_at = now
        otp_rec.verification_token = None
        verification_token = ""
    else:
        verification_token = f"OTPVER.{secrets.token_urlsafe(24)}"
        otp_rec.verification_token = sha256_hex(verification_token)

    record_audit_log(
        db,
        action="otp.verified",
        entity_type="otp_verification",
        entity_id=masked,
        actor_user_id=actor_user_id or otp_rec.user_id,
        ip_address=ip_address,
        details={"purpose": data.purpose, "consumed_immediately": consume_immediately},
    )
    db.commit()

    return OTPVerifyResponse(
        verified=True,
        verification_token=verification_token,
        expires_at=now + timedelta(minutes=30),
    )


def validate_otp_verification_token(
    db: Session,
    *,
    target: str,
    purpose: str,
    raw_verification_token: Optional[str],
    user_id: Optional[UUID] = None,
    consume: bool = False,
) -> bool:
    if not raw_verification_token or not target:
        return False
    try:
        norm_target, _ = _normalize_otp_target(target)
    except HTTPException:
        return False

    token_hash = sha256_hex(raw_verification_token.strip())
    stmt = (
        select(OTPVerification)
        .where(
            OTPVerification.target == norm_target,
            OTPVerification.purpose == purpose,
            OTPVerification.verified_at.is_not(None),
            OTPVerification.consumed_at.is_(None),
            OTPVerification.invalidated_at.is_(None),
        )
        .order_by(OTPVerification.verified_at.desc())
    )
    if consume:
        stmt = stmt.with_for_update()

    rec = db.scalar(stmt)
    if not rec or not rec.verification_token or not rec.verified_at:
        return False
    if not hmac.compare_digest(rec.verification_token, token_hash):
        return False
    if rec.user_id and user_id and rec.user_id != user_id:
        return False

    now = datetime.now(timezone.utc)
    ver_at = _as_utc(rec.verified_at) or now
    if (now - ver_at) > timedelta(minutes=30):
        return False

    if consume:
        rec.consumed_at = now
        rec.verification_token = None
    return True


def validate_guest_otp_token(
    db: Session,
    target: str,
    raw_verification_token: Optional[str],
    *,
    consume: bool = False,
) -> bool:
    return validate_otp_verification_token(
        db,
        target=target,
        purpose="guest_checkout",
        raw_verification_token=raw_verification_token,
        consume=consume,
    )


def login_with_otp(db: Session, data: OTPLoginRequest, ip_address: Optional[str] = None) -> TokenResponse:
    verify_otp(
        db,
        OTPVerifyRequest(target=data.target, purpose="login", code=data.code),
        consume_immediately=True,
        ip_address=ip_address,
    )
    user = _find_user_by_identifier(db, data.target)
    if not user:
        raise HTTPException(status_code=404, detail="No account registered with this email or mobile number")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")
    user.is_verified = True
    record_audit_log(
        db,
        action="user.otp_login",
        entity_type="user",
        entity_id=str(user.id),
        actor_user_id=user.id,
        actor_role=user.user_kind,
        ip_address=ip_address,
    )
    return _issue_session_tokens(db, user, device_info=data.device_info, ip_address=ip_address)


def verify_phone_with_otp(
    db: Session,
    user: User,
    code: str,
    target: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> UserOut:
    phone_target = (target or user.phone or "").strip()
    if not phone_target:
        raise HTTPException(status_code=400, detail="Mobile number is required to verify phone")
    norm_phone, ch = _normalize_otp_target(phone_target)
    if ch != "sms":
        raise HTTPException(status_code=400, detail="Enter a valid mobile number for phone verification")
    verify_otp(
        db,
        OTPVerifyRequest(target=norm_phone, purpose="phone_verify", code=code),
        consume_immediately=True,
        actor_user_id=user.id,
        ip_address=ip_address,
    )
    if norm_phone != user.phone:
        conflict = db.scalar(select(User).where(User.phone.in_({norm_phone, phone_target}), User.id != user.id))
        if conflict:
            raise HTTPException(status_code=409, detail="Mobile number already linked to another account")
        user.phone = norm_phone
    user.is_verified = True
    db.commit()
    db.refresh(user)
    return build_user_out(db, user)


def verify_email_with_otp(
    db: Session,
    user: User,
    code: str,
    target: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> UserOut:
    email_target = (target or user.email or "").strip().lower()
    if not email_target:
        raise HTTPException(status_code=400, detail="Email address is required to verify email")
    norm_email, ch = _normalize_otp_target(email_target)
    if ch != "email":
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    verify_otp(
        db,
        OTPVerifyRequest(target=norm_email, purpose="email_verify", code=code),
        consume_immediately=True,
        actor_user_id=user.id,
        ip_address=ip_address,
    )
    if norm_email != user.email:
        conflict = db.scalar(select(User).where(User.email == norm_email, User.id != user.id))
        if conflict:
            raise HTTPException(status_code=409, detail="Email address already linked to another account")
        user.email = norm_email
    user.is_verified = True
    db.commit()
    db.refresh(user)
    return build_user_out(db, user)


def change_user_password(
    db: Session,
    user: User,
    current_session_id: UUID,
    data: ChangePasswordRequest,
    ip_address: Optional[str] = None,
) -> None:
    if not user.password_hash or not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
    now = datetime.now(timezone.utc)
    other_sessions = db.scalars(
        select(SessionRecord).where(
            SessionRecord.user_id == user.id,
            SessionRecord.id != current_session_id,
            SessionRecord.revoked_at.is_(None),
        )
    ).all()
    for sess in other_sessions:
        sess.revoked_at = now
    for tok in db.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.session_id != current_session_id,
            RefreshToken.revoked_at.is_(None),
        )
    ).all():
        tok.revoked_at = now
    record_audit_log(
        db,
        action="user.password_changed",
        entity_type="user",
        entity_id=str(user.id),
        actor_user_id=user.id,
        ip_address=ip_address,
    )
    db.commit()
    from app.core.cache import invalidate_auth_session, invalidate_auth_user

    invalidate_auth_user(user.id)
    for sess in other_sessions:
        invalidate_auth_session(sess.id)


def confirm_password_reset(db: Session, data: PasswordResetConfirmRequest, ip_address: Optional[str] = None) -> None:
    verify_otp(
        db,
        OTPVerifyRequest(target=data.target, purpose="password_reset", code=data.code),
        consume_immediately=True,
        ip_address=ip_address,
    )
    user = _find_user_by_identifier(db, data.target)
    if not user:
        raise HTTPException(status_code=404, detail="No matching account found")
    user.password_hash = hash_password(data.new_password)
    now = datetime.now(timezone.utc)
    revoked_sessions = db.scalars(
        select(SessionRecord).where(SessionRecord.user_id == user.id, SessionRecord.revoked_at.is_(None))
    ).all()
    for sess in revoked_sessions:
        sess.revoked_at = now
    for tok in db.scalars(
        select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
    ).all():
        tok.revoked_at = now
    record_audit_log(
        db,
        action="user.password_reset",
        entity_type="user",
        entity_id=str(user.id),
        actor_user_id=user.id,
        ip_address=ip_address,
    )
    db.commit()
    from app.core.cache import invalidate_auth_session, invalidate_auth_user

    invalidate_auth_user(user.id)
    for sess in revoked_sessions:
        invalidate_auth_session(sess.id)


def create_staff_user(
    db: Session,
    data: StaffCreateRequest,
    actor_user_id: UUID,
    ip_address: Optional[str] = None,
) -> UserOut:
    for r in data.role_names:
        if r not in ALL_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid role: {r}")

    existing = db.scalar(
        select(User).where(
            or_(User.email == data.email.lower(), User.phone == (data.phone.strip() if data.phone else "__none__"))
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="User with email or phone already exists")

    existing_emp = db.scalar(select(StaffProfile).where(StaffProfile.employee_code == data.employee_code))
    if existing_emp:
        raise HTTPException(status_code=409, detail="Employee code already exists")

    user_kind = "admin" if any(r in {"super_admin", "college_admin"} for r in data.role_names) else "staff"
    user = User(
        email=data.email.lower(),
        phone=data.phone.strip() if data.phone else None,
        full_name=data.full_name.strip(),
        password_hash=hash_password(data.password),
        user_kind=user_kind,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()

    db.add(
        StaffProfile(
            user_id=user.id,
            employee_code=data.employee_code,
            designation=data.designation,
            assigned_canteen_id=data.assigned_canteen_id,
            assigned_counter_id=data.assigned_counter_id,
            assigned_kitchen_id=data.assigned_kitchen_id,
        )
    )
    for role_name in data.role_names:
        role = db.scalar(select(Role).where(Role.name == role_name))
        if role:
            db.add(UserRole(user_id=user.id, role_id=role.id, canteen_id=data.assigned_canteen_id))

    record_audit_log(
        db,
        action="staff.created",
        entity_type="user",
        entity_id=str(user.id),
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        details={"roles": data.role_names, "employee_code": data.employee_code},
    )
    db.commit()
    db.refresh(user)
    return build_user_out(db, user)


def assign_user_roles(
    db: Session,
    target_user_id: UUID,
    data: UserRoleAssignRequest,
    actor_user_id: UUID,
    ip_address: Optional[str] = None,
) -> UserOut:
    user = db.get(User, target_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for r in data.role_names:
        if r not in ALL_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid role: {r}")

    existing_links = db.scalars(select(UserRole).where(UserRole.user_id == user.id)).all()
    for link in existing_links:
        db.delete(link)
    db.flush()

    for role_name in data.role_names:
        role = db.scalar(select(Role).where(Role.name == role_name))
        if role:
            db.add(UserRole(user_id=user.id, role_id=role.id, canteen_id=data.canteen_id))

    revoked_sessions: list[SessionRecord] = []
    if data.is_active is not None:
        user.is_active = data.is_active
        if not data.is_active:
            now = datetime.now(timezone.utc)
            revoked_sessions = list(
                db.scalars(
                    select(SessionRecord).where(SessionRecord.user_id == user.id, SessionRecord.revoked_at.is_(None))
                ).all()
            )
            for sess in revoked_sessions:
                sess.revoked_at = now
            for tok in db.scalars(
                select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            ).all():
                tok.revoked_at = now

    staff_prof = db.scalar(select(StaffProfile).where(StaffProfile.user_id == user.id))
    if staff_prof and data.canteen_id is not None:
        staff_prof.assigned_canteen_id = data.canteen_id

    record_audit_log(
        db,
        action="user.roles_updated",
        entity_type="user",
        entity_id=str(user.id),
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        details={"roles": data.role_names, "canteen_id": str(data.canteen_id) if data.canteen_id else None},
    )
    db.commit()
    from app.core.cache import invalidate_auth_session, invalidate_auth_user

    invalidate_auth_user(user.id)
    for sess in revoked_sessions:
        invalidate_auth_session(sess.id)
    db.refresh(user)
    return build_user_out(db, user)
