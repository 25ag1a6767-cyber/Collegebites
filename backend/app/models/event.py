import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TimestampMixin, UUIDPrimaryKeyMixin


class CollegeEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "college_events"

    event_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    canteen_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    organizer_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    organizer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    contact_email: Mapped[Optional[str]] = mapped_column(String(160))
    event_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    location: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    ordering_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eligible_food_item_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    min_order_quantity: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    max_order_quantity: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class EventBulkOrder(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "event_bulk_orders"

    bulk_order_number: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(96), unique=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("college_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canteen_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organizer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    linked_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    scheduled_prep_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_pickup_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pickup_arrangement: Mapped[str] = mapped_column(
        String(32), default="grouped_token", nullable=False
    )  # grouped_token | individual_tokens
    group_pickup_token: Mapped[Optional[str]] = mapped_column(String(48))
    individual_tokens_json: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(
        String(32), default="pending_approval", nullable=False, index=True
    )  # pending_approval | approved | rejected | preparing | ready | completed | cancelled
    payment_method: Mapped[str] = mapped_column(String(32), default="razorpay", nullable=False)
    payment_status: Mapped[str] = mapped_column(
        String(32), default="PENDING", nullable=False, index=True
    )  # PENDING | CONFIRMED | FAILED
    provider_order_id: Mapped[Optional[str]] = mapped_column(String(128))
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(128))
    payment_reference: Mapped[Optional[str]] = mapped_column(String(128))
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class EventBulkOrderItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "event_bulk_order_items"

    bulk_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_bulk_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    food_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_items.id", ondelete="RESTRICT"), nullable=False
    )
    item_name: Mapped[str] = mapped_column(String(140), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
