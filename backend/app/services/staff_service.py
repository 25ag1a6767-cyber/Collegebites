from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import StaffProfile, User
from app.models.staff import StaffAttendance, StaffShift, StaffTask
from app.models.system import ActivityLog
from app.services.audit_service import record_activity_log, record_audit_log


def list_staff_directory(db: Session, canteen_id: Optional[UUID] = None) -> list[dict]:
    stmt = select(StaffProfile, User).join(User, User.id == StaffProfile.user_id)
    if canteen_id:
        stmt = stmt.where(StaffProfile.assigned_canteen_id == canteen_id)
    rows = db.execute(stmt.order_by(User.full_name)).all()
    return [
        {
            "user_id": str(u.id),
            "full_name": u.full_name,
            "email": u.email,
            "phone": u.phone,
            "employee_code": sp.employee_code,
            "designation": sp.designation,
            "assigned_canteen_id": str(sp.assigned_canteen_id) if sp.assigned_canteen_id else None,
            "is_on_duty": sp.is_on_duty,
            "is_active": u.is_active,
        }
        for sp, u in rows
    ]


def schedule_shift(
    db: Session,
    *,
    staff_user_id: UUID,
    canteen_id: UUID,
    shift_date: date,
    start_time: time,
    end_time: time,
    shift_type: str,
    actor_user_id: UUID,
) -> StaffShift:
    shift = StaffShift(
        staff_user_id=staff_user_id,
        canteen_id=canteen_id,
        shift_date=shift_date,
        start_time=start_time,
        end_time=end_time,
        shift_type=shift_type,
        status="scheduled",
        opening_cash_amount=Decimal("0.00"),
    )
    db.add(shift)
    record_audit_log(db, action="staff.shift_scheduled", entity_type="staff_shift", entity_id=str(staff_user_id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(shift)
    return shift


def check_in_staff(db: Session, staff_user_id: UUID, canteen_id: UUID) -> StaffAttendance:
    today = date.today()
    rec = db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.staff_user_id == staff_user_id, StaffAttendance.attendance_date == today
        )
    )
    now = datetime.now(timezone.utc)
    if not rec:
        rec = StaffAttendance(
            staff_user_id=staff_user_id,
            canteen_id=canteen_id,
            attendance_date=today,
            status="present",
            check_in_at=now,
        )
        db.add(rec)
    else:
        rec.status = "present"
        rec.check_in_at = rec.check_in_at or now
    prof = db.scalar(select(StaffProfile).where(StaffProfile.user_id == staff_user_id))
    if prof:
        prof.is_on_duty = True
    record_activity_log(db, activity_type="staff.check_in", description="Staff checked in", user_id=staff_user_id, canteen_id=canteen_id)
    db.commit()
    db.refresh(rec)
    return rec


def check_out_staff(db: Session, staff_user_id: UUID) -> StaffAttendance:
    today = date.today()
    rec = db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.staff_user_id == staff_user_id, StaffAttendance.attendance_date == today
        )
    )
    if not rec:
        raise HTTPException(status_code=404, detail="No check-in record for today")
    rec.check_out_at = datetime.now(timezone.utc)
    prof = db.scalar(select(StaffProfile).where(StaffProfile.user_id == staff_user_id))
    if prof:
        prof.is_on_duty = False
    record_activity_log(db, activity_type="staff.check_out", description="Staff checked out", user_id=staff_user_id, canteen_id=rec.canteen_id)
    db.commit()
    db.refresh(rec)
    return rec


def record_leave(db: Session, *, staff_user_id: UUID, canteen_id: UUID, attendance_date: date, reason: str, actor_user_id: UUID) -> StaffAttendance:
    rec = StaffAttendance(
        staff_user_id=staff_user_id,
        canteen_id=canteen_id,
        attendance_date=attendance_date,
        status="leave",
        leave_reason=reason,
        approved_by_user_id=actor_user_id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def create_task(db: Session, *, canteen_id: UUID, assigned_to_user_id: Optional[UUID], title: str, description: Optional[str], priority: str, is_urgent: bool, actor_user_id: UUID) -> StaffTask:
    task = StaffTask(
        canteen_id=canteen_id,
        assigned_to_user_id=assigned_to_user_id,
        created_by_user_id=actor_user_id,
        title=title,
        description=description,
        priority=priority,
        is_urgent=is_urgent,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task_status(db: Session, task_id: UUID, status_val: str, actor_user_id: UUID) -> StaffTask:
    task = db.get(StaffTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = status_val
    if status_val == "done":
        task.completed_at = datetime.now(timezone.utc)
    record_activity_log(db, activity_type="staff.task_updated", description=f"Task '{task.title}' -> {status_val}", user_id=actor_user_id, canteen_id=task.canteen_id)
    db.commit()
    db.refresh(task)
    return task
