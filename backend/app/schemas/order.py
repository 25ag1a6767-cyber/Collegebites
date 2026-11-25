from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class AddonSelectionIn(BaseModel):
    addon_id: UUID
    quantity: int = Field(default=1, ge=1, le=10)


class CartItemAddIn(BaseModel):
    canteen_id: UUID
    food_item_id: UUID
    variant_id: Optional[UUID] = None
    quantity: int = Field(default=1, ge=1, le=50)
    spice_level: Optional[str] = Field(default=None, max_length=40)
    sugar_level: Optional[str] = Field(default=None, max_length=40)
    removed_ingredients: list[str] = []
    addons: list[AddonSelectionIn] = []
    special_instructions: Optional[str] = Field(default=None, max_length=300)


class CartItemUpdateIn(BaseModel):
    quantity: Optional[int] = Field(default=None, ge=0, le=50)
    variant_id: Optional[UUID] = None
    spice_level: Optional[str] = Field(default=None, max_length=40)
    sugar_level: Optional[str] = Field(default=None, max_length=40)
    removed_ingredients: Optional[list[str]] = None
    addons: Optional[list[AddonSelectionIn]] = None
    special_instructions: Optional[str] = Field(default=None, max_length=300)


class CartCustomizationOut(BaseModel):
    customization_type: str
    addon_id: Optional[UUID]
    option_name: str
    option_value: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal


class CartItemOut(BaseModel):
    id: UUID
    food_item_id: UUID
    item_name: str
    variant_id: Optional[UUID]
    variant_name: Optional[str]
    quantity: int
    unit_price: Decimal
    addon_total_per_unit: Decimal
    line_subtotal: Decimal
    special_instructions: Optional[str]
    customizations: list[CartCustomizationOut] = []


class CartSummaryOut(BaseModel):
    cart_id: Optional[UUID]
    canteen_id: UUID
    canteen_name: str
    coupon_code: Optional[str]
    coupon_valid: bool = True
    coupon_message: Optional[str] = None
    items: list[CartItemOut] = []
    subtotal_amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    is_canteen_open: bool
    has_capacity: bool
    estimated_prep_minutes: int
    validation_errors: list[str] = []


class CheckoutItemDirectIn(BaseModel):
    food_item_id: UUID
    variant_id: Optional[UUID] = None
    quantity: int = Field(default=1, ge=1, le=50)
    spice_level: Optional[str] = None
    sugar_level: Optional[str] = None
    removed_ingredients: list[str] = []
    addons: list[AddonSelectionIn] = []
    special_instructions: Optional[str] = None


class CheckoutRequest(BaseModel):
    canteen_id: UUID
    counter_id: Optional[UUID] = None
    table_id: Optional[UUID] = None
    location_qr_code: Optional[str] = None
    pickup_slot_id: Optional[UUID] = None
    order_type: str = Field(default="pickup", pattern="^(pickup|dine_in|walk_in|kiosk|qr_table)$")
    order_channel: str = Field(default="web", pattern="^(web|mobile|qr|pos|kiosk)$")
    payment_method: str = Field(default="razorpay", pattern="^(razorpay|cash|pay_at_pickup|card_pos|upi_pos)$")
    coupon_code: Optional[str] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=120)
    guest_name: Optional[str] = Field(default=None, max_length=160)
    guest_phone: Optional[str] = Field(default=None, max_length=32)
    guest_email: Optional[str] = Field(default=None, max_length=160)
    notes: Optional[str] = Field(default=None, max_length=500)
    redeem_loyalty_points: int = Field(default=0, ge=0, le=100000)
    use_cart: bool = True
    direct_items: list[CheckoutItemDirectIn] = []
    accepted_policy: bool = True


class OrderItemCustomizationOut(ORMModel):
    id: UUID
    addon_id: Optional[UUID] = None
    customization_type: str
    option_name: str
    option_value: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal


class OrderItemOut(ORMModel):
    id: UUID
    food_item_id: Optional[UUID]
    variant_id: Optional[UUID] = None
    station_id: Optional[UUID] = None
    prep_status: str = "PENDING"
    item_name: str
    variant_name: Optional[str]
    quantity: int
    unit_price: Decimal
    addon_total_per_unit: Decimal
    line_subtotal: Decimal
    tax_amount: Decimal
    line_total: Decimal
    special_instructions: Optional[str]
    customizations: list[OrderItemCustomizationOut] = []


class OrderStatusHistoryOut(ORMModel):
    id: UUID
    from_status: Optional[str]
    to_status: str
    reason: Optional[str]
    created_at: datetime


class OrderOut(ORMModel):
    id: UUID
    order_number: str
    canteen_id: UUID
    canteen_name: Optional[str] = None
    counter_id: UUID
    counter_name: Optional[str] = None
    kitchen_id: Optional[UUID]
    table_id: Optional[UUID]
    customer_id: Optional[UUID]
    is_guest: bool
    guest_name: Optional[str]
    guest_phone_masked: Optional[str] = None
    order_type: str
    order_channel: str
    status: str
    payment_status: str
    payment_method: str
    subtotal_amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    coupon_code: Optional[str]
    estimated_prep_minutes: int
    estimated_pickup_at: Optional[datetime]
    delayed_minutes: int
    delay_reason: Optional[str]
    is_priority: bool = False
    queue_position: Optional[int] = None
    orders_ahead_count: Optional[int] = None
    counter_queue_position: Optional[int] = None
    dynamic_wait_minutes: Optional[int] = None
    waiting_time_available: bool = True
    waiting_time_message: Optional[str] = None
    last_updated_at: Optional[datetime] = None
    pickup_token_code: Optional[str] = None
    qr_verification_path: Optional[str] = None
    qr_token_raw: Optional[str] = None
    guest_access_token: Optional[str] = None
    razorpay_order_id: Optional[str] = None
    razorpay_key_id: Optional[str] = None
    cancellation_policy_text: Optional[str] = None
    created_at: datetime
    confirmed_at: Optional[datetime]
    accepted_at: Optional[datetime]
    preparing_at: Optional[datetime]
    ready_at: Optional[datetime]
    completed_at: Optional[datetime]
    items: list[OrderItemOut] = []
    status_history: list[OrderStatusHistoryOut] = []


class OrderCancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=255)
    finance_note: Optional[str] = None


class PickupSlotOut(ORMModel):
    id: UUID
    canteen_id: UUID
    slot_date: date
    start_time: time
    end_time: time
    capacity: int
    reserved_count: int
    available_count: int = 0
    is_active: bool
