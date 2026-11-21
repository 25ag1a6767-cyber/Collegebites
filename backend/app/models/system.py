import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TimestampMixin, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor_role: Mapped[Optional[str]] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    details: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


class ActivityLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "activity_logs"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"))
    activity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


class DailySalesSummary(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "daily_sales_summaries"
    __table_args__ = (UniqueConstraint("canteen_id", "summary_date", name="uq_daily_sales_canteen_date"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    summary_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_sales: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    tax_collected: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    net_sales: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    breakdown_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


class SystemEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "system_events"

    event_source: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="info")
    event_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
