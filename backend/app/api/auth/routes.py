from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.permissions import (
    AuthenticatedPrincipal,
    client_ip_from_request,
    get_current_principal,
)
from app.models.auth import SessionRecord
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RefreshTokenRequest,
    RegisterCustomerRequest,
    TokenResponse,
    UserOut,
)
from app.schemas.common import MessageResponse
from app.services import auth_service, security_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def register(payload: RegisterCustomerRequest, request: Request, db: Session = Depends(get_db)):
    return auth_service.register_customer(db, payload, ip_address=client_ip_from_request(request))


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH_LOGIN)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = client_ip_from_request(request)
    ua = request.headers.get("user-agent")
    security_service.assert_login_allowed(db, payload.identifier, ip_address=ip, user_agent=ua)
    try:
        res = auth_service.login_user(db, payload, ip_address=ip)
    except HTTPException as exc:
        security_service.record_login_failure(
            db,
            payload.identifier,
            ip_address=ip,
            user_agent=ua,
            reason=str(exc.detail),
        )
        raise
    security_service.record_login_success(
        db,
        res.user.id,
        payload.identifier,
        ip_address=ip,
        user_agent=ua,
    )
    return res


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
def refresh(payload: RefreshTokenRequest, request: Request, db: Session = Depends(get_db)):
    return auth_service.refresh_user_session(db, payload.refresh_token, ip_address=client_ip_from_request(request))


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    auth_service.logout_session(db, principal.session_id, principal.user.id, ip_address=client_ip_from_request(request))
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserOut)
def get_me(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return auth_service.build_user_out(db, principal.user)


@router.post("/change-password", response_model=MessageResponse)
@limiter.limit("10/minute")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    auth_service.change_user_password(
        db, principal.user, principal.session_id, payload, ip_address=client_ip_from_request(request)
    )
    return MessageResponse(message="Password updated successfully")


@router.post("/password-reset/request", response_model=PasswordResetRequestResponse)
@limiter.limit("5/minute")
def password_reset_request(payload: PasswordResetRequest, request: Request, db: Session = Depends(get_db)):
    return auth_service.request_password_reset(db, payload, ip_address=client_ip_from_request(request))


@router.post("/password-reset/confirm", response_model=MessageResponse)
@limiter.limit("8/minute")
def password_reset_confirm(payload: PasswordResetConfirmRequest, request: Request, db: Session = Depends(get_db)):
    auth_service.confirm_password_reset(db, payload, ip_address=client_ip_from_request(request))
    return MessageResponse(message="Password reset successfully")


@router.get("/sessions")
def list_sessions(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(SessionRecord)
        .where(SessionRecord.user_id == principal.user.id, SessionRecord.revoked_at.is_(None))
        .order_by(SessionRecord.created_at.desc())
        .limit(20)
    ).all()
    return [
        {
            "id": str(s.id),
            "device_info": s.device_info,
            "ip_address": s.ip_address,
            "created_at": s.created_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
            "is_current": s.id == principal.session_id,
        }
        for s in rows
    ]


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
def revoke_session(
    session_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    sess = db.get(SessionRecord, session_id)
    if not sess or sess.user_id != principal.user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    auth_service.logout_session(db, session_id, principal.user.id, ip_address=client_ip_from_request(request))
    return MessageResponse(message="Session revoked")
