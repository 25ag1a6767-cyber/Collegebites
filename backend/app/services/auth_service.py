import hmac
import re
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
    generate_password_reset_token,
    hash_password,
    hash_password_reset_token,
    sha256_hex,
    verify_password,
)
from app.integrations.email_provider import resolve_email_provider, send_password_reset_email
from app.models.auth import (
    CustomerProfile,
    PasswordResetToken,
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
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
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

    user = User(
        email=data.email.lower() if data.email else None,
        phone=data.phone.strip() if data.phone else None,
        full_name=data.full_name.strip(),
        password_hash=hash_password(data.password),
        user_kind="customer",
        is_active=True,
        is_verified=True,
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
        # Refresh token reuse detected -> revoke entire session family & invalidate cache immediately
        session_rec = db.get(SessionRecord, token_rec.session_id)
        if session_rec and session_rec.revoked_at is None:
            session_rec.revoked_at = now
        for sibling in db.scalars(
            select(RefreshToken).where(
                RefreshToken.session_id == token_rec.session_id,
                RefreshToken.revoked_at.is_(None),
            )
        ).all():
            sibling.revoked_at = now
        record_audit_log(
            db,
            action="user.refresh_token_reuse_detected",
            entity_type="session",
            entity_id=str(token_rec.session_id),
            actor_user_id=token_rec.user_id,
            ip_address=ip_address,
        )
        db.commit()
        from app.core.cache import invalidate_auth_session

        invalidate_auth_session(token_rec.session_id)
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


def request_password_reset(
    db: Session,
    data: PasswordResetRequest,
    *,
    ip_address: Optional[str] = None,
) -> PasswordResetRequestResponse:
    """
    Issue a cryptographically secure, single-use non-OTP password reset link via email.
    Always returns a non-enumerating response and never exposes the raw token in API responses or logs.
    """
    expiry_minutes = max(5, int(settings.PASSWORD_RESET_TOKEN_EXPIRY_MINUTES or 30))
    provider = resolve_email_provider()
    now = datetime.now(timezone.utc)
    user = _find_user_by_identifier(db, data.identifier)

    if user and user.is_active and user.email and provider:
        # Invalidate any prior unused tokens for this user
        for prev in db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.invalidated_at.is_(None),
            )
        ).all():
            prev.invalidated_at = now

        raw_token, token_hash = generate_password_reset_token()
        reset_url = f"{settings.public_frontend_url}/reset-password?token={raw_token}"
        delivered, detail = send_password_reset_email(user.email, reset_url, expiry_minutes)
        if delivered:
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=token_hash,
                    ip_address=ip_address,
                    expires_at=now + timedelta(minutes=expiry_minutes),
                )
            )
            record_audit_log(
                db,
                action="user.password_reset_requested",
                entity_type="user",
                entity_id=str(user.id),
                actor_user_id=user.id,
                ip_address=ip_address,
                details={"provider": provider},
            )
            db.commit()
        else:
            record_audit_log(
                db,
                action="user.password_reset_delivery_failed",
                entity_type="user",
                entity_id=str(user.id),
                actor_user_id=user.id,
                ip_address=ip_address,
                details={"reason": detail},
            )
            db.commit()

    return PasswordResetRequestResponse(
        message=(
            "If an active account with a registered email matches this identifier, "
            "a single-use password reset link has been sent."
            if provider
            else "Email delivery is not configured on this server. Contact a campus administrator for password recovery."
        ),
        email_delivery_configured=bool(provider),
        expires_in_minutes=expiry_minutes,
    )


def change_user_password(
    db: Session,
    user: User,
    current_session_id: UUID,
    data: ChangePasswordRequest,
    ip_address: Optional[str] = None,
) -> None:
    if not user.password_hash or not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if data.new_password == data.current_password:
        raise HTTPException(status_code=400, detail="New password must differ from current password")
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
    now = datetime.now(timezone.utc)
    token_hash = hash_password_reset_token(data.token)
    rec = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    )
    if not rec or rec.used_at is not None or rec.invalidated_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already-used password reset token")
    exp_at = _as_utc(rec.expires_at)
    if exp_at is not None and exp_at <= now:
        rec.invalidated_at = now
        db.commit()
        raise HTTPException(status_code=400, detail="Password reset token has expired")

    user = db.get(User, rec.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Account is unavailable or deactivated")

    rec.used_at = now
    user.password_hash = hash_password(data.new_password)
    user.locked_until = None
    user.failed_login_attempts = 0
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
