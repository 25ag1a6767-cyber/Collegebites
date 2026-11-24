from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_FOOD_SAFETY_INSPECTOR,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
)
from app.models.enterprise import CleaningTaskLog, EquipmentTemperatureConfig, FoodSafetyIncident, FoodSafetyInspection
from app.models.inventory import InventoryItem, StockBatch
from app.services import food_safety_service

router = APIRouter(prefix="/food-safety", tags=["Food Safety & Hygiene Compliance"])

FS_VIEW_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_FOOD_SAFETY_INSPECTOR,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
)
FS_INSPECT_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_FOOD_SAFETY_INSPECTOR,
)
FS_ADMIN_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_FOOD_SAFETY_INSPECTOR)


class ChecklistTemplateCreateIn(BaseModel):
    canteen_id: Optional[UUID] = None
    name: str = Field(min_length=3, max_length=160)
    category: str = Field(default="daily_hygiene", max_length=64)
    items: list[dict] = Field(min_length=1)


class InspectionItemIn(BaseModel):
    item_code: str = Field(min_length=1, max_length=64)
    item_title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="general", max_length=64)
    result: str = Field(pattern="^(pass|fail|not_applicable)$")
    notes: Optional[str] = None
    photo_url: Optional[str] = None


class InspectionCreateIn(BaseModel):
    canteen_id: UUID
    template_id: Optional[UUID] = None
    items: list[InspectionItemIn] = Field(min_length=1)
    notes: Optional[str] = None
    photo_urls: list[str] = Field(default_factory=list)
    inspected_at: Optional[datetime] = None


class EquipmentTempConfigIn(BaseModel):
    canteen_id: UUID
    equipment_name: str = Field(min_length=2, max_length=140)
    equipment_code: str = Field(min_length=2, max_length=48)
    equipment_type: str = Field(default="refrigerator", max_length=48)
    location: Optional[str] = None
    min_temp_c: Decimal
    max_temp_c: Decimal
    standard_reference: Optional[str] = None


class TemperatureLogIn(BaseModel):
    equipment_id: UUID
    recorded_temp_c: Decimal
    notes: Optional[str] = None
    corrective_action: Optional[str] = None
    recorded_at: Optional[datetime] = None


class BatchDisposalIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class CleaningScheduleIn(BaseModel):
    canteen_id: UUID
    area_name: str = Field(min_length=2, max_length=160)
    frequency: str = Field(default="daily", pattern="^(daily|weekly|monthly)$")
    instructions: Optional[str] = None
    assigned_staff_user_id: Optional[UUID] = None
    initial_due_at: Optional[datetime] = None


class CleaningTaskUpdateIn(BaseModel):
    status: str = Field(pattern="^(pending|in_progress|completed)$")
    evidence_url: Optional[str] = None
    notes: Optional[str] = None


class IncidentCreateIn(BaseModel):
    canteen_id: UUID
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=4000)
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    occurred_at: Optional[datetime] = None
    assigned_to_user_id: Optional[UUID] = None
    evidence_urls: list[str] = Field(default_factory=list)


class IncidentUpdateIn(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(open|under_investigation|resolved|closed)$")
    corrective_action: Optional[str] = None
    resolution_notes: Optional[str] = None
    assigned_to_user_id: Optional[UUID] = None


@router.get("/dashboard")
def get_dashboard(
    canteen_id: UUID = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return food_safety_service.get_food_safety_dashboard(db, canteen_id, days=days)


@router.get("/templates")
def get_templates(
    canteen_id: Optional[UUID] = Query(default=None),
    seed_default: bool = Query(default=True),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    return food_safety_service.list_checklist_templates(db, canteen_id, seed_default_if_empty=seed_default)


@router.post("/templates")
def create_template(
    payload: ChecklistTemplateCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    if payload.canteen_id:
        enforce_canteen_scope(principal, payload.canteen_id)
    return food_safety_service.create_checklist_template(
        db,
        canteen_id=payload.canteen_id,
        name=payload.name,
        category=payload.category,
        items=payload.items,
        actor_user_id=principal.user.id,
    )


@router.get("/inspections")
def list_inspections(
    canteen_id: UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return food_safety_service.list_inspections(db, canteen_id, limit=limit)


@router.post("/inspections")
def record_inspection(
    payload: InspectionCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_INSPECT_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return food_safety_service.create_inspection(
        db,
        canteen_id=payload.canteen_id,
        template_id=payload.template_id,
        items=[it.model_dump() for it in payload.items],
        notes=payload.notes,
        photo_urls=payload.photo_urls,
        inspected_at=payload.inspected_at,
        actor_user_id=principal.user.id,
    )


@router.get("/inspections/{inspection_id}/pdf")
def download_inspection_pdf(
    inspection_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    insp = db.get(FoodSafetyInspection, inspection_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")
    enforce_canteen_scope(principal, insp.canteen_id)
    pdf_bytes = food_safety_service.export_inspection_pdf(db, inspection_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{insp.inspection_number}.pdf"'},
    )


@router.get("/equipment")
def list_equipment(
    canteen_id: UUID = Query(...),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return food_safety_service.list_equipment_configs(db, canteen_id)


@router.post("/equipment")
def upsert_equipment(
    payload: EquipmentTempConfigIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return food_safety_service.upsert_equipment_config(
        db,
        canteen_id=payload.canteen_id,
        equipment_name=payload.equipment_name,
        equipment_code=payload.equipment_code,
        equipment_type=payload.equipment_type,
        location=payload.location,
        min_temp_c=payload.min_temp_c,
        max_temp_c=payload.max_temp_c,
        standard_reference=payload.standard_reference,
        actor_user_id=principal.user.id,
    )


@router.get("/temperatures")
def list_temperatures(
    canteen_id: UUID = Query(...),
    equipment_id: Optional[UUID] = Query(default=None),
    violations_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=300),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return food_safety_service.list_temperature_logs(
        db, canteen_id, equipment_id=equipment_id, violations_only=violations_only, limit=limit
    )


@router.post("/temperatures")
def log_temperature(
    payload: TemperatureLogIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    cfg = db.get(EquipmentTemperatureConfig, payload.equipment_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Equipment configuration not found")
    enforce_canteen_scope(principal, cfg.canteen_id)
    return food_safety_service.record_temperature_log(
        db,
        equipment_id=payload.equipment_id,
        recorded_temp_c=payload.recorded_temp_c,
        notes=payload.notes,
        corrective_action=payload.corrective_action,
        recorded_at=payload.recorded_at,
        actor_user_id=principal.user.id,
    )


@router.get("/expiry-monitoring")
def expiry_monitoring(
    canteen_id: UUID = Query(...),
    soon_days: int = Query(default=7, ge=1, le=90),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return food_safety_service.get_expiry_monitoring(db, canteen_id, soon_days=soon_days)


@router.post("/batches/{batch_id}/dispose")
def dispose_batch(
    batch_id: UUID,
    payload: BatchDisposalIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_ADMIN_ROLES, ROLE_INVENTORY_MANAGER)),
    db: Session = Depends(get_db),
):
    batch = db.get(StockBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Stock batch not found")
    inv = db.get(InventoryItem, batch.inventory_item_id)
    if inv:
        enforce_canteen_scope(principal, inv.canteen_id)
    return food_safety_service.dispose_expired_batch(db, batch_id, reason=payload.reason, actor_user_id=principal.user.id)


@router.get("/cleaning")
def list_cleaning(
    canteen_id: UUID = Query(...),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return food_safety_service.list_cleaning_schedules_and_tasks(db, canteen_id)


@router.post("/cleaning/schedules")
def create_cleaning_schedule(
    payload: CleaningScheduleIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return food_safety_service.create_cleaning_schedule(
        db,
        canteen_id=payload.canteen_id,
        area_name=payload.area_name,
        frequency=payload.frequency,
        instructions=payload.instructions,
        assigned_staff_user_id=payload.assigned_staff_user_id,
        initial_due_at=payload.initial_due_at,
        actor_user_id=principal.user.id,
    )


@router.patch("/cleaning/tasks/{task_id}")
def update_cleaning_task(
    task_id: UUID,
    payload: CleaningTaskUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    task = db.get(CleaningTaskLog, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Cleaning task not found")
    enforce_canteen_scope(principal, task.canteen_id)
    return food_safety_service.update_cleaning_task(
        db,
        task_id,
        status=payload.status,
        evidence_url=payload.evidence_url,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )


@router.post("/cleaning/notify-overdue")
def trigger_overdue_cleaning_reminders(
    canteen_id: UUID = Query(...),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return food_safety_service.notify_overdue_cleaning_tasks(db, canteen_id)


@router.get("/incidents")
def list_incidents(
    canteen_id: UUID = Query(...),
    status: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return food_safety_service.list_incidents(db, canteen_id, status_filter=status)


@router.post("/incidents")
def create_incident(
    payload: IncidentCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return food_safety_service.create_incident(
        db,
        canteen_id=payload.canteen_id,
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        occurred_at=payload.occurred_at,
        assigned_to_user_id=payload.assigned_to_user_id,
        evidence_urls=payload.evidence_urls,
        actor_user_id=principal.user.id,
    )


@router.patch("/incidents/{incident_id}")
def update_incident(
    incident_id: UUID,
    payload: IncidentUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FS_INSPECT_ROLES)),
    db: Session = Depends(get_db),
):
    inc = db.get(FoodSafetyIncident, incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Food safety incident not found")
    enforce_canteen_scope(principal, inc.canteen_id)
    return food_safety_service.update_incident(
        db,
        incident_id,
        status=payload.status,
        corrective_action=payload.corrective_action,
        resolution_notes=payload.resolution_notes,
        assigned_to_user_id=payload.assigned_to_user_id,
        actor_user_id=principal.user.id,
    )
