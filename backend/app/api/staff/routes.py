from datetime import date, time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
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
    require_roles,
)
from app.models.staff import StaffAttendance, StaffShift, StaffTask
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


class ShiftScheduleIn(BaseModel):
    staff_user_id: UUID
    canteen_id: UUID
    shift_date: date
    start_time: time
    end_time: time
    shift_type: str = Field(default="regular", pattern="^(morning|afternoon|regular|cashier)$")


class LeaveIn(BaseModel):
    staff_user_id: UUID
    canteen_id: UUID
    attendance_date: date
    reason: str = Field(min_length=2, max_length=255)


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
    return staff_service.list_staff_directory(db, canteen_id=canteen_id)


@router.get("/shifts")
def list_shifts(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    stmt = select(StaffShift).order_by(StaffShift.shift_date.desc())
    if canteen_id:
        stmt = stmt.where(StaffShift.canteen_id == canteen_id)
    if not principal.has_role(*MANAGER_ROLES):
        stmt = stmt.where(StaffShift.staff_user_id == principal.user.id)
    return list(db.scalars(stmt.limit(100)).all())


@router.post("/shifts", status_code=status.HTTP_201_CREATED)
def schedule_shift(
    payload: ShiftScheduleIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return staff_service.schedule_shift(db, **payload.model_dump(), actor_user_id=principal.user.id)


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


@router.post("/attendance/leave", status_code=status.HTTP_201_CREATED)
def record_leave(
    payload: LeaveIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return staff_service.record_leave(db, **payload.model_dump(), actor_user_id=principal.user.id)


@router.get("/attendance")
def list_attendance(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    stmt = select(StaffAttendance).order_by(StaffAttendance.attendance_date.desc())
    if canteen_id:
        stmt = stmt.where(StaffAttendance.canteen_id == canteen_id)
    if not principal.has_role(*MANAGER_ROLES):
        stmt = stmt.where(StaffAttendance.staff_user_id == principal.user.id)
    return list(db.scalars(stmt.limit(100)).all())


@router.get("/tasks")
def list_tasks(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    stmt = select(StaffTask).order_by(StaffTask.created_at.desc())
    if canteen_id:
        stmt = stmt.where(StaffTask.canteen_id == canteen_id)
    if not principal.has_role(*MANAGER_ROLES):
        stmt = stmt.where(StaffTask.assigned_to_user_id == principal.user.id)
    return list(db.scalars(stmt.limit(100)).all())


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return staff_service.create_task(db, **payload.model_dump(), actor_user_id=principal.user.id)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: UUID,
    payload: TaskUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*ALL_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    return staff_service.update_task_status(db, task_id, payload.status, principal.user.id)


@router.get("/activity")
def list_staff_activity(
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(100)).all())
