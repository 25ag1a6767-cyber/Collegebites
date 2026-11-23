from datetime import date, datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
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
    get_current_principal,
    require_roles,
)
from app.models.event import CollegeEvent, EventBulkOrder
from app.services import event_service

router = APIRouter(prefix="/events", tags=["College Events & Bulk Ordering"])

EVENT_ADMIN_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
EVENT_STAFF_ROLES = (*EVENT_ADMIN_ROLES, ROLE_KITCHEN_STAFF)


class EventCreateIn(BaseModel):
    canteen_id: UUID
    event_code: Optional[str] = Field(default=None, max_length=48)
    name: str = Field(min_length=2, max_length=160)
    department: str = Field(min_length=2, max_length=120)
    organizer_user_id: Optional[UUID] = None
    organizer_name: str = Field(min_length=2, max_length=120)
    contact_phone: str = Field(min_length=6, max_length=32)
    contact_email: Optional[str] = Field(default=None, max_length=160)
    event_date: date
    location: str = Field(min_length=2, max_length=180)
    description: Optional[str] = None
    ordering_deadline: datetime
    eligible_food_item_ids: Optional[list[UUID]] = None
    min_order_quantity: int = Field(default=5, ge=1, le=5000)
    max_order_quantity: int = Field(default=500, ge=1, le=10000)
    is_active: bool = True


class EventUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    department: Optional[str] = Field(default=None, min_length=2, max_length=120)
    organizer_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    contact_phone: Optional[str] = Field(default=None, min_length=6, max_length=32)
    contact_email: Optional[str] = Field(default=None, max_length=160)
    event_date: Optional[date] = None
    location: Optional[str] = Field(default=None, min_length=2, max_length=180)
    description: Optional[str] = None
    ordering_deadline: Optional[datetime] = None
    eligible_food_item_ids: Optional[list[UUID]] = None
    min_order_quantity: Optional[int] = Field(default=None, ge=1, le=5000)
    max_order_quantity: Optional[int] = Field(default=None, ge=1, le=10000)
    is_active: Optional[bool] = None


class BulkOrderItemIn(BaseModel):
    food_item_id: UUID
    quantity: int = Field(ge=1, le=5000)


class BulkOrderCreateIn(BaseModel):
    idempotency_key: Optional[str] = Field(default=None, max_length=96)
    scheduled_prep_at: datetime
    scheduled_pickup_at: datetime
    pickup_arrangement: str = Field(default="grouped_token", pattern="^(grouped_token|individual_tokens)$")
    payment_method: str = Field(default="razorpay", pattern="^(razorpay|stripe)$")
    notes: Optional[str] = Field(default=None, max_length=500)
    items: list[BulkOrderItemIn] = Field(min_length=1)


class BulkOrderReviewIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    rejection_reason: Optional[str] = Field(default=None, max_length=300)


class BulkOrderVerifyPaymentIn(BaseModel):
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_signature: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None


class BulkOrderStatusIn(BaseModel):
    status: str = Field(pattern="^(preparing|ready|completed|cancelled)$")


@router.get("")
def list_events(
    canteen_id: Optional[UUID] = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return event_service.list_events(db, canteen_id=canteen_id, include_inactive=include_inactive)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*EVENT_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return event_service.create_event(db, payload.model_dump(), principal.user.id)


@router.patch("/{event_id}")
def update_event(
    event_id: UUID,
    payload: EventUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*EVENT_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    ev = db.get(CollegeEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    enforce_canteen_scope(principal, ev.canteen_id)
    return event_service.update_event(db, event_id, payload.model_dump(exclude_unset=True), principal.user.id)


@router.post("/{event_id}/bulk-orders", status_code=status.HTTP_201_CREATED)
def create_bulk_order(
    event_id: UUID,
    payload: BulkOrderCreateIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return event_service.create_bulk_order(
        db,
        event_id=event_id,
        organizer_user_id=principal.user.id,
        data=payload.model_dump(),
    )


@router.get("/bulk-orders/my")
def list_my_bulk_orders(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return event_service.list_bulk_orders(db, organizer_user_id=principal.user.id)


@router.get("/bulk-orders")
def list_bulk_orders(
    canteen_id: Optional[UUID] = Query(default=None),
    event_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*EVENT_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    elif principal.assigned_canteen_id and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        canteen_id = principal.assigned_canteen_id
    return event_service.list_bulk_orders(
        db, canteen_id=canteen_id, event_id=event_id, status_filter=status_filter
    )


@router.post("/bulk-orders/{bulk_order_id}/review")
def review_bulk_order(
    bulk_order_id: UUID,
    payload: BulkOrderReviewIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*EVENT_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    bo = db.get(EventBulkOrder, bulk_order_id)
    if not bo:
        raise HTTPException(status_code=404, detail="Event bulk order not found")
    enforce_canteen_scope(principal, bo.canteen_id)
    return event_service.review_bulk_order(
        db,
        bulk_order_id=bulk_order_id,
        decision=payload.decision,
        rejection_reason=payload.rejection_reason,
        actor_user_id=principal.user.id,
    )


@router.post("/bulk-orders/{bulk_order_id}/verify-payment")
def verify_bulk_order_payment(
    bulk_order_id: UUID,
    payload: BulkOrderVerifyPaymentIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return event_service.verify_bulk_order_payment(
        db,
        bulk_order_id=bulk_order_id,
        actor_user_id=principal.user.id,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
        stripe_payment_intent_id=payload.stripe_payment_intent_id,
    )


@router.post("/bulk-orders/{bulk_order_id}/status")
def update_bulk_order_status(
    bulk_order_id: UUID,
    payload: BulkOrderStatusIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*EVENT_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    bo = db.get(EventBulkOrder, bulk_order_id)
    if not bo:
        raise HTTPException(status_code=404, detail="Event bulk order not found")
    enforce_canteen_scope(principal, bo.canteen_id)
    return event_service.update_bulk_order_status(
        db,
        bulk_order_id=bulk_order_id,
        target_status=payload.status,
        actor_user_id=principal.user.id,
    )


@router.get("/reports/summary")
def get_events_report(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*EVENT_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    elif principal.assigned_canteen_id and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        canteen_id = principal.assigned_canteen_id
    return event_service.get_events_report_summary(db, canteen_id=canteen_id)


@router.get("/reports/csv")
def export_events_csv(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*EVENT_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    elif principal.assigned_canteen_id and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        canteen_id = principal.assigned_canteen_id
    summary = event_service.get_events_report_summary(db, canteen_id=canteen_id)
    csv_text = event_service.export_events_report_csv(summary)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="collegebites_events_report.csv"'},
    )
