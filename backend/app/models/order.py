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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, TimestampMixin, UUIDPrimaryKeyMixin


class Cart(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "carts"
    __table_args__ = (
        Index("ix_carts_user_canteen_status", "user_id", "canteen_id", "status"),
        Index("ix_carts_guest_canteen_status", "guest_session_id", "canteen_id", "status"),
    )

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    guest_session_id: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    coupon_code: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")  # active | converted | abandoned

    items: Mapped[list["CartItem"]] = relationship(back_populates="cart", cascade="all, delete-orphan")


class CartItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "cart_items"

    cart_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True)
    food_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("food_variants.id", ondelete="SET NULL"))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    special_instructions: Mapped[Optional[str]] = mapped_column(String(300))

    cart: Mapped["Cart"] = relationship(back_populates="items")
    customizations: Mapped[list["CartItemCustomization"]] = relationship(
        back_populates="cart_item", cascade="all, delete-orphan"
    )


class CartItemCustomization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "cart_item_customizations"

    cart_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cart_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customization_type: Mapped[str] = mapped_column(String(32), nullable=False)  # addon | spice | sugar | remove_ingredient
    addon_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("food_addons.id", ondelete="SET NULL"))
    option_name: Mapped[str] = mapped_column(String(120), nullable=False)
    option_value: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    cart_item: Mapped["CartItem"] = relationship(back_populates="customizations")


class PickupSlot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "pickup_slots"
    __table_args__ = (
        UniqueConstraint("canteen_id", "slot_date", "start_time", name="uq_pickup_slot_canteen_start"),
        Index("ix_pickup_slots_lookup", "canteen_id", "slot_date", "is_active"),
    )

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False)
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    reserved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Order(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_canteen_status", "canteen_id", "status"),
        Index("ix_orders_canteen_created_at", "canteen_id", "created_at"),
        Index("ix_orders_customer", "customer_id", "created_at"),
        Index("ix_orders_counter_status", "counter_id", "status"),
        Index("ix_orders_canteen_payment_created", "canteen_id", "payment_status", "created_at"),
        Index("ix_orders_payment_created", "payment_status", "created_at"),
        Index("ix_orders_canteen_status_ready", "canteen_id", "status", "ready_at"),
        Index("ix_orders_canteen_status_completed", "canteen_id", "status", "completed_at"),
        Index("ix_orders_created_at", "created_at"),
    )

    order_number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), unique=True, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="RESTRICT"), nullable=False, index=True)
    counter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("counters.id", ondelete="RESTRICT"), nullable=False)
    kitchen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("kitchens.id", ondelete="SET NULL"))
    table_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("tables.id", ondelete="SET NULL"))
    kiosk_device_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("kiosk_devices.id", ondelete="SET NULL"))
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cashier_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    pickup_slot_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("pickup_slots.id", ondelete="SET NULL"))
    location_qr_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("location_qr_codes.id", ondelete="SET NULL"))

    is_guest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    guest_name: Mapped[Optional[str]] = mapped_column(String(160))
    guest_phone: Mapped[Optional[str]] = mapped_column(String(32))
    guest_email: Mapped[Optional[str]] = mapped_column(String(160))
    guest_access_token_hash: Mapped[Optional[str]] = mapped_column(String(128), index=True)

    order_type: Mapped[str] = mapped_column(String(32), nullable=False, default="pickup")  # pickup | dine_in | walk_in | kiosk | qr_table
    order_channel: Mapped[str] = mapped_column(String(32), nullable=False, default="web")  # web | mobile | qr | pos | kiosk

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED", index=True)
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False, default="razorpay")

    subtotal_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    discount_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    coupon_code: Mapped[Optional[str]] = mapped_column(String(64))

    estimated_prep_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    estimated_pickup_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    preparing_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delayed_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delay_reason: Mapped[Optional[str]] = mapped_column(String(255))
    is_priority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    inventory_deducted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "order_items"
    __table_args__ = (
        Index("ix_order_items_food_item_id", "food_item_id"),
        Index("ix_order_items_prep_status", "prep_status"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    food_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("food_items.id", ondelete="SET NULL"))
    variant_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("food_variants.id", ondelete="SET NULL"))
    station_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("kitchen_stations.id", ondelete="SET NULL"))
    prep_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")  # PENDING | PREPARING | READY
    # Historical snapshot fields (never mutated when menus change)
    item_name: Mapped[str] = mapped_column(String(160), nullable=False)
    variant_name: Mapped[Optional[str]] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    addon_total_per_unit: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    line_subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    special_instructions: Mapped[Optional[str]] = mapped_column(String(300))

    order: Mapped["Order"] = relationship(back_populates="items")
    customizations: Mapped[list["OrderItemCustomization"]] = relationship(
        back_populates="order_item", cascade="all, delete-orphan"
    )


class OrderItemCustomization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "order_item_customizations"

    order_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    addon_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("food_addons.id", ondelete="SET NULL"))
    customization_type: Mapped[str] = mapped_column(String(32), nullable=False)
    option_name: Mapped[str] = mapped_column(String(120), nullable=False)
    option_value: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    total_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))

    order_item: Mapped["OrderItem"] = relationship(back_populates="customizations")


class OrderStatusHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "order_status_history"
    __table_args__ = (
        Index("ix_order_status_history_created_actor", "created_at", "changed_by_user_id"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    order: Mapped["Order"] = relationship(back_populates="status_history")


class OrderCancellation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Records order cancellation or rejection; payment records remain intact with NO refunds."""

    __tablename__ = "order_cancellations"

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    cancellation_type: Mapped[str] = mapped_column(String(32), nullable=False)  # cancelled | rejected
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    cancelled_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    payment_retained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    finance_note: Mapped[Optional[str]] = mapped_column(Text)


class OrderAssignment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "order_assignments"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    kitchen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("kitchens.id", ondelete="SET NULL"))
    station_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("kitchen_stations.id", ondelete="SET NULL"))
    staff_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    role_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="kitchen")  # kitchen | pickup


class SlotReservation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "slot_reservations"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_slot_reservation_order"),
        Index("ix_slot_reservations_status_expires", "status", "expires_at"),
    )

    pickup_slot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pickup_slots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="reserved")  # reserved | released | fulfilled
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
