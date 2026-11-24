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
    ROLE_INVENTORY_MANAGER,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
)
from app.models.enterprise import ReorderRecommendation
from app.models.inventory import InventoryItem
from app.services import reorder_service

router = APIRouter(prefix="/reordering", tags=["Automated Reordering System"])

REORDER_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)


class ReorderRuleUpsertIn(BaseModel):
    min_stock_level: Decimal = Field(default=Decimal("0.000"), ge=0)
    reorder_level: Decimal = Field(ge=0)
    safety_stock: Decimal = Field(default=Decimal("0.000"), ge=0)
    supplier_lead_time_days: int = Field(default=2, ge=0, le=90)
    target_days_of_cover: int = Field(default=7, ge=1, le=90)
    preferred_supplier_id: Optional[UUID] = None
    is_active: bool = True


class DraftPOFromRecIn(BaseModel):
    supplier_id: Optional[UUID] = None
    quantity_override: Optional[Decimal] = Field(default=None, gt=0)
    unit_cost_override: Optional[Decimal] = Field(default=None, ge=0)
    notes: Optional[str] = None


class DismissRecIn(BaseModel):
    notes: Optional[str] = None


@router.get("/rules")
def list_rules(
    canteen_id: UUID = Query(...),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REORDER_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return reorder_service.list_reorder_rules(db, canteen_id)


@router.put("/rules/{inventory_item_id}")
def upsert_rule(
    inventory_item_id: UUID,
    payload: ReorderRuleUpsertIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*REORDER_ROLES)),
    db: Session = Depends(get_db),
):
    inv = db.get(InventoryItem, inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return reorder_service.upsert_reorder_rule(
        db,
        inventory_item_id=inventory_item_id,
        min_stock_level=payload.min_stock_level,
        reorder_level=payload.reorder_level,
        safety_stock=payload.safety_stock,
        supplier_lead_time_days=payload.supplier_lead_time_days,
        target_days_of_cover=payload.target_days_of_cover,
        preferred_supplier_id=payload.preferred_supplier_id,
        is_active=payload.is_active,
        actor_user_id=principal.user.id,
    )


@router.get("/recommendations")
def list_recommendations(
    canteen_id: UUID = Query(...),
    status: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REORDER_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return reorder_service.list_reorder_recommendations(db, canteen_id, status_filter=status)


@router.post("/recommendations/generate")
def generate_recommendations(
    canteen_id: UUID = Query(...),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REORDER_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return reorder_service.generate_reorder_recommendations(db, canteen_id, actor_user_id=principal.user.id)


@router.post("/recommendations/{recommendation_id}/create-draft-po")
def create_draft_po(
    recommendation_id: UUID,
    payload: DraftPOFromRecIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*REORDER_ROLES)),
    db: Session = Depends(get_db),
):
    rec = db.get(ReorderRecommendation, recommendation_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Reorder recommendation not found")
    enforce_canteen_scope(principal, rec.canteen_id)
    return reorder_service.create_draft_po_from_recommendation(
        db,
        recommendation_id,
        supplier_id=payload.supplier_id,
        quantity_override=payload.quantity_override,
        unit_cost_override=payload.unit_cost_override,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )


@router.post("/recommendations/{recommendation_id}/dismiss")
def dismiss_recommendation(
    recommendation_id: UUID,
    payload: DismissRecIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*REORDER_ROLES)),
    db: Session = Depends(get_db),
):
    rec = db.get(ReorderRecommendation, recommendation_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Reorder recommendation not found")
    enforce_canteen_scope(principal, rec.canteen_id)
    return reorder_service.dismiss_recommendation(
        db,
        recommendation_id,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )
