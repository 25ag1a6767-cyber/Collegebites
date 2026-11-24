from datetime import date, time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_KITCHEN_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_optional_principal,
    require_roles,
)
from app.models.order import Order
from app.schemas.order import OrderOut, PickupSlotOut
from app.services import order_service, queue_service

router = APIRouter(prefix="/queue", tags=["Queue & Crowd Management"])


class QueueControlsUpdate(BaseModel):
    ordering_paused: Optional[bool] = None
    pause_reason: Optional[str] = None
    max_concurrent_orders: Optional[int] = Field(default=None, ge=1, le=500)
    orders_per_slot_capacity: Optional[int] = Field(default=None, ge=1, le=500)
    default_prep_time_minutes: Optional[int] = Field(default=None, ge=1, le=180)
    peak_hour_buffer_minutes: Optional[int] = Field(default=None, ge=0, le=60)
    crowd_moderate_threshold: Optional[int] = Field(default=None, ge=1)
    crowd_high_threshold: Optional[int] = Field(default=None, ge=2)
    crowd_very_high_threshold: Optional[int] = Field(default=None, ge=3)
    auto_throttle_enabled: Optional[bool] = None


class PickupSlotUpsert(BaseModel):
    slot_date: date
    start_time: time
    end_time: time
    capacity: int = Field(ge=1, le=500)
    is_active: bool = True


@router.get("/canteens/{canteen_id}")
def get_live_queue(canteen_id: UUID, db: Session = Depends(get_db)):
    return queue_service.get_live_queue_dashboard(db, canteen_id)


@router.get("/canteens/{canteen_id}/estimate")
def estimate_prep(
    canteen_id: UUID,
    item_ids: list[UUID] = Query(default=[]),
    db: Session = Depends(get_db),
):
    return queue_service.estimate_prep_time(db, canteen_id, item_ids)


@router.get("/canteens/{canteen_id}/accuracy")
def get_queue_accuracy(
    canteen_id: UUID,
    days: int = Query(default=30, ge=1, le=365),
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF)
    ),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return queue_service.get_queue_accuracy_metrics(db, canteen_id, days=days)


@router.patch("/canteens/{canteen_id}/controls")
def update_controls(
    canteen_id: UUID,
    payload: QueueControlsUpdate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return queue_service.update_queue_controls(db, canteen_id, payload.model_dump(exclude_unset=True), principal.user.id)


class CounterReassignIn(BaseModel):
    counter_id: UUID


@router.get("/orders/{order_id_or_number}")
def get_order_queue_status(
    order_id_or_number: str,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF))
    staff_cid = None if (principal and principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)) else (principal.assigned_canteen_id if principal else None)
    order_out: OrderOut = order_service.get_order_authorized(
        db,
        order_id_or_number,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        staff_canteen_id=staff_cid,
        guest_access_token=guest_token or x_guest_token,
    )
    return {
        "order_id": str(order_out.id),
        "order_number": order_out.order_number,
        "status": order_out.status,
        "counter_id": str(order_out.counter_id),
        "counter_name": order_out.counter_name,
        "is_priority": order_out.is_priority,
        "queue_position": order_out.queue_position,
        "orders_ahead_count": order_out.orders_ahead_count,
        "counter_queue_position": order_out.counter_queue_position,
        "dynamic_wait_minutes": order_out.dynamic_wait_minutes,
        "estimated_prep_minutes": order_out.estimated_prep_minutes,
        "delayed_minutes": order_out.delayed_minutes,
    }


@router.post("/orders/{order_id}/assign-counter")
def reassign_order_counter(
    order_id: UUID,
    payload: CounterReassignIn,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF)
    ),
    db: Session = Depends(get_db),
):
    order = db.get(Order, order_id)
    if order:
        enforce_canteen_scope(principal, order.canteen_id)
    return queue_service.assign_order_counter(
        db,
        order_id=order_id,
        counter_id=payload.counter_id,
        actor_user_id=principal.user.id,
    )


@router.post("/canteens/{canteen_id}/escalate-overdue")
def escalate_overdue(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF)
    ),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return queue_service.escalate_overdue_orders(db, canteen_id=canteen_id, actor_user_id=principal.user.id)


@router.post("/canteens/{canteen_id}/slots", response_model=PickupSlotOut)
def upsert_slot(
    canteen_id: UUID,
    payload: PickupSlotUpsert,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    slot = queue_service.upsert_pickup_slot(
        db,
        canteen_id=canteen_id,
        slot_date=payload.slot_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        capacity=payload.capacity,
        is_active=payload.is_active,
    )
    out = PickupSlotOut.model_validate(slot)
    out.available_count = max(0, slot.capacity - slot.reserved_count)
    return out
