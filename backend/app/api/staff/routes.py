from datetime import date, time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
    scoped_canteen_for_principal,
)
from app.models.auth import User
from app.models.staff import StaffAttendance, StaffShift, StaffTask, StaffWeeklySchedule
from app.models.system import ActivityLog
from app.services import staff_service

router = APIRouter(prefix="/staff", tags=["Staff Operations"])

ALL_STAFF_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
    ROLE_PICKUP_STAFF,
)
MANAGER_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)


class StaffUpdateIn(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    phone: Optional[str] = Field(default=None, max_length=20)
    designation: Optional[str] = Field(default=None, min_length=2, max_length=120)
    assigned_canteen_id: Optional[UUID] = None
    assigned_counter_id: Optional[UUID] = None
    assigned_kitchen_id: Optional[UUID] = None
    availability_status: Optional[str] = Field(default=None, pattern="^(available|busy|on_break|off_duty|on_leave)$")
    weekly_hours_target: Optional[int] = Field(default=None, ge=1, le=84)
    is_active: Optional[bool] = None


class SelfAvailabilityIn(BaseModel):
    availability_status: str = Field(pattern="^(available|busy|on_break|off_duty)$")


class ShiftScheduleIn(BaseModel):
    staff_user_id: UUID
    canteen_id: UUID
    counter_id: Optional[UUID] = None
    shift_date: date
    start_time: time
    end_time: time
    shift_type: str = Field(default="regular", pattern="^(morning|afternoon|evening|night|regular|cashier)$")
    notes: Optional[str] = Field(default=None, max_length=255)


class ShiftUpdateIn(BaseModel):
    shift_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    shift_type: Optional[str] = Field(default=None, pattern="^(morning|afternoon|evening|night|regular|cashier)$")
    counter_id: Optional[UUID] = None
    notes: Optional[str] = Field(default=None, max_length=255)


class WeeklyScheduleIn(BaseModel):
    staff_user_id: UUID
    canteen_id: UUID
    counter_id: Optional[UUID] = None
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    shift_type: str = Field(default="regular", pattern="^(morning|afternoon|evening|night|regular|cashier|kitchen|pickup)$")
    is_available: bool = True


class GenerateWeekIn(BaseModel):
    canteen_id: UUID
    week_start_date: date


class LeaveIn(BaseModel):
    staff_user_id: UUID
    canteen_id: UUID
    attendance_date: date
    end_date: Optional[date] = None
    leave_type: str = Field(default="casual", pattern="^(casual|sick|emergency|unpaid)$")
    reason: str = Field(min_length=2, max_length=255)


class SelfLeaveRequestIn(BaseModel):
    canteen_id: Optional[UUID] = None
    attendance_date: date
    end_date: Optional[date] = None
    leave_type: str = Field(default="casual", pattern="^(casual|sick|emergency|unpaid)$")
    reason: str = Field(min_length=2, max_length=255)


class LeaveReviewIn(BaseModel):
    approved: bool
    review_notes: Optional[str] = Field(default=None, max_length=255)
    mark_status: Optional[str] = Field(default=None, pattern="^(present|leave|absent|rejected)$")


class ManualAttendanceIn(BaseModel):
    staff_user_id: UUID
    canteen_id: UUID
    attendance_date: date
    status: str = Field(pattern="^(present|leave|absent)$")
    notes: Optional[str] = Field(default=None, max_length=255)


class TaskCreateIn(BaseModel):
    canteen_id: UUID
    assigned_to_user_id: Optional[UUID] = None
    title: str = Field(min_length=2, max_length=160)
    description: Optional[str] = None
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    is_urgent: bool = False


class TaskUpdateIn(BaseModel):
    status: str = Field(pattern="^(pending|in_progress|done)$")


@router.get("")
def list_staff(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    effective_cid = scoped_canteen_for_principal(principal, canteen_id)
    return staff_service.list_staff_directory(db, canteen_id=effective_cid)


@router.get("/dashboard")
def staff_dashboard(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    effective_cid = scoped_canteen_for_principal(principal, canteen_id)
    return staff_service.get_staff_dashboard(db, canteen_id=effective_cid)


@router.get("/workload")
def staff_workload_report(
    canteen_id: Optional[UUID] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    effective_cid = scoped_canteen_for_principal(principal, canteen_id)
    return staff_service.get_staff_workload_report(
        db,
        canteen_id=effective_cid,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/me/overview")
def my_staff_overview(
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    return staff_service.get_my_staff_overview(db, principal.user.id)


@router.patch("/me/availability")
def update_my_availability(
    payload: SelfAvailabilityIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    return staff_service.update_my_availability(db, principal.user.id, payload.availability_status)


@router.get("/weekly-schedules")
def list_weekly_schedules(
    canteen_id: Optional[UUID] = Query(default=None),
    staff_user_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    if principal.has_role(*MANAGER_ROLES):
        effective_cid = scoped_canteen_for_principal(principal, canteen_id)
        return staff_service.list_weekly_schedules(db, canteen_id=effective_cid, staff_user_id=staff_user_id)
    return staff_service.list_weekly_schedules(db, canteen_id=None, staff_user_id=principal.user.id)


@router.post("/weekly-schedules", status_code=status.HTTP_201_CREATED)
def upsert_weekly_schedule(
    payload: WeeklyScheduleIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return staff_service.upsert_weekly_schedule(db, **payload.model_dump(), actor_user_id=principal.user.id)


@router.delete("/weekly-schedules/{schedule_id}")
def delete_weekly_schedule(
    schedule_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    row = db.get(StaffWeeklySchedule, schedule_id)
    if not row:
        raise HTTPException(status_code=404, detail="Weekly duty schedule not found")
    enforce_canteen_scope(principal, row.canteen_id)
    row.is_active = False
    db.commit()
    return {"deleted": True, "id": str(schedule_id)}


@router.post("/weekly-schedules/generate-week")
def generate_weekly_shifts(
    payload: GenerateWeekIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return staff_service.generate_weekly_shifts_from_templates(
        db,
        canteen_id=payload.canteen_id,
        week_start_date=payload.week_start_date,
        actor_user_id=principal.user.id,
    )


@router.get("/shifts")
def list_shifts(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    stmt = select(StaffShift).order_by(StaffShift.shift_date.desc())
    if principal.has_role(*MANAGER_ROLES):
        effective_cid = scoped_canteen_for_principal(principal, canteen_id)
        if effective_cid:
            stmt = stmt.where(StaffShift.canteen_id == effective_cid)
    else:
        stmt = stmt.where(StaffShift.staff_user_id == principal.user.id)
        if canteen_id:
            enforce_canteen_scope(principal, canteen_id)
            stmt = stmt.where(StaffShift.canteen_id == canteen_id)
    return list(db.scalars(stmt.limit(100)).all())


@router.post("/shifts", status_code=status.HTTP_201_CREATED)
def schedule_shift(
    payload: ShiftScheduleIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return staff_service.schedule_shift(db, **payload.model_dump(), actor_user_id=principal.user.id)


@router.patch("/shifts/{shift_id}")
def update_shift(
    shift_id: UUID,
    payload: ShiftUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    shift = db.get(StaffShift, shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    enforce_canteen_scope(principal, shift.canteen_id)
    return staff_service.update_shift(db, shift_id, payload.model_dump(exclude_unset=True), principal.user.id)


@router.delete("/shifts/{shift_id}")
def delete_shift(
    shift_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    shift = db.get(StaffShift, shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    enforce_canteen_scope(principal, shift.canteen_id)
    return staff_service.delete_shift(db, shift_id, principal.user.id)


@router.post("/attendance/check-in")
def check_in(
    canteen_id: UUID = Query(...),
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    return staff_service.check_in_staff(db, principal.user.id, canteen_id)


@router.post("/attendance/check-out")
def check_out(
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    return staff_service.check_out_staff(db, principal.user.id)


@router.post("/attendance/leave/request", status_code=status.HTTP_201_CREATED)
def request_leave(
    payload: SelfLeaveRequestIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    cid = payload.canteen_id or principal.assigned_canteen_id
    if not cid:
        raise HTTPException(status_code=400, detail="canteen_id is required when staff has no assigned canteen")
    if principal.assigned_canteen_id and payload.canteen_id and payload.canteen_id != principal.assigned_canteen_id:
        enforce_canteen_scope(principal, payload.canteen_id)
    return staff_service.request_leave(
        db,
        staff_user_id=principal.user.id,
        canteen_id=cid,
        attendance_date=payload.attendance_date,
        end_date=payload.end_date,
        leave_type=payload.leave_type,
        reason=payload.reason,
    )


@router.post("/attendance/leave", status_code=status.HTTP_201_CREATED)
def record_leave(
    payload: LeaveIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return staff_service.record_leave(db, **payload.model_dump(), actor_user_id=principal.user.id)


@router.post("/attendance/manual")
def mark_manual_attendance(
    payload: ManualAttendanceIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return staff_service.record_manual_attendance(
        db,
        staff_user_id=payload.staff_user_id,
        canteen_id=payload.canteen_id,
        attendance_date=payload.attendance_date,
        status_val=payload.status,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )


@router.patch("/attendance/{attendance_id}/review")
def review_leave(
    attendance_id: UUID,
    payload: LeaveReviewIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    rec = db.get(StaffAttendance, attendance_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    enforce_canteen_scope(principal, rec.canteen_id)
    return staff_service.review_leave(
        db,
        attendance_id,
        approved=payload.approved,
        review_notes=payload.review_notes,
        mark_status=payload.mark_status,
        actor_user_id=principal.user.id,
    )


@router.get("/attendance")
def list_attendance(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    stmt = select(StaffAttendance).order_by(StaffAttendance.attendance_date.desc())
    if principal.has_role(*MANAGER_ROLES):
        effective_cid = scoped_canteen_for_principal(principal, canteen_id)
        if effective_cid:
            stmt = stmt.where(StaffAttendance.canteen_id == effective_cid)
    else:
        stmt = stmt.where(StaffAttendance.staff_user_id == principal.user.id)
        if canteen_id:
            enforce_canteen_scope(principal, canteen_id)
            stmt = stmt.where(StaffAttendance.canteen_id == canteen_id)
    return list(db.scalars(stmt.limit(100)).all())


@router.get("/tasks")
def list_tasks(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    stmt = select(StaffTask).order_by(StaffTask.created_at.desc())
    if principal.has_role(*MANAGER_ROLES):
        effective_cid = scoped_canteen_for_principal(principal, canteen_id)
        if effective_cid:
            stmt = stmt.where(StaffTask.canteen_id == effective_cid)
    else:
        stmt = stmt.where(StaffTask.assigned_to_user_id == principal.user.id)
        if canteen_id:
            enforce_canteen_scope(principal, canteen_id)
            stmt = stmt.where(StaffTask.canteen_id == canteen_id)
    return list(db.scalars(stmt.limit(100)).all())


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return staff_service.create_task(db, **payload.model_dump(), actor_user_id=principal.user.id)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: UUID,
    payload: TaskUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    task = db.get(StaffTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if principal.has_role(*MANAGER_ROLES):
        enforce_canteen_scope(principal, task.canteen_id)
    elif task.assigned_to_user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Staff can only update tasks assigned to them")
    return staff_service.update_task_status(db, task_id, payload.status, principal.user.id)


@router.get("/activity")
def list_staff_activity(
    canteen_id: Optional[UUID] = Query(default=None),
    user_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    effective_cid = scoped_canteen_for_principal(principal, canteen_id)
    stmt = (
        select(ActivityLog, User.full_name)
        .outerjoin(User, User.id == ActivityLog.user_id)
        .order_by(ActivityLog.created_at.desc())
    )
    if effective_cid:
        stmt = stmt.where(ActivityLog.canteen_id == effective_cid)
    if user_id:
        stmt = stmt.where(ActivityLog.user_id == user_id)
    rows = db.execute(stmt.limit(limit)).all()
    return [
        {
            "id": str(log.id),
            "user_id": str(log.user_id) if log.user_id else None,
            "user_name": uname or "System",
            "canteen_id": str(log.canteen_id) if log.canteen_id else None,
            "activity_type": log.activity_type,
            "description": log.description,
            "metadata_json": log.metadata_json,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log, uname in rows
    ]


@router.get("/{staff_user_id}")
def get_staff_member(
    staff_user_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    if staff_user_id != principal.user.id and not principal.has_role(*MANAGER_ROLES):
        raise HTTPException(status_code=403, detail="Not authorized to view another staff member's profile")
    detail = staff_service.get_staff_detail(db, staff_user_id)
    if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) and staff_user_id != principal.user.id:
        if detail["assigned_canteen_id"] and UUID(detail["assigned_canteen_id"]) != principal.assigned_canteen_id:
            raise HTTPException(status_code=403, detail="Staff member belongs to another canteen")
    return detail


@router.patch("/{staff_user_id}")
def update_staff_member(
    staff_user_id: UUID,
    payload: StaffUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    is_admin = principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)
    return staff_service.update_staff_member(
        db,
        staff_user_id,
        payload.model_dump(exclude_unset=True),
        actor_user_id=principal.user.id,
        is_college_admin=is_admin,
        actor_canteen_id=principal.assigned_canteen_id,
    )
