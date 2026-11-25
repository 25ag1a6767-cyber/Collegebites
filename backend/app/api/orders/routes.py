from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    client_ip_from_request,
    get_current_principal,
    get_optional_principal,
)
from app.models.order import Order, OrderItem
from app.schemas.order import CheckoutRequest, OrderCancelRequest, OrderOut, PickupSlotOut
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["Orders & Checkout"])

STAFF_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
)


@router.get("/slots/{canteen_id}", response_model=list[PickupSlotOut])
def get_pickup_slots(canteen_id: UUID, db: Session = Depends(get_db)):
    return order_service.list_pickup_slots(db, canteen_id)


@router.post("/checkout", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def checkout(
    payload: CheckoutRequest,
    request: Request,
    x_guest_session_id: Optional[str] = Header(default=None),
    x_idempotency_key: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    if not payload.idempotency_key and x_idempotency_key and x_idempotency_key.strip():
        payload.idempotency_key = x_idempotency_key.strip()[:120]
    return order_service.checkout_order(
        db,
        payload,
        user_id=principal.user.id if principal else None,
        guest_session_id=x_guest_session_id,
        ip_address=client_ip_from_request(request),
    )


@router.get("/my", response_model=list[OrderOut])
def my_orders(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.customer_id == principal.user.id)
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return order_service.serialize_orders_batch(db, list(orders))


class GuestOrderLookupRequest(BaseModel):
    order_number: str = Field(min_length=6, max_length=48)
    guest_contact: str = Field(min_length=5, max_length=160)


@router.post("/guest/lookup", response_model=list[OrderOut])
def guest_order_lookup(payload: GuestOrderLookupRequest, db: Session = Depends(get_db)):
    return order_service.lookup_guest_orders(
        db, order_number=payload.order_number, guest_contact=payload.guest_contact
    )


def _staff_scoped_canteen(principal: Optional[AuthenticatedPrincipal]) -> Optional[UUID]:
    if not principal or not principal.has_role(*STAFF_ROLES):
        return None
    if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return None
    return principal.assigned_canteen_id


@router.get("/{order_id_or_number}", response_model=OrderOut)
def get_order(
    order_id_or_number: str,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(*STAFF_ROLES))
    return order_service.get_order_authorized(
        db,
        order_id_or_number,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        staff_canteen_id=_staff_scoped_canteen(principal),
        guest_access_token=guest_token or x_guest_token,
    )


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: UUID,
    payload: OrderCancelRequest,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(*STAFF_ROLES))
    return order_service.cancel_or_reject_order(
        db,
        order_id,
        cancellation_type="cancelled",
        reason=payload.reason,
        actor_user_id=principal.user.id if principal else None,
        finance_note=payload.finance_note,
        guest_access_token=guest_token or x_guest_token,
        is_staff=is_staff,
        staff_canteen_id=_staff_scoped_canteen(principal),
    )
