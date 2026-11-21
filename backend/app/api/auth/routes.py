from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    AuthenticatedPrincipal,
    client_ip_from_request,
    get_current_principal,
)
from app.schemas.auth import (
    LoginRequest,
    OTPRequest,
    OTPRequestResponse,
    OTPVerifyRequest,
    OTPVerifyResponse,
    RefreshTokenRequest,
    RegisterCustomerRequest,
    TokenResponse,
    UserOut,
)
from app.schemas.common import MessageResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterCustomerRequest, request: Request, db: Session = Depends(get_db)):
    return auth_service.register_customer(db, payload, ip_address=client_ip_from_request(request))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    return auth_service.login_user(db, payload, ip_address=client_ip_from_request(request))


@router.post("/refresh", response_model=TokenResponse)
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


@router.post("/otp/request", response_model=OTPRequestResponse)
def request_otp(payload: OTPRequest, db: Session = Depends(get_db)):
    return auth_service.request_otp(db, payload)


@router.post("/otp/verify", response_model=OTPVerifyResponse)
def verify_otp(payload: OTPVerifyRequest, db: Session = Depends(get_db)):
    return auth_service.verify_otp(db, payload)


@router.get("/me", response_model=UserOut)
def get_me(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return auth_service.build_user_out(db, principal.user)
