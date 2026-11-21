from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_INVENTORY_MANAGER,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    require_roles,
)
from app.models.inventory import PurchaseOrder
from app.services import inventory_service

router = APIRouter(prefix="/inventory", tags=["Inventory, Recipes & Suppliers"])

INV_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)


class SupplierCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    gst_number: Optional[str] = None


class IngredientCreate(BaseModel):
    canteen_id: UUID
    name: str = Field(min_length=2, max_length=120)
    sku: str = Field(min_length=2, max_length=64)
    unit: str = Field(default="grams")
    initial_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    reorder_level: Decimal = Field(default=Decimal("100"), ge=0)
    unit_cost: Decimal = Field(default=Decimal("0.00"), ge=0)
    expiry_date: Optional[date] = None
    is_allergen: bool = False


class RecipeIngredientIn(BaseModel):
    ingredient_id: UUID
    quantity_required: Decimal = Field(gt=0)


class RecipeUpsertIn(BaseModel):
    yield_portions: int = Field(default=1, ge=1)
    ingredients: list[RecipeIngredientIn] = Field(min_length=1)


class POItemIn(BaseModel):
    ingredient_id: UUID
    quantity_ordered: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    expiry_date: Optional[date] = None


class POCreateIn(BaseModel):
    canteen_id: UUID
    supplier_id: UUID
    notes: Optional[str] = None
    items: list[POItemIn] = Field(min_length=1)


class StockAdjustIn(BaseModel):
    inventory_item_id: UUID
    quantity_delta: Decimal
    reason: str = Field(min_length=2, max_length=255)


class WastageIn(BaseModel):
    inventory_item_id: UUID
    quantity: Decimal = Field(gt=0)
    reason: str = Field(min_length=2, max_length=255)


class StockTransferIn(BaseModel):
    from_canteen_id: UUID
    to_canteen_id: UUID
    ingredient_id: UUID
    quantity: Decimal = Field(gt=0)
    notes: Optional[str] = None


@router.get("/suppliers")
def list_suppliers(
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.list_suppliers(db)


@router.post("/suppliers", status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.create_supplier(db, payload.model_dump(), principal.user.id)


@router.get("/canteens/{canteen_id}/items")
def list_inventory(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.list_canteen_inventory(db, canteen_id)


@router.post("/ingredients", status_code=status.HTTP_201_CREATED)
def create_ingredient(
    payload: IngredientCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.create_ingredient_with_stock(db, payload.model_dump(), principal.user.id)


@router.put("/recipes/{food_item_id}")
def upsert_recipe(
    food_item_id: UUID,
    payload: RecipeUpsertIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.upsert_recipe(
        db,
        food_item_id,
        payload.yield_portions,
        [it.model_dump() for it in payload.ingredients],
        principal.user.id,
    )


@router.get("/canteens/{canteen_id}/purchase-orders")
def list_pos(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return list(
        db.scalars(select(PurchaseOrder).where(PurchaseOrder.canteen_id == canteen_id).order_by(PurchaseOrder.created_at.desc())).all()
    )


@router.post("/purchase-orders", status_code=status.HTTP_201_CREATED)
def create_po(
    payload: POCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.create_purchase_order(db, payload.model_dump(), principal.user.id)


@router.post("/purchase-orders/{po_id}/receive")
def receive_po(
    po_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.receive_purchase_order(db, po_id, principal.user.id)


@router.post("/adjustments")
def adjust_stock(
    payload: StockAdjustIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.adjust_or_waste_stock(
        db,
        inventory_item_id=payload.inventory_item_id,
        quantity_delta=payload.quantity_delta,
        reason=payload.reason,
        is_wastage=False,
        actor_user_id=principal.user.id,
    )


@router.post("/wastage")
def record_wastage(
    payload: WastageIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.adjust_or_waste_stock(
        db,
        inventory_item_id=payload.inventory_item_id,
        quantity_delta=payload.quantity,
        reason=payload.reason,
        is_wastage=True,
        actor_user_id=principal.user.id,
    )


@router.post("/transfers")
def transfer_stock(
    payload: StockTransferIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.transfer_stock(
        db,
        from_canteen_id=payload.from_canteen_id,
        to_canteen_id=payload.to_canteen_id,
        ingredient_id=payload.ingredient_id,
        quantity=payload.quantity,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )


@router.get("/canteens/{canteen_id}/alerts")
def get_alerts(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.get_inventory_alerts(db, canteen_id)
