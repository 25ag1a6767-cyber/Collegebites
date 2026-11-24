from datetime import date
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
from app.models.enterprise import RecallIncident
from app.models.inventory import InventoryItem, StockBatch
from app.models.order import Order
from app.services import traceability_service

router = APIRouter(prefix="/traceability", tags=["Food Traceability & Batch Tracking"])

TRACE_VIEW_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_INVENTORY_MANAGER,
    ROLE_FOOD_SAFETY_INSPECTOR,
    ROLE_KITCHEN_STAFF,
)
TRACE_MANAGE_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_INVENTORY_MANAGER,
    ROLE_FOOD_SAFETY_INSPECTOR,
)
RECALL_APPROVE_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_FOOD_SAFETY_INSPECTOR)


class BatchRegisterIn(BaseModel):
    inventory_item_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Optional[Decimal] = Field(default=None, ge=0)
    supplier_id: Optional[UUID] = None
    purchase_order_id: Optional[UUID] = None
    goods_receipt_id: Optional[UUID] = None
    batch_number: Optional[str] = Field(default=None, max_length=64)
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    storage_location: Optional[str] = Field(default="Main Store", max_length=120)
    quality_status: str = Field(default="approved", pattern="^(pending|approved|rejected|blocked|recalled)$")
    supporting_documents: list[str] = Field(default_factory=list)


class BatchQualityUpdateIn(BaseModel):
    quality_status: str = Field(pattern="^(pending|approved|rejected|blocked|recalled)$")
    block_reason: Optional[str] = None
    storage_location: Optional[str] = None


class RecallInitiateIn(BaseModel):
    canteen_id: UUID
    title: str = Field(min_length=3, max_length=200)
    reason: str = Field(min_length=5, max_length=2000)
    severity: str = Field(default="high", pattern="^(medium|high|critical)$")
    stock_batch_ids: list[UUID] = Field(min_length=1)
    investigation_notes: Optional[str] = None


class RecallUpdateIn(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(resolved|closed)$")
    investigation_notes: Optional[str] = None
    corrective_actions: Optional[str] = None


@router.get("/batches")
def list_batches(
    canteen_id: UUID = Query(...),
    inventory_item_id: Optional[UUID] = Query(default=None),
    quality_status: Optional[str] = Query(default=None),
    include_empty: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(require_roles(*TRACE_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return traceability_service.list_batches(
        db,
        canteen_id,
        inventory_item_id=inventory_item_id,
        quality_status=quality_status,
        include_empty=include_empty,
    )


@router.post("/batches")
def register_batch(
    payload: BatchRegisterIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*TRACE_MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    inv = db.get(InventoryItem, payload.inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    enforce_canteen_scope(principal, inv.canteen_id)
    return traceability_service.register_stock_batch(
        db,
        inventory_item_id=payload.inventory_item_id,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        supplier_id=payload.supplier_id,
        purchase_order_id=payload.purchase_order_id,
        goods_receipt_id=payload.goods_receipt_id,
        batch_number=payload.batch_number,
        manufacturing_date=payload.manufacturing_date,
        expiry_date=payload.expiry_date,
        storage_location=payload.storage_location,
        quality_status=payload.quality_status,
        supporting_documents=payload.supporting_documents,
        actor_user_id=principal.user.id,
    )


@router.patch("/batches/{batch_id}/quality")
def update_batch_quality(
    batch_id: UUID,
    payload: BatchQualityUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*TRACE_MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    batch = db.get(StockBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Stock batch not found")
    inv = db.get(InventoryItem, batch.inventory_item_id)
    if inv:
        enforce_canteen_scope(principal, inv.canteen_id)
    return traceability_service.update_batch_quality(
        db,
        batch_id,
        quality_status=payload.quality_status,
        block_reason=payload.block_reason,
        storage_location=payload.storage_location,
        actor_user_id=principal.user.id,
    )


@router.get("/batches/{batch_id}/chain")
def get_batch_chain(
    batch_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*TRACE_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    batch = db.get(StockBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Stock batch not found")
    inv = db.get(InventoryItem, batch.inventory_item_id)
    if inv:
        enforce_canteen_scope(principal, inv.canteen_id)
    return traceability_service.get_batch_traceability_chain(db, batch_id)


@router.get("/orders/{order_id}/chain")
def get_order_chain(
    order_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*TRACE_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    enforce_canteen_scope(principal, order.canteen_id)
    return traceability_service.get_order_traceability_chain(db, order_id)


@router.get("/recalls")
def list_recalls(
    canteen_id: UUID = Query(...),
    principal: AuthenticatedPrincipal = Depends(require_roles(*TRACE_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return traceability_service.list_recalls(db, canteen_id)


@router.post("/recalls")
def initiate_recall(
    payload: RecallInitiateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*TRACE_MANAGE_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return traceability_service.initiate_recall(
        db,
        canteen_id=payload.canteen_id,
        title=payload.title,
        reason=payload.reason,
        severity=payload.severity,
        stock_batch_ids=payload.stock_batch_ids,
        investigation_notes=payload.investigation_notes,
        actor_user_id=principal.user.id,
    )


@router.post("/recalls/{recall_id}/approve")
def approve_recall(
    recall_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*RECALL_APPROVE_ROLES)),
    db: Session = Depends(get_db),
):
    rec = db.get(RecallIncident, recall_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recall incident not found")
    enforce_canteen_scope(principal, rec.canteen_id)
    return traceability_service.approve_recall(db, recall_id, actor_user_id=principal.user.id)


@router.patch("/recalls/{recall_id}")
def update_recall(
    recall_id: UUID,
    payload: RecallUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*RECALL_APPROVE_ROLES)),
    db: Session = Depends(get_db),
):
    rec = db.get(RecallIncident, recall_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recall incident not found")
    enforce_canteen_scope(principal, rec.canteen_id)
    return traceability_service.update_recall(
        db,
        recall_id,
        status=payload.status,
        investigation_notes=payload.investigation_notes,
        corrective_actions=payload.corrective_actions,
        actor_user_id=principal.user.id,
    )


@router.get("/recalls/{recall_id}/report.pdf")
def download_recall_pdf(
    recall_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*TRACE_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    rec = db.get(RecallIncident, recall_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recall incident not found")
    enforce_canteen_scope(principal, rec.canteen_id)
    pdf_bytes = traceability_service.export_recall_pdf(db, recall_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{rec.recall_number}.pdf"'},
    )
