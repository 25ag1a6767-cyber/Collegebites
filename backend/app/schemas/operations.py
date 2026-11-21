from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.order import CheckoutItemDirectIn, OrderOut


class DelayReportRequest(BaseModel):
    additional_minutes: int = Field(ge=1, le=120)
    reason: str = Field(min_length=2, max_length=255)


class ItemUnavailableRequest(BaseModel):
    is_available: bool = False
    reason: Optional[str] = Field(default="Ingredients unavailable", max_length=255)


class PickupVerifyRequest(BaseModel):
    qr_payload: Optional[str] = None
    pickup_token: Optional[str] = None
    order_number: Optional[str] = None
    canteen_id: Optional[UUID] = None
    counter_id: Optional[UUID] = None


class PickupVerifyResponse(BaseModel):
    valid: bool
    can_handover: bool
    result_code: str  # VALID_ORDER | INVALID_QR | PAYMENT_NOT_CONFIRMED | ORDER_NOT_READY | ALREADY_COLLECTED | WRONG_COUNTER | WRONG_CANTEEN | CANCELLED_OR_REJECTED
    message: str
    order_id: Optional[UUID] = None
    order_number: Optional[str] = None
    pickup_token: Optional[str] = None
    order_status: Optional[str] = None
    payment_status: Optional[str] = None
    canteen_name: Optional[str] = None
    counter_id: Optional[UUID] = None
    counter_name: Optional[str] = None
    previous_handover_at: Optional[datetime] = None
    items: list[dict[str, Any]] = []


class HandoverConfirmRequest(BaseModel):
    order_id: UUID
    counter_id: Optional[UUID] = None
    verification_method: str = Field(default="qr_scan", pattern="^(qr_scan|manual_token|order_number)$")
    notes: Optional[str] = Field(default=None, max_length=255)


class HandoverRecordOut(ORMModel):
    id: UUID
    order_id: UUID
    pickup_token_id: UUID
    counter_id: UUID
    handed_over_by_user_id: UUID
    verification_method: str
    handed_over_at: datetime
    notes: Optional[str]


class TokenBoardItem(BaseModel):
    token_code: str
    counter_name: str
    order_status: str
    ready_at: Optional[datetime] = None


class DigitalBoardResponse(BaseModel):
    canteen_id: UUID
    canteen_name: str
    now_preparing: list[TokenBoardItem]
    ready_for_pickup: list[TokenBoardItem]
    recently_completed: list[TokenBoardItem]
    updated_at: datetime


class POSWalkInOrderRequest(BaseModel):
    canteen_id: UUID
    counter_id: Optional[UUID] = None
    customer_name: str = Field(default="Walk-in Customer", max_length=160)
    customer_phone: Optional[str] = Field(default=None, max_length=32)
    payment_method: str = Field(default="cash", pattern="^(cash|upi_pos|card_pos)$")
    coupon_code: Optional[str] = None
    notes: Optional[str] = None
    items: list[CheckoutItemDirectIn] = Field(min_length=1)


class ShiftOpenRequest(BaseModel):
    canteen_id: UUID
    counter_id: Optional[UUID] = None
    opening_cash_amount: Decimal = Field(default=Decimal("0.00"), ge=0)


class ShiftCloseRequest(BaseModel):
    closing_cash_amount: Decimal = Field(ge=0)
    closing_notes: Optional[str] = None


class ShiftOut(ORMModel):
    id: UUID
    staff_user_id: UUID
    canteen_id: UUID
    counter_id: Optional[UUID]
    status: str
    opening_cash_amount: Decimal
    closing_cash_amount: Optional[Decimal]
    expected_cash_amount: Optional[Decimal]
    closed_at: Optional[datetime]
    closing_notes: Optional[str]
    shift_sales_summary: Optional[dict[str, Any]] = None
