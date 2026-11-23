import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint
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
    shift_type: Mapped[str] = mapped_column(String(32), nullable=False, default="regular")  # morning | afternoon | evening | night | regular | cashier
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled")  # scheduled | open | closed
    is_weekly_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[Optional[str]] = mapped_column(String(255))
    opening_cash_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    closing_cash_amount: Mapped[Optional[Decimal]] = mapped_column(Money)
    expected_cash_amount: Mapped[Optional[Decimal]] = mapped_column(Money)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closing_notes: Mapped[Optional[str]] = mapped_column(Text)


class StaffWeeklySchedule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "staff_weekly_schedules"
    __table_args__ = (
        UniqueConstraint("staff_user_id", "canteen_id", "day_of_week", "shift_type", name="uq_staff_weekly_sched"),
    )

    staff_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    counter_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("counters.id", ondelete="SET NULL"))
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon..6=Sun
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    shift_type: Mapped[str] = mapped_column(String(32), nullable=False, default="regular")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StaffAttendance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "staff_attendance"

    staff_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="present")  # present | leave | leave_pending | absent | rejected
    leave_type: Mapped[str] = mapped_column(String(32), nullable=False, default="casual")  # casual | sick | emergency | unpaid
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="approved")  # pending | approved | rejected
    check_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    check_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    worked_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    leave_reason: Mapped[Optional[str]] = mapped_column(String(255))
    review_notes: Mapped[Optional[str]] = mapped_column(String(255))
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
