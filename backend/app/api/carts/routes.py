from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import AuthenticatedPrincipal, get_optional_principal
from app.schemas.order import CartItemAddIn, CartItemUpdateIn, CartSummaryOut
from app.services import cart_service

router = APIRouter(prefix="/carts", tags=["Cart"])


class CartCouponIn(BaseModel):
    canteen_id: UUID
    coupon_code: str = Field(min_length=2, max_length=48)


@router.get("", response_model=CartSummaryOut)
def get_cart(
    canteen_id: UUID = Query(...),
    x_guest_session_id: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    return cart_service.calculate_cart_summary(
        db,
        canteen_id,
        user_id=principal.user.id if principal else None,
        guest_session_id=x_guest_session_id,
    )


@router.post("/items", response_model=CartSummaryOut)
def add_cart_item(
    payload: CartItemAddIn,
    x_guest_session_id: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    return cart_service.add_item_to_cart(
        db,
        payload,
        user_id=principal.user.id if principal else None,
        guest_session_id=x_guest_session_id,
    )


@router.patch("/items/{cart_item_id}", response_model=CartSummaryOut)
def update_cart_item(
    cart_item_id: UUID,
    payload: CartItemUpdateIn,
    x_guest_session_id: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    return cart_service.update_cart_item(
        db,
        cart_item_id,
        payload,
        user_id=principal.user.id if principal else None,
        guest_session_id=x_guest_session_id,
    )


@router.post("/coupon", response_model=CartSummaryOut)
def apply_cart_coupon(
    payload: CartCouponIn,
    x_guest_session_id: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    return cart_service.apply_coupon_to_cart(
        db,
        canteen_id=payload.canteen_id,
        coupon_code=payload.coupon_code,
        user_id=principal.user.id if principal else None,
        guest_session_id=x_guest_session_id,
    )


@router.delete("/coupon", response_model=CartSummaryOut)
def remove_cart_coupon(
    canteen_id: UUID = Query(...),
    x_guest_session_id: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    return cart_service.remove_coupon_from_cart(
        db,
        canteen_id=canteen_id,
        user_id=principal.user.id if principal else None,
        guest_session_id=x_guest_session_id,
    )
