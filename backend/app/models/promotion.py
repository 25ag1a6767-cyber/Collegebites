import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TimestampMixin, UUIDPrimaryKeyMixin


class Coupon(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "coupons"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"))
    discount_type: Mapped[str] = mapped_column(String(32), nullable=False, default="percentage")  # percentage | fixed | category | food_item
    discount_value: Mapped[Decimal] = mapped_column(Money, nullable=False)
    target_category_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("food_categories.id", ondelete="SET NULL"))
    target_food_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("food_items.id", ondelete="SET NULL"))
    min_order_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    max_discount_amount: Mapped[Optional[Decimal]] = mapped_column(Money)
    first_order_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    usage_limit_total: Mapped[Optional[int]] = mapped_column(Integer)
    usage_limit_per_user: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    times_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CouponRedemption(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "coupon_redemptions"

    coupon_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("coupons.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    guest_phone: Mapped[Optional[str]] = mapped_column(String(32))
    discount_applied: Mapped[Decimal] = mapped_column(Money, nullable=False)


class Promotion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "promotions"

    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    subtitle: Mapped[Optional[str]] = mapped_column(String(255))
    badge_text: Mapped[Optional[str]] = mapped_column(String(48))
    promo_type: Mapped[str] = mapped_column(String(32), nullable=False, default="banner")  # banner | flash_offer | combo
    coupon_code: Mapped[Optional[str]] = mapped_column(String(64))
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class LoyaltyAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "loyalty_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    points_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tier_level: Mapped[str] = mapped_column(String(32), nullable=False, default="BRONZE")  # BRONZE | SILVER | GOLD | PLATINUM
    referral_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    referred_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class LoyaltyTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "loyalty_transactions"

    loyalty_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("loyalty_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    points_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)  # earn | redeem | referral_bonus
    description: Mapped[str] = mapped_column(String(255), nullable=False)
