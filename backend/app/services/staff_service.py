from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.time_utils import today_college
from app.models.auth import Permission, Role, StaffProfile, User, UserPermission, UserRole
from app.models.college import Counter
from app.models.order import Order, OrderAssignment, OrderStatusHistory
from app.models.payment import OrderHandoverRecord
from app.models.staff import StaffAttendance, StaffShift, StaffTask, StaffWeeklySchedule
from app.models.system import ActivityLog
from app.services.audit_service import record_activity_log, record_audit_log


def list_staff_directory(db: Session, canteen_id: Optional[UUID] = None) -> list[dict]:
    stmt = select(StaffProfile, User).join(User, User.id == StaffProfile.user_id)
    if canteen_id:
        stmt = stmt.where(StaffProfile.assigned_canteen_id == canteen_id)
    rows = db.execute(stmt.order_by(User.full_name)).all()
    user_ids = [u.id for _, u in rows]
    roles_map: dict[UUID, list[str]] = defaultdict(list)
    custom_grants: dict[UUID, list[str]] = defaultdict(list)
    custom_revokes: dict[UUID, list[str]] = defaultdict(list)
    if user_ids:
        for uid, rname in db.execute(
            select(UserRole.user_id, Role.name)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
        ).all():
            roles_map[uid].append(rname)
        for uid, code, granted in db.execute(
            select(UserPermission.user_id, Permission.code, UserPermission.granted)
            .join(Permission, Permission.id == UserPermission.permission_id)
            .where(UserPermission.user_id.in_(user_ids))
        ).all():
            if granted:
                custom_grants[uid].append(code)
            else:
                custom_revokes[uid].append(code)

    return [
        {
            "user_id": str(u.id),
            "full_name": u.full_name,
            "email": u.email,
            "phone": u.phone,
            "employee_code": sp.employee_code,
            "designation": sp.designation,
            "assigned_canteen_id": str(sp.assigned_canteen_id) if sp.assigned_canteen_id else None,
            "assigned_counter_id": str(sp.assigned_counter_id) if sp.assigned_counter_id else None,
            "assigned_kitchen_id": str(sp.assigned_kitchen_id) if sp.assigned_kitchen_id else None,
            "availability_status": getattr(sp, "availability_status", "available"),
            "weekly_hours_target": getattr(sp, "weekly_hours_target", 48),
            "roles": roles_map.get(u.id, []),
            "granted_permissions": custom_grants.get(u.id, []),
            "revoked_permissions": custom_revokes.get(u.id, []),
            "is_on_duty": sp.is_on_duty,
            "is_active": u.is_active,
        }
        for sp, u in rows
    ]


def get_staff_detail(db: Session, staff_user_id: UUID) -> dict:
    row = db.execute(
        select(StaffProfile, User)
        .join(User, User.id == StaffProfile.user_id)
        .where(StaffProfile.user_id == staff_user_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Staff profile not found")
    sp, u = row
    entries = list_staff_directory(db, canteen_id=None)
    return next(e for e in entries if e["user_id"] == str(u.id))


def update_staff_member(
    db: Session,
    staff_user_id: UUID,
    updates: dict[str, Any],
    *,
    actor_user_id: UUID,
    is_college_admin: bool = False,
    actor_canteen_id: Optional[UUID] = None,
) -> dict:
    user = db.get(User, staff_user_id)
    prof = db.scalar(select(StaffProfile).where(StaffProfile.user_id == staff_user_id))
    if not user or not prof:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if not is_college_admin:
        if actor_canteen_id and prof.assigned_canteen_id != actor_canteen_id:
            raise HTTPException(status_code=403, detail="Staff user belongs to a different canteen")
        target_roles = {
            rname
            for rname in db.scalars(
                select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == staff_user_id)
            ).all()
        }
        if target_roles & {"super_admin", "college_admin"}:
            raise HTTPException(status_code=403, detail="Canteen managers cannot modify college admin accounts")

    if updates.get("full_name"):
        user.full_name = str(updates["full_name"]).strip()
    if "phone" in updates and updates["phone"] is not None:
        clean_phone = updates["phone"].strip() or None
        if clean_phone:
            dup = db.scalar(select(User).where(User.phone == clean_phone, User.id != user.id))
            if dup:
                raise HTTPException(status_code=409, detail="Phone number already assigned to another user")
        user.phone = clean_phone
    if "is_active" in updates and updates["is_active"] is not None:
        if staff_user_id == actor_user_id and not updates["is_active"]:
            raise HTTPException(status_code=400, detail="Cannot deactivate your own active account")
        user.is_active = bool(updates["is_active"])
    if updates.get("designation"):
        prof.designation = str(updates["designation"]).strip()
    if "assigned_counter_id" in updates:
        prof.assigned_counter_id = updates["assigned_counter_id"]
    if "assigned_kitchen_id" in updates:
        prof.assigned_kitchen_id = updates["assigned_kitchen_id"]
    if "assigned_canteen_id" in updates and updates["assigned_canteen_id"] is not None and is_college_admin:
        prof.assigned_canteen_id = updates["assigned_canteen_id"]
    if updates.get("availability_status"):
        prof.availability_status = updates["availability_status"]
        if updates["availability_status"] == "off_duty":
            prof.is_on_duty = False
    if updates.get("weekly_hours_target") is not None:
        prof.weekly_hours_target = int(updates["weekly_hours_target"])

    record_audit_log(
        db,
        action="staff.profile_updated",
        entity_type="user",
        entity_id=str(user.id),
        actor_user_id=actor_user_id,
        details={k: str(v) if isinstance(v, UUID) else v for k, v in updates.items()},
    )
    record_activity_log(
        db,
        activity_type="staff.profile_updated",
        description=f"Updated staff profile for {user.full_name}",
        user_id=actor_user_id,
        canteen_id=prof.assigned_canteen_id,
    )
    db.commit()
    return get_staff_detail(db, staff_user_id)


def update_my_availability(db: Session, staff_user_id: UUID, availability_status: str) -> dict:
    prof = db.scalar(select(StaffProfile).where(StaffProfile.user_id == staff_user_id))
    if not prof:
        raise HTTPException(status_code=404, detail="Staff profile not found")
    prof.availability_status = availability_status
    if availability_status == "off_duty":
        prof.is_on_duty = False
    elif availability_status == "available":
        prof.is_on_duty = True
    record_activity_log(
        db,
        activity_type="staff.availability_changed",
        description=f"Availability updated to {availability_status}",
        user_id=staff_user_id,
        canteen_id=prof.assigned_canteen_id,
    )
    db.commit()
    return {"user_id": str(staff_user_id), "availability_status": prof.availability_status, "is_on_duty": prof.is_on_duty}


def _assert_no_shift_conflict(
    db: Session,
    *,
    staff_user_id: UUID,
    shift_date: date,
    start_time: time,
    end_time: time,
    exclude_shift_id: Optional[UUID] = None,
) -> None:
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="Shift end_time must be after start_time")
    existing = db.scalars(
        select(StaffShift).where(
            StaffShift.staff_user_id == staff_user_id,
            StaffShift.shift_date == shift_date,
        )
    ).all()
    for ex in existing:
        if exclude_shift_id and ex.id == exclude_shift_id:
            continue
        if max(ex.start_time, start_time) < min(ex.end_time, end_time):
            raise HTTPException(
                status_code=409,
                detail=f"Overlapping shift already exists on {shift_date.isoformat()} ({ex.start_time.strftime('%H:%M')}-{ex.end_time.strftime('%H:%M')})",
            )


def schedule_shift(
    db: Session,
    *,
    staff_user_id: UUID,
    canteen_id: UUID,
    shift_date: date,
    start_time: time,
    end_time: time,
    shift_type: str,
    counter_id: Optional[UUID] = None,
    notes: Optional[str] = None,
    is_weekly_recurring: bool = False,
    actor_user_id: UUID,
) -> StaffShift:
    _assert_no_shift_conflict(
        db,
        staff_user_id=staff_user_id,
        shift_date=shift_date,
        start_time=start_time,
        end_time=end_time,
    )
    shift = StaffShift(
        staff_user_id=staff_user_id,
        canteen_id=canteen_id,
        counter_id=counter_id,
        shift_date=shift_date,
        start_time=start_time,
        end_time=end_time,
        shift_type=shift_type,
        status="scheduled",
        is_weekly_recurring=is_weekly_recurring,
        notes=notes,
        opening_cash_amount=Decimal("0.00"),
    )
    db.add(shift)
    record_audit_log(db, action="staff.shift_scheduled", entity_type="staff_shift", entity_id=str(staff_user_id), actor_user_id=actor_user_id)
    record_activity_log(
        db,
        activity_type="staff.shift_scheduled",
        description=f"Scheduled {shift_type} shift on {shift_date.isoformat()} ({start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')})",
        user_id=staff_user_id,
        canteen_id=canteen_id,
    )
    db.commit()
    db.refresh(shift)
    return shift


def update_shift(
    db: Session,
    shift_id: UUID,
    data: dict,
    actor_user_id: UUID,
) -> StaffShift:
    shift = db.get(StaffShift, shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    new_date = data.get("shift_date") or shift.shift_date
    new_start = data.get("start_time") or shift.start_time
    new_end = data.get("end_time") or shift.end_time
    _assert_no_shift_conflict(
        db,
        staff_user_id=shift.staff_user_id,
        shift_date=new_date,
        start_time=new_start,
        end_time=new_end,
        exclude_shift_id=shift.id,
    )
    for k, v in data.items():
        if v is not None:
            setattr(shift, k, v)
    record_audit_log(db, action="staff.shift_updated", entity_type="staff_shift", entity_id=str(shift.id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(shift)
    return shift


def delete_shift(db: Session, shift_id: UUID, actor_user_id: UUID) -> dict:
    shift = db.get(StaffShift, shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    if shift.status == "open":
        raise HTTPException(status_code=409, detail="Cannot delete an active open cash/duty shift")
    db.delete(shift)
    record_audit_log(db, action="staff.shift_deleted", entity_type="staff_shift", entity_id=str(shift_id), actor_user_id=actor_user_id)
    db.commit()
    return {"deleted": True, "id": str(shift_id)}


def upsert_weekly_schedule(
    db: Session,
    *,
    staff_user_id: UUID,
    canteen_id: UUID,
    day_of_week: int,
    start_time: time,
    end_time: time,
    shift_type: str,
    counter_id: Optional[UUID] = None,
    is_available: bool = True,
    actor_user_id: UUID,
) -> StaffWeeklySchedule:
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="Weekly shift end_time must be after start_time")
    existing = db.scalar(
        select(StaffWeeklySchedule).where(
            StaffWeeklySchedule.staff_user_id == staff_user_id,
            StaffWeeklySchedule.canteen_id == canteen_id,
            StaffWeeklySchedule.day_of_week == day_of_week,
            StaffWeeklySchedule.shift_type == shift_type,
        )
    )
    if existing:
        existing.start_time = start_time
        existing.end_time = end_time
        existing.counter_id = counter_id
        existing.is_available = is_available
        existing.is_active = True
        row = existing
    else:
        row = StaffWeeklySchedule(
            staff_user_id=staff_user_id,
            canteen_id=canteen_id,
            counter_id=counter_id,
            day_of_week=day_of_week,
            start_time=start_time,
            end_time=end_time,
            shift_type=shift_type,
            is_available=is_available,
            is_active=True,
        )
        db.add(row)
    record_audit_log(
        db,
        action="staff.weekly_schedule_saved",
        entity_type="staff_weekly_schedule",
        entity_id=str(staff_user_id),
        actor_user_id=actor_user_id,
        details={"day_of_week": day_of_week, "shift_type": shift_type},
    )
    db.commit()
    db.refresh(row)
    return row


def list_weekly_schedules(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    staff_user_id: Optional[UUID] = None,
) -> list[dict]:
    stmt = (
        select(StaffWeeklySchedule, User.full_name, Counter.name)
        .join(User, User.id == StaffWeeklySchedule.staff_user_id)
        .outerjoin(Counter, Counter.id == StaffWeeklySchedule.counter_id)
        .where(StaffWeeklySchedule.is_active.is_(True))
        .order_by(StaffWeeklySchedule.day_of_week, StaffWeeklySchedule.start_time)
    )
    if canteen_id:
        stmt = stmt.where(StaffWeeklySchedule.canteen_id == canteen_id)
    if staff_user_id:
        stmt = stmt.where(StaffWeeklySchedule.staff_user_id == staff_user_id)
    rows = db.execute(stmt).all()
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return [
        {
            "id": str(s.id),
            "staff_user_id": str(s.staff_user_id),
            "staff_name": fname,
            "canteen_id": str(s.canteen_id),
            "counter_id": str(s.counter_id) if s.counter_id else None,
            "counter_name": cname,
            "day_of_week": s.day_of_week,
            "day_name": day_names[s.day_of_week] if 0 <= s.day_of_week < 7 else str(s.day_of_week),
            "start_time": s.start_time.strftime("%H:%M:%S"),
            "end_time": s.end_time.strftime("%H:%M:%S"),
            "shift_type": s.shift_type,
            "is_available": s.is_available,
        }
        for s, fname, cname in rows
    ]


def generate_weekly_shifts_from_templates(
    db: Session,
    *,
    canteen_id: UUID,
    week_start_date: date,
    actor_user_id: UUID,
) -> dict:
    templates = db.scalars(
        select(StaffWeeklySchedule).where(
            StaffWeeklySchedule.canteen_id == canteen_id,
            StaffWeeklySchedule.is_active.is_(True),
            StaffWeeklySchedule.is_available.is_(True),
        )
    ).all()
    created_count = 0
    skipped_count = 0
    for tpl in templates:
        # Find exact date in [week_start_date .. week_start_date + 6] matching tpl.day_of_week
        offset = (tpl.day_of_week - week_start_date.weekday()) % 7
        target_date = week_start_date + timedelta(days=offset)
        existing = db.scalars(
            select(StaffShift).where(
                StaffShift.staff_user_id == tpl.staff_user_id,
                StaffShift.shift_date == target_date,
            )
        ).all()
        overlap = any(max(ex.start_time, tpl.start_time) < min(ex.end_time, tpl.end_time) for ex in existing)
        if overlap:
            skipped_count += 1
            continue
        db.add(
            StaffShift(
                staff_user_id=tpl.staff_user_id,
                canteen_id=tpl.canteen_id,
                counter_id=tpl.counter_id,
                shift_date=target_date,
                start_time=tpl.start_time,
                end_time=tpl.end_time,
                shift_type=tpl.shift_type,
                status="scheduled",
                is_weekly_recurring=True,
                notes="Generated from weekly duty template",
                opening_cash_amount=Decimal("0.00"),
            )
        )
        created_count += 1
    record_activity_log(
        db,
        activity_type="staff.weekly_roster_generated",
        description=f"Generated {created_count} shift(s) starting {week_start_date.isoformat()}",
        user_id=actor_user_id,
        canteen_id=canteen_id,
    )
    db.commit()
    return {"created": created_count, "skipped_existing": skipped_count, "week_start_date": week_start_date.isoformat()}


def check_in_staff(db: Session, staff_user_id: UUID, canteen_id: UUID) -> StaffAttendance:
    prof = db.scalar(select(StaffProfile).where(StaffProfile.user_id == staff_user_id))
    if prof and prof.assigned_canteen_id and prof.assigned_canteen_id != canteen_id:
        raise HTTPException(status_code=403, detail="Staff member is not assigned to this canteen")
    today = today_college()
    rec = db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.staff_user_id == staff_user_id, StaffAttendance.attendance_date == today
        )
    )
    now = datetime.now(timezone.utc)
    if rec and rec.status == "leave":
        raise HTTPException(status_code=409, detail="Approved leave exists for today")
    if not rec:
        rec = StaffAttendance(
            staff_user_id=staff_user_id,
            canteen_id=canteen_id,
            attendance_date=today,
            status="present",
            approval_status="approved",
            check_in_at=now,
        )
        db.add(rec)
    else:
        rec.status = "present"
        rec.approval_status = "approved"
        rec.check_in_at = rec.check_in_at or now
    if prof:
        prof.is_on_duty = True
        prof.availability_status = "available"
    record_activity_log(db, activity_type="staff.check_in", description="Staff checked in", user_id=staff_user_id, canteen_id=canteen_id)
    db.commit()
    db.refresh(rec)
    return rec


def check_out_staff(db: Session, staff_user_id: UUID) -> StaffAttendance:
    today = today_college()
    rec = db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.staff_user_id == staff_user_id, StaffAttendance.attendance_date == today
        )
    )
    if not rec or rec.status != "present":
        raise HTTPException(status_code=404, detail="No active check-in record for today")
    now = datetime.now(timezone.utc)
    rec.check_out_at = now
    if rec.check_in_at:
        cin = rec.check_in_at if rec.check_in_at.tzinfo else rec.check_in_at.replace(tzinfo=timezone.utc)
        rec.worked_minutes = max(0, int((now - cin).total_seconds() // 60))
    prof = db.scalar(select(StaffProfile).where(StaffProfile.user_id == staff_user_id))
    if prof:
        prof.is_on_duty = False
        prof.availability_status = "off_duty"
    record_activity_log(db, activity_type="staff.check_out", description="Staff checked out", user_id=staff_user_id, canteen_id=rec.canteen_id)
    db.commit()
    db.refresh(rec)
    return rec


def record_leave(
    db: Session,
    *,
    staff_user_id: UUID,
    canteen_id: UUID,
    attendance_date: date,
    end_date: Optional[date] = None,
    leave_type: str = "casual",
    reason: str,
    actor_user_id: UUID,
) -> StaffAttendance:
    existing = db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.staff_user_id == staff_user_id, StaffAttendance.attendance_date == attendance_date
        )
    )
    if existing:
        if existing.status == "present":
            raise HTTPException(status_code=409, detail="Staff already checked in on this date")
        if existing.status == "leave":
            raise HTTPException(status_code=409, detail="Leave already recorded for this date")
        existing.status = "leave"
        existing.leave_type = leave_type
        existing.end_date = end_date or attendance_date
        existing.approval_status = "approved"
        existing.leave_reason = reason
        existing.approved_by_user_id = actor_user_id
        record_activity_log(
            db,
            activity_type="staff.leave_recorded",
            description=f"Leave recorded for {attendance_date.isoformat()}",
            user_id=staff_user_id,
            canteen_id=canteen_id,
        )
        db.commit()
        db.refresh(existing)
        return existing

    rec = StaffAttendance(
        staff_user_id=staff_user_id,
        canteen_id=canteen_id,
        attendance_date=attendance_date,
        end_date=end_date or attendance_date,
        status="leave",
        leave_type=leave_type,
        approval_status="approved",
        leave_reason=reason,
        approved_by_user_id=actor_user_id,
    )
    db.add(rec)
    record_activity_log(
        db,
        activity_type="staff.leave_recorded",
        description=f"Leave recorded ({leave_type}) for {attendance_date.isoformat()}",
        user_id=staff_user_id,
        canteen_id=canteen_id,
    )
    db.commit()
    db.refresh(rec)
    return rec


def request_leave(
    db: Session,
    *,
    staff_user_id: UUID,
    canteen_id: UUID,
    attendance_date: date,
    end_date: Optional[date] = None,
    leave_type: str = "casual",
    reason: str,
) -> StaffAttendance:
    if end_date and end_date < attendance_date:
        raise HTTPException(status_code=400, detail="Leave end_date cannot be before start date")
    existing = db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.staff_user_id == staff_user_id, StaffAttendance.attendance_date == attendance_date
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Attendance record already exists for this date ({existing.status})")
    rec = StaffAttendance(
        staff_user_id=staff_user_id,
        canteen_id=canteen_id,
        attendance_date=attendance_date,
        end_date=end_date or attendance_date,
        status="leave_pending",
        leave_type=leave_type,
        approval_status="pending",
        leave_reason=reason,
    )
    db.add(rec)
    record_activity_log(db, activity_type="staff.leave_requested", description=f"Leave requested ({leave_type}) for {attendance_date}", user_id=staff_user_id, canteen_id=canteen_id)
    db.commit()
    db.refresh(rec)
    return rec


def review_leave(
    db: Session,
    attendance_id: UUID,
    *,
    approved: bool,
    review_notes: Optional[str] = None,
    mark_status: Optional[str] = None,
    actor_user_id: UUID,
) -> StaffAttendance:
    rec = db.get(StaffAttendance, attendance_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    if mark_status in ("present", "leave", "absent", "rejected"):
        rec.status = mark_status
    else:
        rec.status = "leave" if approved else "rejected"
    rec.approval_status = "approved" if approved else "rejected"
    rec.review_notes = review_notes
    rec.approved_by_user_id = actor_user_id
    record_audit_log(
        db,
        action="staff.leave_reviewed",
        entity_type="staff_attendance",
        entity_id=str(rec.id),
        actor_user_id=actor_user_id,
        details={"approved": approved, "status": rec.status, "review_notes": review_notes},
    )
    record_activity_log(
        db,
        activity_type="staff.attendance_reviewed",
        description=f"Attendance {rec.attendance_date.isoformat()} marked {rec.status} ({rec.approval_status})",
        user_id=rec.staff_user_id,
        canteen_id=rec.canteen_id,
    )
    db.commit()
    db.refresh(rec)
    return rec


def record_manual_attendance(
    db: Session,
    *,
    staff_user_id: UUID,
    canteen_id: UUID,
    attendance_date: date,
    status_val: str,
    notes: Optional[str],
    actor_user_id: UUID,
) -> StaffAttendance:
    rec = db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.staff_user_id == staff_user_id, StaffAttendance.attendance_date == attendance_date
        )
    )
    now = datetime.now(timezone.utc)
    if rec:
        rec.status = status_val
        rec.approval_status = "approved"
        rec.review_notes = notes
        rec.approved_by_user_id = actor_user_id
        if status_val == "present" and not rec.check_in_at:
            rec.check_in_at = now
    else:
        rec = StaffAttendance(
            staff_user_id=staff_user_id,
            canteen_id=canteen_id,
            attendance_date=attendance_date,
            status=status_val,
            approval_status="approved",
            check_in_at=now if status_val == "present" else None,
            leave_reason=notes if status_val in ("leave", "absent") else None,
            review_notes=notes,
            approved_by_user_id=actor_user_id,
        )
        db.add(rec)
    record_audit_log(
        db,
        action="staff.manual_attendance",
        entity_type="staff_attendance",
        entity_id=str(staff_user_id),
        actor_user_id=actor_user_id,
        details={"date": attendance_date.isoformat(), "status": status_val},
    )
    db.commit()
    db.refresh(rec)
    return rec


def create_task(db: Session, *, canteen_id: UUID, assigned_to_user_id: Optional[UUID], title: str, description: Optional[str], priority: str, is_urgent: bool, due_at: Optional[datetime] = None, actor_user_id: UUID) -> StaffTask:
    task = StaffTask(
        canteen_id=canteen_id,
        assigned_to_user_id=assigned_to_user_id,
        created_by_user_id=actor_user_id,
        title=title,
        description=description,
        priority=priority,
        is_urgent=is_urgent,
        due_at=due_at,
    )
    db.add(task)
    record_activity_log(
        db,
        activity_type="staff.task_assigned",
        description=f"Task created: '{title}' ({priority})",
        user_id=assigned_to_user_id or actor_user_id,
        canteen_id=canteen_id,
    )
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


def get_staff_dashboard(db: Session, canteen_id: Optional[UUID] = None) -> dict[str, Any]:
    today = today_college()
    sp_stmt = select(StaffProfile, User).join(User, User.id == StaffProfile.user_id)
    if canteen_id:
        sp_stmt = sp_stmt.where(StaffProfile.assigned_canteen_id == canteen_id)
    staff_rows = db.execute(sp_stmt).all()
    total_staff = len(staff_rows)
    active_staff = sum(1 for _, u in staff_rows if u.is_active)
    on_duty_now = sum(1 for sp, u in staff_rows if u.is_active and sp.is_on_duty)

    att_filters = []
    shift_filters = [StaffShift.shift_date == today]
    task_filters = []
    if canteen_id:
        att_filters.append(StaffAttendance.canteen_id == canteen_id)
        shift_filters.append(StaffShift.canteen_id == canteen_id)
        task_filters.append(StaffTask.canteen_id == canteen_id)

    present_today = db.scalar(
        select(func.count(StaffAttendance.id)).where(
            *att_filters, StaffAttendance.attendance_date == today, StaffAttendance.status == "present"
        )
    ) or 0
    on_leave_today = db.scalar(
        select(func.count(StaffAttendance.id)).where(
            *att_filters, StaffAttendance.attendance_date == today, StaffAttendance.status == "leave"
        )
    ) or 0
    pending_leave = db.scalar(
        select(func.count(StaffAttendance.id)).where(
            *att_filters, or_(StaffAttendance.status == "leave_pending", StaffAttendance.approval_status == "pending")
        )
    ) or 0
    shifts_today = db.scalar(select(func.count(StaffShift.id)).where(*shift_filters)) or 0
    open_tasks = db.scalar(
        select(func.count(StaffTask.id)).where(*task_filters, StaffTask.status != "done")
    ) or 0
    urgent_tasks = db.scalar(
        select(func.count(StaffTask.id)).where(*task_filters, StaffTask.status != "done", StaffTask.is_urgent.is_(True))
    ) or 0

    return {
        "total_staff": total_staff,
        "active_staff": active_staff,
        "on_duty_now": on_duty_now,
        "present_today": int(present_today),
        "on_leave_today": int(on_leave_today),
        "pending_leave_requests": int(pending_leave),
        "scheduled_shifts_today": int(shifts_today),
        "open_tasks": int(open_tasks),
        "urgent_tasks": int(urgent_tasks),
    }


def get_staff_workload_report(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, Any]:
    today = today_college()
    s_date = start_date or (today - timedelta(days=29))
    e_date = end_date or today
    s_dt = datetime.combine(s_date, time.min, tzinfo=timezone.utc)
    e_dt = datetime.combine(e_date, time.max, tzinfo=timezone.utc)

    staff_entries = list_staff_directory(db, canteen_id=canteen_id)
    if not staff_entries:
        return {"start_date": s_date.isoformat(), "end_date": e_date.isoformat(), "staff_metrics": []}

    user_ids = [UUID(s["user_id"]) for s in staff_entries]
    att_rows = db.scalars(
        select(StaffAttendance).where(
            StaffAttendance.staff_user_id.in_(user_ids),
            StaffAttendance.attendance_date >= s_date,
            StaffAttendance.attendance_date <= e_date,
        )
    ).all()
    shift_rows = db.scalars(
        select(StaffShift).where(
            StaffShift.staff_user_id.in_(user_ids),
            StaffShift.shift_date >= s_date,
            StaffShift.shift_date <= e_date,
        )
    ).all()
    task_rows = db.scalars(
        select(StaffTask).where(
            StaffTask.assigned_to_user_id.in_(user_ids),
            StaffTask.created_at >= s_dt,
            StaffTask.created_at <= e_dt,
        )
    ).all()
    assign_rows = db.execute(
        select(OrderAssignment.staff_user_id, func.count(OrderAssignment.id))
        .where(
            OrderAssignment.staff_user_id.in_(user_ids),
            OrderAssignment.created_at >= s_dt,
            OrderAssignment.created_at <= e_dt,
        )
        .group_by(OrderAssignment.staff_user_id)
    ).all()
    handover_rows = db.execute(
        select(OrderHandoverRecord.handed_over_by_user_id, func.count(OrderHandoverRecord.id))
        .where(
            OrderHandoverRecord.handed_over_by_user_id.in_(user_ids),
            OrderHandoverRecord.created_at >= s_dt,
            OrderHandoverRecord.created_at <= e_dt,
        )
        .group_by(OrderHandoverRecord.handed_over_by_user_id)
    ).all()
    pos_collected_rows = db.execute(
        select(OrderStatusHistory.changed_by_user_id, func.count(OrderStatusHistory.id))
        .where(
            OrderStatusHistory.changed_by_user_id.in_(user_ids),
            OrderStatusHistory.to_status == "PAYMENT_CONFIRMED",
            OrderStatusHistory.created_at >= s_dt,
            OrderStatusHistory.created_at <= e_dt,
        )
        .group_by(OrderStatusHistory.changed_by_user_id)
    ).all()

    assign_map = {uid: int(c) for uid, c in assign_rows if uid}
    handover_map = {uid: int(c) for uid, c in handover_rows if uid}
    pos_map = {uid: int(c) for uid, c in pos_collected_rows if uid}

    metrics = []
    for st in staff_entries:
        uid = UUID(st["user_id"])
        u_att = [a for a in att_rows if a.staff_user_id == uid]
        u_shifts = [s for s in shift_rows if s.staff_user_id == uid]
        u_tasks = [t for t in task_rows if t.assigned_to_user_id == uid]
        worked_mins = 0
        for a in u_att:
            if a.worked_minutes is not None:
                worked_mins += a.worked_minutes
            elif a.check_in_at and a.check_out_at:
                cin = a.check_in_at if a.check_in_at.tzinfo else a.check_in_at.replace(tzinfo=timezone.utc)
                cout = a.check_out_at if a.check_out_at.tzinfo else a.check_out_at.replace(tzinfo=timezone.utc)
                worked_mins += max(0, int((cout - cin).total_seconds() // 60))

        tasks_done = sum(1 for t in u_tasks if t.status == "done")
        task_rate = round((tasks_done / len(u_tasks)) * 100.0, 1) if u_tasks else 0.0
        kds_assigned = assign_map.get(uid, 0)
        handovers = handover_map.get(uid, 0)
        pos_orders = pos_map.get(uid, 0)

        metrics.append(
            {
                "user_id": st["user_id"],
                "full_name": st["full_name"],
                "employee_code": st["employee_code"],
                "designation": st["designation"],
                "roles": st["roles"],
                "availability_status": st["availability_status"],
                "is_on_duty": st["is_on_duty"],
                "present_days": sum(1 for a in u_att if a.status == "present"),
                "leave_days": sum(1 for a in u_att if a.status == "leave"),
                "shifts_scheduled": len(u_shifts),
                "worked_hours": round(worked_mins / 60.0, 1),
                "tasks_total": len(u_tasks),
                "tasks_completed": tasks_done,
                "task_completion_rate": task_rate,
                "orders_assigned_kds": kds_assigned,
                "orders_handed_over": handovers,
                "pos_payments_processed": pos_orders,
                "workload_score": tasks_done + kds_assigned + handovers + pos_orders,
            }
        )

    metrics.sort(key=lambda m: (-m["workload_score"], -m["worked_hours"]))
    return {
        "canteen_id": str(canteen_id) if canteen_id else None,
        "start_date": s_date.isoformat(),
        "end_date": e_date.isoformat(),
        "staff_metrics": metrics,
    }


def get_my_staff_overview(db: Session, user_id: UUID) -> dict[str, Any]:
    detail = get_staff_detail(db, user_id)
    today = today_college()
    today_att = db.scalar(
        select(StaffAttendance).where(
            StaffAttendance.staff_user_id == user_id,
            StaffAttendance.attendance_date == today,
        )
    )
    upcoming_shifts = list(
        db.scalars(
            select(StaffShift)
            .where(StaffShift.staff_user_id == user_id, StaffShift.shift_date >= today)
            .order_by(StaffShift.shift_date.asc(), StaffShift.start_time.asc())
            .limit(21)
        ).all()
    )
    weekly = list_weekly_schedules(db, staff_user_id=user_id)
    my_att = list(
        db.scalars(
            select(StaffAttendance)
            .where(StaffAttendance.staff_user_id == user_id)
            .order_by(StaffAttendance.attendance_date.desc())
            .limit(30)
        ).all()
    )
    my_tasks = list(
        db.scalars(
            select(StaffTask)
            .where(StaffTask.assigned_to_user_id == user_id)
            .order_by(StaffTask.created_at.desc())
            .limit(30)
        ).all()
    )
    my_activity = list(
        db.scalars(
            select(ActivityLog)
            .where(ActivityLog.user_id == user_id)
            .order_by(ActivityLog.created_at.desc())
            .limit(30)
        ).all()
    )
    return {
        "profile": detail,
        "today_attendance": today_att,
        "upcoming_shifts": upcoming_shifts,
        "weekly_schedules": weekly,
        "attendance_history": my_att,
        "tasks": my_tasks,
        "activity_logs": my_activity,
    }
