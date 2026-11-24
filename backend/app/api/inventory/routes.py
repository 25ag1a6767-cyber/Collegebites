from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
)
from app.models.inventory import DailyFoodPrepLog, InventoryItem, PriceChangeRequest, PurchaseOrder, StockTransfer
from app.models.menu import FoodItem
from app.services import inventory_service, waste_service

router = APIRouter(prefix="/inventory", tags=["Inventory, Recipes & Suppliers"])

INV_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)
WASTE_RECORD_ROLES = (*INV_ROLES, ROLE_KITCHEN_STAFF)


class SupplierCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    gst_number: Optional[str] = None
    business_details: Optional[str] = None
    supplied_products: Optional[list[str]] = None
    payment_terms: Optional[str] = None
    lead_time_days: Optional[int] = Field(default=None, ge=0, le=90)
    is_active: bool = True


class IngredientCreate(BaseModel):
    canteen_id: UUID
    name: str = Field(min_length=2, max_length=120)
    sku: Optional[str] = Field(default=None, max_length=64)
    category: str = Field(default="General", max_length=80)
    description: Optional[str] = Field(default=None, max_length=1000)
    image_url: Optional[str] = Field(default=None, max_length=500)
    storage_location: Optional[str] = Field(default=None, max_length=120)
    preferred_supplier_id: Optional[UUID] = None
    is_available: bool = True
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
    ingredient_id: Optional[UUID] = None
    item_name: Optional[str] = Field(default=None, max_length=140)
    unit: Optional[str] = Field(default=None, max_length=32)
    quantity_ordered: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    tax_rate_percent: Decimal = Field(default=Decimal("0.00"), ge=0, le=100)
    expiry_date: Optional[date] = None


class POCreateIn(BaseModel):
    canteen_id: UUID
    supplier_id: UUID
    initial_status: Optional[str] = Field(default=None, pattern="^(draft|pending_approval|approved|ordered)$")
    expected_delivery_date: Optional[date] = None
    notes: Optional[str] = None
    items: list[POItemIn] = Field(min_length=1)


class POStatusTransitionIn(BaseModel):
    status: str = Field(pattern="^(pending_approval|approved|ordered|cancelled)$")
    notes: Optional[str] = Field(default=None, max_length=255)


class VendorPaymentCreateIn(BaseModel):
    supplier_id: UUID
    canteen_id: Optional[UUID] = None
    purchase_order_id: Optional[UUID] = None
    amount: Decimal = Field(gt=0)
    payment_method: str = Field(default="bank_transfer", pattern="^(bank_transfer|upi|neft_rtgs|cheque)$")
    payment_reference: Optional[str] = Field(default=None, max_length=128)
    document_url: Optional[str] = Field(default=None, max_length=255)
    status: Optional[str] = Field(default=None, pattern="^(pending_verification|verified)$")
    payment_date: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=500)


class VendorPaymentVerifyIn(BaseModel):
    payment_reference: str = Field(min_length=2, max_length=128)
    document_url: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=500)


class StockAdjustIn(BaseModel):
    inventory_item_id: UUID
    quantity_delta: Decimal
    reason: str = Field(min_length=2, max_length=255)
    operation_type: Optional[str] = Field(
        default=None,
        pattern="^(add_stock|reduce_stock|adjustment|damaged|expired|wastage)$",
    )
    batch_id: Optional[UUID] = None
    expiry_date: Optional[date] = None


class SupplierUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    gst_number: Optional[str] = None
    business_details: Optional[str] = None
    supplied_products: Optional[list[str]] = None
    payment_terms: Optional[str] = None
    lead_time_days: Optional[int] = Field(default=None, ge=0, le=90)
    is_active: Optional[bool] = None


class InventoryItemUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    category: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = Field(default=None, max_length=1000)
    image_url: Optional[str] = Field(default=None, max_length=500)
    storage_location: Optional[str] = Field(default=None, max_length=120)
    preferred_supplier_id: Optional[UUID] = None
    is_available: Optional[bool] = None
    is_allergen: Optional[bool] = None
    reorder_level: Optional[Decimal] = Field(default=None, ge=0)
    unit_cost: Optional[Decimal] = Field(default=None, ge=0)
    unit: Optional[str] = None
    reason: Optional[str] = Field(default=None, max_length=255)


class POReceiveItemIn(BaseModel):
    po_item_id: Optional[UUID] = None
    ingredient_id: Optional[UUID] = None
    quantity_received: Decimal = Field(ge=0)
    quantity_delivered: Optional[Decimal] = Field(default=None, ge=0)
    quantity_damaged: Decimal = Field(default=Decimal("0"), ge=0)
    quantity_rejected: Decimal = Field(default=Decimal("0"), ge=0)
    quantity_missing: Decimal = Field(default=Decimal("0"), ge=0)
    expiry_date: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=255)


class POReceiveIn(BaseModel):
    idempotency_key: Optional[str] = Field(default=None, max_length=96)
    delivery_challan_ref: Optional[str] = Field(default=None, max_length=96)
    notes: Optional[str] = Field(default=None, max_length=255)
    received_items: list[POReceiveItemIn] = Field(min_length=1)


class WastageIn(BaseModel):
    inventory_item_id: Optional[UUID] = None
    food_item_id: Optional[UUID] = None
    prep_log_id: Optional[UUID] = None
    canteen_id: Optional[UUID] = None
    quantity: Decimal = Field(gt=0)
    reason: str = Field(min_length=2, max_length=255)
    batch_id: Optional[UUID] = None
    operation_type: str = Field(default="wastage", pattern="^(damaged|expired|wastage|unsold)$")
    waste_date: Optional[date] = None
    responsible_staff_id: Optional[UUID] = None
    unit_cost: Optional[Decimal] = Field(default=None, ge=0)


class FoodPrepUpsertIn(BaseModel):
    canteen_id: UUID
    food_item_id: UUID
    prep_date: Optional[date] = None
    meal_session: str = Field(default="all_day", pattern="^(breakfast|lunch|evening|dinner|all_day)$")
    prepared_quantity: int = Field(ge=0)
    unit_cost: Optional[Decimal] = Field(default=None, ge=0)
    responsible_staff_id: Optional[UUID] = None
    notes: Optional[str] = Field(default=None, max_length=255)


class PreparedFoodWasteIn(BaseModel):
    quantity: Decimal = Field(gt=0)
    reason: str = Field(min_length=2, max_length=255)
    loss_type: str = Field(default="unsold", pattern="^(unsold|wastage|damaged|expired)$")
    waste_date: Optional[date] = None
    responsible_staff_id: Optional[UUID] = None
    unit_cost: Optional[Decimal] = Field(default=None, ge=0)


class ArchiveItemIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=255)


class RestockItemIn(BaseModel):
    quantity: Decimal = Field(gt=0)
    unit_cost: Optional[Decimal] = Field(default=None, ge=0)
    supplier_id: Optional[UUID] = None
    expiry_date: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=255)


class PurchasePriceUpdateIn(BaseModel):
    new_purchase_price: Decimal = Field(ge=0)
    reason: str = Field(min_length=2, max_length=300)


class SellingPriceRequestIn(BaseModel):
    canteen_id: UUID
    food_item_id: UUID
    new_price: Decimal = Field(gt=0)
    reason: str = Field(min_length=2, max_length=300)
    inventory_item_id: Optional[UUID] = None


class SellingPriceReviewIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    review_notes: Optional[str] = Field(default=None, max_length=300)


class StockTransferIn(BaseModel):
    from_canteen_id: UUID
    to_canteen_id: UUID
    ingredient_id: UUID
    quantity: Decimal = Field(gt=0)
    notes: Optional[str] = None


@router.get("/suppliers")
def list_suppliers(
    search: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    product: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.list_suppliers(db, search=search, is_active=is_active, product=product)


@router.get("/suppliers/{supplier_id}/statement")
def get_supplier_statement(
    supplier_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.get_supplier_statement(db, supplier_id)


@router.post("/suppliers", status_code=status.HTTP_201_CREATED)
def create_supplier(
    payload: SupplierCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.create_supplier(db, payload.model_dump(), principal.user.id)


@router.patch("/suppliers/{supplier_id}")
def update_supplier(
    supplier_id: UUID,
    payload: SupplierUpdate,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    return inventory_service.update_supplier(db, supplier_id, payload.model_dump(exclude_unset=True), principal.user.id)


@router.get("/canteens/{canteen_id}/items")
def list_inventory(
    canteen_id: UUID,
    search: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    stock_status: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return inventory_service.list_canteen_inventory(
        db,
        canteen_id,
        search=search,
        category=category,
        stock_status=stock_status,
        include_archived=include_archived,
    )


@router.patch("/items/{inventory_item_id}")
def update_inventory_item(
    inventory_item_id: UUID,
    payload: InventoryItemUpdate,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    inv = db.get(InventoryItem, inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return inventory_service.update_inventory_item(
        db, inventory_item_id, payload.model_dump(exclude_unset=True), principal.user.id
    )


@router.get("/canteens/{canteen_id}/movements")
def list_movements(
    canteen_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return inventory_service.list_inventory_movements(db, canteen_id, limit=limit, offset=offset)


@router.get("/canteens/{canteen_id}/transfers")
def list_transfers(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    rows = db.scalars(
        select(StockTransfer)
        .where((StockTransfer.from_canteen_id == canteen_id) | (StockTransfer.to_canteen_id == canteen_id))
        .order_by(StockTransfer.created_at.desc())
        .limit(100)
    ).all()
    return list(rows)


@router.post("/ingredients", status_code=status.HTTP_201_CREATED)
def create_ingredient(
    payload: IngredientCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return inventory_service.create_ingredient_with_stock(db, payload.model_dump(), principal.user.id)


@router.get("/recipes/{food_item_id}")
def get_recipe(
    food_item_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    food = db.get(FoodItem, food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, food.canteen_id)
    return inventory_service.get_recipe(db, food_item_id)


@router.put("/recipes/{food_item_id}")
def upsert_recipe(
    food_item_id: UUID,
    payload: RecipeUpsertIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    food = db.get(FoodItem, food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, food.canteen_id)
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
    status_filter: Optional[str] = Query(default=None),
    supplier_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return inventory_service.list_purchase_orders(
        db, canteen_id, status_filter=status_filter, supplier_id=supplier_id
    )


@router.post("/purchase-orders", status_code=status.HTTP_201_CREATED)
def create_po(
    payload: POCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    can_approve = principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    return inventory_service.create_purchase_order(
        db, payload.model_dump(), principal.user.id, can_approve=can_approve
    )


@router.post("/purchase-orders/{po_id}/status")
def update_po_status(
    po_id: UUID,
    payload: POStatusTransitionIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    enforce_canteen_scope(principal, po.canteen_id)
    can_approve = principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    return inventory_service.transition_purchase_order_status(
        db,
        po_id,
        target_status=payload.status,
        actor_user_id=principal.user.id,
        can_approve=can_approve,
        notes=payload.notes,
    )


@router.get("/purchase-orders/{po_id}/receipts")
def list_po_receipts(
    po_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    enforce_canteen_scope(principal, po.canteen_id)
    return inventory_service.list_goods_receipts_for_po(db, po_id)


@router.get("/purchase-orders/{po_id}/pdf")
def download_po_pdf(
    po_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    enforce_canteen_scope(principal, po.canteen_id)
    pdf_bytes = inventory_service.export_purchase_order_pdf(db, po_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{po.po_number}.pdf"'},
    )


@router.post("/purchase-orders/{po_id}/receive")
def receive_po(
    po_id: UUID,
    payload: Optional[POReceiveIn] = None,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    enforce_canteen_scope(principal, po.canteen_id)
    rec_items = [it.model_dump() for it in payload.received_items] if payload else None
    return inventory_service.receive_purchase_order(
        db,
        po_id,
        principal.user.id,
        received_items=rec_items,
        idempotency_key=payload.idempotency_key if payload else None,
        delivery_challan_ref=payload.delivery_challan_ref if payload else None,
        notes=payload.notes if payload else None,
    )


@router.get("/vendor-payments")
def list_vendor_payments(
    canteen_id: Optional[UUID] = Query(default=None),
    supplier_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    elif principal.assigned_canteen_id and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        canteen_id = principal.assigned_canteen_id
    return inventory_service.list_vendor_payments(
        db, canteen_id=canteen_id, supplier_id=supplier_id, status_filter=status_filter
    )


@router.post("/vendor-payments", status_code=status.HTTP_201_CREATED)
def create_vendor_payment(
    payload: VendorPaymentCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    if payload.canteen_id:
        enforce_canteen_scope(principal, payload.canteen_id)
    return inventory_service.create_vendor_payment(db, payload.model_dump(), principal.user.id)


@router.post("/vendor-payments/{payment_id}/verify")
def verify_vendor_payment(
    payment_id: UUID,
    payload: VendorPaymentVerifyIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    return inventory_service.verify_vendor_payment(
        db,
        payment_id,
        payment_reference=payload.payment_reference,
        document_url=payload.document_url,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )


@router.post("/purchase-orders/{po_id}/cancel")
def cancel_po(
    po_id: UUID,
    reason: Optional[str] = Query(default=None, max_length=255),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    enforce_canteen_scope(principal, po.canteen_id)
    return inventory_service.cancel_purchase_order(db, po_id, principal.user.id, reason=reason)


@router.get("/canteens/{canteen_id}/wastage")
def list_wastage(
    canteen_id: UUID,
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    loss_type: Optional[str] = Query(default=None),
    source_type: Optional[str] = Query(default=None),
    responsible_staff_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(require_roles(*WASTE_RECORD_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return inventory_service.list_wastage_records(
        db,
        canteen_id,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
        loss_type=loss_type,
        source_type=source_type,
        responsible_staff_id=responsible_staff_id,
    )


@router.get("/canteens/{canteen_id}/staff-members")
def list_inventory_staff_members(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*WASTE_RECORD_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return waste_service.list_canteen_staff_for_select(db, canteen_id)


@router.get("/canteens/{canteen_id}/food-prep")
def list_food_prep_logs(
    canteen_id: UUID,
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    meal_session: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*WASTE_RECORD_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return waste_service.list_daily_food_prep_logs(
        db,
        canteen_id=canteen_id,
        start_date=start_date,
        end_date=end_date,
        meal_session=meal_session,
    )


@router.post("/food-prep", status_code=status.HTTP_201_CREATED)
def upsert_food_prep_log(
    payload: FoodPrepUpsertIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*WASTE_RECORD_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    from app.core.time_utils import today_college

    return waste_service.upsert_daily_food_prep_log(
        db,
        canteen_id=payload.canteen_id,
        food_item_id=payload.food_item_id,
        prep_date=payload.prep_date or today_college(),
        meal_session=payload.meal_session,
        prepared_quantity=payload.prepared_quantity,
        unit_cost=payload.unit_cost,
        responsible_staff_id=payload.responsible_staff_id,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )


@router.post("/food-prep/{prep_log_id}/record-waste")
def record_unsold_prep_waste(
    prep_log_id: UUID,
    payload: PreparedFoodWasteIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*WASTE_RECORD_ROLES)),
    db: Session = Depends(get_db),
):
    log_row = db.get(DailyFoodPrepLog, prep_log_id)
    if not log_row:
        raise HTTPException(status_code=404, detail="Daily food prep log not found")
    enforce_canteen_scope(principal, log_row.canteen_id)
    return waste_service.record_prepared_food_waste(
        db,
        canteen_id=log_row.canteen_id,
        prep_log_id=prep_log_id,
        waste_date=payload.waste_date,
        quantity=payload.quantity,
        reason=payload.reason,
        loss_type=payload.loss_type,
        responsible_staff_id=payload.responsible_staff_id,
        actor_user_id=principal.user.id,
        unit_cost=payload.unit_cost,
    )


@router.get("/canteens/{canteen_id}/waste-analytics")
def get_canteen_waste_analytics(
    canteen_id: UUID,
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*WASTE_RECORD_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return waste_service.get_waste_analytics(
        db,
        canteen_id=canteen_id,
        period=period,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/canteens/{canteen_id}/consumption-report")
def get_canteen_consumption_report(
    canteen_id: UUID,
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    inventory_item_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return waste_service.get_consumption_report(
        db,
        canteen_id=canteen_id,
        start_date=start_date,
        end_date=end_date,
        inventory_item_id=inventory_item_id,
    )


@router.get("/canteens/{canteen_id}/waste-recommendations")
def get_canteen_waste_recommendations(
    canteen_id: UUID,
    lookback_days: int = Query(default=30, ge=7, le=180),
    principal: AuthenticatedPrincipal = Depends(require_roles(*WASTE_RECORD_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return waste_service.get_waste_recommendations(
        db,
        canteen_id=canteen_id,
        lookback_days=lookback_days,
    )


@router.get("/canteens/{canteen_id}/wastage/csv")
def export_canteen_wastage_csv(
    canteen_id: UUID,
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    analytics = waste_service.get_waste_analytics(
        db,
        canteen_id=canteen_id,
        period=period,
        start_date=start_date,
        end_date=end_date,
    )
    records = inventory_service.list_wastage_records(
        db,
        canteen_id,
        limit=500,
        start_date=date.fromisoformat(analytics["start_date"]),
        end_date=date.fromisoformat(analytics["end_date"]),
    )
    csv_text = waste_service.export_wastage_csv(
        db,
        canteen_id=canteen_id,
        analytics=analytics,
        wastage_records=records,
    )
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=collegebites-food-waste-report.csv"},
    )


@router.get("/canteens/{canteen_id}/adjustments")
def list_adjustments(
    canteen_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return inventory_service.list_stock_adjustments(db, canteen_id, limit=limit)


@router.post("/adjustments")
def adjust_stock(
    payload: StockAdjustIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    inv = db.get(InventoryItem, payload.inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return inventory_service.adjust_or_waste_stock(
        db,
        inventory_item_id=payload.inventory_item_id,
        quantity_delta=payload.quantity_delta,
        reason=payload.reason,
        is_wastage=False,
        actor_user_id=principal.user.id,
        batch_id=payload.batch_id,
        operation_type=payload.operation_type,
        expiry_date=payload.expiry_date,
    )


@router.post("/wastage")
def record_wastage(
    payload: WastageIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*WASTE_RECORD_ROLES)),
    db: Session = Depends(get_db),
):
    if payload.prep_log_id or payload.food_item_id:
        resolved_canteen_id = payload.canteen_id
        if payload.prep_log_id:
            pl = db.get(DailyFoodPrepLog, payload.prep_log_id)
            if not pl:
                raise HTTPException(status_code=404, detail="Daily food prep log not found")
            resolved_canteen_id = pl.canteen_id
        elif payload.food_item_id:
            fi = db.get(FoodItem, payload.food_item_id)
            if not fi:
                raise HTTPException(status_code=404, detail="Food item not found")
            resolved_canteen_id = fi.canteen_id
        if not resolved_canteen_id:
            raise HTTPException(status_code=400, detail="canteen_id is required")
        enforce_canteen_scope(principal, resolved_canteen_id)
        return waste_service.record_prepared_food_waste(
            db,
            canteen_id=resolved_canteen_id,
            food_item_id=payload.food_item_id,
            prep_log_id=payload.prep_log_id,
            waste_date=payload.waste_date,
            quantity=payload.quantity,
            reason=payload.reason,
            loss_type=payload.operation_type if payload.operation_type in ("damaged", "expired", "wastage", "unsold") else "unsold",
            responsible_staff_id=payload.responsible_staff_id,
            actor_user_id=principal.user.id,
            unit_cost=payload.unit_cost,
        )

    if not payload.inventory_item_id:
        raise HTTPException(status_code=400, detail="Either inventory_item_id or food_item_id/prep_log_id is required")
    inv = db.get(InventoryItem, payload.inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return inventory_service.adjust_or_waste_stock(
        db,
        inventory_item_id=payload.inventory_item_id,
        quantity_delta=payload.quantity,
        reason=payload.reason,
        is_wastage=True,
        actor_user_id=principal.user.id,
        batch_id=payload.batch_id,
        operation_type=payload.operation_type if payload.operation_type in ("damaged", "expired", "wastage") else "wastage",
        waste_date=payload.waste_date,
        responsible_staff_id=payload.responsible_staff_id,
    )


@router.post("/transfers")
def transfer_stock(
    payload: StockTransferIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.from_canteen_id)
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
    enforce_canteen_scope(principal, canteen_id)
    return inventory_service.get_inventory_alerts(db, canteen_id)


@router.get("/canteens/{canteen_id}/dashboard")
def get_dashboard(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return inventory_service.get_inventory_dashboard(db, canteen_id)


@router.post("/items/{inventory_item_id}/archive")
def archive_item(
    inventory_item_id: UUID,
    payload: Optional[ArchiveItemIn] = None,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    inv = db.get(InventoryItem, inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return inventory_service.archive_inventory_item(
        db, inventory_item_id, reason=payload.reason if payload else None, actor_user_id=principal.user.id
    )


@router.post("/items/{inventory_item_id}/restore")
def restore_item(
    inventory_item_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    inv = db.get(InventoryItem, inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return inventory_service.restore_inventory_item(db, inventory_item_id, actor_user_id=principal.user.id)


@router.post("/items/{inventory_item_id}/restock")
def restock_item(
    inventory_item_id: UUID,
    payload: RestockItemIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    inv = db.get(InventoryItem, inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return inventory_service.restock_inventory_item(
        db,
        inventory_item_id,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        supplier_id=payload.supplier_id,
        expiry_date=payload.expiry_date,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )


@router.post("/items/{inventory_item_id}/purchase-price")
def update_purchase_price(
    inventory_item_id: UUID,
    payload: PurchasePriceUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    inv = db.get(InventoryItem, inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return inventory_service.update_purchase_price(
        db,
        inventory_item_id,
        new_purchase_price=payload.new_purchase_price,
        reason=payload.reason,
        actor_user_id=principal.user.id,
    )


@router.get("/canteens/{canteen_id}/price-changes")
def list_price_changes(
    canteen_id: UUID,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return inventory_service.list_price_changes(db, canteen_id, status_filter=status_filter)


@router.post("/price-changes", status_code=status.HTTP_201_CREATED)
def create_selling_price_request(
    payload: SellingPriceRequestIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return inventory_service.request_selling_price_change(
        db,
        canteen_id=payload.canteen_id,
        food_item_id=payload.food_item_id,
        new_price=payload.new_price,
        reason=payload.reason,
        inventory_item_id=payload.inventory_item_id,
        actor_user_id=principal.user.id,
    )


@router.post("/price-changes/{request_id}/review")
def review_selling_price_request(
    request_id: UUID,
    payload: SellingPriceReviewIn,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    req = db.get(PriceChangeRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Price change request not found")
    enforce_canteen_scope(principal, req.canteen_id)
    return inventory_service.review_selling_price_change(
        db,
        request_id,
        decision=payload.decision,
        review_notes=payload.review_notes,
        actor_user_id=principal.user.id,
    )


@router.get("/canteens/{canteen_id}/audit-logs")
def list_audit_logs(
    canteen_id: UUID,
    inventory_item_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return inventory_service.list_inventory_audit_logs(
        db, canteen_id, inventory_item_id=inventory_item_id, limit=limit
    )


@router.get("/canteens/{canteen_id}/reports/summary")
def get_inventory_report_summary(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return inventory_service.get_inventory_report_data(db, canteen_id)


@router.get("/canteens/{canteen_id}/reports/csv")
def export_inventory_report_csv(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    report = inventory_service.get_inventory_report_data(db, canteen_id)
    csv_text = inventory_service.export_inventory_csv(report)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=collegebites-inventory-report.csv"},
    )


@router.get("/canteens/{canteen_id}/reports/pdf")
def export_inventory_report_pdf(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*INV_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    report = inventory_service.get_inventory_report_data(db, canteen_id)
    pdf_bytes = inventory_service.export_inventory_pdf(report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=collegebites-inventory-report.pdf"},
    )
