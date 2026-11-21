import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TimestampMixin, UUIDPrimaryKeyMixin


class StaffShift(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "staff_shifts"

    staff_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    counter_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("counters.id", ondelete="SET NULL"))
    shift_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    shift_type: Mapped[str] = mapped_column(String(32), nullable=False, default="regular")  # morning | afternoon | regular | cashier
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled")  # scheduled | open | closed
    opening_cash_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    closing_cash_amount: Mapped[Optional[Decimal]] = mapped_column(Money)
    expected_cash_amount: Mapped[Optional[Decimal]] = mapped_column(Money)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closing_notes: Mapped[Optional[str]] = mapped_column(Text)


class StaffAttendance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "staff_attendance"

    staff_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="present")  # present | leave | absent
    check_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    check_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    leave_reason: Mapped[Optional[str]] = mapped_column(String(255))
    approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class StaffTask(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "staff_tasks"

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_to_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(24), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending | in_progress | done
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_urgent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
