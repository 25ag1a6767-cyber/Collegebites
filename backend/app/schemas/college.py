from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CollegeSettingsOut(ORMModel):
    id: UUID
    college_name: str
    college_short_code: str
    logo_url: Optional[str]
    address: Optional[str]
    contact_phone: Optional[str]
    contact_email: Optional[str]
    default_tax_rate_percent: Decimal
    currency_code: str
    currency_symbol: str
    cancellation_policy_text: str
    kiosk_enabled: bool
    guest_otp_required: bool
    razorpay_enabled: bool
    stripe_enabled: bool = True
    cash_at_counter_enabled: bool
    pay_at_pickup_enabled: bool
    college_timezone: str = "Asia/Kolkata"


class CollegeSettingsUpdate(BaseModel):
    college_name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    college_short_code: Optional[str] = Field(default=None, min_length=2, max_length=32)
    logo_url: Optional[str] = Field(default=None, max_length=500)
    address: Optional[str] = None
    contact_phone: Optional[str] = Field(default=None, max_length=32)
    contact_email: Optional[str] = Field(default=None, max_length=160)
    default_tax_rate_percent: Optional[Decimal] = Field(default=None, ge=0, le=50)
    cancellation_policy_text: Optional[str] = None
    kiosk_enabled: Optional[bool] = None
    guest_otp_required: Optional[bool] = None
    razorpay_enabled: Optional[bool] = None
    stripe_enabled: Optional[bool] = None
    cash_at_counter_enabled: Optional[bool] = None
    pay_at_pickup_enabled: Optional[bool] = None
    college_timezone: Optional[str] = Field(default=None, max_length=64)


class CounterCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=1, max_length=32)
    counter_type: str = Field(default="pickup", pattern="^(pickup|cashier|express|both)$")
    description: Optional[str] = None
    max_queue_capacity: int = Field(default=25, ge=1, le=500)


class CounterOut(ORMModel):
    id: UUID
    canteen_id: UUID
    name: str
    code: str
    counter_type: str
    description: Optional[str]
    is_active: bool
    max_queue_capacity: int


class CounterUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    counter_type: Optional[str] = Field(default=None, pattern="^(pickup|cashier|express|both)$")
    description: Optional[str] = None
    is_active: Optional[bool] = None
    max_queue_capacity: Optional[int] = Field(default=None, ge=1, le=500)


class KitchenCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=1, max_length=32)
    description: Optional[str] = None
    max_active_orders: int = Field(default=35, ge=1, le=500)


class KitchenOut(ORMModel):
    id: UUID
    canteen_id: UUID
    name: str
    code: str
    description: Optional[str]
    max_active_orders: int
    is_active: bool


class KitchenUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    description: Optional[str] = None
    max_active_orders: Optional[int] = Field(default=None, ge=1, le=500)
    is_active: Optional[bool] = None


class KitchenStationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    station_type: str = Field(default="general", max_length=64)


class KitchenStationOut(ORMModel):
    id: UUID
    kitchen_id: UUID
    name: str
    station_type: str
    is_active: bool


class PickupLocationCreate(BaseModel):
    counter_id: UUID
    name: str = Field(min_length=2, max_length=120)
    display_code: str = Field(min_length=1, max_length=32)


class PickupLocationOut(ORMModel):
    id: UUID
    canteen_id: UUID
    counter_id: UUID
    name: str
    display_code: str
    is_active: bool


class DiningTableCreate(BaseModel):
    table_number: str = Field(min_length=1, max_length=32)
    counter_id: Optional[UUID] = None
    zone_label: Optional[str] = Field(default=None, max_length=80)
    capacity: int = Field(default=4, ge=1, le=30)


class DiningTableUpdate(BaseModel):
    counter_id: Optional[UUID] = None
    zone_label: Optional[str] = Field(default=None, max_length=80)
    capacity: Optional[int] = Field(default=None, ge=1, le=30)
    is_active: Optional[bool] = None


class DiningTableOut(ORMModel):
    id: UUID
    canteen_id: UUID
    counter_id: Optional[UUID]
    table_number: str
    zone_label: Optional[str]
    capacity: int
    is_active: bool


class OperatingHourItem(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    open_time: time
    close_time: time
    is_closed: bool = False


class OperatingHourOut(ORMModel):
    id: UUID
    canteen_id: UUID
    day_of_week: int
    open_time: time
    close_time: time
    is_closed: bool


class HolidayCreate(BaseModel):
    canteen_id: Optional[UUID] = None
    holiday_date: date
    title: str = Field(min_length=2, max_length=160)
    is_full_day: bool = True
    start_time: Optional[time] = None
    end_time: Optional[time] = None


class HolidayUpdate(BaseModel):
    holiday_date: Optional[date] = None
    title: Optional[str] = Field(default=None, min_length=2, max_length=160)
    is_full_day: Optional[bool] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    is_active: Optional[bool] = None


class HolidayOut(ORMModel):
    id: UUID
    canteen_id: Optional[UUID]
    holiday_date: date
    title: str
    is_full_day: bool
    start_time: Optional[time]
    end_time: Optional[time]
    is_active: bool


class CanteenCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=160, pattern="^[a-z0-9-]+$")
    code: str = Field(min_length=2, max_length=16)
    token_prefix: str = Field(default="A", min_length=1, max_length=4)
    description: Optional[str] = None
    location: str = Field(min_length=2, max_length=255)
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    canteen_type: str = Field(default="canteen")
    tax_rate_percent: Decimal = Field(default=Decimal("0.00"), ge=0, le=0)
    allow_online_payment: bool = True
    allow_cash_at_counter: bool = False
    allow_pay_at_pickup: bool = False
    max_concurrent_orders: int = Field(default=50, ge=1, le=500)
    orders_per_slot_capacity: int = Field(default=30, ge=1, le=500)
    default_prep_time_minutes: int = Field(default=12, ge=1, le=180)


class CanteenUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = None
    location: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    is_active: Optional[bool] = None
    is_temporarily_closed: Optional[bool] = None
    closure_reason: Optional[str] = None
    ordering_paused: Optional[bool] = None
    pause_reason: Optional[str] = None
    tax_rate_percent: Optional[Decimal] = Field(default=None, ge=0, le=50)
    allow_online_payment: Optional[bool] = None
    allow_cash_at_counter: Optional[bool] = None
    allow_pay_at_pickup: Optional[bool] = None
    max_concurrent_orders: Optional[int] = Field(default=None, ge=1, le=500)
    orders_per_slot_capacity: Optional[int] = Field(default=None, ge=1, le=500)
    default_prep_time_minutes: Optional[int] = Field(default=None, ge=1, le=180)
    peak_hour_buffer_minutes: Optional[int] = Field(default=None, ge=0, le=60)
    crowd_moderate_threshold: Optional[int] = Field(default=None, ge=1)
    crowd_high_threshold: Optional[int] = Field(default=None, ge=2)
    crowd_very_high_threshold: Optional[int] = Field(default=None, ge=3)
    auto_throttle_enabled: Optional[bool] = None


class CanteenOut(ORMModel):
    id: UUID
    name: str
    slug: str
    code: str
    token_prefix: str
    description: Optional[str]
    location: str
    contact_phone: Optional[str]
    contact_email: Optional[str]
    canteen_type: str
    is_active: bool
    is_temporarily_closed: bool
    closure_reason: Optional[str]
    ordering_paused: bool
    pause_reason: Optional[str]
    tax_rate_percent: Decimal
    allow_online_payment: bool
    allow_cash_at_counter: bool
    allow_pay_at_pickup: bool
    max_concurrent_orders: int
    orders_per_slot_capacity: int
    default_prep_time_minutes: int
    is_open_now: bool = True
    crowd_level: str = "LOW"
    estimated_wait_minutes: int = 12
    active_order_count: int = 0


class CanteenDetailOut(CanteenOut):
    counters: list[CounterOut] = []
    kitchens: list[KitchenOut] = []
    tables: list[DiningTableOut] = []
    operating_hours: list[OperatingHourOut] = []
    upcoming_holidays: list[HolidayOut] = []


class LocationQRCreate(BaseModel):
    target_type: str = Field(pattern="^(canteen|counter|table|kiosk)$")
    canteen_id: UUID
    counter_id: Optional[UUID] = None
    table_id: Optional[UUID] = None
    kiosk_device_id: Optional[UUID] = None
    label: str = Field(min_length=2, max_length=160)
    expires_at: Optional[datetime] = None


class LocationQROut(ORMModel):
    id: UUID
    code: str
    target_type: str
    canteen_id: UUID
    counter_id: Optional[UUID]
    table_id: Optional[UUID]
    kiosk_device_id: Optional[UUID]
    label: str
    is_active: bool
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    replaced_by_id: Optional[UUID]
    scan_url: str = ""
    qr_image_base64: Optional[str] = None
    extra: Optional[dict[str, Any]] = None
