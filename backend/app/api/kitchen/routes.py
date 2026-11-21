from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_KITCHEN_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
)
from app.schemas.operations import DelayReportRequest, ItemUnavailableRequest
from app.schemas.order import OrderOut
from app.services import kitchen_service

router = APIRouter(prefix="/kitchen", tags=["Kitchen Display System"])

KITCHEN_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF)


@router.get("/canteens/{canteen_id}/orders", response_model=list[OrderOut])
def get_kitchen_orders(
    canteen_id: UUID,
    status: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return kitchen_service.list_kitchen_orders(db, canteen_id, status_filter=status)


@router.post("/orders/{order_id}/accept", response_model=OrderOut)
def accept_order(
    order_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    return kitchen_service.accept_order(db, order_id, principal.user.id)


@router.post("/orders/{order_id}/start-preparing", response_model=OrderOut)
def start_preparing(
    order_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    return kitchen_service.start_preparing_order(db, order_id, principal.user.id)


@router.post("/orders/{order_id}/mark-ready", response_model=OrderOut)
def mark_ready(
    order_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    return kitchen_service.mark_order_ready(db, order_id, principal.user.id)


@router.post("/orders/{order_id}/report-delay", response_model=OrderOut)
def report_delay(
    order_id: UUID,
    payload: DelayReportRequest,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    return kitchen_service.report_order_delay(db, order_id, payload, principal.user.id)


@router.post("/items/{food_item_id}/unavailable")
def mark_item_unavailable(
    food_item_id: UUID,
    payload: ItemUnavailableRequest,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    return kitchen_service.toggle_item_availability_from_kitchen(db, food_item_id, payload, principal.user.id)
