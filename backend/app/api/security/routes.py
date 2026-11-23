from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    client_ip_from_request,
    require_roles,
    scoped_canteen_for_principal,
)
from app.services import security_service

router = APIRouter(prefix="/security", tags=["Security & Fraud Detection"])


class AlertResolveIn(BaseModel):
    status: str = Field(default="resolved", pattern="^(acknowledged|resolved|dismissed)$")
    notes: Optional[str] = Field(default=None, max_length=500)


@router.get("/dashboard")
def get_security_dashboard(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    eff_canteen = scoped_canteen_for_principal(principal, canteen_id)
    return security_service.list_security_dashboard(db, canteen_id=eff_canteen)


@router.get("/alerts")
def list_alerts(
    canteen_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    alert_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    eff_canteen = scoped_canteen_for_principal(principal, canteen_id)
    return security_service.list_security_alerts(
        db,
        canteen_id=eff_canteen,
        status_filter=status_filter,
        severity=severity,
        alert_type=alert_type,
        limit=limit,
        offset=offset,
    )


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: UUID,
    payload: AlertResolveIn,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    scoped_canteen = None if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) else principal.assigned_canteen_id
    return security_service.resolve_security_alert(
        db,
        alert_id,
        status_value=payload.status,
        notes=payload.notes,
        actor_user_id=principal.user.id,
        scoped_canteen_id=scoped_canteen,
        ip_address=client_ip_from_request(request),
    )


@router.post("/users/{user_id}/unlock")
def unlock_user(
    user_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    user = security_service.unlock_user_account(
        db,
        user_id,
        actor_user_id=principal.user.id,
        ip_address=client_ip_from_request(request),
    )
    return {
        "unlocked": True,
        "user_id": str(user.id),
        "email": user.email,
        "failed_login_attempts": user.failed_login_attempts,
        "locked_until": user.locked_until,
    }


@router.get("/login-attempts")
def list_login_attempts(
    identifier: Optional[str] = Query(default=None),
    success: Optional[bool] = Query(default=None),
    ip_address: Optional[str] = Query(default=None),
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return security_service.list_login_attempts(
        db,
        identifier=identifier,
        success=success,
        ip_address=ip_address,
        limit=limit,
        offset=offset,
    )


@router.get("/qr-events")
def list_qr_events(
    canteen_id: Optional[UUID] = Query(default=None),
    is_valid: Optional[bool] = Query(default=None),
    result_code: Optional[str] = Query(default=None),
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    eff_canteen = scoped_canteen_for_principal(principal, canteen_id)
    return security_service.list_qr_verification_events(
        db,
        canteen_id=eff_canteen,
        is_valid=is_valid,
        result_code=result_code,
        limit=limit,
        offset=offset,
    )


@router.get("/audit-logs")
def search_audit_logs(
    action: Optional[str] = Query(default=None),
    entity_type: Optional[str] = Query(default=None),
    ip_address: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    actor_user_id: Optional[UUID] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient privileges")
    return security_service.search_audit_logs(
        db,
        action=action,
        entity_type=entity_type,
        ip_address=ip_address,
        search=search,
        actor_user_id=actor_user_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
