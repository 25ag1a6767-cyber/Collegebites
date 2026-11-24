from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.models.enterprise import ProductionBatch
from app.models.menu import FoodItem
from app.services import production_service

router = APIRouter(prefix="/production", tags=["Kitchen & Food Production Management"])

PROD_VIEW_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
    ROLE_FOOD_SAFETY_INSPECTOR,
)
PROD_MANAGE_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF)
PROD_APPROVE_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_FOOD_SAFETY_INSPECTOR)


class RecipeIngredientIn(BaseModel):
    ingredient_id: UUID
    quantity_required: Decimal = Field(gt=0)
    unit: Optional[str] = Field(default=None, max_length=32)


class RecipeUpsertIn(BaseModel):
    yield_portions: int = Field(default=1, ge=1, le=5000)
    instructions: Optional[str] = None
    ingredients: list[RecipeIngredientIn] = Field(min_length=1)
    verify: bool = False


class ProductionPlanCreateIn(BaseModel):
    canteen_id: UUID
    plan_date: date
    meal_session: str = Field(default="all_day", max_length=32)
    notes: Optional[str] = None


class ProductionBatchCreateIn(BaseModel):
    canteen_id: UUID
    food_item_id: UUID
    planned_quantity: int = Field(ge=1, le=10000)
    allocation_strategy: str = Field(default="FEFO", pattern="^(FEFO|FIFO)$")
    production_plan_id: Optional[UUID] = None
    assigned_staff_user_id: Optional[UUID] = None
    planned_prep_at: Optional[datetime] = None
    notes: Optional[str] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=96)


class BatchTransitionIn(BaseModel):
    target_status: str = Field(
        pattern="^(ingredients_allocated|ready_for_preparation|preparing|prepared|quality_checked|completed|cancelled)$"
    )
    actual_quantity: Optional[int] = Field(default=None, ge=0)
    allow_batch_override: bool = False
    override_reason: Optional[str] = None
    notes: Optional[str] = None


class QualityCheckIn(BaseModel):
    appearance_ok: bool = True
    preparation_ok: bool = True
    hygiene_ok: bool = True
    temperature_c: Optional[Decimal] = None
    status: str = Field(default="passed", pattern="^(passed|failed|corrective_action_required)$")
    notes: Optional[str] = None
    evidence_url: Optional[str] = None
    corrective_action: Optional[str] = None
    approve_corrective_action: bool = False


class BatchQuantitiesIn(BaseModel):
    actual_quantity: Optional[int] = Field(default=None, ge=0)
    sold_quantity: Optional[int] = Field(default=None, ge=0)
    waste_quantity: Optional[int] = Field(default=None, ge=0)
    waste_reason: Optional[str] = None


@router.get("/recipes")
def list_recipes(
    canteen_id: UUID = Query(...),
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return production_service.list_recipes(db, canteen_id)


@router.put("/recipes/{food_item_id}")
def upsert_recipe(
    food_item_id: UUID,
    payload: RecipeUpsertIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_APPROVE_ROLES, ROLE_INVENTORY_MANAGER)),
    db: Session = Depends(get_db),
):
    food = db.get(FoodItem, food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, food.canteen_id)
    return production_service.upsert_recipe(
        db,
        food_item_id=food_item_id,
        yield_portions=payload.yield_portions,
        instructions=payload.instructions,
        ingredients=[it.model_dump() for it in payload.ingredients],
        verify=payload.verify,
        actor_user_id=principal.user.id,
    )


@router.post("/recipes/{food_item_id}/verify")
def verify_recipe(
    food_item_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_APPROVE_ROLES)),
    db: Session = Depends(get_db),
):
    food = db.get(FoodItem, food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, food.canteen_id)
    return production_service.verify_recipe(db, food_item_id, actor_user_id=principal.user.id)


@router.get("/recipes/{food_item_id}/requirements")
def recipe_requirements(
    food_item_id: UUID,
    quantity: int = Query(default=10, ge=1, le=10000),
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    food = db.get(FoodItem, food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, food.canteen_id)
    return production_service.compute_recipe_requirements(db, food_item_id, quantity=quantity)


@router.get("/planning")
def production_planning(
    canteen_id: UUID = Query(...),
    plan_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return production_service.get_production_planning_overview(db, canteen_id, plan_date=plan_date)


@router.get("/plans")
def list_plans(
    canteen_id: UUID = Query(...),
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return production_service.list_production_plans(db, canteen_id)


@router.post("/plans")
def create_plan(
    payload: ProductionPlanCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return production_service.create_production_plan(
        db,
        canteen_id=payload.canteen_id,
        plan_date=payload.plan_date,
        meal_session=payload.meal_session,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )


@router.get("/batches")
def list_batches(
    canteen_id: UUID = Query(...),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=80, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return production_service.list_production_batches(db, canteen_id, status_filter=status, limit=limit)


@router.post("/batches")
def create_batch(
    payload: ProductionBatchCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return production_service.create_production_batch(
        db,
        canteen_id=payload.canteen_id,
        food_item_id=payload.food_item_id,
        planned_quantity=payload.planned_quantity,
        allocation_strategy=payload.allocation_strategy,
        production_plan_id=payload.production_plan_id,
        assigned_staff_user_id=payload.assigned_staff_user_id,
        planned_prep_at=payload.planned_prep_at,
        notes=payload.notes,
        idempotency_key=payload.idempotency_key,
        actor_user_id=principal.user.id,
    )


@router.post("/batches/{batch_id}/transition")
def transition_batch(
    batch_id: UUID,
    payload: BatchTransitionIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_MANAGE_ROLES, ROLE_FOOD_SAFETY_INSPECTOR)),
    db: Session = Depends(get_db),
):
    b = db.get(ProductionBatch, batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="Production batch not found")
    enforce_canteen_scope(principal, b.canteen_id)
    can_override = principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    return production_service.transition_production_batch(
        db,
        batch_id,
        target_status=payload.target_status,
        actual_quantity=payload.actual_quantity,
        allow_batch_override=payload.allow_batch_override,
        override_reason=payload.override_reason,
        can_override=can_override,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )


@router.post("/batches/{batch_id}/quality-check")
def quality_check(
    batch_id: UUID,
    payload: QualityCheckIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_MANAGE_ROLES, ROLE_FOOD_SAFETY_INSPECTOR)),
    db: Session = Depends(get_db),
):
    b = db.get(ProductionBatch, batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="Production batch not found")
    enforce_canteen_scope(principal, b.canteen_id)
    can_approve = principal.has_role(*PROD_APPROVE_ROLES)
    return production_service.record_quality_check(
        db,
        batch_id,
        appearance_ok=payload.appearance_ok,
        preparation_ok=payload.preparation_ok,
        hygiene_ok=payload.hygiene_ok,
        temperature_c=payload.temperature_c,
        status=payload.status,
        notes=payload.notes,
        evidence_url=payload.evidence_url,
        corrective_action=payload.corrective_action,
        approve_corrective_action=payload.approve_corrective_action,
        can_approve=can_approve,
        actor_user_id=principal.user.id,
    )


@router.patch("/batches/{batch_id}/quantities")
def update_quantities(
    batch_id: UUID,
    payload: BatchQuantitiesIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    b = db.get(ProductionBatch, batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="Production batch not found")
    enforce_canteen_scope(principal, b.canteen_id)
    return production_service.update_batch_quantities(
        db,
        batch_id,
        actual_quantity=payload.actual_quantity,
        sold_quantity=payload.sold_quantity,
        waste_quantity=payload.waste_quantity,
        waste_reason=payload.waste_reason,
        actor_user_id=principal.user.id,
    )


@router.get("/report")
def production_report(
    canteen_id: UUID = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROD_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return production_service.get_production_report(db, canteen_id, days=days)
