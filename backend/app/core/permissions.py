from dataclasses import dataclass
from typing import Iterable, Optional
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token
from app.models.auth import Role, RolePermission, Permission, SessionRecord, StaffProfile, User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

# Role constants matching Section 3
ROLE_SUPER_ADMIN = "super_admin"
ROLE_COLLEGE_ADMIN = "college_admin"
ROLE_CANTEEN_MANAGER = "canteen_manager"
ROLE_CASHIER = "cashier"
ROLE_KITCHEN_STAFF = "kitchen_staff"
ROLE_INVENTORY_MANAGER = "inventory_manager"
ROLE_PICKUP_STAFF = "pickup_staff"
ROLE_CUSTOMER = "customer"

ALL_ROLES = [
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
    ROLE_PICKUP_STAFF,
    ROLE_CUSTOMER,
]

ROLE_PERMISSIONS_MAP: dict[str, list[str]] = {
    ROLE_SUPER_ADMIN: ["*"],
    ROLE_COLLEGE_ADMIN: [
        "college:manage",
        "canteen:manage",
        "menu:manage",
        "staff:manage",
        "customer:manage",
        "order:view_all",
        "order:manage",
        "payment:view",
        "payment:reconcile",
        "inventory:manage",
        "qr:manage",
        "queue:manage",
        "notification:manage",
        "announcement:manage",
        "promotion:manage",
        "report:view",
        "support:manage",
        "kiosk:manage",
        "audit:view",
        "qr:website_manage",
    ],
    ROLE_CANTEEN_MANAGER: [
        "canteen:manage_assigned",
        "menu:manage",
        "order:view_canteen",
        "order:manage",
        "kitchen:manage",
        "staff:manage_canteen",
        "inventory:manage",
        "queue:manage",
        "report:view_canteen",
        "support:view",
        "qr:manage",
    ],
    ROLE_CASHIER: [
        "pos:use",
        "order:create_walkin",
        "order:view_canteen",
        "payment:accept_counter",
        "receipt:print",
        "receipt:reprint",
        "pickup:verify",
        "pickup:handover",
        "shift:manage_own",
    ],
    ROLE_KITCHEN_STAFF: [
        "kitchen:view",
        "kitchen:update_order",
        "kitchen:report_delay",
        "kitchen:report_unavailable",
    ],
    ROLE_INVENTORY_MANAGER: [
        "inventory:manage",
        "supplier:manage",
        "purchase_order:manage",
        "wastage:record",
    ],
    ROLE_PICKUP_STAFF: [
        "pickup:verify",
        "pickup:handover",
        "order:view_canteen",
    ],
    ROLE_CUSTOMER: [
        "order:create",
        "order:view_own",
        "receipt:view_own",
        "review:create",
        "support:create_own",
        "profile:manage_own",
    ],
}


@dataclass
class AuthenticatedPrincipal:
    user: User
    session_id: UUID
    roles: set[str]
    permissions: set[str]
    assigned_canteen_id: Optional[UUID]

    def has_role(self, *role_names: str) -> bool:
        return bool(self.roles.intersection(role_names))

    def has_permission(self, permission: str) -> bool:
        if "*" in self.permissions or ROLE_SUPER_ADMIN in self.roles:
            return True
        return permission in self.permissions


def load_user_roles_and_permissions(db: Session, user_id: UUID) -> tuple[set[str], set[str], Optional[UUID]]:
    role_rows = db.execute(
        select(Role.name, Role.id, UserRole.canteen_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    ).all()
    roles = {row[0] for row in role_rows}
    assigned_canteen_id = next((row[2] for row in role_rows if row[2] is not None), None)

    if assigned_canteen_id is None:
        staff_prof = db.scalar(select(StaffProfile).where(StaffProfile.user_id == user_id))
        if staff_prof:
            assigned_canteen_id = staff_prof.assigned_canteen_id

    if ROLE_SUPER_ADMIN in roles:
        return roles, {"*"}, assigned_canteen_id

    role_ids = [row[1] for row in role_rows]
    perms: set[str] = set()
    if role_ids:
        perm_rows = db.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id.in_(role_ids))
        ).all()
        perms.update(perm_rows)

    for r in roles:
        perms.update(ROLE_PERMISSIONS_MAP.get(r, []))
    return roles, perms, assigned_canteen_id


def get_optional_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[AuthenticatedPrincipal]:
    if not credentials or not credentials.credentials:
        return None
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token") from exc

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    try:
        user_id = UUID(payload["sub"])
        session_id = UUID(payload["sid"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token claims") from exc

    session_rec = db.get(SessionRecord, session_id)
    if not session_rec or session_rec.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account inactive or missing")

    roles, permissions, assigned_canteen_id = load_user_roles_and_permissions(db, user.id)
    return AuthenticatedPrincipal(
        user=user,
        session_id=session_id,
        roles=roles,
        permissions=permissions,
        assigned_canteen_id=assigned_canteen_id,
    )


def get_current_principal(
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
) -> AuthenticatedPrincipal:
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return principal


def require_roles(*allowed_roles: str):
    def dependency(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
        if ROLE_SUPER_ADMIN in principal.roles or principal.has_role(*allowed_roles):
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires one of roles: {', '.join(allowed_roles)}",
        )

    return dependency


def require_role_or_permission(allowed_roles: Iterable[str], *required_permissions: str):
    allowed = tuple(allowed_roles)

    def dependency(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
        if ROLE_SUPER_ADMIN in principal.roles or "*" in principal.permissions:
            return principal
        if principal.has_role(*allowed) or any(principal.has_permission(p) for p in required_permissions):
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires permission ({', '.join(required_permissions)}) or role ({', '.join(allowed)})",
        )

    return dependency


def require_permissions(*required_permissions: str):
    def dependency(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
        if "*" in principal.permissions or ROLE_SUPER_ADMIN in principal.roles:
            return principal
        if any(principal.has_permission(p) for p in required_permissions):
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {', '.join(required_permissions)}",
        )

    return dependency


def enforce_canteen_scope(principal: AuthenticatedPrincipal, canteen_id: Optional[UUID]) -> None:
    if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return
    if not principal.assigned_canteen_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff user has no assigned canteen",
        )
    if canteen_id and principal.assigned_canteen_id != canteen_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff user is not authorized for this canteen",
        )


def scoped_canteen_for_principal(principal: AuthenticatedPrincipal, requested_canteen_id: Optional[UUID]) -> Optional[UUID]:
    """Resolve effective canteen filter, locking non-college-admin staff to their assigned canteen."""
    if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return requested_canteen_id
    enforce_canteen_scope(principal, requested_canteen_id)
    return principal.assigned_canteen_id


def client_ip_from_request(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
