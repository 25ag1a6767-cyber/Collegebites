"""
Phase 4: Food Traceability & Batch Tracking Service (FIFO/FEFO + End-to-End Trace + Recalls).
- Reuses existing StockBatch, InventoryItem, PurchaseOrder, GoodsReceipt, Supplier, Order.
- Strictly blocks expired, rejected, blocked, or recalled batches unless an authorized admin/manager
  provides allow_override=True + mandatory override_reason (audit-logged).
- Never fabricates missing expiry dates or missing traceability links (explicitly flags partial chains).
"""

import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.time_utils import today_college
from app.models.college import Canteen
from app.models.enterprise import (
    ProductionBatch,
    ProductionBatchIngredient,
    RecallIncident,
    TraceabilityRecord,
)
from app.models.inventory import GoodsReceipt, InventoryItem, PurchaseOrder, StockBatch, StockMovement, Supplier
from app.models.menu import FoodItem, Ingredient, Recipe
from app.models.order import Order, OrderItem
from app.services.audit_service import record_audit_log
from app.services.notification_service import notify_food_safety_event

VALID_QUALITY_STATUSES = ("pending", "approved", "rejected", "blocked", "recalled")
VALID_STRATEGIES = ("FEFO", "FIFO")


def _serialize_batch(
    b: StockBatch,
    *,
    ingredient_name: Optional[str] = None,
    unit: Optional[str] = None,
    supplier_name: Optional[str] = None,
    po_number: Optional[str] = None,
    grn_number: Optional[str] = None,
) -> dict:
    today = today_college()
    is_expired = bool(b.expiry_date and b.expiry_date < today)
    is_unusable = is_expired or b.quality_status in ("blocked", "rejected", "recalled")
    avail_qty = Decimal("0.000") if is_unusable else max(Decimal("0.000"), b.remaining_quantity)
    return {
        "id": str(b.id),
        "inventory_item_id": str(b.inventory_item_id),
        "batch_number": b.batch_number,
        "ingredient_name": ingredient_name,
        "unit": unit,
        "supplier_id": str(b.supplier_id) if b.supplier_id else None,
        "supplier_name": supplier_name,
        "purchase_order_id": str(b.purchase_order_id) if b.purchase_order_id else None,
        "po_number": po_number,
        "goods_receipt_id": str(b.goods_receipt_id) if b.goods_receipt_id else None,
        "grn_number": grn_number,
        "initial_quantity": str(b.initial_quantity),
        "allocated_quantity": str(b.allocated_quantity or Decimal("0.000")),
        "consumed_quantity": str(b.consumed_quantity or Decimal("0.000")),
        "rejected_quantity": str(b.rejected_quantity or Decimal("0.000")),
        "wasted_quantity": str(b.wasted_quantity or Decimal("0.000")),
        "remaining_quantity": str(b.remaining_quantity),
        "available_quantity": str(avail_qty.quantize(Decimal("0.001"))),
        "unit_cost": str(b.unit_cost),
        "manufacturing_date": b.manufacturing_date.isoformat() if b.manufacturing_date else None,
        "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
        "is_expired": is_expired,
        "storage_location": b.storage_location,
        "quality_status": b.quality_status,
        "block_reason": b.block_reason,
        "supporting_documents": list(b.supporting_documents or []),
        "received_at": b.received_at.isoformat() if b.received_at else None,
    }


def list_batches(
    db: Session,
    canteen_id: UUID,
    *,
    inventory_item_id: Optional[UUID] = None,
    quality_status: Optional[str] = None,
    include_empty: bool = False,
) -> list[dict]:
    stmt = (
        select(StockBatch, InventoryItem, Ingredient)
        .join(InventoryItem, InventoryItem.id == StockBatch.inventory_item_id)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id)
    )
    if inventory_item_id:
        stmt = stmt.where(StockBatch.inventory_item_id == inventory_item_id)
    if quality_status and quality_status != "all":
        stmt = stmt.where(StockBatch.quality_status == quality_status)
    if not include_empty:
        stmt = stmt.where(StockBatch.remaining_quantity > 0)
    rows = db.execute(stmt.order_by(StockBatch.expiry_date.asc().nulls_last(), StockBatch.received_at.asc())).all()
    if not rows:
        return []
    sup_ids = {b.supplier_id for b, _, _ in rows if b.supplier_id}
    po_ids = {b.purchase_order_id for b, _, _ in rows if b.purchase_order_id}
    grn_ids = {b.goods_receipt_id for b, _, _ in rows if b.goods_receipt_id}
    sup_map = {s.id: s.name for s in db.scalars(select(Supplier).where(Supplier.id.in_(list(sup_ids)))).all()} if sup_ids else {}
    po_map = {p.id: p.po_number for p in db.scalars(select(PurchaseOrder).where(PurchaseOrder.id.in_(list(po_ids)))).all()} if po_ids else {}
    grn_map = {g.id: g.grn_number for g in db.scalars(select(GoodsReceipt).where(GoodsReceipt.id.in_(list(grn_ids)))).all()} if grn_ids else {}

    return [
        _serialize_batch(
            b,
            ingredient_name=ing.name,
            unit=inv.unit,
            supplier_name=sup_map.get(b.supplier_id),
            po_number=po_map.get(b.purchase_order_id),
            grn_number=grn_map.get(b.goods_receipt_id),
        )
        for b, inv, ing in rows
    ]


def register_stock_batch(
    db: Session,
    *,
    inventory_item_id: UUID,
    quantity: Decimal,
    unit_cost: Optional[Decimal],
    supplier_id: Optional[UUID],
    purchase_order_id: Optional[UUID],
    goods_receipt_id: Optional[UUID],
    batch_number: Optional[str],
    manufacturing_date: Optional[date],
    expiry_date: Optional[date],
    storage_location: Optional[str],
    quality_status: str,
    supporting_documents: Optional[list[str]],
    actor_user_id: UUID,
) -> dict:
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    if quantity <= Decimal("0.000"):
        raise HTTPException(status_code=400, detail="Batch quantity must be greater than zero")
    q_st = (quality_status or "approved").strip().lower()
    if q_st not in VALID_QUALITY_STATUSES:
        raise HTTPException(status_code=400, detail=f"quality_status must be one of {', '.join(VALID_QUALITY_STATUSES)}")
    if manufacturing_date and expiry_date and expiry_date < manufacturing_date:
        raise HTTPException(status_code=400, detail="expiry_date cannot precede manufacturing_date")

    if supplier_id is not None and not db.get(Supplier, supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")
    if purchase_order_id is not None:
        po_obj = db.get(PurchaseOrder, purchase_order_id)
        if not po_obj or po_obj.canteen_id != inv.canteen_id:
            raise HTTPException(status_code=400, detail="Purchase order not found for this canteen")
    if goods_receipt_id is not None:
        grn_obj = db.get(GoodsReceipt, goods_receipt_id)
        if not grn_obj or grn_obj.canteen_id != inv.canteen_id:
            raise HTTPException(status_code=400, detail="Goods receipt not found for this canteen")

    now = datetime.now(timezone.utc)
    eff_cost = unit_cost if unit_cost is not None else inv.unit_cost
    b_no = (batch_number or f"BAT-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:4].upper()}").strip()[:64]
    batch = StockBatch(
        inventory_item_id=inv.id,
        supplier_id=supplier_id or inv.preferred_supplier_id,
        purchase_order_id=purchase_order_id,
        goods_receipt_id=goods_receipt_id,
        batch_number=b_no,
        initial_quantity=quantity,
        remaining_quantity=quantity if q_st not in ("rejected", "recalled") else Decimal("0.000"),
        rejected_quantity=quantity if q_st == "rejected" else Decimal("0.000"),
        unit_cost=eff_cost,
        received_at=now,
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
        storage_location=storage_location or "Main Store",
        quality_status=q_st,
        supporting_documents=list(supporting_documents or []),
    )
    db.add(batch)
    db.flush()

    if q_st in ("approved", "pending"):
        inv.current_quantity += quantity
        db.add(
            StockMovement(
                inventory_item_id=inv.id,
                batch_id=batch.id,
                movement_type="purchase",
                quantity_delta=quantity,
                balance_after=inv.current_quantity,
                reference_type="batch_registration",
                reference_id=str(batch.id),
                created_by_user_id=actor_user_id,
                notes=f"Registered traceable batch {b_no}",
            )
        )

    missing = []
    if not batch.supplier_id:
        missing.append("supplier_id")
    if not batch.purchase_order_id:
        missing.append("purchase_order_id")
    if not batch.goods_receipt_id:
        missing.append("goods_receipt_id")
    missing.extend(["production_batch_id", "order_id"])

    db.add(
        TraceabilityRecord(
            canteen_id=inv.canteen_id,
            supplier_id=batch.supplier_id,
            purchase_order_id=batch.purchase_order_id,
            goods_receipt_id=batch.goods_receipt_id,
            stock_batch_id=batch.id,
            trace_completeness="partial",
            missing_links=missing,
            notes=f"Batch {b_no} registered ({quantity} {inv.unit}, status={q_st})",
        )
    )
    from app.services.inventory_service import refresh_food_item_ingredient_sufficiency

    refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    record_audit_log(
        db,
        action="traceability.batch_registered",
        entity_type="stock_batch",
        entity_id=b_no,
        actor_user_id=actor_user_id,
        details={"quantity": str(quantity), "quality_status": q_st, "expiry_date": expiry_date.isoformat() if expiry_date else None},
    )
    db.commit()
    db.refresh(batch)
    ing = db.get(Ingredient, inv.ingredient_id)
    return _serialize_batch(batch, ingredient_name=ing.name if ing else None, unit=inv.unit)


def update_batch_quality(
    db: Session,
    batch_id: UUID,
    *,
    quality_status: str,
    block_reason: Optional[str],
    storage_location: Optional[str],
    actor_user_id: UUID,
) -> dict:
    batch = db.scalar(select(StockBatch).where(StockBatch.id == batch_id).with_for_update())
    if not batch:
        raise HTTPException(status_code=404, detail="Stock batch not found")
    q_st = quality_status.strip().lower()
    if q_st not in VALID_QUALITY_STATUSES:
        raise HTTPException(status_code=400, detail=f"quality_status must be one of {', '.join(VALID_QUALITY_STATUSES)}")
    if q_st in ("blocked", "rejected", "recalled") and not (block_reason and block_reason.strip()):
        raise HTTPException(status_code=400, detail="block_reason is required when blocking, rejecting, or recalling a batch")
    prev = batch.quality_status
    batch.quality_status = q_st
    if block_reason is not None:
        batch.block_reason = block_reason.strip()[:255]
    if storage_location is not None:
        batch.storage_location = storage_location.strip()[:120]
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == batch.inventory_item_id).with_for_update())
    if inv and q_st == "rejected" and prev != "rejected" and batch.remaining_quantity > Decimal("0.000"):
        rej_qty = batch.remaining_quantity
        batch.rejected_quantity = (batch.rejected_quantity or Decimal("0.000")) + rej_qty
        batch.remaining_quantity = Decimal("0.000")
        inv.current_quantity = max(Decimal("0.000"), inv.current_quantity - rej_qty)
        db.add(
            StockMovement(
                inventory_item_id=inv.id,
                batch_id=batch.id,
                movement_type="wastage",
                quantity_delta=-rej_qty,
                balance_after=inv.current_quantity,
                reference_type="batch_quality_rejected",
                reference_id=str(batch.id),
                created_by_user_id=actor_user_id,
                notes=f"Batch {batch.batch_number} rejected: {batch.block_reason or 'Quality failure'}",
            )
        )
    if inv:
        from app.services.inventory_service import refresh_food_item_ingredient_sufficiency

        refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    record_audit_log(
        db,
        action="traceability.batch_quality_updated",
        entity_type="stock_batch",
        entity_id=batch.batch_number,
        actor_user_id=actor_user_id,
        details={"from_status": prev, "to_status": q_st, "block_reason": batch.block_reason},
    )
    db.commit()
    db.refresh(batch)
    ing = db.get(Ingredient, inv.ingredient_id) if inv else None
    return _serialize_batch(batch, ingredient_name=ing.name if ing else None, unit=inv.unit if inv else None)


def list_batch_movements(db: Session, batch_id: UUID) -> list[dict]:
    batch = db.get(StockBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Stock batch not found")
    inv = db.get(InventoryItem, batch.inventory_item_id)
    rows = db.scalars(
        select(StockMovement)
        .where(StockMovement.batch_id == batch_id)
        .order_by(StockMovement.created_at.desc())
        .limit(200)
    ).all()
    return [
        {
            "id": str(m.id),
            "batch_id": str(m.batch_id) if m.batch_id else None,
            "inventory_item_id": str(m.inventory_item_id),
            "unit": inv.unit if inv else None,
            "movement_type": m.movement_type,
            "quantity_delta": str(m.quantity_delta),
            "balance_after": str(m.balance_after),
            "reference_type": m.reference_type,
            "reference_id": m.reference_id,
            "notes": m.notes,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


def allocate_stock_batches(
    db: Session,
    *,
    inventory_item_id: UUID,
    required_qty: Decimal,
    strategy: str = "FEFO",
    allow_override: bool = False,
    override_reason: Optional[str] = None,
    can_override: bool = False,
    actor_user_id: Optional[UUID] = None,
    reference_type: str = "production_batch",
    reference_id: str = "",
) -> list[dict]:
    """
    Atomic FIFO / FEFO batch allocation under SELECT ... FOR UPDATE.
    Strictly blocks expired, rejected, blocked, or recalled batches unless authorized manager/admin
    explicitly requests allow_override=True with a documented override_reason.
    """
    strat = (strategy or "FEFO").strip().upper()
    if strat not in VALID_STRATEGIES:
        raise HTTPException(status_code=400, detail="Allocation strategy must be FEFO or FIFO")
    if required_qty <= Decimal("0.000"):
        return []
    if allow_override:
        if not can_override:
            raise HTTPException(status_code=403, detail="Only authorized admins or canteen managers may override expired/blocked batch rules")
        if not (override_reason and len(override_reason.strip()) >= 5):
            raise HTTPException(status_code=400, detail="A documented override_reason (min 5 chars) is mandatory for batch override")

    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    today = today_college()
    order_clauses = (
        [StockBatch.expiry_date.asc().nulls_last(), StockBatch.received_at.asc()]
        if strat == "FEFO"
        else [StockBatch.received_at.asc(), StockBatch.expiry_date.asc().nulls_last()]
    )

    stmt = (
        select(StockBatch)
        .where(
            StockBatch.inventory_item_id == inv.id,
            StockBatch.remaining_quantity > 0,
            StockBatch.quality_status.not_in(["recalled", "rejected"]),
        )
        .order_by(*order_clauses)
        .with_for_update()
    )
    if not allow_override:
        stmt = stmt.where(
            StockBatch.quality_status.in_(["approved", "pending"]),
            or_(StockBatch.expiry_date.is_(None), StockBatch.expiry_date >= today),
        )

    candidates = list(db.scalars(stmt).all())
    total_usable = sum((b.remaining_quantity for b in candidates), Decimal("0.000"))
    if total_usable < required_qty:
        ing = db.get(Ingredient, inv.ingredient_id)
        ing_label = ing.name if ing else str(inv.id)
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient usable non-expired/unblocked batch stock for {ing_label}: need {required_qty} {inv.unit}, usable {total_usable} {inv.unit}",
        )

    remaining = required_qty
    allocations: list[dict] = []
    for batch in candidates:
        if remaining <= Decimal("0.000"):
            break
        take = min(batch.remaining_quantity, remaining)
        was_override = bool(
            (batch.expiry_date and batch.expiry_date < today) or batch.quality_status == "blocked"
        )
        batch.remaining_quantity -= take
        batch.allocated_quantity = (batch.allocated_quantity or Decimal("0.000")) + take
        batch.consumed_quantity = (batch.consumed_quantity or Decimal("0.000")) + take
        remaining -= take

        inv.current_quantity = max(Decimal("0.000"), inv.current_quantity - take)
        db.add(
            StockMovement(
                inventory_item_id=inv.id,
                batch_id=batch.id,
                movement_type="production_use",
                quantity_delta=-take,
                balance_after=inv.current_quantity,
                reference_type=reference_type,
                reference_id=reference_id or str(batch.id),
                created_by_user_id=actor_user_id,
                notes=f"{strat} allocation from {batch.batch_number}" + (f" [OVERRIDE: {override_reason}]" if was_override else ""),
            )
        )
        if was_override:
            record_audit_log(
                db,
                action="traceability.batch_override_used",
                entity_type="stock_batch",
                entity_id=batch.batch_number,
                actor_user_id=actor_user_id,
                details={"quantity": str(take), "override_reason": override_reason, "reference_id": reference_id},
            )
        allocations.append(
            {
                "stock_batch_id": batch.id,
                "batch_number": batch.batch_number,
                "inventory_item_id": inv.id,
                "ingredient_id": inv.ingredient_id,
                "supplier_id": batch.supplier_id,
                "purchase_order_id": batch.purchase_order_id,
                "goods_receipt_id": batch.goods_receipt_id,
                "quantity_used": take,
                "unit": inv.unit,
                "unit_cost": batch.unit_cost,
                "override_used": was_override,
                "override_reason": override_reason if was_override else None,
            }
        )
    return allocations


# =============================================================================
# END-TO-END TRACEABILITY CHAINS (NO FABRICATED LINKS)
# =============================================================================


def get_batch_traceability_chain(db: Session, batch_id: UUID) -> dict:
    batch = db.get(StockBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Stock batch not found")
    inv = db.get(InventoryItem, batch.inventory_item_id)
    ing = db.get(Ingredient, inv.ingredient_id) if inv else None
    sup = db.get(Supplier, batch.supplier_id) if batch.supplier_id else None
    po = db.get(PurchaseOrder, batch.purchase_order_id) if batch.purchase_order_id else None
    grn = db.get(GoodsReceipt, batch.goods_receipt_id) if batch.goods_receipt_id else None

    prod_links = list(
        db.scalars(select(ProductionBatchIngredient).where(ProductionBatchIngredient.stock_batch_id == batch.id)).all()
    )
    prod_batch_ids = list({pl.production_batch_id for pl in prod_links})
    prod_batches = (
        list(db.scalars(select(ProductionBatch).where(ProductionBatch.id.in_(prod_batch_ids))).all())
        if prod_batch_ids
        else []
    )
    food_ids = list({pb.food_item_id for pb in prod_batches if pb.food_item_id})
    food_map = (
        {f.id: f.name for f in db.scalars(select(FoodItem).where(FoodItem.id.in_(food_ids))).all()}
        if food_ids
        else {}
    )
    recipes = (
        list(db.scalars(select(Recipe).where(Recipe.food_item_id.in_(food_ids))).all())
        if food_ids
        else []
    )

    trace_rows = list(
        db.scalars(select(TraceabilityRecord).where(TraceabilityRecord.stock_batch_id == batch.id)).all()
    )
    order_ids = list({tr.order_id for tr in trace_rows if tr.order_id})
    # Bound related order matching to realistic 3-day shelf/serving window after production
    if prod_batches:
        earliest_prod = min((pb.created_at for pb in prod_batches if pb.created_at), default=None)
        latest_prod = max((pb.created_at for pb in prod_batches if pb.created_at), default=earliest_prod)
        if food_ids and earliest_prod:
            window_end = (latest_prod or earliest_prod) + timedelta(days=3)
            related_order_ids = db.scalars(
                select(Order.id)
                .join(OrderItem, OrderItem.order_id == Order.id)
                .where(
                    Order.canteen_id == (inv.canteen_id if inv else None),
                    Order.payment_status == "CONFIRMED",
                    Order.created_at >= earliest_prod,
                    Order.created_at <= window_end,
                    OrderItem.food_item_id.in_(food_ids),
                )
                .limit(200)
            ).all()
            order_ids = list(set(order_ids) | set(related_order_ids))

    orders = list(db.scalars(select(Order).where(Order.id.in_(order_ids))).all()) if order_ids else []

    missing_links: list[str] = []
    if not sup:
        missing_links.append("vendor_supplier")
    if not po:
        missing_links.append("purchase_order")
    if not grn:
        missing_links.append("goods_receipt")
    if not prod_batches:
        missing_links.append("production_batch")
    if not orders:
        missing_links.append("customer_order")

    completeness = "complete" if not missing_links else "partial"
    return {
        "batch": _serialize_batch(
            batch,
            ingredient_name=ing.name if ing else None,
            unit=inv.unit if inv else None,
            supplier_name=sup.name if sup else None,
            po_number=po.po_number if po else None,
            grn_number=grn.grn_number if grn else None,
        ),
        "trace_completeness": completeness,
        "missing_links": missing_links,
        "data_classification": "actual",
        "vendor": {"id": str(sup.id), "name": sup.name, "phone": sup.phone} if sup else None,
        "purchase_order": {"id": str(po.id), "po_number": po.po_number, "status": po.status} if po else None,
        "goods_receipt": {"id": str(grn.id), "grn_number": grn.grn_number, "received_at": grn.received_at.isoformat() if grn.received_at else None} if grn else None,
        "recipes": [
            {
                "id": str(r.id),
                "food_item_id": str(r.food_item_id),
                "food_item_name": food_map.get(r.food_item_id),
                "yield_portions": r.yield_portions,
                "is_verified": bool(r.is_verified),
            }
            for r in recipes
        ],
        "production_batches": [
            {
                "id": str(pb.id),
                "batch_code": pb.batch_code,
                "food_item_id": str(pb.food_item_id),
                "food_item_name": food_map.get(pb.food_item_id),
                "status": pb.status,
                "planned_quantity": pb.planned_quantity,
                "actual_quantity": pb.actual_quantity,
            }
            for pb in prod_batches
        ],
        "affected_orders": [
            {
                "id": str(o.id),
                "order_number": o.order_number,
                "status": o.status,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ],
    }


def get_order_traceability_chain(db: Session, order_id: UUID) -> dict:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    trace_rows = list(db.scalars(select(TraceabilityRecord).where(TraceabilityRecord.order_id == order.id)).all())
    batch_ids = list({tr.stock_batch_id for tr in trace_rows if tr.stock_batch_id})
    chains = [get_batch_traceability_chain(db, bid) for bid in batch_ids]
    missing = []
    if not chains:
        missing.append("stock_batch_links")
    return {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "canteen_id": str(order.canteen_id),
        "trace_completeness": "complete" if (chains and all(c["trace_completeness"] == "complete" for c in chains)) else "partial",
        "missing_links": missing if not chains else sorted({m for c in chains for m in c["missing_links"]}),
        "data_classification": "actual",
        "linked_batches_count": len(chains),
        "linked_batches": chains,
    }


# =============================================================================
# RECALL MANAGEMENT WORKFLOW & PDF REPORT
# =============================================================================


def initiate_recall(
    db: Session,
    *,
    canteen_id: UUID,
    title: str,
    reason: str,
    severity: str,
    stock_batch_ids: list[UUID],
    investigation_notes: Optional[str],
    actor_user_id: UUID,
) -> dict:
    if not stock_batch_ids:
        raise HTTPException(status_code=400, detail="At least one stock_batch_id is required to initiate a recall")
    sev = (severity or "high").strip().lower()
    if sev not in ("medium", "high", "critical"):
        raise HTTPException(status_code=400, detail="Recall severity must be medium, high, or critical")

    affected_prod_ids: set[str] = set()
    affected_order_ids: set[str] = set()
    valid_batch_ids: list[str] = []

    for bid in stock_batch_ids:
        batch = db.scalar(select(StockBatch).where(StockBatch.id == bid).with_for_update())
        if not batch:
            raise HTTPException(status_code=404, detail=f"Stock batch {bid} not found")
        inv = db.get(InventoryItem, batch.inventory_item_id)
        if inv and inv.canteen_id != canteen_id:
            raise HTTPException(status_code=400, detail="Stock batch does not belong to specified canteen")
        # Immediately quarantine batch under recall investigation
        batch.quality_status = "blocked"
        batch.block_reason = f"Recall under review: {title}"[:255]
        valid_batch_ids.append(str(batch.id))

        chain = get_batch_traceability_chain(db, batch.id)
        for pb in chain["production_batches"]:
            affected_prod_ids.add(pb["id"])
        for o in chain["affected_orders"]:
            affected_order_ids.add(o["id"])

    now = datetime.now(timezone.utc)
    recall_no = f"RCL-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:4].upper()}"
    rec = RecallIncident(
        recall_number=recall_no,
        canteen_id=canteen_id,
        title=title.strip(),
        reason=reason.strip(),
        severity=sev,
        status="under_review",
        affected_stock_batch_ids=valid_batch_ids,
        affected_production_batch_ids=sorted(affected_prod_ids),
        affected_order_ids=sorted(affected_order_ids),
        investigation_notes=investigation_notes,
        initiated_by_user_id=actor_user_id,
    )
    db.add(rec)
    db.flush()
    from app.services.inventory_service import refresh_food_item_ingredient_sufficiency

    refresh_food_item_ingredient_sufficiency(db, canteen_id)
    record_audit_log(
        db,
        action="traceability.recall_initiated",
        entity_type="recall_incident",
        entity_id=recall_no,
        actor_user_id=actor_user_id,
        details={
            "batches": len(valid_batch_ids),
            "production_batches": len(affected_prod_ids),
            "orders": len(affected_order_ids),
        },
    )
    notify_food_safety_event(
        db,
        canteen_id=canteen_id,
        event_type="recall_initiated",
        ref_id=recall_no,
        title=f"Food Recall Initiated (Pending Approval) • {recall_no}",
        message=f"{title}: {len(valid_batch_ids)} stock batch(es), {len(affected_prod_ids)} production batch(es), {len(affected_order_ids)} order(s) identified.",
        priority="critical",
    )
    db.commit()
    db.refresh(rec)
    return _serialize_recall(rec)


def approve_recall(db: Session, recall_id: UUID, *, actor_user_id: UUID) -> dict:
    rec = db.scalar(select(RecallIncident).where(RecallIncident.id == recall_id).with_for_update())
    if not rec:
        raise HTTPException(status_code=404, detail="Recall incident not found")
    if rec.status != "under_review":
        raise HTTPException(status_code=409, detail=f"Recall in status '{rec.status}' cannot be approved")

    now = datetime.now(timezone.utc)
    rec.status = "active_recall"
    rec.approved_by_user_id = actor_user_id
    rec.approved_at = now

    for bid_str in rec.affected_stock_batch_ids or []:
        batch = db.scalar(select(StockBatch).where(StockBatch.id == UUID(bid_str)).with_for_update())
        if batch:
            batch.quality_status = "recalled"
            batch.block_reason = f"Active Recall {rec.recall_number}: {rec.reason}"[:255]

    from app.services.inventory_service import refresh_food_item_ingredient_sufficiency

    refresh_food_item_ingredient_sufficiency(db, rec.canteen_id)
    record_audit_log(
        db,
        action="traceability.recall_approved",
        entity_type="recall_incident",
        entity_id=rec.recall_number,
        actor_user_id=actor_user_id,
        details={"affected_batches": len(rec.affected_stock_batch_ids or [])},
    )
    notify_food_safety_event(
        db,
        canteen_id=rec.canteen_id,
        event_type="recall_activated",
        ref_id=f"{rec.recall_number}:active",
        title=f"ACTIVE FOOD RECALL APPROVED • {rec.recall_number}",
        message=f"{rec.title} is now ACTIVE. All affected ingredient batches are permanently blocked from allocation.",
        priority="critical",
    )
    db.commit()
    db.refresh(rec)
    return _serialize_recall(rec)


def update_recall(
    db: Session,
    recall_id: UUID,
    *,
    status: Optional[str],
    investigation_notes: Optional[str],
    corrective_actions: Optional[str],
    actor_user_id: UUID,
) -> dict:
    rec = db.scalar(select(RecallIncident).where(RecallIncident.id == recall_id).with_for_update())
    if not rec:
        raise HTTPException(status_code=404, detail="Recall incident not found")
    if status is not None:
        st = status.strip().lower()
        if st not in ("resolved", "closed"):
            raise HTTPException(status_code=400, detail="Use /approve to activate a recall, or set status to resolved/closed")
        if rec.status == "closed":
            raise HTTPException(status_code=409, detail="Closed recall incident cannot transition")
        if rec.status == "under_review" and st == "resolved":
            raise HTTPException(
                status_code=409,
                detail="Recall under review must be approved first via /approve before resolving, or closed with investigation_notes",
            )
        eff_notes = investigation_notes if investigation_notes is not None else rec.investigation_notes
        eff_ca = corrective_actions if corrective_actions is not None else rec.corrective_actions
        if st == "resolved" and not (eff_ca and eff_ca.strip()):
            raise HTTPException(status_code=400, detail="corrective_actions are required to mark a recall resolved")
        if rec.status == "under_review" and st == "closed" and not (eff_notes and eff_notes.strip()):
            raise HTTPException(status_code=400, detail="investigation_notes are required to close an unapproved recall")
        if st == "resolved":
            rec.resolved_at = datetime.now(timezone.utc)
        rec.status = st
    if investigation_notes is not None:
        rec.investigation_notes = investigation_notes
    if corrective_actions is not None:
        rec.corrective_actions = corrective_actions
    record_audit_log(
        db,
        action="traceability.recall_updated",
        entity_type="recall_incident",
        entity_id=rec.recall_number,
        actor_user_id=actor_user_id,
        details={"status": rec.status},
    )
    db.commit()
    db.refresh(rec)
    return _serialize_recall(rec)


def _serialize_recall(rec: RecallIncident) -> dict:
    return {
        "id": str(rec.id),
        "recall_number": rec.recall_number,
        "canteen_id": str(rec.canteen_id),
        "title": rec.title,
        "reason": rec.reason,
        "severity": rec.severity,
        "status": rec.status,
        "affected_stock_batch_ids": list(rec.affected_stock_batch_ids or []),
        "affected_production_batch_ids": list(rec.affected_production_batch_ids or []),
        "affected_order_ids": list(rec.affected_order_ids or []),
        "investigation_notes": rec.investigation_notes,
        "corrective_actions": rec.corrective_actions,
        "approved_at": rec.approved_at.isoformat() if rec.approved_at else None,
        "resolved_at": rec.resolved_at.isoformat() if rec.resolved_at else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def list_recalls(db: Session, canteen_id: UUID) -> list[dict]:
    rows = db.scalars(
        select(RecallIncident).where(RecallIncident.canteen_id == canteen_id).order_by(RecallIncident.created_at.desc())
    ).all()
    return [_serialize_recall(r) for r in rows]


def export_recall_pdf(db: Session, recall_id: UUID) -> bytes:
    rec = db.get(RecallIncident, recall_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recall incident not found")
    canteen = db.get(Canteen, rec.canteen_id)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _w, h = A4
    y = h - 45

    def _ensure_space(need: int = 20):
        nonlocal y
        if y < 65 + need:
            c.showPage()
            y = h - 45
            c.setFont("Helvetica", 8.5)

    def _draw_wrapped(prefix: str, text: str, x: int = 40, font: str = "Helvetica", size: float = 8.5, max_chars: int = 92):
        nonlocal y
        c.setFont(font, size)
        full = f"{prefix}{text}"
        words = full.split()
        line = ""
        for w in words:
            cand = f"{line} {w}".strip()
            if len(cand) > max_chars and line:
                _ensure_space(13)
                c.setFont(font, size)
                c.drawString(x, y, line)
                y -= 13
                line = w
            else:
                line = cand
        if line:
            _ensure_space(13)
            c.setFont(font, size)
            c.drawString(x, y, line)
            y -= 13

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, f"CollegeBites Food Traceability & Recall Report — {rec.recall_number}")
    y -= 20
    c.setFont("Helvetica", 9)
    c.drawString(40, y, f"Canteen: {canteen.name if canteen else rec.canteen_id} | Status: {rec.status.upper()} | Severity: {rec.severity.upper()}")
    y -= 15
    c.drawString(
        40,
        y,
        f"Initiated: {rec.created_at.isoformat()[:19] if rec.created_at else 'N/A'} | Approved: {rec.approved_at.isoformat()[:19] if rec.approved_at else 'Pending'} | Resolved: {rec.resolved_at.isoformat()[:19] if rec.resolved_at else 'Open'}",
    )
    y -= 16
    _draw_wrapped("Title: ", rec.title, font="Helvetica-Bold", size=9.5)
    _draw_wrapped("Reason: ", rec.reason, font="Helvetica", size=9)
    if rec.investigation_notes:
        _draw_wrapped("Investigation Notes: ", rec.investigation_notes, font="Helvetica", size=8.5)
    y -= 8

    _ensure_space(28)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, f"Affected Stock Batches ({len(rec.affected_stock_batch_ids or [])}):")
    y -= 14
    for bid in (rec.affected_stock_batch_ids or []):
        b = db.get(StockBatch, UUID(bid))
        if b:
            sup = db.get(Supplier, b.supplier_id) if b.supplier_id else None
            po = db.get(PurchaseOrder, b.purchase_order_id) if b.purchase_order_id else None
            grn = db.get(GoodsReceipt, b.goods_receipt_id) if b.goods_receipt_id else None
            label = (
                f"- {b.batch_number} | status={b.quality_status} | rem={b.remaining_quantity} | expiry={b.expiry_date or 'N/A'} "
                f"| vendor={sup.name if sup else 'N/A'} | PO={po.po_number if po else 'N/A'} | GRN={grn.grn_number if grn else 'N/A'}"
            )
        else:
            label = f"- {bid}"
        _draw_wrapped("", label, x=48, font="Helvetica", size=8)

    y -= 6
    _ensure_space(28)
    prod_ids = [UUID(pid) for pid in (rec.affected_production_batch_ids or [])]
    prod_rows = list(db.scalars(select(ProductionBatch).where(ProductionBatch.id.in_(prod_ids))).all()) if prod_ids else []
    food_ids = list({pb.food_item_id for pb in prod_rows if pb.food_item_id})
    food_map = {f.id: f.name for f in db.scalars(select(FoodItem).where(FoodItem.id.in_(food_ids))).all()} if food_ids else {}
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, f"Affected Production Batches ({len(rec.affected_production_batch_ids or [])}):")
    y -= 14
    if not prod_rows:
        _draw_wrapped("", "None recorded.", x=48, size=8)
    else:
        for pb in prod_rows:
            _draw_wrapped(
                "",
                f"- {pb.batch_code} | Dish: {food_map.get(pb.food_item_id, str(pb.food_item_id))} | Status: {pb.status} | Planned: {pb.planned_quantity} | Actual: {pb.actual_quantity or 0}",
                x=48,
                size=8,
            )

    y -= 6
    _ensure_space(28)
    ord_ids = [UUID(oid) for oid in (rec.affected_order_ids or [])]
    ord_rows = list(db.scalars(select(Order).where(Order.id.in_(ord_ids))).all()) if ord_ids else []
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, f"Affected Confirmed Customer Orders ({len(rec.affected_order_ids or [])}):")
    y -= 14
    if not ord_rows:
        _draw_wrapped("", "None recorded.", x=48, size=8)
    else:
        for o in ord_rows[:80]:
            _draw_wrapped(
                "",
                f"- {o.order_number} | Status: {o.status} | Created: {o.created_at.isoformat()[:19] if o.created_at else 'N/A'}",
                x=48,
                size=8,
            )
        if len(ord_rows) > 80:
            _draw_wrapped("", f"... and {len(ord_rows) - 80} additional order(s).", x=48, size=8)

    if rec.corrective_actions:
        y -= 6
        _draw_wrapped("Corrective Actions: ", rec.corrective_actions, font="Helvetica-Bold", size=8.5)
    c.showPage()
    c.save()
    return buf.getvalue()
