from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    client_ip_from_request,
    enforce_canteen_scope,
    require_roles,
    scoped_canteen_for_principal,
)
from app.schemas.operations import POSWalkInOrderRequest, ShiftCloseRequest, ShiftOpenRequest, ShiftOut
from app.schemas.order import OrderOut
from app.services import pos_service

router = APIRouter(prefix="/pos", tags=["Cashier Point of Sale"])

POS_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER)


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_walkin_order(
    payload: POSWalkInOrderRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(*POS_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return pos_service.create_pos_walkin_order(db, payload, principal.user.id, client_ip_from_request(request))


@router.get("/orders/pending-counter", response_model=list[OrderOut])
def pending_counter_orders(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*POS_ROLES)),
    db: Session = Depends(get_db),
):
    scoped = scoped_canteen_for_principal(principal, canteen_id)
    return pos_service.list_pending_counter_orders(db, canteen_id=scoped)


@router.get("/orders/search", response_model=list[OrderOut])
def search_orders(
    q: str = Query(min_length=1),
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*POS_ROLES)),
    db: Session = Depends(get_db),
):
    scoped = scoped_canteen_for_principal(principal, canteen_id)
    return pos_service.search_pos_orders(db, q, canteen_id=scoped)


@router.post("/shifts/open", response_model=ShiftOut)
def open_shift(
    payload: ShiftOpenRequest,
    principal: AuthenticatedPrincipal = Depends(require_roles(*POS_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return pos_service.open_cashier_shift(db, payload, principal.user.id)


@router.get("/shifts/current", response_model=Optional[ShiftOut])
def current_shift(
    principal: AuthenticatedPrincipal = Depends(require_roles(*POS_ROLES)),
    db: Session = Depends(get_db),
):
    return pos_service.get_current_cashier_shift(db, principal.user.id)


@router.post("/shifts/close", response_model=ShiftOut)
def close_shift(
    payload: ShiftCloseRequest,
    principal: AuthenticatedPrincipal = Depends(require_roles(*POS_ROLES)),
    db: Session = Depends(get_db),
):
    return pos_service.close_cashier_shift(db, payload, principal.user.id)
