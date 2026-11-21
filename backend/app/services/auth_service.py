import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from sqlalchemy import or_, select
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
from app.models.promotion import LoyaltyAccount
from app.schemas.auth import (
    LoginRequest,
    OTPRequest,
    OTPRequestResponse,
    OTPVerifyRequest,
    OTPVerifyResponse,
    RegisterCustomerRequest,
    StaffCreateRequest,
    TokenResponse,
    UserOut,
    UserRoleAssignRequest,
)
from app.services.audit_service import record_audit_log


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

    user = User(
        email=data.email.lower() if data.email else None,
        phone=data.phone.strip() if data.phone else None,
        full_name=data.full_name.strip(),
        password_hash=hash_password(data.password),
        user_kind="customer",
        is_active=True,
        is_verified=False,
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
    db.add(
        LoyaltyAccount(
            user_id=user.id,
            referral_code=f"CB{secrets.token_hex(4).upper()}",
        )
    )
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
    user = db.scalar(select(User).where(or_(User.email == ident.lower(), User.phone == ident)))
    if not user or not user.password_hash or not verify_password(data.password, user.password_hash):
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
    token_rec = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
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

    if token_rec.expires_at <= now:
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


def request_otp(db: Session, data: OTPRequest) -> OTPRequestResponse:
    code = generate_otp_code()
    target = data.target.strip()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)

    otp_rec = OTPVerification(
        target=target,
        purpose=data.purpose,
        otp_hash=hash_otp(target, data.purpose, code),
        attempts=0,
        max_attempts=settings.OTP_MAX_ATTEMPTS,
        expires_at=expires_at,
    )
    db.add(otp_rec)
    db.commit()

    return OTPRequestResponse(
        message="Verification code generated",
        expires_in_seconds=settings.OTP_EXPIRY_MINUTES * 60,
        dev_otp=code if (not settings.is_production and settings.OTP_TEST_ECHO) else None,
    )


def verify_otp(db: Session, data: OTPVerifyRequest) -> OTPVerifyResponse:
    target = data.target.strip()
    now = datetime.now(timezone.utc)
    otp_rec = db.scalar(
        select(OTPVerification)
        .where(
            OTPVerification.target == target,
            OTPVerification.purpose == data.purpose,
            OTPVerification.verified_at.is_(None),
        )
        .order_by(OTPVerification.created_at.desc())
    )
    if not otp_rec:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending OTP request found")

    if otp_rec.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP has expired")

    if otp_rec.attempts >= otp_rec.max_attempts:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Maximum OTP attempts exceeded")

    otp_rec.attempts += 1
    expected_hash = hash_otp(target, data.purpose, data.code.strip())
    if otp_rec.otp_hash != expected_hash:
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP code")

    verification_token = f"OTPVER.{secrets.token_urlsafe(24)}"
    otp_rec.verified_at = now
    otp_rec.verification_token = sha256_hex(verification_token)
    db.commit()

    return OTPVerifyResponse(
        verified=True,
        verification_token=verification_token,
        expires_at=now + timedelta(minutes=30),
    )


def validate_guest_otp_token(db: Session, target: str, raw_verification_token: Optional[str]) -> bool:
    if not raw_verification_token:
        return False
    token_hash = sha256_hex(raw_verification_token.strip())
    rec = db.scalar(
        select(OTPVerification).where(
            OTPVerification.target == target.strip(),
            OTPVerification.purpose == "guest_checkout",
            OTPVerification.verification_token == token_hash,
            OTPVerification.verified_at.is_not(None),
        )
    )
    if not rec or not rec.verified_at:
        return False
    return (datetime.now(timezone.utc) - rec.verified_at) <= timedelta(minutes=30)


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

    if data.is_active is not None:
        user.is_active = data.is_active

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
    db.refresh(user)
    return build_user_out(db, user)
