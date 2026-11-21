from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    client_ip_from_request,
    enforce_canteen_scope,
    require_roles,
)
from app.core.redis_client import get_redis
from app.models.auth import User
from app.models.order import Order
from app.models.payment import Payment
from app.models.system import AuditLog
from app.schemas.auth import StaffCreateRequest, UserOut, UserRoleAssignRequest
from app.schemas.college import (
    CanteenCreate,
    CanteenOut,
    CanteenUpdate,
    CollegeSettingsOut,
    CollegeSettingsUpdate,
    CounterCreate,
    CounterOut,
    DiningTableCreate,
    DiningTableOut,
    HolidayCreate,
    HolidayOut,
    KitchenCreate,
    KitchenOut,
    OperatingHourItem,
    OperatingHourOut,
)
from app.schemas.common import AuditLogOut
from app.services import auth_service, college_service

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.put("/college", response_model=CollegeSettingsOut)
def update_college(
    payload: CollegeSettingsUpdate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return college_service.update_college_settings(db, payload, principal.user.id, client_ip_from_request(request))


@router.post("/canteens", response_model=CanteenOut, status_code=status.HTTP_201_CREATED)
def create_canteen(
    payload: CanteenCreate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return college_service.create_canteen(db, payload, principal.user.id, client_ip_from_request(request))


@router.patch("/canteens/{canteen_id}", response_model=CanteenOut)
def update_canteen(
    canteen_id: UUID,
    payload: CanteenUpdate,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return college_service.update_canteen(db, canteen_id, payload, principal.user.id, client_ip_from_request(request))


@router.post("/canteens/{canteen_id}/counters", response_model=CounterOut, status_code=status.HTTP_201_CREATED)
def create_counter(
    canteen_id: UUID,
    payload: CounterCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return college_service.add_counter(db, canteen_id, payload, principal.user.id)


@router.post("/canteens/{canteen_id}/kitchens", response_model=KitchenOut, status_code=status.HTTP_201_CREATED)
def create_kitchen(
    canteen_id: UUID,
    payload: KitchenCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return college_service.add_kitchen(db, canteen_id, payload, principal.user.id)


@router.post("/canteens/{canteen_id}/tables", response_model=DiningTableOut, status_code=status.HTTP_201_CREATED)
def create_table(
    canteen_id: UUID,
    payload: DiningTableCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return college_service.add_dining_table(db, canteen_id, payload, principal.user.id)


@router.put("/canteens/{canteen_id}/hours", response_model=list[OperatingHourOut])
def set_operating_hours(
    canteen_id: UUID,
    payload: list[OperatingHourItem],
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return college_service.upsert_operating_hours(db, canteen_id, payload, principal.user.id)


@router.post("/holidays", response_model=HolidayOut, status_code=status.HTTP_201_CREATED)
def create_holiday(
    payload: HolidayCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return college_service.create_holiday(db, payload, principal.user.id)


@router.get("/users", response_model=list[UserOut])
def list_users(
    user_kind: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.created_at.desc())
    if user_kind:
        stmt = stmt.where(User.user_kind == user_kind)
    users = db.scalars(stmt.limit(200)).all()
    return [auth_service.build_user_out(db, u) for u in users]


@router.post("/users/staff", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_staff(
    payload: StaffCreateRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    if ROLE_CANTEEN_MANAGER in principal.roles and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        if any(r in {"super_admin", "college_admin"} for r in payload.role_names):
            payload.role_names = [r for r in payload.role_names if r not in {"super_admin", "college_admin"}]
        enforce_canteen_scope(principal, payload.assigned_canteen_id)
    return auth_service.create_staff_user(db, payload, principal.user.id, client_ip_from_request(request))


@router.patch("/users/{user_id}/roles", response_model=UserOut)
def assign_roles(
    user_id: UUID,
    payload: UserRoleAssignRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return auth_service.assign_user_roles(db, user_id, payload, principal.user.id, client_ip_from_request(request))


@router.get("/audit-logs", response_model=list[AuditLogOut])
def get_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    action: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    return db.scalars(stmt).all()


@router.get("/health")
def system_health(
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    redis_ok = True
    try:
        get_redis().ping()
    except Exception:
        redis_ok = False

    total_orders = db.scalar(select(func.count(Order.id))) or 0
    total_payments = db.scalar(select(func.count(Payment.id))) or 0
    total_users = db.scalar(select(func.count(User.id))) or 0

    return {
        "status": "healthy" if (db_ok and redis_ok) else "degraded",
        "database": "connected" if db_ok else "error",
        "redis": "connected" if redis_ok else "error",
        "total_orders": total_orders,
        "total_payments": total_payments,
        "total_users": total_users,
    }
