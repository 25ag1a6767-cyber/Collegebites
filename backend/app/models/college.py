import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, TimestampMixin, UUIDPrimaryKeyMixin


class CollegeSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "college_settings"

    college_name: Mapped[str] = mapped_column(String(200), nullable=False, default="ACE Engineering College")
    college_short_code: Mapped[str] = mapped_column(String(32), nullable=False, default="ACE")
    logo_url: Mapped[Optional[str]] = mapped_column(String(500))
    address: Mapped[Optional[str]] = mapped_column(Text)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(32))
    contact_email: Mapped[Optional[str]] = mapped_column(String(160))
    default_tax_rate_percent: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("5.00"))
    currency_code: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    currency_symbol: Mapped[str] = mapped_column(String(8), nullable=False, default="₹")
    cancellation_policy_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=(
            "Orders confirmed after payment enter kitchen preparation immediately and cannot be refunded "
            "through the CollegeBites app. Please verify items, canteen, and pickup slot before paying. "
            "Any exceptional financial adjustment required outside the application is handled strictly through "
            "the college's authorized finance office subject to applicable college policy."
        ),
    )
    kiosk_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    guest_otp_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    razorpay_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stripe_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cash_at_counter_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pay_at_pickup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    college_timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    extra_config: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


class Canteen(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "canteens"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(String(4), nullable=False, default="A")
    description: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(32))
    contact_email: Mapped[Optional[str]] = mapped_column(String(160))
    canteen_type: Mapped[str] = mapped_column(String(64), nullable=False, default="canteen")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_temporarily_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closure_reason: Mapped[Optional[str]] = mapped_column(String(255))
    ordering_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pause_reason: Mapped[Optional[str]] = mapped_column(String(255))
    tax_rate_percent: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("5.00"))
    allow_online_payment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_cash_at_counter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_pay_at_pickup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_concurrent_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    orders_per_slot_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    default_prep_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    peak_hour_buffer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    crowd_moderate_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    crowd_high_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    crowd_very_high_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    auto_throttle_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    prep_settings: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    payment_settings: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    counters: Mapped[list["Counter"]] = relationship(back_populates="canteen", cascade="all, delete-orphan")
    kitchens: Mapped[list["Kitchen"]] = relationship(back_populates="canteen", cascade="all, delete-orphan")
    operating_hours: Mapped[list["OperatingHour"]] = relationship(back_populates="canteen", cascade="all, delete-orphan")


class Counter(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "counters"
    __table_args__ = (UniqueConstraint("canteen_id", "code", name="uq_counters_canteen_code"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    counter_type: Mapped[str] = mapped_column(String(48), nullable=False, default="pickup")
    description: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_queue_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=25)

    canteen: Mapped["Canteen"] = relationship(back_populates="counters")
    pickup_locations: Mapped[list["PickupLocation"]] = relationship(back_populates="counter", cascade="all, delete-orphan")


class Kitchen(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "kitchens"
    __table_args__ = (UniqueConstraint("canteen_id", "code", name="uq_kitchens_canteen_code"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    max_active_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=35)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    canteen: Mapped["Canteen"] = relationship(back_populates="kitchens")
    stations: Mapped[list["KitchenStation"]] = relationship(back_populates="kitchen", cascade="all, delete-orphan")


class KitchenStation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "kitchen_stations"

    kitchen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    station_type: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    kitchen: Mapped["Kitchen"] = relationship(back_populates="stations")


class DiningTable(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tables"
    __table_args__ = (UniqueConstraint("canteen_id", "table_number", name="uq_tables_canteen_number"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    counter_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("counters.id", ondelete="SET NULL"))
    table_number: Mapped[str] = mapped_column(String(32), nullable=False)
    zone_label: Mapped[Optional[str]] = mapped_column(String(80))
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PickupLocation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "pickup_locations"

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    counter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("counters.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_code: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    counter: Mapped["Counter"] = relationship(back_populates="pickup_locations")


class KioskDevice(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "kiosk_devices"

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    counter_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("counters.id", ondelete="SET NULL"))
    device_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    device_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idle_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    supported_languages: Mapped[list] = mapped_column(JSON, nullable=False, default=lambda: ["en", "hi", "te"])
    printer_config: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class OperatingHour(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "operating_hours"
    __table_args__ = (UniqueConstraint("canteen_id", "day_of_week", name="uq_operating_hours_canteen_day"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Monday .. 6=Sunday
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    canteen: Mapped["Canteen"] = relationship(back_populates="operating_hours")


class CollegeHoliday(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "college_holidays"

    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), index=True)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    is_full_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    start_time: Mapped[Optional[time]] = mapped_column(Time)
    end_time: Mapped[Optional[time]] = mapped_column(Time)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class LocationQRCode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Permanent, revocable, replaceable QR identifiers for canteens, counters, tables, and kiosks."""

    __tablename__ = "location_qr_codes"
    __table_args__ = (Index("ix_location_qr_target", "target_type", "canteen_id"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)  # canteen | counter | table | kiosk
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False)
    counter_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("counters.id", ondelete="SET NULL"))
    table_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("tables.id", ondelete="SET NULL"))
    kiosk_device_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("kiosk_devices.id", ondelete="SET NULL"))
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True))
