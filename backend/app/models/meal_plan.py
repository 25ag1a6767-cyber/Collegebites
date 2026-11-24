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


class MealPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meal_plans"

    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("canteens.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    plan_type: Mapped[str] = mapped_column(
        String(32), default="monthly", nullable=False
    )  # daily | weekly | monthly | custom
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_rate_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    validity_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    total_meals: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    eligible_category_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    eligible_food_item_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class StudentMealSubscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "student_meal_subscriptions"

    subscription_number: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    student_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    meal_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meal_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("canteens.id", ondelete="SET NULL"), index=True
    )
    total_meals: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_meals: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(32), default="razorpay", nullable=False)
    payment_status: Mapped[str] = mapped_column(
        String(32), default="PENDING", nullable=False, index=True
    )  # PENDING | CONFIRMED | FAILED
    provider_order_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True)
    payment_reference: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(32), default="pending_payment", nullable=False, index=True
    )  # pending_payment | active | exhausted | expired | cancelled
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    redemption_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    redemption_qr_payload: Mapped[str] = mapped_column(String(255), nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class MealPlanRedemption(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "meal_plan_redemptions"

    redemption_number: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(96), unique=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_meal_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canteen_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True
    )
    food_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("food_items.id", ondelete="SET NULL")
    )
    meal_item_name: Mapped[str] = mapped_column(String(140), nullable=False)
    meals_deducted: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    remaining_meals_after: Mapped[int] = mapped_column(Integer, nullable=False)
    redeemed_by_staff_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
