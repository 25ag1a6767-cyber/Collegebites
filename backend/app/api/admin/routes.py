import hmac
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    client_ip_from_request,
    enforce_canteen_scope,
    get_optional_principal,
    require_roles,
    scoped_canteen_for_principal,
)
from app.core.redis_client import get_redis
from app.models.auth import Permission, Role, RolePermission, StaffProfile, User, UserPermission
from app.models.college import CollegeHoliday, Counter, DiningTable, Kitchen, KitchenStation, PickupLocation
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PickupToken
from app.models.system import AuditLog, SystemEvent
from app.schemas.auth import StaffCreateRequest, UserOut, UserRoleAssignRequest
from app.schemas.order import OrderOut
from app.schemas.college import (
    CanteenCreate,
    CanteenOut,
    CanteenUpdate,
    CollegeSettingsOut,
    CollegeSettingsUpdate,
    CounterCreate,
    CounterOut,
    CounterUpdate,
    DiningTableCreate,
    DiningTableOut,
    DiningTableUpdate,
    HolidayCreate,
    HolidayOut,
    HolidayUpdate,
    KitchenCreate,
    KitchenOut,
    KitchenStationCreate,
    KitchenStationOut,
    KitchenUpdate,
    OperatingHourItem,
    OperatingHourOut,
    PickupLocationCreate,
    PickupLocationOut,
)
from app.schemas.common import AuditLogOut
from app.services import auth_service, college_service, maintenance_service, order_service
from app.services.audit_service import record_audit_log

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


@router.get("/holidays", response_model=list[HolidayOut])
def list_holidays(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    stmt = select(CollegeHoliday).order_by(CollegeHoliday.holiday_date.asc())
    if canteen_id:
        stmt = stmt.where(or_(CollegeHoliday.canteen_id == canteen_id, CollegeHoliday.canteen_id.is_(None)))
    return list(db.scalars(stmt).all())


@router.patch("/holidays/{holiday_id}", response_model=HolidayOut)
def update_holiday(
    holiday_id: UUID,
    payload: HolidayUpdate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return college_service.update_holiday(db, holiday_id, payload, principal.user.id)


@router.delete("/holidays/{holiday_id}")
def delete_holiday(
    holiday_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    hol = db.get(CollegeHoliday, holiday_id)
    if not hol:
        raise HTTPException(status_code=404, detail="Holiday not found")
    hol.is_active = False
    db.commit()
    return {"status": "deactivated", "id": str(holiday_id)}


@router.patch("/counters/{counter_id}", response_model=CounterOut)
def update_counter(
    counter_id: UUID,
    payload: CounterUpdate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    cnt = db.get(Counter, counter_id)
    if not cnt:
        raise HTTPException(status_code=404, detail="Counter not found")
    enforce_canteen_scope(principal, cnt.canteen_id)
    return college_service.update_counter(db, counter_id, payload, principal.user.id)


@router.patch("/kitchens/{kitchen_id}", response_model=KitchenOut)
def update_kitchen(
    kitchen_id: UUID,
    payload: KitchenUpdate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    kit = db.get(Kitchen, kitchen_id)
    if not kit:
        raise HTTPException(status_code=404, detail="Kitchen not found")
    enforce_canteen_scope(principal, kit.canteen_id)
    return college_service.update_kitchen(db, kitchen_id, payload, principal.user.id)


@router.get("/canteens/{canteen_id}/kitchen-stations", response_model=list[KitchenStationOut])
def list_kitchen_stations(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return list(
        db.scalars(
            select(KitchenStation)
            .join(Kitchen, Kitchen.id == KitchenStation.kitchen_id)
            .where(Kitchen.canteen_id == canteen_id)
            .order_by(KitchenStation.name)
        ).all()
    )


@router.post("/kitchens/{kitchen_id}/stations", response_model=KitchenStationOut, status_code=status.HTTP_201_CREATED)
def create_kitchen_station(
    kitchen_id: UUID,
    payload: KitchenStationCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    kit = db.get(Kitchen, kitchen_id)
    if not kit:
        raise HTTPException(status_code=404, detail="Kitchen not found")
    enforce_canteen_scope(principal, kit.canteen_id)
    return college_service.add_kitchen_station(db, kitchen_id, payload, principal.user.id)


@router.get("/canteens/{canteen_id}/pickup-locations", response_model=list[PickupLocationOut])
def list_pickup_locations(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return list(db.scalars(select(PickupLocation).where(PickupLocation.canteen_id == canteen_id).order_by(PickupLocation.name)).all())


@router.post("/canteens/{canteen_id}/pickup-locations", response_model=PickupLocationOut, status_code=status.HTTP_201_CREATED)
def create_pickup_location(
    canteen_id: UUID,
    payload: PickupLocationCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return college_service.add_pickup_location(db, canteen_id, payload, principal.user.id)


@router.patch("/tables/{table_id}", response_model=DiningTableOut)
def update_table(
    table_id: UUID,
    payload: DiningTableUpdate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    tbl = db.get(DiningTable, table_id)
    if not tbl:
        raise HTTPException(status_code=404, detail="Dining table not found")
    enforce_canteen_scope(principal, tbl.canteen_id)
    return college_service.update_dining_table(db, table_id, payload, principal.user.id)


@router.get("/users", response_model=list[UserOut])
def list_users(
    user_kind: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    stmt = select(User).order_by(User.created_at.desc())
    if ROLE_CANTEEN_MANAGER in principal.roles and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        scoped_canteen = scoped_canteen_for_principal(principal, None)
        stmt = stmt.join(StaffProfile, StaffProfile.user_id == User.id).where(
            StaffProfile.assigned_canteen_id == scoped_canteen
        )
    elif user_kind:
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
        if not payload.role_names:
            raise HTTPException(status_code=403, detail="Canteen managers cannot create college admin accounts")
        scoped_cid = scoped_canteen_for_principal(principal, payload.assigned_canteen_id)
        payload.assigned_canteen_id = scoped_cid
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


class UserStatusUpdateIn(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}/status", response_model=UserOut)
def update_user_status(
    user_id: UUID,
    payload: UserStatusUpdateIn,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    if user_id == principal.user.id and not payload.is_active:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own active admin account")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = payload.is_active
    record_audit_log(
        db,
        action="user.status_updated",
        entity_type="user",
        entity_id=str(target.id),
        actor_user_id=principal.user.id,
        ip_address=client_ip_from_request(request),
        details={"is_active": payload.is_active},
    )
    db.commit()
    db.refresh(target)
    return auth_service.build_user_out(db, target)


class UserPermissionsUpdateIn(BaseModel):
    grant: list[str] = []
    revoke: list[str] = []


@router.get("/permissions")
def list_all_permissions(
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    from app.core.permissions import ROLE_PERMISSIONS_MAP

    rows = db.scalars(select(Permission).order_by(Permission.code)).all()
    code_map = {p.code: {"id": str(p.id), "code": p.code, "resource": p.resource, "action": p.action, "description": p.description} for p in rows}
    for plist in ROLE_PERMISSIONS_MAP.values():
        for code in plist:
            if code != "*" and code not in code_map:
                res, act = code.split(":", 1) if ":" in code else (code, "all")
                code_map[code] = {"id": code, "code": code, "resource": res, "action": act, "description": code}
    return sorted(code_map.values(), key=lambda x: x["code"])


@router.get("/roles")
def list_roles_with_permissions(
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    from app.core.permissions import ROLE_PERMISSIONS_MAP

    roles = db.scalars(select(Role).order_by(Role.name)).all()
    out = []
    for r in roles:
        db_codes = set(
            db.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == r.id)
            ).all()
        )
        default_codes = set(ROLE_PERMISSIONS_MAP.get(r.name, []))
        out.append({
            "id": str(r.id),
            "name": r.name,
            "display_name": r.display_name,
            "permissions": sorted(db_codes | default_codes),
        })
    return out


@router.put("/users/{user_id}/permissions", response_model=UserOut)
def update_user_custom_permissions(
    user_id: UUID,
    payload: UserPermissionsUpdateIn,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    old_rows = db.scalars(select(UserPermission).where(UserPermission.user_id == target.id)).all()
    for row in old_rows:
        db.delete(row)
    db.flush()

    def _get_or_create_perm(code: str) -> Permission:
        clean = code.strip()
        p = db.scalar(select(Permission).where(Permission.code == clean))
        if not p:
            res, act = clean.split(":", 1) if ":" in clean else (clean, "all")
            p = Permission(code=clean, resource=res[:64], action=act[:64], description=clean)
            db.add(p)
            db.flush()
        return p

    for code in sorted({c.strip() for c in payload.grant if c.strip()}):
        perm = _get_or_create_perm(code)
        db.add(UserPermission(user_id=target.id, permission_id=perm.id, granted=True))
    for code in sorted({c.strip() for c in payload.revoke if c.strip() and c.strip() not in set(payload.grant)}):
        perm = _get_or_create_perm(code)
        db.add(UserPermission(user_id=target.id, permission_id=perm.id, granted=False))

    record_audit_log(
        db,
        action="user.permissions_updated",
        entity_type="user",
        entity_id=str(target.id),
        actor_user_id=principal.user.id,
        ip_address=client_ip_from_request(request),
        details={"grant": payload.grant, "revoke": payload.revoke},
    )
    db.commit()
    db.refresh(target)
    return auth_service.build_user_out(db, target)


@router.get("/orders", response_model=list[OrderOut])
def list_all_orders(
    canteen_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    payment_status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    scoped_canteen = canteen_id
    if ROLE_CANTEEN_MANAGER in principal.roles and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        enforce_canteen_scope(principal, canteen_id or principal.assigned_canteen_id)
        scoped_canteen = canteen_id or principal.assigned_canteen_id

    stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    if scoped_canteen:
        stmt = stmt.where(Order.canteen_id == scoped_canteen)
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    if payment_status:
        stmt = stmt.where(Order.payment_status == payment_status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.outerjoin(PickupToken, PickupToken.order_id == Order.id).where(
            or_(
                Order.order_number.ilike(like),
                Order.guest_name.ilike(like),
                Order.guest_phone.ilike(like),
                PickupToken.token_code.ilike(like),
            )
        )
    orders = db.scalars(stmt).all()
    return [order_service.serialize_order(db, o) for o in orders]


@router.get("/audit-logs", response_model=list[AuditLogOut])
def get_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: Optional[str] = Query(default=None),
    entity_type: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    return db.scalars(stmt).all()


@router.get("/system-events")
def get_system_events(
    limit: int = Query(default=50, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(limit)).all())


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


@router.post("/maintenance/run")
def run_scheduled_maintenance_endpoint(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Run expired auth/slot cleanup and low-stock alert scan (via Vercel Schedule CRON_SECRET or Admin JWT)."""
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    cron_secret = (settings.CRON_SECRET or "").strip()
    if cron_secret and len(cron_secret) >= 16 and token and hmac.compare_digest(token, cron_secret):
        return maintenance_service.run_scheduled_maintenance(db, trigger="vercel_schedule")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid CRON_SECRET bearer token or Admin session required",
        )

    principal = get_optional_principal(
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
        db=db,
    )
    if not principal or not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Super Admin or College Admin may trigger maintenance",
        )

    return maintenance_service.run_scheduled_maintenance(
        db,
        actor_user_id=principal.user.id,
        trigger="admin_manual",
    )
