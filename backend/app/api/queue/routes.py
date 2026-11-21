from datetime import date, time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
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
    require_roles,
)
from app.schemas.order import PickupSlotOut
from app.services import queue_service

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


@router.patch("/canteens/{canteen_id}/controls")
def update_controls(
    canteen_id: UUID,
    payload: QueueControlsUpdate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF)
    ),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return queue_service.update_queue_controls(db, canteen_id, payload.model_dump(exclude_unset=True), principal.user.id)


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
