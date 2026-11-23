from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
)
from app.models.inventory import InventoryItem
from app.models.menu import FoodItem
from app.models.order import Order, OrderItem
from app.schemas.operations import DelayReportRequest, ItemUnavailableRequest
from app.schemas.order import OrderOut
from app.services import kitchen_service

router = APIRouter(prefix="/kitchen", tags=["Kitchen Display System"])

KITCHEN_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF)


def _enforce_order_scope(db: Session, principal: AuthenticatedPrincipal, order_id: UUID) -> None:
    ord_row = db.get(Order, order_id)
    if not ord_row:
        raise HTTPException(status_code=404, detail="Order not found")
    enforce_canteen_scope(principal, ord_row.canteen_id)


@router.get("/canteens/{canteen_id}/orders", response_model=list[OrderOut])
def get_kitchen_orders(
    canteen_id: UUID,
    status: Optional[str] = Query(default=None),
    kitchen_id: Optional[UUID] = Query(default=None),
    station_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return kitchen_service.list_kitchen_orders(
        db, canteen_id, status_filter=status, kitchen_id=kitchen_id, station_id=station_id
    )


@router.post("/orders/{order_id}/accept", response_model=OrderOut)
def accept_order(
    order_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    _enforce_order_scope(db, principal, order_id)
    return kitchen_service.accept_order(db, order_id, principal.user.id)


@router.post("/orders/{order_id}/start-preparing", response_model=OrderOut)
def start_preparing(
    order_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    _enforce_order_scope(db, principal, order_id)
    return kitchen_service.start_preparing_order(db, order_id, principal.user.id)


@router.post("/orders/{order_id}/mark-ready", response_model=OrderOut)
def mark_ready(
    order_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    _enforce_order_scope(db, principal, order_id)
    return kitchen_service.mark_order_ready(db, order_id, principal.user.id)


@router.post("/orders/{order_id}/report-delay", response_model=OrderOut)
def report_delay(
    order_id: UUID,
    payload: DelayReportRequest,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    _enforce_order_scope(db, principal, order_id)
    return kitchen_service.report_order_delay(db, order_id, payload, principal.user.id)


@router.post("/items/{food_item_id}/unavailable")
def mark_item_unavailable(
    food_item_id: UUID,
    payload: ItemUnavailableRequest,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    item = db.get(FoodItem, food_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, item.canteen_id)
    return kitchen_service.toggle_item_availability_from_kitchen(db, food_item_id, payload, principal.user.id)


class KitchenRejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class IngredientUnavailableIn(BaseModel):
    reason: str = Field(default="Depleted in kitchen", min_length=2, max_length=255)


@router.post("/orders/{order_id}/reject", response_model=OrderOut)
def reject_order(
    order_id: UUID,
    payload: KitchenRejectIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    _enforce_order_scope(db, principal, order_id)
    return kitchen_service.reject_order_from_kitchen(db, order_id, payload.reason, principal.user.id)


@router.get("/canteens/{canteen_id}/ingredients")
def list_kitchen_ingredients(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return kitchen_service.list_canteen_ingredients_for_kitchen(db, canteen_id)


class OrderPriorityIn(BaseModel):
    is_priority: bool


class OrderItemPrepStatusIn(BaseModel):
    prep_status: str = Field(pattern="^(PENDING|PREPARING|READY)$")


@router.post("/orders/{order_id}/priority", response_model=OrderOut)
def set_order_priority(
    order_id: UUID,
    payload: OrderPriorityIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    _enforce_order_scope(db, principal, order_id)
    return kitchen_service.toggle_order_priority(db, order_id, payload.is_priority, principal.user.id)


@router.post("/order-items/{order_item_id}/prep-status", response_model=OrderOut)
def set_order_item_prep_status(
    order_item_id: UUID,
    payload: OrderItemPrepStatusIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    oi = db.get(OrderItem, order_item_id)
    if not oi:
        raise HTTPException(status_code=404, detail="Order item not found")
    _enforce_order_scope(db, principal, oi.order_id)
    return kitchen_service.update_order_item_prep_status(db, order_item_id, payload.prep_status, principal.user.id)


@router.post("/ingredients/{inventory_item_id}/unavailable")
def report_ingredient_unavailable(
    inventory_item_id: UUID,
    payload: IngredientUnavailableIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    inv = db.get(InventoryItem, inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return kitchen_service.report_ingredient_unavailable(db, inventory_item_id, payload.reason, principal.user.id)


@router.post("/ingredients/{inventory_item_id}/restore")
def restore_ingredient_available(
    inventory_item_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    inv = db.get(InventoryItem, inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return kitchen_service.restore_ingredient_availability(db, inventory_item_id, principal.user.id)


class OrderAssignIn(BaseModel):
    kitchen_id: Optional[UUID] = None
    station_id: Optional[UUID] = None
    staff_user_id: Optional[UUID] = None
    role_scope: str = Field(default="kitchen", pattern="^(kitchen|pickup)$")


@router.get("/canteens/{canteen_id}/stations")
def list_kitchen_stations(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES, ROLE_INVENTORY_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return kitchen_service.list_canteen_stations_with_workload(db, canteen_id)


@router.get("/canteens/{canteen_id}/staff")
def list_kitchen_staff_members(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return kitchen_service.list_canteen_kitchen_staff(db, canteen_id)


@router.post("/orders/{order_id}/assign")
def assign_order(
    order_id: UUID,
    payload: OrderAssignIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KITCHEN_ROLES)),
    db: Session = Depends(get_db),
):
    _enforce_order_scope(db, principal, order_id)
    return kitchen_service.assign_order_to_station_or_staff(
        db,
        order_id,
        kitchen_id=payload.kitchen_id,
        station_id=payload.station_id,
        staff_user_id=payload.staff_user_id,
        role_scope=payload.role_scope,
        actor_user_id=principal.user.id,
    )
