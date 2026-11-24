import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import desc, func, or_, select
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from app.core.cache import invalidate_menu, invalidate_reports
from app.core.time_utils import today_college
from app.models.auth import User
from app.models.college import Canteen
from app.models.inventory import (
    DailyFoodPrepLog,
    GoodsReceipt,
    GoodsReceiptItem,
    InventoryAuditLog,
    InventoryItem,
    PriceChangeRequest,
    PurchaseOrder,
    PurchaseOrderItem,
    StockAdjustment,
    StockBatch,
    StockMovement,
    StockTransfer,
    Supplier,
    VendorPayment,
    WastageRecord,
)
from app.models.menu import FoodItem, Ingredient, MenuRestoreApproval, Recipe, RecipeIngredient
from app.models.order import Order, OrderItem
from app.services.audit_service import record_audit_log
from app.websockets import emit_order_event_sync


@sa_event.listens_for(Session, "after_commit")
def _flush_inventory_ws_events(session: Session) -> None:
    pending = session.info.pop("_pending_inv_ws", None)
    if not pending:
        return
    for canteen_id, event_type, payload in pending:
        invalidate_menu(canteen_id)
        invalidate_reports(canteen_id)
        emit_order_event_sync(canteen_id, "inventory", event_type, payload)


def _queue_inv_ws_event(db: Session, canteen_id: UUID, event_type: str, payload: dict) -> None:
    queue = db.info.setdefault("_pending_inv_ws", [])
    queue.append((str(canteen_id), event_type, payload))


ACTIVE_ORDER_STATUSES = (
    "CREATED",
    "PAYMENT_PENDING",
    "PAYMENT_CONFIRMED",
    "PLACED",
    "ACCEPTED",
    "PREPARING",
    "READY",
)


def _log_inv_audit(
    db: Session,
    *,
    canteen_id: UUID,
    inventory_item_id: Optional[UUID],
    action: str,
    field_name: Optional[str],
    old_value: Optional[str],
    new_value: Optional[str],
    actor_user_id: Optional[UUID],
    reason: Optional[str] = None,
) -> None:
    db.add(
        InventoryAuditLog(
            canteen_id=canteen_id,
            inventory_item_id=inventory_item_id,
            action=action,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            changed_by_user_id=actor_user_id,
        )
    )


def _classify_loss_type(operation_type: Optional[str], reason: str) -> str:
    if operation_type in ("damaged", "expired", "wastage"):
        return operation_type
    r = (reason or "").lower()
    if "expir" in r:
        return "expired"
    if any(k in r for k in ("damag", "spoil", "spill", "broken", "leak")):
        return "damaged"
    return "wastage"


def _consume_batches(
    db: Session,
    inventory_item_id: UUID,
    qty: Decimal,
    *,
    exclude_expired: bool = False,
    batch_id: Optional[UUID] = None,
) -> list[tuple[Optional[UUID], Decimal, Optional[date], Decimal]]:
    """Consume stock from specific batch or FEFO order with row locks, returning [(batch_id, taken, expiry, unit_cost)]."""
    if qty <= Decimal("0.000"):
        return []
    consumed: list[tuple[Optional[UUID], Decimal, Optional[date], Decimal]] = []
    if batch_id:
        batch = db.scalar(
            select(StockBatch)
            .where(StockBatch.id == batch_id, StockBatch.inventory_item_id == inventory_item_id)
            .with_for_update()
        )
        if not batch:
            raise HTTPException(status_code=404, detail="Stock batch not found for this inventory item")
        take = min(batch.remaining_quantity, qty)
        batch.remaining_quantity -= take
        if take > 0:
            consumed.append((batch.id, take, batch.expiry_date, batch.unit_cost))
        return consumed

    stmt = (
        select(StockBatch)
        .where(StockBatch.inventory_item_id == inventory_item_id, StockBatch.remaining_quantity > 0)
        .order_by(StockBatch.expiry_date.asc().nulls_last(), StockBatch.received_at.asc())
        .with_for_update()
    )
    if exclude_expired:
        today = today_college()
        stmt = stmt.where(
            or_(StockBatch.expiry_date.is_(None), StockBatch.expiry_date >= today),
            StockBatch.quality_status.not_in(["rejected", "blocked", "recalled"]),
        )
    remaining = qty
    for batch in db.scalars(stmt).all():
        if remaining <= Decimal("0.000"):
            break
        take = min(batch.remaining_quantity, remaining)
        batch.remaining_quantity -= take
        batch.consumed_quantity = (batch.consumed_quantity or Decimal("0.000")) + take
        remaining -= take
        if take > 0:
            consumed.append((batch.id, take, batch.expiry_date, batch.unit_cost))
    return consumed


def _expired_batch_totals_map(db: Session, inv_ids: list[UUID]) -> dict[UUID, Decimal]:
    """Sum remaining batch quantities that are unusable (expired, blocked, rejected, or recalled)."""
    if not inv_ids:
        return {}
    today = today_college()
    rows = db.execute(
        select(StockBatch.inventory_item_id, func.coalesce(func.sum(StockBatch.remaining_quantity), 0))
        .where(
            StockBatch.inventory_item_id.in_(inv_ids),
            StockBatch.remaining_quantity > 0,
            or_(
                StockBatch.expiry_date < today,
                StockBatch.quality_status.in_(("blocked", "rejected", "recalled")),
            ),
        )
        .group_by(StockBatch.inventory_item_id)
    ).all()
    return {iid: Decimal(str(tot)) for iid, tot in rows}


def get_unexpired_stock_quantity(
    db: Session,
    inv: InventoryItem,
    *,
    exclude_reserved: bool = False,
    expired_map: Optional[dict[UUID, Decimal]] = None,
) -> Decimal:
    if inv.is_archived or not inv.is_available:
        return Decimal("0.000")
    exp_qty = (
        expired_map.get(inv.id, Decimal("0.000"))
        if expired_map is not None
        else _expired_batch_totals_map(db, [inv.id]).get(inv.id, Decimal("0.000"))
    )
    usable = max(Decimal("0.000"), inv.current_quantity - exp_qty)
    if exclude_reserved:
        usable = max(Decimal("0.000"), usable - max(Decimal("0.000"), inv.reserved_quantity))
    return usable


def _compute_order_needed_ingredients(db: Session, order_id: UUID) -> dict[UUID, Decimal]:
    needed_map: dict[UUID, Decimal] = {}
    order_items = db.scalars(select(OrderItem).where(OrderItem.order_id == order_id)).all()
    food_ids = list({oi.food_item_id for oi in order_items if oi.food_item_id})
    if not food_ids:
        return needed_map
    recipes = {r.food_item_id: r for r in db.scalars(select(Recipe).where(Recipe.food_item_id.in_(food_ids))).all()}
    if not recipes:
        return needed_map
    recipe_ids = [r.id for r in recipes.values()]
    reqs_by_recipe: dict[UUID, list[RecipeIngredient]] = {}
    for req in db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(recipe_ids))).all():
        reqs_by_recipe.setdefault(req.recipe_id, []).append(req)
    for oi in order_items:
        if not oi.food_item_id:
            continue
        recipe = recipes.get(oi.food_item_id)
        if not recipe:
            continue
        for req in reqs_by_recipe.get(recipe.id, ()):
            needed = ((req.quantity_required * Decimal(oi.quantity)) / Decimal(max(1, recipe.yield_portions))).quantize(
                Decimal("0.001")
            )
            needed_map[req.ingredient_id] = needed_map.get(req.ingredient_id, Decimal("0.000")) + needed
    return needed_map


def _trigger_low_stock_alert_if_needed(
    db: Session,
    inv: InventoryItem,
    ingredient_name: str,
    *,
    canteen_id: UUID,
) -> None:
    if inv.is_archived or inv.current_quantity > inv.reorder_level:
        return
    blocked_names = [
        fi.name
        for fi in db.scalars(
            select(FoodItem)
            .join(Recipe, Recipe.food_item_id == FoodItem.id)
            .join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id)
            .where(
                FoodItem.canteen_id == canteen_id,
                RecipeIngredient.ingredient_id == inv.ingredient_id,
                FoodItem.insufficient_ingredients.is_(True),
            )
        ).all()
    ]
    try:
        from app.services.notification_service import notify_inventory_stock_alert

        notify_inventory_stock_alert(
            db,
            canteen_id=canteen_id,
            inventory_item_id=inv.id,
            ingredient_name=ingredient_name,
            current_qty=str(inv.current_quantity),
            reorder_level=str(inv.reorder_level),
            unit=inv.unit,
            blocked_foods=blocked_names,
            is_critical=(inv.current_quantity <= Decimal("0.000")),
        )
    except ImportError:
        pass


def refresh_food_item_ingredient_sufficiency(
    db: Session,
    canteen_id: UUID,
    *,
    require_restore_approval: bool = True,
) -> list[str]:
    """Recompute FoodItem.insufficient_ingredients using unexpired, unreserved ingredient stock (batched O(1) queries).
    Auto-disables depleted items and queues Manager Approval before re-enabling upon restock."""
    invs = db.scalars(select(InventoryItem).where(InventoryItem.canteen_id == canteen_id)).all()
    expired_map = _expired_batch_totals_map(db, [inv.id for inv in invs])
    inv_map = {
        inv.ingredient_id: get_unexpired_stock_quantity(
            db, inv, exclude_reserved=True, expired_map=expired_map
        )
        for inv in invs
    }
    items = db.scalars(select(FoodItem).where(FoodItem.canteen_id == canteen_id)).all()
    if not items:
        return []
    item_ids = [f.id for f in items]
    recipes_by_food = {
        r.food_item_id: r for r in db.scalars(select(Recipe).where(Recipe.food_item_id.in_(item_ids))).all()
    }
    recipe_ids = [r.id for r in recipes_by_food.values()]
    reqs_by_recipe: dict[UUID, list[RecipeIngredient]] = {}
    if recipe_ids:
        for req in db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(recipe_ids))).all():
            reqs_by_recipe.setdefault(req.recipe_id, []).append(req)
    pending_approval_food_ids = (
        set(
            db.scalars(
                select(MenuRestoreApproval.food_item_id).where(
                    MenuRestoreApproval.food_item_id.in_(item_ids),
                    MenuRestoreApproval.status == "pending_approval",
                )
            ).all()
        )
        if require_restore_approval
        else set()
    )

    blocked_names: list[str] = []
    changed_foods: list[dict] = []
    for food in items:
        recipe = recipes_by_food.get(food.id)
        if not recipe:
            continue
        req_rows = reqs_by_recipe.get(recipe.id)
        if not req_rows:
            continue
        short = False
        for req in req_rows:
            avail = inv_map.get(req.ingredient_id, Decimal("0.000"))
            per_portion = req.quantity_required / Decimal(max(1, recipe.yield_portions))
            if avail < per_portion:
                short = True
                break
        was_short = bool(food.insufficient_ingredients)
        if short:
            if not was_short or food.is_available:
                changed_foods.append(
                    {
                        "food_item_id": str(food.id),
                        "name": food.name,
                        "insufficient_ingredients": True,
                        "is_available": False,
                    }
                )
            food.insufficient_ingredients = True
            food.is_available = False
            food.pending_restore_approval = False
            blocked_names.append(food.name)
        elif was_short:
            # Ingredients replenished above threshold
            food.insufficient_ingredients = False
            if require_restore_approval:
                food.is_available = False
                food.pending_restore_approval = True
                if food.id not in pending_approval_food_ids:
                    pending_approval_food_ids.add(food.id)
                    db.add(
                        MenuRestoreApproval(
                            canteen_id=canteen_id,
                            food_item_id=food.id,
                            status="pending_approval",
                            reason="Stock replenished above recipe minimum; awaiting manager approval to restore menu visibility",
                        )
                    )
            else:
                if not food.pending_restore_approval:
                    food.is_available = True
            changed_foods.append(
                {
                    "food_item_id": str(food.id),
                    "name": food.name,
                    "insufficient_ingredients": False,
                    "is_available": food.is_available,
                    "pending_restore_approval": food.pending_restore_approval,
                }
            )
    _queue_inv_ws_event(
        db,
        canteen_id,
        "inventory.updated",
        {"canteen_id": str(canteen_id), "blocked_items": blocked_names},
    )
    if changed_foods:
        _queue_inv_ws_event(
            db,
            canteen_id,
            "menu.availability_changed",
            {"canteen_id": str(canteen_id), "changed": changed_foods},
        )
    return blocked_names


def reserve_inventory_for_order(
    db: Session,
    canteen_id: UUID,
    needed_ingredients: dict[UUID, Decimal],
) -> None:
    """Atomically lock and reserve ingredient quantities during checkout to prevent concurrent overselling."""
    if not needed_ingredients:
        return
    invs = db.scalars(
        select(InventoryItem)
        .where(
            InventoryItem.canteen_id == canteen_id,
            InventoryItem.ingredient_id.in_(list(needed_ingredients.keys())),
        )
        .order_by(InventoryItem.id.asc())
        .with_for_update()
    ).all()
    if not invs:
        return
    expired_map = _expired_batch_totals_map(db, [inv.id for inv in invs])
    for inv in invs:
        req_qty = needed_ingredients.get(inv.ingredient_id, Decimal("0.000")).quantize(Decimal("0.001"))
        if req_qty <= Decimal("0.000"):
            continue
        avail = get_unexpired_stock_quantity(db, inv, exclude_reserved=True, expired_map=expired_map)
        if avail < req_qty:
            raise HTTPException(
                status_code=400,
                detail="Insufficient non-expired ingredient stock for requested quantity",
            )
        inv.reserved_quantity = max(Decimal("0.000"), inv.reserved_quantity) + req_qty
    db.flush()
    refresh_food_item_ingredient_sufficiency(db, canteen_id)


def release_inventory_reservation_for_order(db: Session, order: Order) -> None:
    """Release previously reserved ingredient quantities when an unpaid order fails, expires, or is cancelled."""
    needed = _compute_order_needed_ingredients(db, order.id)
    if not needed:
        return
    invs = db.scalars(
        select(InventoryItem)
        .where(
            InventoryItem.canteen_id == order.canteen_id,
            InventoryItem.ingredient_id.in_(list(needed.keys())),
        )
        .order_by(InventoryItem.id.asc())
        .with_for_update()
    ).all()
    for inv in invs:
        rel_qty = needed.get(inv.ingredient_id, Decimal("0.000"))
        if rel_qty > Decimal("0.000"):
            inv.reserved_quantity = max(Decimal("0.000"), inv.reserved_quantity - rel_qty)
    db.flush()
    refresh_food_item_ingredient_sufficiency(db, order.canteen_id, require_restore_approval=False)


def deduct_inventory_for_order(db: Session, order: Order, actor_user_id: Optional[UUID] = None) -> None:
    """Deduct ingredients for an order exactly once using FEFO batches, row locks, and reservation settlement."""
    if order.inventory_deducted:
        return
    already = db.scalar(
        select(StockMovement.id).where(StockMovement.reference_type == "order", StockMovement.reference_id == str(order.id))
    )
    if already:
        order.inventory_deducted = True
        return

    needed_map = _compute_order_needed_ingredients(db, order.id)
    low_stock_targets: list[tuple[InventoryItem, str]] = []
    if needed_map:
        invs = db.scalars(
            select(InventoryItem)
            .where(
                InventoryItem.canteen_id == order.canteen_id,
                InventoryItem.ingredient_id.in_(list(needed_map.keys())),
            )
            .order_by(InventoryItem.id.asc())
            .with_for_update()
        ).all()
        ing_names = {
            ing.id: ing.name
            for ing in db.scalars(select(Ingredient).where(Ingredient.id.in_(list(needed_map.keys())))).all()
        }
        for inv in invs:
            needed = needed_map.get(inv.ingredient_id, Decimal("0.000"))
            if needed <= Decimal("0.000"):
                continue
            inv.current_quantity = max(Decimal("0.000"), inv.current_quantity - needed)
            inv.reserved_quantity = max(Decimal("0.000"), inv.reserved_quantity - needed)

            consumed = _consume_batches(db, inv.id, needed, exclude_expired=True)
            db.add(
                StockMovement(
                    inventory_item_id=inv.id,
                    batch_id=consumed[0][0] if consumed else None,
                    movement_type="order_deduct",
                    quantity_delta=-needed,
                    balance_after=inv.current_quantity,
                    reference_type="order",
                    reference_id=str(order.id),
                    created_by_user_id=actor_user_id,
                    notes=f"Deducted for order {order.order_number}",
                )
            )
            if consumed:
                try:
                    from app.models.enterprise import TraceabilityRecord

                    for b_id, b_taken, _b_exp, _b_cost in consumed:
                        if not b_id:
                            continue
                        b_obj = db.get(StockBatch, b_id)
                        missing = []
                        if not (b_obj and b_obj.supplier_id):
                            missing.append("supplier_id")
                        if not (b_obj and b_obj.purchase_order_id):
                            missing.append("purchase_order_id")
                        if not (b_obj and b_obj.goods_receipt_id):
                            missing.append("goods_receipt_id")
                        missing.append("production_batch_id")
                        db.add(
                            TraceabilityRecord(
                                canteen_id=order.canteen_id,
                                supplier_id=b_obj.supplier_id if b_obj else None,
                                purchase_order_id=b_obj.purchase_order_id if b_obj else None,
                                goods_receipt_id=b_obj.goods_receipt_id if b_obj else None,
                                stock_batch_id=b_id,
                                order_id=order.id,
                                trace_completeness="partial",
                                missing_links=missing,
                                notes=f"Direct order deduction {b_taken} {inv.unit} for order {order.order_number}",
                            )
                        )
                except Exception:
                    pass
            if inv.current_quantity <= inv.reorder_level:
                low_stock_targets.append((inv, ing_names.get(inv.ingredient_id, "Ingredient")))

    order.inventory_deducted = True
    refresh_food_item_ingredient_sufficiency(db, order.canteen_id)
    for inv_low, ing_name in low_stock_targets:
        _trigger_low_stock_alert_if_needed(db, inv_low, ing_name, canteen_id=order.canteen_id)


def _compute_supplier_metrics_map(db: Session, supplier_ids: list[UUID]) -> dict[UUID, dict]:
    if not supplier_ids:
        return {}
    from sqlalchemy import case

    metrics: dict[UUID, dict] = {
        sid: {
            "total_purchase_orders": 0,
            "received_orders_count": 0,
            "pending_orders_count": 0,
            "total_billed_amount": Decimal("0.00"),
            "total_paid_amount": Decimal("0.00"),
            "pending_payment_amount": Decimal("0.00"),
            "outstanding_balance": Decimal("0.00"),
            "total_ordered_qty": Decimal("0.000"),
            "total_received_qty": Decimal("0.000"),
            "total_damaged_rejected_qty": Decimal("0.000"),
        }
        for sid in supplier_ids
    }

    # 3 single-pass SQL GROUP BY queries instead of loading all PO, POItem & VendorPayment ORM rows
    for sid, tot_po, rec_po, pend_po, billed in db.execute(
        select(
            PurchaseOrder.supplier_id,
            func.count(PurchaseOrder.id),
            func.coalesce(func.sum(case((PurchaseOrder.status == "received", 1), else_=0)), 0),
            func.coalesce(func.sum(case((PurchaseOrder.status.not_in(["received", "cancelled", "draft"]), 1), else_=0)), 0),
            func.coalesce(func.sum(case((PurchaseOrder.status.not_in(["cancelled", "draft"]), PurchaseOrder.total_cost), else_=0)), 0),
        )
        .where(PurchaseOrder.supplier_id.in_(supplier_ids))
        .group_by(PurchaseOrder.supplier_id)
    ).all():
        m = metrics[sid]
        m["total_purchase_orders"] = int(tot_po or 0)
        m["received_orders_count"] = int(rec_po or 0)
        m["pending_orders_count"] = int(pend_po or 0)
        m["total_billed_amount"] = Decimal(str(billed or 0))

    for sid, ord_q, rec_q, dmg_q, rej_q in db.execute(
        select(
            PurchaseOrder.supplier_id,
            func.coalesce(func.sum(PurchaseOrderItem.quantity_ordered), 0),
            func.coalesce(func.sum(PurchaseOrderItem.quantity_received), 0),
            func.coalesce(func.sum(PurchaseOrderItem.quantity_damaged), 0),
            func.coalesce(func.sum(PurchaseOrderItem.quantity_rejected), 0),
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
        .where(PurchaseOrder.supplier_id.in_(supplier_ids), PurchaseOrder.status != "cancelled")
        .group_by(PurchaseOrder.supplier_id)
    ).all():
        m = metrics[sid]
        m["total_ordered_qty"] = Decimal(str(ord_q or 0))
        m["total_received_qty"] = Decimal(str(rec_q or 0))
        m["total_damaged_rejected_qty"] = Decimal(str(dmg_q or 0)) + Decimal(str(rej_q or 0))

    for sid, paid_amt, pend_amt in db.execute(
        select(
            VendorPayment.supplier_id,
            func.coalesce(func.sum(case((VendorPayment.status == "verified", VendorPayment.amount), else_=0)), 0),
            func.coalesce(func.sum(case((VendorPayment.status == "pending_verification", VendorPayment.amount), else_=0)), 0),
        )
        .where(VendorPayment.supplier_id.in_(supplier_ids))
        .group_by(VendorPayment.supplier_id)
    ).all():
        m = metrics[sid]
        m["total_paid_amount"] = Decimal(str(paid_amt or 0))
        m["pending_payment_amount"] = Decimal(str(pend_amt or 0))

    for sid, m in metrics.items():
        billed = m["total_billed_amount"].quantize(Decimal("0.01"))
        paid = m["total_paid_amount"].quantize(Decimal("0.01"))
        pend = m["pending_payment_amount"].quantize(Decimal("0.01"))
        outstanding = max(Decimal("0.00"), billed - paid).quantize(Decimal("0.01"))
        ord_q = m["total_ordered_qty"]
        rec_q = m["total_received_qty"]
        fulfillment_pct = float(((rec_q / ord_q) * Decimal("100")).quantize(Decimal("0.1"))) if ord_q > 0 else 100.0
        m["total_billed_amount"] = str(billed)
        m["total_paid_amount"] = str(paid)
        m["pending_payment_amount"] = str(pend)
        m["outstanding_balance"] = str(outstanding)
        m["total_ordered_qty"] = str(ord_q.quantize(Decimal("0.001")))
        m["total_received_qty"] = str(rec_q.quantize(Decimal("0.001")))
        m["total_damaged_rejected_qty"] = str(m["total_damaged_rejected_qty"].quantize(Decimal("0.001")))
        m["fulfillment_rate_percent"] = fulfillment_pct
    return metrics


def _serialize_supplier(sup: Supplier, perf: Optional[dict] = None) -> dict:
    p = perf or {
        "total_purchase_orders": 0,
        "received_orders_count": 0,
        "pending_orders_count": 0,
        "total_billed_amount": "0.00",
        "total_paid_amount": "0.00",
        "pending_payment_amount": "0.00",
        "outstanding_balance": "0.00",
        "total_ordered_qty": "0.000",
        "total_received_qty": "0.000",
        "total_damaged_rejected_qty": "0.000",
        "fulfillment_rate_percent": 100.0,
    }
    return {
        "id": str(sup.id),
        "name": sup.name,
        "contact_person": sup.contact_person,
        "phone": sup.phone,
        "email": sup.email,
        "address": sup.address,
        "gst_number": sup.gst_number,
        "business_details": sup.business_details,
        "supplied_products": list(sup.supplied_products or []),
        "payment_terms": sup.payment_terms,
        "lead_time_days": int(sup.lead_time_days) if sup.lead_time_days is not None else 2,
        "is_active": sup.is_active,
        "created_at": sup.created_at.isoformat() if sup.created_at else None,
        "updated_at": sup.updated_at.isoformat() if sup.updated_at else None,
        **p,
    }


def list_suppliers(
    db: Session,
    *,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    product: Optional[str] = None,
) -> list[dict]:
    stmt = select(Supplier).order_by(Supplier.name)
    if is_active is not None:
        stmt = stmt.where(Supplier.is_active.is_(is_active))
    rows = list(db.scalars(stmt).all())
    q = (search or "").strip().lower()
    prod_q = (product or "").strip().lower()
    filtered: list[Supplier] = []
    for s in rows:
        if q:
            hay = " ".join(
                filter(
                    None,
                    [
                        s.name,
                        s.contact_person,
                        s.phone,
                        s.email,
                        s.gst_number,
                        s.business_details,
                        " ".join(str(x) for x in (s.supplied_products or [])),
                    ],
                )
            ).lower()
            if q not in hay:
                continue
        if prod_q:
            prods = [str(x).lower() for x in (s.supplied_products or [])]
            if not any(prod_q in p for p in prods):
                continue
        filtered.append(s)
    perf_map = _compute_supplier_metrics_map(db, [s.id for s in filtered])
    return [_serialize_supplier(s, perf_map.get(s.id)) for s in filtered]


def create_supplier(db: Session, data: dict, actor_user_id: UUID) -> dict:
    payload = dict(data)
    if payload.get("supplied_products") is None:
        payload["supplied_products"] = []
    if payload.get("lead_time_days") is None:
        payload.pop("lead_time_days", None)
    sup = Supplier(**payload)
    db.add(sup)
    record_audit_log(db, action="supplier.created", entity_type="supplier", entity_id=sup.name, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(sup)
    perf_map = _compute_supplier_metrics_map(db, [sup.id])
    return _serialize_supplier(sup, perf_map.get(sup.id))


def update_supplier(db: Session, supplier_id: UUID, data: dict, actor_user_id: UUID) -> dict:
    sup = db.get(Supplier, supplier_id)
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")
    for k, v in data.items():
        if v is not None:
            setattr(sup, k, v)
    record_audit_log(db, action="supplier.updated", entity_type="supplier", entity_id=str(sup.id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(sup)
    perf_map = _compute_supplier_metrics_map(db, [sup.id])
    return _serialize_supplier(sup, perf_map.get(sup.id))


def update_inventory_item(db: Session, inventory_item_id: UUID, data: dict, actor_user_id: UUID) -> dict:
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    ing = db.get(Ingredient, inv.ingredient_id)
    reason = data.get("reason")

    if data.get("preferred_supplier_id") is not None:
        sup = db.get(Supplier, data["preferred_supplier_id"])
        if not sup:
            raise HTTPException(status_code=404, detail="Preferred supplier not found")

    # Track per-field metadata changes on InventoryItem
    inv_field_specs = [
        ("reorder_level", lambda v: Decimal(str(v))),
        ("unit_cost", lambda v: Decimal(str(v)).quantize(Decimal("0.01"))),
        ("unit", lambda v: str(v).strip()),
        ("category", lambda v: str(v).strip()),
        ("description", lambda v: (str(v).strip() if v is not None else None)),
        ("image_url", lambda v: (str(v).strip() if v else None)),
        ("storage_location", lambda v: (str(v).strip() if v else None)),
        ("preferred_supplier_id", lambda v: v),
        ("is_available", lambda v: bool(v)),
    ]
    old_cost = inv.unit_cost
    for field_name, coerce in inv_field_specs:
        if field_name not in data:
            continue
        new_val = coerce(data[field_name])
        old_val = getattr(inv, field_name)
        if new_val != old_val:
            setattr(inv, field_name, new_val)
            _log_inv_audit(
                db,
                canteen_id=inv.canteen_id,
                inventory_item_id=inv.id,
                action="purchase_price_updated" if field_name == "unit_cost" else "edited",
                field_name="purchase_price" if field_name == "unit_cost" else field_name,
                old_value=str(old_val) if old_val is not None else None,
                new_value=str(new_val) if new_val is not None else None,
                actor_user_id=actor_user_id,
                reason=reason,
            )

    if ing:
        if "name" in data and data["name"] is not None:
            new_name = str(data["name"]).strip()
            if new_name and new_name != ing.name:
                _log_inv_audit(
                    db,
                    canteen_id=inv.canteen_id,
                    inventory_item_id=inv.id,
                    action="edited",
                    field_name="name",
                    old_value=ing.name,
                    new_value=new_name,
                    actor_user_id=actor_user_id,
                    reason=reason,
                )
                ing.name = new_name
        if "unit" in data and data["unit"]:
            ing.unit = inv.unit
        if "is_allergen" in data and data["is_allergen"] is not None:
            new_alg = bool(data["is_allergen"])
            if new_alg != ing.is_allergen:
                _log_inv_audit(
                    db,
                    canteen_id=inv.canteen_id,
                    inventory_item_id=inv.id,
                    action="edited",
                    field_name="is_allergen",
                    old_value=str(ing.is_allergen),
                    new_value=str(new_alg),
                    actor_user_id=actor_user_id,
                    reason=reason,
                )
                ing.is_allergen = new_alg

    if inv.unit_cost != old_cost:
        db.add(
            PriceChangeRequest(
                canteen_id=inv.canteen_id,
                inventory_item_id=inv.id,
                price_kind="purchase_cost",
                old_price=old_cost,
                new_price=inv.unit_cost,
                reason=reason or "Direct purchase cost update",
                status="applied",
                requested_by_user_id=actor_user_id,
                reviewed_by_user_id=actor_user_id,
                reviewed_at=datetime.now(timezone.utc),
            )
        )

    refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    record_audit_log(
        db,
        action="inventory.item_updated",
        entity_type="inventory_item",
        entity_id=str(inv.id),
        actor_user_id=actor_user_id,
    )
    db.commit()
    return {
        "inventory_item_id": str(inv.id),
        "name": ing.name if ing else None,
        "category": inv.category,
        "description": inv.description,
        "image_url": inv.image_url,
        "storage_location": inv.storage_location,
        "preferred_supplier_id": str(inv.preferred_supplier_id) if inv.preferred_supplier_id else None,
        "is_available": inv.is_available,
        "is_archived": inv.is_archived,
        "reorder_level": str(inv.reorder_level),
        "unit_cost": str(inv.unit_cost),
        "unit": inv.unit,
    }


def list_inventory_movements(db: Session, canteen_id: UUID, limit: int = 100, offset: int = 0) -> list[dict]:
    rows = db.execute(
        select(StockMovement, InventoryItem, Ingredient.name)
        .join(InventoryItem, InventoryItem.id == StockMovement.inventory_item_id)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id)
        .order_by(desc(StockMovement.created_at))
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": str(mv.id),
            "inventory_item_id": str(mv.inventory_item_id),
            "ingredient_name": ing_name,
            "unit": inv.unit,
            "movement_type": mv.movement_type,
            "quantity_delta": str(mv.quantity_delta),
            "balance_after": str(mv.balance_after),
            "reference_type": mv.reference_type,
            "reference_id": mv.reference_id,
            "notes": mv.notes,
            "created_at": mv.created_at.isoformat() if mv.created_at else None,
        }
        for mv, inv, ing_name in rows
    ]


def create_ingredient_with_stock(db: Session, data: dict, actor_user_id: UUID) -> dict:
    sku = (data.get("sku") or "").strip().upper() or f"ING-{uuid4().hex[:6].upper()}"
    dup = db.scalar(
        select(Ingredient).where(Ingredient.canteen_id == data["canteen_id"], Ingredient.sku == sku)
    )
    if dup:
        raise HTTPException(status_code=409, detail="Ingredient SKU already exists in this canteen")
    pref_sup_id = data.get("preferred_supplier_id")
    if pref_sup_id is not None and not db.get(Supplier, pref_sup_id):
        raise HTTPException(status_code=404, detail="Preferred supplier not found")

    ing = Ingredient(
        canteen_id=data["canteen_id"],
        name=data["name"].strip(),
        sku=sku,
        unit=data.get("unit", "grams"),
        is_allergen=data.get("is_allergen", False),
    )
    db.add(ing)
    db.flush()
    inv = InventoryItem(
        canteen_id=data["canteen_id"],
        ingredient_id=ing.id,
        current_quantity=Decimal(str(data.get("initial_quantity", "0"))),
        reorder_level=Decimal(str(data.get("reorder_level", "100"))),
        unit=ing.unit,
        unit_cost=Decimal(str(data.get("unit_cost", "0.00"))).quantize(Decimal("0.01")),
        category=(data.get("category") or "General").strip(),
        description=(data.get("description") or "").strip() or None,
        image_url=(data.get("image_url") or "").strip() or None,
        storage_location=(data.get("storage_location") or "").strip() or None,
        preferred_supplier_id=pref_sup_id,
        is_available=data.get("is_available", True),
    )
    db.add(inv)
    db.flush()
    _log_inv_audit(
        db,
        canteen_id=inv.canteen_id,
        inventory_item_id=inv.id,
        action="created",
        field_name="item",
        old_value=None,
        new_value=f"{ing.name} ({ing.sku}) qty={inv.current_quantity} {inv.unit} cost={inv.unit_cost}",
        actor_user_id=actor_user_id,
    )
    if inv.current_quantity > 0:
        db.add(
            StockBatch(
                inventory_item_id=inv.id,
                supplier_id=pref_sup_id,
                batch_number=f"OPEN-{ing.sku}",
                initial_quantity=inv.current_quantity,
                remaining_quantity=inv.current_quantity,
                unit_cost=inv.unit_cost,
                received_at=datetime.now(timezone.utc),
                expiry_date=data.get("expiry_date"),
            )
        )
        db.add(
            StockMovement(
                inventory_item_id=inv.id,
                movement_type="purchase",
                quantity_delta=inv.current_quantity,
                balance_after=inv.current_quantity,
                reference_type="opening",
                reference_id=str(inv.id),
                created_by_user_id=actor_user_id,
                notes="Opening stock",
            )
        )
    db.commit()
    return {
        "ingredient_id": str(ing.id),
        "inventory_item_id": str(inv.id),
        "name": ing.name,
        "sku": ing.sku,
        "category": inv.category,
        "unit_cost": str(inv.unit_cost),
    }


def list_canteen_inventory(
    db: Session,
    canteen_id: UUID,
    *,
    search: Optional[str] = None,
    category: Optional[str] = None,
    stock_status: Optional[str] = None,
    include_archived: bool = False,
) -> list[dict]:
    stmt = (
        select(InventoryItem, Ingredient, Supplier.name)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .outerjoin(Supplier, Supplier.id == InventoryItem.preferred_supplier_id)
        .where(InventoryItem.canteen_id == canteen_id)
    )
    if not include_archived:
        stmt = stmt.where(InventoryItem.is_archived.is_(False))
    rows = db.execute(stmt.order_by(InventoryItem.is_archived.asc(), Ingredient.name.asc())).all()

    # Map ingredient_id -> linked food items (from recipes) in a single query
    recipe_rows = db.execute(
        select(RecipeIngredient.ingredient_id, FoodItem)
        .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
        .join(FoodItem, FoodItem.id == Recipe.food_item_id)
        .where(FoodItem.canteen_id == canteen_id)
    ).all()
    linked_dishes_map: dict[UUID, list[dict]] = {}
    for ing_id, fi in recipe_rows:
        linked_dishes_map.setdefault(ing_id, [])
        if all(d["id"] != str(fi.id) for d in linked_dishes_map[ing_id]):
            linked_dishes_map[ing_id].append({
                "id": str(fi.id),
                "name": fi.name,
                "base_price": str(fi.base_price),
                "is_available": fi.is_available,
            })

    today = today_college()
    inv_ids = [inv.id for inv, _ing, _sup in rows]
    batches_by_inv: dict[UUID, list[StockBatch]] = {}
    if inv_ids:
        for b in db.scalars(
            select(StockBatch)
            .where(StockBatch.inventory_item_id.in_(inv_ids), StockBatch.remaining_quantity > 0)
            .order_by(StockBatch.expiry_date.asc().nulls_last())
        ).all():
            batches_by_inv.setdefault(b.inventory_item_id, []).append(b)

    q_norm = (search or "").strip().lower()
    cat_norm = (category or "").strip().lower()
    result = []
    for inv, ing, sup_name in rows:
        if q_norm and not (
            q_norm in ing.name.lower()
            or q_norm in ing.sku.lower()
            or q_norm in (inv.category or "").lower()
            or q_norm in (inv.storage_location or "").lower()
        ):
            continue
        if cat_norm and cat_norm != "all" and (inv.category or "").lower() != cat_norm:
            continue
        status_val = (
            "out_of_stock"
            if inv.current_quantity <= Decimal("0.000")
            else ("low_stock" if inv.current_quantity <= inv.reorder_level else "in_stock")
        )
        if stock_status and stock_status != "all" and status_val != stock_status:
            continue

        batches = batches_by_inv.get(inv.id, [])
        stock_value = (inv.current_quantity * inv.unit_cost).quantize(Decimal("0.01"))
        result.append({
            "inventory_item_id": str(inv.id),
            "ingredient_id": str(ing.id),
            "name": ing.name,
            "sku": ing.sku,
            "category": inv.category,
            "description": inv.description,
            "image_url": inv.image_url,
            "unit": inv.unit,
            "current_quantity": str(inv.current_quantity),
            "reserved_quantity": str(inv.reserved_quantity),
            "reorder_level": str(inv.reorder_level),
            "unit_cost": str(inv.unit_cost),
            "stock_value": str(stock_value),
            "storage_location": inv.storage_location,
            "preferred_supplier_id": str(inv.preferred_supplier_id) if inv.preferred_supplier_id else None,
            "preferred_supplier_name": sup_name,
            "is_available": inv.is_available,
            "is_archived": inv.is_archived,
            "archived_at": inv.archived_at.isoformat() if inv.archived_at else None,
            "is_allergen": ing.is_allergen,
            "is_low_stock": inv.current_quantity <= inv.reorder_level,
            "stock_status": status_val,
            "updated_at": inv.updated_at.isoformat() if inv.updated_at else None,
            "linked_food_items": linked_dishes_map.get(ing.id, []),
            "batches": [
                {
                    "id": str(b.id),
                    "batch_number": b.batch_number,
                    "remaining_quantity": str(b.remaining_quantity),
                    "unit_cost": str(b.unit_cost),
                    "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                    "is_expired": bool(b.expiry_date and b.expiry_date < today),
                }
                for b in batches
            ],
        })
    return result


def get_recipe(db: Session, food_item_id: UUID) -> dict:
    food = db.get(FoodItem, food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    recipe = db.scalar(select(Recipe).where(Recipe.food_item_id == food_item_id))
    if not recipe:
        return {"food_item_id": str(food_item_id), "recipe_id": None, "yield_portions": 1, "ingredients": []}
    rows = db.execute(
        select(RecipeIngredient, Ingredient)
        .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
        .where(RecipeIngredient.recipe_id == recipe.id)
    ).all()
    return {
        "food_item_id": str(food_item_id),
        "recipe_id": str(recipe.id),
        "yield_portions": recipe.yield_portions,
        "ingredients": [
            {
                "ingredient_id": str(ri.ingredient_id),
                "ingredient_name": ing.name,
                "unit": ing.unit,
                "quantity_required": str(ri.quantity_required),
            }
            for ri, ing in rows
        ],
    }


def upsert_recipe(db: Session, food_item_id: UUID, yield_portions: int, ingredients: list[dict], actor_user_id: UUID) -> dict:
    food = db.get(FoodItem, food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    recipe = db.scalar(select(Recipe).where(Recipe.food_item_id == food_item_id))
    if not recipe:
        recipe = Recipe(food_item_id=food_item_id, yield_portions=yield_portions)
        db.add(recipe)
        db.flush()
    else:
        recipe.yield_portions = yield_portions
        recipe.is_verified = False
        recipe.verified_by_user_id = None
        recipe.verified_at = None
        for old in db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)).all():
            db.delete(old)
        db.flush()

    for row in ingredients:
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=row["ingredient_id"],
                quantity_required=Decimal(str(row["quantity_required"])),
            )
        )
    db.flush()
    blocked = refresh_food_item_ingredient_sufficiency(db, food.canteen_id)
    record_audit_log(db, action="recipe.updated", entity_type="food_item", entity_id=str(food_item_id), actor_user_id=actor_user_id)
    db.commit()
    return {"recipe_id": str(recipe.id), "food_item_id": str(food_item_id), "blocked_items": blocked}


VALID_PO_STATUSES = {
    "draft",
    "pending_approval",
    "approved",
    "ordered",
    "partially_received",
    "partial",
    "received",
    "cancelled",
}


def _serialize_purchase_order(
    db: Session,
    po: PurchaseOrder,
    *,
    supplier_map: Optional[dict[UUID, Supplier]] = None,
    items_by_po: Optional[dict[UUID, list[PurchaseOrderItem]]] = None,
    ing_map: Optional[dict[UUID, Ingredient]] = None,
    grn_count_map: Optional[dict[UUID, int]] = None,
    paid_sum_map: Optional[dict[UUID, Decimal]] = None,
) -> dict:
    sup = (supplier_map or {}).get(po.supplier_id) or db.get(Supplier, po.supplier_id)
    po_items = (
        items_by_po.get(po.id, [])
        if items_by_po is not None
        else list(db.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == po.id)).all())
    )
    if ing_map is None:
        ing_ids = {it.ingredient_id for it in po_items if it.ingredient_id}
        ing_map = (
            {i.id: i for i in db.scalars(select(Ingredient).where(Ingredient.id.in_(ing_ids))).all()}
            if ing_ids
            else {}
        )
    if grn_count_map is not None:
        grn_count = grn_count_map.get(po.id, 0)
    else:
        grn_count = db.scalar(select(func.count(GoodsReceipt.id)).where(GoodsReceipt.purchase_order_id == po.id)) or 0
    if paid_sum_map is not None:
        paid_sum = paid_sum_map.get(po.id, Decimal("0.00"))
    else:
        paid_sum = (
            db.scalar(
                select(func.coalesce(func.sum(VendorPayment.amount), 0)).where(
                    VendorPayment.purchase_order_id == po.id,
                    VendorPayment.status == "verified",
                )
            )
            or Decimal("0.00")
        )
    total_cost_dec = Decimal(str(po.total_cost or 0)).quantize(Decimal("0.01"))
    paid_dec = Decimal(str(paid_sum)).quantize(Decimal("0.01"))
    outstanding_dec = max(Decimal("0.00"), total_cost_dec - paid_dec).quantize(Decimal("0.01"))
    display_status = "partially_received" if po.status == "partial" else po.status
    return {
        "id": str(po.id),
        "po_number": po.po_number,
        "canteen_id": str(po.canteen_id),
        "supplier_id": str(po.supplier_id),
        "supplier_name": sup.name if sup else "Vendor",
        "status": po.status,
        "lifecycle_status": display_status,
        "subtotal_amount": str(Decimal(str(po.subtotal_amount or po.total_cost or 0)).quantize(Decimal("0.01"))),
        "tax_amount": str(Decimal(str(po.tax_amount or 0)).quantize(Decimal("0.01"))),
        "total_cost": str(total_cost_dec),
        "paid_amount": str(paid_dec),
        "outstanding_amount": str(outstanding_dec),
        "goods_receipts_count": int(grn_count),
        "ordered_by_user_id": str(po.ordered_by_user_id) if po.ordered_by_user_id else None,
        "approved_by_user_id": str(po.approved_by_user_id) if po.approved_by_user_id else None,
        "approved_at": po.approved_at.isoformat() if po.approved_at else None,
        "expected_delivery_date": po.expected_delivery_date.isoformat() if po.expected_delivery_date else None,
        "received_at": po.received_at.isoformat() if po.received_at else None,
        "notes": po.notes,
        "created_at": po.created_at.isoformat() if po.created_at else None,
        "items": [
            {
                "id": str(it.id),
                "ingredient_id": str(it.ingredient_id) if it.ingredient_id else None,
                "item_name": it.item_name or (ing_map.get(it.ingredient_id).name if it.ingredient_id and ing_map.get(it.ingredient_id) else "Supply Item"),
                "unit": it.unit or (ing_map.get(it.ingredient_id).unit if it.ingredient_id and ing_map.get(it.ingredient_id) else "units"),
                "quantity_ordered": str(it.quantity_ordered),
                "quantity_received": str(it.quantity_received),
                "quantity_damaged": str(it.quantity_damaged or Decimal("0.000")),
                "quantity_rejected": str(it.quantity_rejected or Decimal("0.000")),
                "quantity_missing": str(it.quantity_missing or Decimal("0.000")),
                "unit_cost": str(it.unit_cost),
                "tax_rate_percent": str(it.tax_rate_percent or Decimal("0.00")),
                "tax_amount": str(it.tax_amount or Decimal("0.00")),
                "line_total": str(
                    (
                        (Decimal(str(it.quantity_ordered)) * Decimal(str(it.unit_cost)))
                        + Decimal(str(it.tax_amount or 0))
                    ).quantize(Decimal("0.01"))
                ),
                "expiry_date": it.expiry_date.isoformat() if it.expiry_date else None,
            }
            for it in po_items
        ],
    }


def list_purchase_orders(
    db: Session,
    canteen_id: UUID,
    *,
    status_filter: Optional[str] = None,
    supplier_id: Optional[UUID] = None,
) -> list[dict]:
    stmt = select(PurchaseOrder).where(PurchaseOrder.canteen_id == canteen_id)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if status_filter and status_filter != "all":
        if status_filter in ("partial", "partially_received"):
            stmt = stmt.where(PurchaseOrder.status.in_(["partial", "partially_received"]))
        else:
            stmt = stmt.where(PurchaseOrder.status == status_filter)
    pos = list(db.scalars(stmt.order_by(PurchaseOrder.created_at.desc())).all())
    if not pos:
        return []
    sup_ids = {p.supplier_id for p in pos}
    sup_map = {s.id: s for s in db.scalars(select(Supplier).where(Supplier.id.in_(sup_ids))).all()}
    po_ids = [p.id for p in pos]
    all_items = db.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id.in_(po_ids))).all()
    items_by_po: dict[UUID, list[PurchaseOrderItem]] = {}
    ing_ids: set[UUID] = set()
    for it in all_items:
        items_by_po.setdefault(it.purchase_order_id, []).append(it)
        if it.ingredient_id:
            ing_ids.add(it.ingredient_id)
    ing_map = (
        {i.id: i for i in db.scalars(select(Ingredient).where(Ingredient.id.in_(ing_ids))).all()}
        if ing_ids
        else {}
    )
    grn_count_map = {
        pid: int(cnt or 0)
        for pid, cnt in db.execute(
            select(GoodsReceipt.purchase_order_id, func.count(GoodsReceipt.id))
            .where(GoodsReceipt.purchase_order_id.in_(po_ids))
            .group_by(GoodsReceipt.purchase_order_id)
        ).all()
    }
    paid_sum_map = {
        pid: Decimal(str(tot or 0))
        for pid, tot in db.execute(
            select(VendorPayment.purchase_order_id, func.coalesce(func.sum(VendorPayment.amount), 0))
            .where(VendorPayment.purchase_order_id.in_(po_ids), VendorPayment.status == "verified")
            .group_by(VendorPayment.purchase_order_id)
        ).all()
    }
    return [
        _serialize_purchase_order(
            db,
            p,
            supplier_map=sup_map,
            items_by_po=items_by_po,
            ing_map=ing_map,
            grn_count_map=grn_count_map,
            paid_sum_map=paid_sum_map,
        )
        for p in pos
    ]


def create_purchase_order(
    db: Session,
    data: dict,
    actor_user_id: UUID,
    *,
    can_approve: bool = False,
    commit: bool = True,
) -> dict:
    sup = db.get(Supplier, data["supplier_id"])
    if not sup:
        raise HTTPException(status_code=404, detail="Vendor / supplier not found")
    if not sup.is_active:
        raise HTTPException(status_code=400, detail="Cannot create purchase order for an inactive vendor")

    raw_init = data.get("initial_status") or data.get("status")
    init_status = (raw_init.strip().lower() if isinstance(raw_init, str) and raw_init.strip() else ("ordered" if can_approve else "pending_approval"))
    if init_status not in ("draft", "pending_approval", "approved", "ordered"):
        raise HTTPException(status_code=400, detail=f"Invalid initial purchase order status: {init_status}")
    if init_status in ("approved", "ordered") and not can_approve:
        raise HTTPException(
            status_code=403,
            detail="Only College Admin or Canteen Manager can create pre-approved or ordered purchase orders; submit as draft or pending_approval",
        )

    now = datetime.now(timezone.utc)
    po_number = f"PO-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6].upper()}"
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")
    prepared_lines: list[dict] = []

    for it in data["items"]:
        ing_id = it.get("ingredient_id")
        ing = db.get(Ingredient, ing_id) if ing_id else None
        item_name = (it.get("item_name") or (ing.name if ing else "")).strip()
        if not item_name:
            raise HTTPException(status_code=400, detail="Each purchase order item must specify an ingredient_id or item_name")
        unit = (it.get("unit") or (ing.unit if ing else "units")).strip()
        qty = Decimal(str(it["quantity_ordered"]))
        ucost = Decimal(str(it["unit_cost"])).quantize(Decimal("0.01"))
        tax_rate = Decimal(str(it.get("tax_rate_percent") or "0.00")).quantize(Decimal("0.01"))
        line_sub = (qty * ucost).quantize(Decimal("0.01"))
        line_tax = ((line_sub * tax_rate) / Decimal("100")).quantize(Decimal("0.01"))
        subtotal += line_sub
        tax_total += line_tax
        prepared_lines.append({
            "ingredient_id": ing.id if ing else None,
            "item_name": item_name,
            "unit": unit,
            "quantity_ordered": qty,
            "unit_cost": ucost,
            "tax_rate_percent": tax_rate,
            "tax_amount": line_tax,
            "expiry_date": it.get("expiry_date"),
        })

    total = (subtotal + tax_total).quantize(Decimal("0.01"))
    po = PurchaseOrder(
        po_number=po_number,
        canteen_id=data["canteen_id"],
        supplier_id=data["supplier_id"],
        status=init_status,
        subtotal_amount=subtotal,
        tax_amount=tax_total,
        total_cost=total,
        ordered_by_user_id=actor_user_id,
        approved_by_user_id=actor_user_id if init_status in ("approved", "ordered") else None,
        approved_at=now if init_status in ("approved", "ordered") else None,
        expected_delivery_date=data.get("expected_delivery_date"),
        notes=data.get("notes"),
    )
    db.add(po)
    db.flush()
    for line in prepared_lines:
        db.add(PurchaseOrderItem(purchase_order_id=po.id, **line))
    db.flush()
    record_audit_log(
        db,
        action="purchase_order.created",
        entity_type="purchase_order",
        entity_id=po_number,
        actor_user_id=actor_user_id,
        details={"status": init_status, "total_cost": str(total)},
    )
    try:
        from app.services.notification_service import notify_procurement_event

        notify_procurement_event(
            db,
            canteen_id=po.canteen_id,
            event_type="purchase_order_created",
            po_number=po_number,
            title=f"Purchase Order Created • {po_number}",
            message=f"PO {po_number} for {sup.name} ({init_status}, ₹{total}) has been created.",
            priority="high" if init_status == "pending_approval" else "normal",
        )
    except Exception:
        pass
    if commit:
        db.commit()
        db.refresh(po)
    else:
        db.flush()
    return _serialize_purchase_order(db, po)


def transition_purchase_order_status(
    db: Session,
    po_id: UUID,
    *,
    target_status: str,
    actor_user_id: UUID,
    can_approve: bool = False,
    notes: Optional[str] = None,
) -> dict:
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update())
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    target = target_status.strip().lower()
    if target not in ("pending_approval", "approved", "ordered", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Unsupported status transition target: {target}")
    if po.status == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled purchase order cannot transition")
    if po.status == "received":
        raise HTTPException(status_code=409, detail="Received purchase order cannot transition")

    if target == "approved" and not can_approve:
        raise HTTPException(status_code=403, detail="Only College Admin or Canteen Manager can approve purchase orders")
    if target == "ordered" and not po.approved_at and not can_approve:
        raise HTTPException(
            status_code=403,
            detail="Purchase order must be approved by College Admin or Canteen Manager before moving to ordered",
        )

    now = datetime.now(timezone.utc)
    if target == "approved":
        po.approved_by_user_id = actor_user_id
        po.approved_at = now
    elif target == "ordered" and not po.approved_at and can_approve:
        po.approved_by_user_id = actor_user_id
        po.approved_at = now

    po.status = target
    if notes:
        po.notes = f"{(po.notes or '').strip()} [{target.upper()}: {notes.strip()}]".strip()
    record_audit_log(
        db,
        action=f"purchase_order.{target}",
        entity_type="purchase_order",
        entity_id=po.po_number,
        actor_user_id=actor_user_id,
        details={"status": po.status, "notes": notes},
    )
    if target in ("pending_approval", "approved", "ordered", "cancelled"):
        try:
            from app.services.notification_service import notify_procurement_event

            notify_procurement_event(
                db,
                canteen_id=po.canteen_id,
                event_type=f"purchase_order_{target}",
                po_number=po.po_number,
                title=f"Purchase Order {target.replace('_', ' ').title()} • {po.po_number}",
                message=f"PO {po.po_number} moved to {target.upper()} status.",
                priority="high" if target in ("pending_approval", "cancelled") else "normal",
            )
        except Exception:
            pass
    db.commit()
    db.refresh(po)
    return _serialize_purchase_order(db, po)


def receive_purchase_order(
    db: Session,
    po_id: UUID,
    actor_user_id: UUID,
    received_items: Optional[list[dict]] = None,
    *,
    idempotency_key: Optional[str] = None,
    delivery_challan_ref: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    if idempotency_key:
        existing_grn = db.scalar(select(GoodsReceipt).where(GoodsReceipt.idempotency_key == idempotency_key))
        if existing_grn:
            po_existing = db.get(PurchaseOrder, existing_grn.purchase_order_id)
            return {
                "id": str(po_existing.id),
                "po_number": po_existing.po_number,
                "status": po_existing.status,
                "lifecycle_status": "partially_received" if po_existing.status == "partial" else po_existing.status,
                "grn_id": str(existing_grn.id),
                "grn_number": existing_grn.grn_number,
                "idempotent_replay": True,
            }

    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update())
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled purchase order cannot be received")
    if po.status in ("draft", "pending_approval"):
        raise HTTPException(
            status_code=400,
            detail=f"Purchase order in '{po.status}' status must be approved and ordered before receiving goods",
        )
    if po.status == "received":
        return {"id": str(po.id), "po_number": po.po_number, "status": "received", "lifecycle_status": "received"}

    po_items = db.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == po.id)).all()
    rec_by_ing = {str(r["ingredient_id"]): r for r in (received_items or []) if r.get("ingredient_id")}
    rec_by_poi = {str(r["po_item_id"]): r for r in (received_items or []) if r.get("po_item_id")}
    now = datetime.now(timezone.utc)

    grn = GoodsReceipt(
        grn_number=f"GRN-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:5].upper()}",
        purchase_order_id=po.id,
        canteen_id=po.canteen_id,
        supplier_id=po.supplier_id,
        idempotency_key=idempotency_key,
        delivery_challan_ref=delivery_challan_ref,
        received_by_user_id=actor_user_id,
        received_at=now,
        notes=notes,
    )
    db.add(grn)
    db.flush()

    any_item_processed = False
    for poi in po_items:
        outstanding = max(Decimal("0.000"), poi.quantity_ordered - poi.quantity_received)
        if outstanding <= Decimal("0.000"):
            continue
        if received_items is not None:
            entry = rec_by_poi.get(str(poi.id)) or (rec_by_ing.get(str(poi.ingredient_id)) if poi.ingredient_id else None)
            if not entry:
                continue
            raw_req_qty = Decimal(str(entry.get("quantity_received", "0")))
            if raw_req_qty > outstanding:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot receive {raw_req_qty} for item '{poi.item_name or poi.ingredient_id}': only {outstanding} remaining on PO",
                )
            receive_qty = max(Decimal("0.000"), raw_req_qty)
            damaged_qty = max(Decimal("0.000"), Decimal(str(entry.get("quantity_damaged") or "0")))
            rejected_qty = max(Decimal("0.000"), Decimal(str(entry.get("quantity_rejected") or "0")))
            missing_qty = max(Decimal("0.000"), Decimal(str(entry.get("quantity_missing") or "0")))
            delivered_qty = Decimal(str(entry.get("quantity_delivered") or (receive_qty + damaged_qty + rejected_qty)))
            expiry = entry.get("expiry_date") or poi.expiry_date
            item_notes = entry.get("notes")
        else:
            receive_qty = outstanding
            damaged_qty = Decimal("0.000")
            rejected_qty = Decimal("0.000")
            missing_qty = Decimal("0.000")
            delivered_qty = outstanding
            expiry = poi.expiry_date
            item_notes = None

        if receive_qty <= Decimal("0.000") and damaged_qty <= Decimal("0.000") and rejected_qty <= Decimal("0.000") and missing_qty <= Decimal("0.000"):
            continue

        any_item_processed = True
        poi.quantity_received += receive_qty
        poi.quantity_damaged = (poi.quantity_damaged or Decimal("0.000")) + damaged_qty
        poi.quantity_rejected = (poi.quantity_rejected or Decimal("0.000")) + rejected_qty
        poi.quantity_missing = (poi.quantity_missing or Decimal("0.000")) + missing_qty

        ing = db.get(Ingredient, poi.ingredient_id) if poi.ingredient_id else None
        eff_item_name = poi.item_name or (ing.name if ing else "Supply Item")
        db.add(
            GoodsReceiptItem(
                goods_receipt_id=grn.id,
                po_item_id=poi.id,
                ingredient_id=poi.ingredient_id,
                item_name=eff_item_name,
                quantity_delivered=delivered_qty,
                quantity_accepted=receive_qty,
                quantity_damaged=damaged_qty,
                quantity_rejected=rejected_qty,
                quantity_missing=missing_qty,
                unit_cost=poi.unit_cost,
                expiry_date=expiry,
                notes=item_notes,
            )
        )

        # CRITICAL: Update inventory stock ONLY for verified accepted quantities (receive_qty > 0)
        if receive_qty > Decimal("0.000") and poi.ingredient_id:
            inv = db.scalar(
                select(InventoryItem)
                .where(InventoryItem.canteen_id == po.canteen_id, InventoryItem.ingredient_id == poi.ingredient_id)
                .with_for_update()
            )
            if not inv:
                inv = InventoryItem(
                    canteen_id=po.canteen_id,
                    ingredient_id=poi.ingredient_id,
                    current_quantity=Decimal("0.000"),
                    unit=ing.unit if ing else (poi.unit or "grams"),
                    unit_cost=poi.unit_cost,
                )
                db.add(inv)
                db.flush()
            inv.current_quantity += receive_qty
            inv.unit_cost = poi.unit_cost
            mfg_date = entry.get("manufacturing_date") if received_items is not None and entry else None
            storage_loc = (entry.get("storage_location") if received_items is not None and entry else None) or "Main Store"
            batch = StockBatch(
                inventory_item_id=inv.id,
                supplier_id=po.supplier_id,
                purchase_order_id=po.id,
                goods_receipt_id=grn.id,
                batch_number=f"{po.po_number}-{str(poi.ingredient_id)[:4]}-{uuid4().hex[:3].upper()}",
                initial_quantity=receive_qty,
                remaining_quantity=receive_qty,
                unit_cost=poi.unit_cost,
                received_at=now,
                manufacturing_date=mfg_date,
                expiry_date=expiry,
                storage_location=storage_loc,
                quality_status="approved",
            )
            db.add(batch)
            db.flush()
            try:
                from app.models.enterprise import TraceabilityRecord

                db.add(
                    TraceabilityRecord(
                        canteen_id=po.canteen_id,
                        supplier_id=po.supplier_id,
                        purchase_order_id=po.id,
                        goods_receipt_id=grn.id,
                        stock_batch_id=batch.id,
                        trace_completeness="partial",
                        missing_links=["production_batch_id", "order_id"],
                        notes=f"GRN {grn.grn_number} received {receive_qty} {inv.unit} (batch {batch.batch_number}) from PO {po.po_number}",
                    )
                )
            except Exception:
                pass
            if expiry:
                today_val = today_college()
                if expiry <= today_val + timedelta(days=7):
                    try:
                        from app.services.notification_service import notify_inventory_expiry_alert

                        notify_inventory_expiry_alert(
                            db,
                            canteen_id=po.canteen_id,
                            batch_id=batch.id,
                            batch_number=batch.batch_number,
                            ingredient_name=eff_item_name,
                            expiry_date_str=expiry.isoformat(),
                            is_expired=(expiry < today_val),
                        )
                    except Exception:
                        pass
            db.add(
                StockMovement(
                    inventory_item_id=inv.id,
                    batch_id=batch.id,
                    movement_type="purchase",
                    quantity_delta=receive_qty,
                    balance_after=inv.current_quantity,
                    reference_type="purchase_order",
                    reference_id=str(po.id),
                    created_by_user_id=actor_user_id,
                    notes=f"GRN {grn.grn_number}: accepted {receive_qty} from {po.po_number}",
                )
            )

    if not any_item_processed:
        raise HTTPException(status_code=400, detail="No valid open purchase order items matched for goods receipt")

    all_done = all(p.quantity_received >= p.quantity_ordered for p in po_items)
    any_done = any(p.quantity_received > 0 for p in po_items)
    po.status = "received" if all_done else ("partial" if any_done else po.status)
    if all_done:
        po.received_at = now
        try:
            from app.models.enterprise import ReorderRecommendation

            for rec in db.scalars(
                select(ReorderRecommendation).where(
                    ReorderRecommendation.purchase_order_id == po.id,
                    ReorderRecommendation.status == "draft_po_created",
                )
            ).all():
                rec.status = "fulfilled"
        except Exception:
            pass
    refresh_food_item_ingredient_sufficiency(db, po.canteen_id)
    record_audit_log(
        db,
        action="purchase_order.received",
        entity_type="purchase_order",
        entity_id=po.po_number,
        actor_user_id=actor_user_id,
        details={"status": po.status, "grn_number": grn.grn_number},
    )
    try:
        from app.services.notification_service import notify_procurement_event

        notify_procurement_event(
            db,
            canteen_id=po.canteen_id,
            event_type="goods_received",
            po_number=f"{po.po_number}:{grn.grn_number}",
            title=f"Goods Received • {grn.grn_number}",
            message=f"Verified goods receipt {grn.grn_number} recorded against PO {po.po_number} (status: {po.status}).",
            priority="normal",
        )
    except Exception:
        pass
    db.commit()
    return {
        "id": str(po.id),
        "po_number": po.po_number,
        "status": po.status,
        "lifecycle_status": "partially_received" if po.status == "partial" else po.status,
        "grn_id": str(grn.id),
        "grn_number": grn.grn_number,
    }


def list_goods_receipts_for_po(db: Session, po_id: UUID) -> list[dict]:
    grns = list(
        db.scalars(
            select(GoodsReceipt)
            .where(GoodsReceipt.purchase_order_id == po_id)
            .order_by(GoodsReceipt.received_at.desc())
        ).all()
    )
    if not grns:
        return []
    grn_ids = [g.id for g in grns]
    g_items = db.scalars(select(GoodsReceiptItem).where(GoodsReceiptItem.goods_receipt_id.in_(grn_ids))).all()
    by_grn: dict[UUID, list[GoodsReceiptItem]] = {}
    for gi in g_items:
        by_grn.setdefault(gi.goods_receipt_id, []).append(gi)
    return [
        {
            "id": str(g.id),
            "grn_number": g.grn_number,
            "purchase_order_id": str(g.purchase_order_id),
            "canteen_id": str(g.canteen_id),
            "supplier_id": str(g.supplier_id),
            "idempotency_key": g.idempotency_key,
            "delivery_challan_ref": g.delivery_challan_ref,
            "received_at": g.received_at.isoformat() if g.received_at else None,
            "notes": g.notes,
            "items": [
                {
                    "id": str(it.id),
                    "po_item_id": str(it.po_item_id),
                    "ingredient_id": str(it.ingredient_id) if it.ingredient_id else None,
                    "item_name": it.item_name,
                    "quantity_delivered": str(it.quantity_delivered),
                    "quantity_accepted": str(it.quantity_accepted),
                    "quantity_damaged": str(it.quantity_damaged),
                    "quantity_rejected": str(it.quantity_rejected),
                    "quantity_missing": str(it.quantity_missing),
                    "unit_cost": str(it.unit_cost),
                    "expiry_date": it.expiry_date.isoformat() if it.expiry_date else None,
                    "notes": it.notes,
                }
                for it in by_grn.get(g.id, [])
            ],
        }
        for g in grns
    ]


def export_purchase_order_pdf(db: Session, po_id: UUID) -> bytes:
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    po_data = _serialize_purchase_order(db, po)
    canteen = db.get(Canteen, po.canteen_id)
    sup = db.get(Supplier, po.supplier_id)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _w, h = A4
    y = h - 40

    c.setFont("Helvetica-Bold", 15)
    c.drawString(40, y, f"CollegeBites Purchase Order — {po_data['po_number']}")
    y -= 18
    c.setFont("Helvetica", 9)
    c.drawString(40, y, f"Canteen: {canteen.name if canteen else ''} | Status: {po_data['lifecycle_status'].upper()} | Date: {(po_data['created_at'] or '')[:10]}")
    y -= 16
    if sup:
        c.drawString(40, y, f"Vendor: {sup.name} | Contact: {sup.contact_person or '-'} ({sup.phone or '-'}) | GST: {sup.gst_number or '-'}")
        y -= 20

    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Item")
    c.drawString(220, y, "Ordered")
    c.drawString(290, y, "Accepted")
    c.drawString(360, y, "Unit Cost")
    c.drawString(430, y, "Tax")
    c.drawString(495, y, "Line Total")
    y -= 14
    c.setFont("Helvetica", 9)
    for it in po_data["items"]:
        if y < 60:
            c.showPage()
            y = h - 40
            c.setFont("Helvetica", 9)
        c.drawString(40, y, f"{it['item_name']} ({it['unit']})"[:34])
        c.drawString(220, y, str(it["quantity_ordered"]))
        c.drawString(290, y, str(it["quantity_received"]))
        c.drawString(360, y, f"Rs.{it['unit_cost']}")
        c.drawString(430, y, f"Rs.{it['tax_amount']}")
        c.drawString(495, y, f"Rs.{it['line_total']}")
        y -= 14

    y -= 12
    c.setFont("Helvetica-Bold", 10)
    c.drawString(360, y, f"Subtotal: Rs.{po_data['subtotal_amount']}")
    y -= 14
    c.drawString(360, y, f"Tax: Rs.{po_data['tax_amount']}")
    y -= 14
    c.drawString(360, y, f"Total PO Value: Rs.{po_data['total_cost']}")
    y -= 14
    c.drawString(360, y, f"Paid / Outstanding: Rs.{po_data['paid_amount']} / Rs.{po_data['outstanding_amount']}")

    c.showPage()
    c.save()
    return buf.getvalue()


def create_vendor_payment(db: Session, data: dict, actor_user_id: UUID) -> dict:
    sup = db.get(Supplier, data["supplier_id"])
    if not sup:
        raise HTTPException(status_code=404, detail="Vendor not found")
    po = None
    if data.get("purchase_order_id"):
        po = db.get(PurchaseOrder, data["purchase_order_id"])
        if not po or po.supplier_id != sup.id:
            raise HTTPException(status_code=400, detail="Purchase order does not belong to the selected vendor")
        if po.status in ("cancelled", "draft"):
            raise HTTPException(status_code=400, detail=f"Cannot record payment against a {po.status} purchase order")

    amount = Decimal(str(data["amount"])).quantize(Decimal("0.01"))
    if amount <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")

    pay_ref = (data.get("payment_reference") or "").strip() or None
    req_status = (data.get("status") or ("verified" if pay_ref else "pending_verification")).strip().lower()
    if req_status == "verified" and not pay_ref:
        raise HTTPException(
            status_code=400,
            detail="Vendor payment cannot be marked as verified/completed without a payment reference",
        )
    if pay_ref:
        dup = db.scalar(
            select(VendorPayment).where(
                VendorPayment.supplier_id == sup.id,
                VendorPayment.payment_reference == pay_ref,
                VendorPayment.status != "cancelled",
            )
        )
        if dup:
            raise HTTPException(status_code=409, detail="Duplicate payment reference for this vendor")

    now = datetime.now(timezone.utc)
    vp = VendorPayment(
        payment_number=f"VPAY-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:5].upper()}",
        supplier_id=sup.id,
        canteen_id=data.get("canteen_id") or (po.canteen_id if po else None),
        purchase_order_id=po.id if po else None,
        amount=amount,
        payment_method=(data.get("payment_method") or "bank_transfer").strip(),
        payment_reference=pay_ref,
        document_url=(data.get("document_url") or "").strip() or None,
        status=req_status,
        payment_date=data.get("payment_date") or today_college(),
        verified_at=now if req_status == "verified" else None,
        recorded_by_user_id=actor_user_id,
        verified_by_user_id=actor_user_id if req_status == "verified" else None,
        notes=data.get("notes"),
    )
    db.add(vp)
    record_audit_log(
        db,
        action="vendor_payment.created",
        entity_type="vendor_payment",
        entity_id=vp.payment_number,
        actor_user_id=actor_user_id,
        details={"supplier_id": str(sup.id), "amount": str(amount), "status": vp.status},
    )
    db.commit()
    db.refresh(vp)
    return _serialize_vendor_payment(vp, sup_name=sup.name, po_number=po.po_number if po else None)


def verify_vendor_payment(
    db: Session,
    payment_id: UUID,
    *,
    payment_reference: str,
    document_url: Optional[str] = None,
    notes: Optional[str] = None,
    actor_user_id: UUID,
) -> dict:
    vp = db.scalar(select(VendorPayment).where(VendorPayment.id == payment_id).with_for_update())
    if not vp:
        raise HTTPException(status_code=404, detail="Vendor payment not found")
    ref = (payment_reference or "").strip()
    if not ref:
        raise HTTPException(
            status_code=400,
            detail="A valid payment reference is required to verify and complete a vendor payment",
        )
    dup = db.scalar(
        select(VendorPayment).where(
            VendorPayment.supplier_id == vp.supplier_id,
            VendorPayment.payment_reference == ref,
            VendorPayment.id != vp.id,
            VendorPayment.status != "cancelled",
        )
    )
    if dup:
        raise HTTPException(status_code=409, detail="Payment reference already used for another payment to this vendor")

    vp.payment_reference = ref
    if document_url is not None:
        vp.document_url = document_url.strip() or None
    if notes:
        vp.notes = notes
    vp.status = "verified"
    vp.verified_at = datetime.now(timezone.utc)
    vp.verified_by_user_id = actor_user_id
    record_audit_log(
        db,
        action="vendor_payment.verified",
        entity_type="vendor_payment",
        entity_id=vp.payment_number,
        actor_user_id=actor_user_id,
        details={"payment_reference": ref, "amount": str(vp.amount)},
    )
    db.commit()
    db.refresh(vp)
    sup = db.get(Supplier, vp.supplier_id)
    po = db.get(PurchaseOrder, vp.purchase_order_id) if vp.purchase_order_id else None
    return _serialize_vendor_payment(vp, sup_name=sup.name if sup else "Vendor", po_number=po.po_number if po else None)


def _serialize_vendor_payment(vp: VendorPayment, *, sup_name: Optional[str] = None, po_number: Optional[str] = None) -> dict:
    return {
        "id": str(vp.id),
        "payment_number": vp.payment_number,
        "supplier_id": str(vp.supplier_id),
        "supplier_name": sup_name,
        "canteen_id": str(vp.canteen_id) if vp.canteen_id else None,
        "purchase_order_id": str(vp.purchase_order_id) if vp.purchase_order_id else None,
        "po_number": po_number,
        "amount": str(Decimal(str(vp.amount)).quantize(Decimal("0.01"))),
        "payment_method": vp.payment_method,
        "payment_reference": vp.payment_reference,
        "document_url": vp.document_url,
        "status": vp.status,
        "payment_date": vp.payment_date.isoformat() if vp.payment_date else None,
        "verified_at": vp.verified_at.isoformat() if vp.verified_at else None,
        "notes": vp.notes,
        "created_at": vp.created_at.isoformat() if vp.created_at else None,
    }


def list_vendor_payments(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    supplier_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
) -> list[dict]:
    stmt = select(VendorPayment)
    if canteen_id:
        stmt = stmt.where((VendorPayment.canteen_id == canteen_id) | (VendorPayment.canteen_id.is_(None)))
    if supplier_id:
        stmt = stmt.where(VendorPayment.supplier_id == supplier_id)
    if status_filter and status_filter != "all":
        stmt = stmt.where(VendorPayment.status == status_filter)
    rows = list(db.scalars(stmt.order_by(VendorPayment.created_at.desc())).all())
    if not rows:
        return []
    sup_ids = {r.supplier_id for r in rows}
    po_ids = {r.purchase_order_id for r in rows if r.purchase_order_id}
    sup_map = {s.id: s.name for s in db.scalars(select(Supplier).where(Supplier.id.in_(sup_ids))).all()}
    po_map = (
        {p.id: p.po_number for p in db.scalars(select(PurchaseOrder).where(PurchaseOrder.id.in_(po_ids))).all()}
        if po_ids
        else {}
    )
    return [
        _serialize_vendor_payment(r, sup_name=sup_map.get(r.supplier_id), po_number=po_map.get(r.purchase_order_id))
        for r in rows
    ]


def get_supplier_statement(db: Session, supplier_id: UUID) -> dict:
    sup = db.get(Supplier, supplier_id)
    if not sup:
        raise HTTPException(status_code=404, detail="Vendor not found")
    perf_map = _compute_supplier_metrics_map(db, [sup.id])
    vendor_info = _serialize_supplier(sup, perf_map.get(sup.id))
    pos = list(
        db.scalars(
            select(PurchaseOrder)
            .where(PurchaseOrder.supplier_id == sup.id)
            .order_by(PurchaseOrder.created_at.asc())
        ).all()
    )
    payments = list(
        db.scalars(
            select(VendorPayment)
            .where(VendorPayment.supplier_id == sup.id)
            .order_by(VendorPayment.created_at.asc())
        ).all()
    )
    grns = list(
        db.scalars(
            select(GoodsReceipt)
            .where(GoodsReceipt.supplier_id == sup.id)
            .order_by(GoodsReceipt.received_at.desc())
        ).all()
    )

    events: list[dict] = []
    for p in pos:
        if p.status in ("cancelled", "draft"):
            continue
        events.append({
            "timestamp": p.created_at.isoformat() if p.created_at else "",
            "entry_type": "purchase_order",
            "reference": p.po_number,
            "status": p.status,
            "debit_billed": Decimal(str(p.total_cost or 0)).quantize(Decimal("0.01")),
            "credit_paid": Decimal("0.00"),
            "notes": p.notes,
        })
    for vp in payments:
        if vp.status != "verified":
            continue
        events.append({
            "timestamp": (vp.verified_at or vp.created_at).isoformat() if (vp.verified_at or vp.created_at) else "",
            "entry_type": "vendor_payment",
            "reference": vp.payment_reference or vp.payment_number,
            "status": vp.status,
            "debit_billed": Decimal("0.00"),
            "credit_paid": Decimal(str(vp.amount or 0)).quantize(Decimal("0.01")),
            "notes": vp.notes,
        })
    events.sort(key=lambda e: e["timestamp"])

    running = Decimal("0.00")
    ledger: list[dict] = []
    for e in events:
        running = (running + e["debit_billed"] - e["credit_paid"]).quantize(Decimal("0.01"))
        ledger.append({
            "timestamp": e["timestamp"],
            "entry_type": e["entry_type"],
            "reference": e["reference"],
            "status": e["status"],
            "debit_billed": str(e["debit_billed"]),
            "credit_paid": str(e["credit_paid"]),
            "running_balance": str(running),
            "notes": e["notes"],
        })

    po_map = {p.id: p.po_number for p in pos}
    return {
        "vendor": vendor_info,
        "purchase_orders": [_serialize_purchase_order(db, p) for p in reversed(pos)],
        "vendor_payments": [
            _serialize_vendor_payment(vp, sup_name=sup.name, po_number=po_map.get(vp.purchase_order_id))
            for vp in reversed(payments)
        ],
        "goods_receipts_count": len(grns),
        "ledger": ledger,
    }


def adjust_or_waste_stock(
    db: Session,
    *,
    inventory_item_id: UUID,
    quantity_delta: Decimal,
    reason: str,
    is_wastage: bool,
    actor_user_id: UUID,
    batch_id: Optional[UUID] = None,
    operation_type: Optional[str] = None,
    expiry_date: Optional[date] = None,
    waste_date: Optional[date] = None,
    responsible_staff_id: Optional[UUID] = None,
) -> dict:
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    if inv.is_archived:
        raise HTTPException(status_code=400, detail="Restore archived item before modifying stock")

    prev_qty = inv.current_quantity
    op = operation_type or ("wastage" if is_wastage else "adjustment")
    if op == "add_stock" and quantity_delta <= Decimal("0.000"):
        raise HTTPException(status_code=400, detail="Stock addition quantity must be greater than zero")

    is_loss_op = is_wastage or op in ("damaged", "expired", "wastage")
    is_reduction = is_loss_op or op == "reduce_stock" or quantity_delta < Decimal("0.000")

    if is_loss_op:
        qty = abs(quantity_delta)
        if qty <= Decimal("0.000"):
            raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
        if inv.current_quantity < qty:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot record {qty} {inv.unit} reduction: current stock is {inv.current_quantity} {inv.unit} (negative stock prohibited)",
            )
        if batch_id:
            target_batch = db.scalar(
                select(StockBatch)
                .where(StockBatch.id == batch_id, StockBatch.inventory_item_id == inv.id)
                .with_for_update()
            )
            if not target_batch:
                raise HTTPException(status_code=404, detail="Stock batch not found")
            if target_batch.remaining_quantity < qty:
                raise HTTPException(
                    status_code=400,
                    detail=f"Selected batch only has {target_batch.remaining_quantity} {inv.unit} remaining",
                )
        consumed = _consume_batches(db, inv.id, qty, exclude_expired=False, batch_id=batch_id)
        used_batch_id = consumed[0][0] if consumed else batch_id
        inv.current_quantity -= qty
        loss_type = _classify_loss_type(op, reason)
        consumed_qty = sum((t[1] for t in consumed), Decimal("0.000"))
        batch_loss = sum((t[1] * t[3] for t in consumed), Decimal("0.00"))
        uncovered_qty = max(Decimal("0.000"), qty - consumed_qty)
        loss = (batch_loss + (uncovered_qty * inv.unit_cost)).quantize(Decimal("0.01"))
        db.add(
            WastageRecord(
                canteen_id=inv.canteen_id,
                inventory_item_id=inv.id,
                batch_id=used_batch_id,
                source_type="ingredient",
                quantity=qty,
                loss_type=loss_type,
                reason=reason,
                waste_date=waste_date or today_college(),
                estimated_loss=loss,
                responsible_staff_id=responsible_staff_id,
                recorded_by_user_id=actor_user_id,
            )
        )
        db.add(
            StockMovement(
                inventory_item_id=inv.id,
                batch_id=used_batch_id,
                movement_type=loss_type,
                quantity_delta=-qty,
                balance_after=inv.current_quantity,
                reference_type=loss_type,
                reference_id=str(inv.id),
                created_by_user_id=actor_user_id,
                notes=reason,
            )
        )
    elif is_reduction:
        qty = abs(quantity_delta)
        if qty <= Decimal("0.000"):
            raise HTTPException(status_code=400, detail="Reduction quantity must be greater than zero")
        if inv.current_quantity < qty:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot reduce stock below 0 (available: {inv.current_quantity} {inv.unit}, requested reduction: {qty} {inv.unit})",
            )
        if batch_id:
            target_batch = db.scalar(
                select(StockBatch)
                .where(StockBatch.id == batch_id, StockBatch.inventory_item_id == inv.id)
                .with_for_update()
            )
            if not target_batch or target_batch.remaining_quantity < qty:
                raise HTTPException(status_code=400, detail="Selected batch has insufficient remaining quantity")
        consumed = _consume_batches(db, inv.id, qty, exclude_expired=False, batch_id=batch_id)
        used_batch_id = consumed[0][0] if consumed else batch_id
        inv.current_quantity -= qty
        db.add(
            StockAdjustment(
                inventory_item_id=inv.id,
                quantity_delta=-qty,
                reason=reason,
                adjusted_by_user_id=actor_user_id,
            )
        )
        db.add(
            StockMovement(
                inventory_item_id=inv.id,
                batch_id=used_batch_id,
                movement_type="adjustment",
                quantity_delta=-qty,
                balance_after=inv.current_quantity,
                reference_type="adjustment",
                reference_id=str(inv.id),
                created_by_user_id=actor_user_id,
                notes=reason,
            )
        )
    else:
        qty = abs(quantity_delta)
        if qty <= Decimal("0.000"):
            raise HTTPException(status_code=400, detail="Adjustment quantity cannot be zero")
        adj_batch = StockBatch(
            inventory_item_id=inv.id,
            batch_number=f"ADD-{uuid4().hex[:6].upper()}",
            initial_quantity=qty,
            remaining_quantity=qty,
            unit_cost=inv.unit_cost,
            received_at=datetime.now(timezone.utc),
            expiry_date=expiry_date,
        )
        db.add(adj_batch)
        db.flush()
        inv.current_quantity += qty
        db.add(
            StockAdjustment(
                inventory_item_id=inv.id,
                quantity_delta=qty,
                reason=reason,
                adjusted_by_user_id=actor_user_id,
            )
        )
        db.add(
            StockMovement(
                inventory_item_id=inv.id,
                batch_id=adj_batch.id,
                movement_type="adjustment",
                quantity_delta=qty,
                balance_after=inv.current_quantity,
                reference_type="adjustment",
                reference_id=str(inv.id),
                created_by_user_id=actor_user_id,
                notes=reason,
            )
        )

    _log_inv_audit(
        db,
        canteen_id=inv.canteen_id,
        inventory_item_id=inv.id,
        action="stock_changed",
        field_name="current_quantity",
        old_value=str(prev_qty),
        new_value=str(inv.current_quantity),
        actor_user_id=actor_user_id,
        reason=f"[{op}] {reason}",
    )
    blocked = refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    ing_obj = db.get(Ingredient, inv.ingredient_id)
    _trigger_low_stock_alert_if_needed(db, inv, ing_obj.name if ing_obj else "Ingredient", canteen_id=inv.canteen_id)
    db.commit()
    return {
        "inventory_item_id": str(inv.id),
        "current_quantity": str(inv.current_quantity),
        "operation_type": op,
        "blocked_items": blocked,
    }


def transfer_stock(
    db: Session,
    *,
    from_canteen_id: UUID,
    to_canteen_id: UUID,
    ingredient_id: UUID,
    quantity: Decimal,
    notes: Optional[str],
    actor_user_id: UUID,
) -> dict:
    if from_canteen_id == to_canteen_id:
        raise HTTPException(status_code=400, detail="Source and destination canteens must be different")
    src_ing = db.get(Ingredient, ingredient_id)
    if not src_ing:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    dst_ing = db.scalar(
        select(Ingredient).where(Ingredient.canteen_id == to_canteen_id, Ingredient.sku == src_ing.sku)
    )
    if not dst_ing:
        dst_ing = Ingredient(
            canteen_id=to_canteen_id,
            name=src_ing.name,
            sku=src_ing.sku,
            unit=src_ing.unit,
            is_allergen=src_ing.is_allergen,
        )
        db.add(dst_ing)
        db.flush()

    # Lock inventory rows in canonical sorted order by (canteen_id, ingredient_id) to prevent deadlocks
    lock_pairs = sorted([(from_canteen_id, ingredient_id), (to_canteen_id, dst_ing.id)], key=lambda x: str(x[0]))
    locked_by_canteen: dict[UUID, Optional[InventoryItem]] = {}
    for cid_lock, ing_lock in lock_pairs:
        locked_by_canteen[cid_lock] = db.scalar(
            select(InventoryItem)
            .where(InventoryItem.canteen_id == cid_lock, InventoryItem.ingredient_id == ing_lock)
            .with_for_update()
        )

    src = locked_by_canteen.get(from_canteen_id)
    if not src or src.current_quantity < quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock in source canteen")
    has_batches = db.scalar(select(StockBatch.id).where(StockBatch.inventory_item_id == src.id).limit(1))
    if has_batches:
        usable_non_expired = get_unexpired_stock_quantity(db, src, exclude_reserved=True)
        if usable_non_expired < quantity:
            raise HTTPException(status_code=400, detail="Insufficient non-expired batch stock in source canteen")
    consumed_slices = _consume_batches(db, src.id, quantity, exclude_expired=True)
    src_prev = src.current_quantity
    src.current_quantity -= quantity

    dst = locked_by_canteen.get(to_canteen_id)
    if not dst:
        dst = InventoryItem(
            canteen_id=to_canteen_id,
            ingredient_id=dst_ing.id,
            current_quantity=Decimal("0.000"),
            reorder_level=src.reorder_level,
            unit=src.unit,
            unit_cost=src.unit_cost,
        )
        db.add(dst)
        db.flush()
    dst_prev = dst.current_quantity
    dst.current_quantity += quantity

    now = datetime.now(timezone.utc)
    dst_batch_id: Optional[UUID] = None
    if consumed_slices:
        for _bid, taken, exp, ucost in consumed_slices:
            b_new = StockBatch(
                inventory_item_id=dst.id,
                batch_number=f"TRF-{uuid4().hex[:6].upper()}",
                initial_quantity=taken,
                remaining_quantity=taken,
                unit_cost=ucost,
                received_at=now,
                expiry_date=exp,
            )
            db.add(b_new)
            db.flush()
            if dst_batch_id is None:
                dst_batch_id = b_new.id
    else:
        b_new = StockBatch(
            inventory_item_id=dst.id,
            batch_number=f"TRF-{uuid4().hex[:6].upper()}",
            initial_quantity=quantity,
            remaining_quantity=quantity,
            unit_cost=src.unit_cost,
            received_at=now,
        )
        db.add(b_new)
        db.flush()
        dst_batch_id = b_new.id

    tr = StockTransfer(
        from_canteen_id=from_canteen_id,
        to_canteen_id=to_canteen_id,
        ingredient_id=ingredient_id,
        quantity=quantity,
        transferred_by_user_id=actor_user_id,
        notes=notes,
    )
    db.add(tr)
    db.flush()
    db.add(
        StockMovement(
            inventory_item_id=src.id,
            batch_id=consumed_slices[0][0] if consumed_slices else None,
            movement_type="transfer_out",
            quantity_delta=-quantity,
            balance_after=src.current_quantity,
            reference_type="transfer",
            reference_id=str(to_canteen_id),
            created_by_user_id=actor_user_id,
            notes=notes,
        )
    )
    db.add(
        StockMovement(
            inventory_item_id=dst.id,
            batch_id=dst_batch_id,
            movement_type="transfer_in",
            quantity_delta=quantity,
            balance_after=dst.current_quantity,
            reference_type="transfer",
            reference_id=str(from_canteen_id),
            created_by_user_id=actor_user_id,
            notes=notes,
        )
    )
    _log_inv_audit(
        db,
        canteen_id=from_canteen_id,
        inventory_item_id=src.id,
        action="stock_transferred_out",
        field_name="current_quantity",
        old_value=str(src_prev),
        new_value=str(src.current_quantity),
        actor_user_id=actor_user_id,
        reason=notes,
    )
    _log_inv_audit(
        db,
        canteen_id=to_canteen_id,
        inventory_item_id=dst.id,
        action="stock_transferred_in",
        field_name="current_quantity",
        old_value=str(dst_prev),
        new_value=str(dst.current_quantity),
        actor_user_id=actor_user_id,
        reason=notes,
    )
    refresh_food_item_ingredient_sufficiency(db, from_canteen_id)
    refresh_food_item_ingredient_sufficiency(db, to_canteen_id)
    _trigger_low_stock_alert_if_needed(db, src, src_ing.name, canteen_id=from_canteen_id)
    record_audit_log(
        db,
        action="inventory.stock_transferred",
        entity_type="stock_transfer",
        entity_id=str(tr.id),
        actor_user_id=actor_user_id,
        details={"from": str(from_canteen_id), "to": str(to_canteen_id), "quantity": str(quantity)},
    )
    db.commit()
    return {"id": str(tr.id), "status": "transferred", "quantity": str(quantity)}


def get_inventory_alerts(db: Session, canteen_id: UUID, expiring_within_days: int = 7) -> dict:
    low_stock = []
    rows = db.execute(
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(
            InventoryItem.canteen_id == canteen_id,
            InventoryItem.is_archived.is_(False),
            InventoryItem.current_quantity <= InventoryItem.reorder_level,
        )
    ).all()
    for inv, ing in rows:
        low_stock.append({
            "inventory_item_id": str(inv.id),
            "ingredient_name": ing.name,
            "current_quantity": str(inv.current_quantity),
            "reorder_level": str(inv.reorder_level),
            "unit": inv.unit,
        })

    cutoff = today_college() + timedelta(days=expiring_within_days)
    expiring_batches = db.execute(
        select(StockBatch, Ingredient.name)
        .join(InventoryItem, InventoryItem.id == StockBatch.inventory_item_id)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(
            InventoryItem.canteen_id == canteen_id,
            InventoryItem.is_archived.is_(False),
            StockBatch.remaining_quantity > 0,
            StockBatch.expiry_date.is_not(None),
            StockBatch.expiry_date <= cutoff,
        )
    ).all()
    expiring = [
        {
            "batch_number": b.batch_number,
            "ingredient_name": ing_name,
            "remaining_quantity": str(b.remaining_quantity),
            "expiry_date": b.expiry_date.isoformat(),
        }
        for b, ing_name in expiring_batches
    ]
    blocked_items = [
        {"id": str(fi.id), "name": fi.name}
        for fi in db.scalars(
            select(FoodItem).where(FoodItem.canteen_id == canteen_id, FoodItem.insufficient_ingredients.is_(True))
        ).all()
    ]
    return {"low_stock": low_stock, "expiring_soon": expiring, "blocked_food_items": blocked_items}


def get_inventory_dashboard(db: Session, canteen_id: UUID) -> dict:
    all_rows = db.execute(
        select(InventoryItem, Ingredient, Supplier.name)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .outerjoin(Supplier, Supplier.id == InventoryItem.preferred_supplier_id)
        .where(InventoryItem.canteen_id == canteen_id)
        .order_by(Ingredient.name)
    ).all()

    active_rows = [(inv, ing, sup) for inv, ing, sup in all_rows if not inv.is_archived]
    archived_count = sum(1 for inv, _, _ in all_rows if inv.is_archived)
    available_count = sum(1 for inv, _, _ in active_rows if inv.is_available and inv.current_quantity > Decimal("0.000"))
    out_of_stock_count = sum(1 for inv, _, _ in active_rows if inv.current_quantity <= Decimal("0.000"))
    low_stock_rows = [
        (inv, ing, sup)
        for inv, ing, sup in active_rows
        if inv.current_quantity <= inv.reorder_level
    ]
    total_valuation = sum(
        (max(Decimal("0.000"), inv.current_quantity) * inv.unit_cost for inv, _, _ in active_rows),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))

    today = today_college()
    soon_cutoff = today + timedelta(days=7)
    expiring_soon_count = db.scalar(
        select(func.count(StockBatch.id))
        .join(InventoryItem, InventoryItem.id == StockBatch.inventory_item_id)
        .where(
            InventoryItem.canteen_id == canteen_id,
            InventoryItem.is_archived.is_(False),
            StockBatch.remaining_quantity > 0,
            StockBatch.expiry_date.is_not(None),
            StockBatch.expiry_date >= today,
            StockBatch.expiry_date <= soon_cutoff,
        )
    ) or 0
    expired_batches_count = db.scalar(
        select(func.count(StockBatch.id))
        .join(InventoryItem, InventoryItem.id == StockBatch.inventory_item_id)
        .where(
            InventoryItem.canteen_id == canteen_id,
            InventoryItem.is_archived.is_(False),
            StockBatch.remaining_quantity > 0,
            StockBatch.expiry_date.is_not(None),
            StockBatch.expiry_date < today,
        )
    ) or 0

    wastage_rows = db.scalars(
        select(WastageRecord)
        .outerjoin(InventoryItem, InventoryItem.id == WastageRecord.inventory_item_id)
        .where(or_(WastageRecord.canteen_id == canteen_id, InventoryItem.canteen_id == canteen_id))
    ).all()
    loss_breakdown: dict[str, dict[str, Decimal]] = {
        "damaged": {"qty": Decimal("0.000"), "loss": Decimal("0.00")},
        "expired": {"qty": Decimal("0.000"), "loss": Decimal("0.00")},
        "wastage": {"qty": Decimal("0.000"), "loss": Decimal("0.00")},
        "unsold": {"qty": Decimal("0.000"), "loss": Decimal("0.00")},
    }
    for wr in wastage_rows:
        lt = wr.loss_type if wr.loss_type in loss_breakdown else _classify_loss_type(None, wr.reason)
        loss_breakdown[lt]["qty"] += wr.quantity
        loss_breakdown[lt]["loss"] += wr.estimated_loss

    total_loss_amt = sum((v["loss"] for v in loss_breakdown.values()), Decimal("0.00")).quantize(Decimal("0.01"))
    pending_price_requests_count = db.scalar(
        select(func.count(PriceChangeRequest.id)).where(
            PriceChangeRequest.canteen_id == canteen_id,
            PriceChangeRequest.status == "pending_approval",
        )
    ) or 0

    low_stock_items = [
        {
            "inventory_item_id": str(inv.id),
            "ingredient_id": str(ing.id),
            "name": ing.name,
            "sku": ing.sku,
            "category": inv.category,
            "unit": inv.unit,
            "current_quantity": str(inv.current_quantity),
            "reorder_level": str(inv.reorder_level),
            "unit_cost": str(inv.unit_cost),
            "preferred_supplier_id": str(inv.preferred_supplier_id) if inv.preferred_supplier_id else None,
            "preferred_supplier_name": sup,
            "suggested_restock_qty": str(max(Decimal("1.000"), (inv.reorder_level * Decimal("2")) - inv.current_quantity)),
        }
        for inv, ing, sup in low_stock_rows
    ]

    return {
        "canteen_id": str(canteen_id),
        "total_inventory_items": len(active_rows),
        "archived_items": archived_count,
        "available_items": available_count,
        "out_of_stock_items": out_of_stock_count,
        "low_stock_alerts_count": len(low_stock_rows),
        "expiring_soon_count": int(expiring_soon_count),
        "expired_batches_count": int(expired_batches_count),
        "total_stock_valuation": f"{total_valuation:.2f}",
        "pending_price_requests_count": int(pending_price_requests_count),
        "loss_breakdown": {
            k: {"quantity": f"{v['qty']:.3f}", "loss_amount": f"{v['loss']:.2f}"}
            for k, v in loss_breakdown.items()
        },
        "total_loss_amount": f"{total_loss_amt:.2f}",
        "low_stock_items": low_stock_items,
        "recent_stock_movements": list_inventory_movements(db, canteen_id, limit=15, offset=0),
    }


def archive_inventory_item(
    db: Session, inventory_item_id: UUID, *, reason: Optional[str], actor_user_id: UUID
) -> dict:
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    if inv.is_archived:
        return {"inventory_item_id": str(inv.id), "is_archived": True}

    # Block archiving if ingredient is used in a recipe for an active order
    affected_food_ids = db.scalars(
        select(FoodItem.id)
        .join(Recipe, Recipe.food_item_id == FoodItem.id)
        .join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id)
        .where(FoodItem.canteen_id == inv.canteen_id, RecipeIngredient.ingredient_id == inv.ingredient_id)
    ).all()
    if affected_food_ids:
        active_order_match = db.scalar(
            select(Order.order_number)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(
                Order.canteen_id == inv.canteen_id,
                Order.status.in_(ACTIVE_ORDER_STATUSES),
                OrderItem.food_item_id.in_(affected_food_ids),
            )
            .limit(1)
        )
        if active_order_match:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot archive item because it is referenced by active order {active_order_match}",
            )

    inv.is_archived = True
    inv.is_available = False
    inv.archived_at = datetime.now(timezone.utc)
    inv.archived_by_user_id = actor_user_id
    _log_inv_audit(
        db,
        canteen_id=inv.canteen_id,
        inventory_item_id=inv.id,
        action="archived",
        field_name="is_archived",
        old_value="False",
        new_value="True",
        actor_user_id=actor_user_id,
        reason=reason,
    )
    blocked = refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    ing_obj = db.get(Ingredient, inv.ingredient_id)
    _trigger_low_stock_alert_if_needed(db, inv, ing_obj.name if ing_obj else "Ingredient", canteen_id=inv.canteen_id)
    db.commit()
    return {"inventory_item_id": str(inv.id), "is_archived": True, "blocked_items": blocked}


def restore_inventory_item(db: Session, inventory_item_id: UUID, *, actor_user_id: UUID) -> dict:
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    inv.is_archived = False
    inv.is_available = True
    inv.archived_at = None
    inv.archived_by_user_id = None
    _log_inv_audit(
        db,
        canteen_id=inv.canteen_id,
        inventory_item_id=inv.id,
        action="restored",
        field_name="is_archived",
        old_value="True",
        new_value="False",
        actor_user_id=actor_user_id,
    )
    blocked = refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    ing_obj = db.get(Ingredient, inv.ingredient_id)
    _trigger_low_stock_alert_if_needed(db, inv, ing_obj.name if ing_obj else "Ingredient", canteen_id=inv.canteen_id)
    db.commit()
    return {"inventory_item_id": str(inv.id), "is_archived": False, "blocked_items": blocked}


def restock_inventory_item(
    db: Session,
    inventory_item_id: UUID,
    *,
    quantity: Decimal,
    unit_cost: Optional[Decimal],
    supplier_id: Optional[UUID],
    expiry_date: Optional[date],
    notes: Optional[str],
    actor_user_id: UUID,
) -> dict:
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    if inv.is_archived:
        raise HTTPException(status_code=400, detail="Restore archived item before restocking")

    eff_supplier_id = supplier_id or inv.preferred_supplier_id
    if eff_supplier_id and not db.get(Supplier, eff_supplier_id):
        raise HTTPException(status_code=404, detail="Supplier not found")

    prev_qty = inv.current_quantity
    eff_cost = unit_cost.quantize(Decimal("0.01")) if unit_cost is not None else inv.unit_cost
    now = datetime.now(timezone.utc)

    po_number = None
    if eff_supplier_id:
        po = PurchaseOrder(
            po_number=f"RST-{now.strftime('%Y%m%d')}-{uuid4().hex[:5].upper()}",
            canteen_id=inv.canteen_id,
            supplier_id=eff_supplier_id,
            status="received",
            total_cost=(quantity * eff_cost).quantize(Decimal("0.01")),
            ordered_by_user_id=actor_user_id,
            received_at=now,
            notes=notes or "1-click low-stock restock",
        )
        db.add(po)
        db.flush()
        db.add(
            PurchaseOrderItem(
                purchase_order_id=po.id,
                ingredient_id=inv.ingredient_id,
                quantity_ordered=quantity,
                quantity_received=quantity,
                unit_cost=eff_cost,
                expiry_date=expiry_date,
            )
        )
        po_number = po.po_number

    if unit_cost is not None and eff_cost != inv.unit_cost:
        db.add(
            PriceChangeRequest(
                canteen_id=inv.canteen_id,
                inventory_item_id=inv.id,
                price_kind="purchase_cost",
                old_price=inv.unit_cost,
                new_price=eff_cost,
                reason=notes or "Restock cost update",
                status="applied",
                requested_by_user_id=actor_user_id,
                reviewed_by_user_id=actor_user_id,
                reviewed_at=now,
            )
        )
        inv.unit_cost = eff_cost

    inv.current_quantity += quantity
    inv.is_available = True
    batch = StockBatch(
        inventory_item_id=inv.id,
        supplier_id=eff_supplier_id,
        batch_number=f"RST-{uuid4().hex[:6].upper()}",
        initial_quantity=quantity,
        remaining_quantity=quantity,
        unit_cost=eff_cost,
        received_at=now,
        expiry_date=expiry_date,
    )
    db.add(batch)
    db.flush()
    db.add(
        StockMovement(
            inventory_item_id=inv.id,
            batch_id=batch.id,
            movement_type="purchase",
            quantity_delta=quantity,
            balance_after=inv.current_quantity,
            reference_type="restock",
            reference_id=po_number or str(inv.id),
            created_by_user_id=actor_user_id,
            notes=notes or f"Quick restock (+{quantity} {inv.unit})",
        )
    )
    _log_inv_audit(
        db,
        canteen_id=inv.canteen_id,
        inventory_item_id=inv.id,
        action="stock_changed",
        field_name="current_quantity",
        old_value=str(prev_qty),
        new_value=str(inv.current_quantity),
        actor_user_id=actor_user_id,
        reason=notes or "Quick restock",
    )
    blocked = refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    ing_obj = db.get(Ingredient, inv.ingredient_id)
    _trigger_low_stock_alert_if_needed(db, inv, ing_obj.name if ing_obj else "Ingredient", canteen_id=inv.canteen_id)
    db.commit()
    return {
        "inventory_item_id": str(inv.id),
        "current_quantity": str(inv.current_quantity),
        "po_number": po_number,
        "is_low_stock": inv.current_quantity <= inv.reorder_level,
        "blocked_items": blocked,
    }


def update_purchase_price(
    db: Session,
    inventory_item_id: UUID,
    *,
    new_purchase_price: Decimal,
    reason: str,
    actor_user_id: UUID,
) -> dict:
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    new_val = new_purchase_price.quantize(Decimal("0.01"))
    old_val = inv.unit_cost
    now = datetime.now(timezone.utc)
    inv.unit_cost = new_val
    req = PriceChangeRequest(
        canteen_id=inv.canteen_id,
        inventory_item_id=inv.id,
        price_kind="purchase_cost",
        old_price=old_val,
        new_price=new_val,
        reason=reason.strip(),
        status="applied",
        requested_by_user_id=actor_user_id,
        reviewed_by_user_id=actor_user_id,
        reviewed_at=now,
    )
    db.add(req)
    _log_inv_audit(
        db,
        canteen_id=inv.canteen_id,
        inventory_item_id=inv.id,
        action="purchase_price_updated",
        field_name="purchase_price",
        old_value=str(old_val),
        new_value=str(new_val),
        actor_user_id=actor_user_id,
        reason=reason,
    )
    db.commit()
    db.refresh(req)
    return {
        "id": str(req.id),
        "price_kind": req.price_kind,
        "old_price": str(req.old_price),
        "new_price": str(req.new_price),
        "status": req.status,
    }


def request_selling_price_change(
    db: Session,
    *,
    canteen_id: UUID,
    food_item_id: UUID,
    new_price: Decimal,
    reason: str,
    inventory_item_id: Optional[UUID],
    actor_user_id: UUID,
) -> dict:
    food = db.get(FoodItem, food_item_id)
    if not food or food.canteen_id != canteen_id:
        raise HTTPException(status_code=404, detail="Menu item not found in selected canteen")
    new_val = new_price.quantize(Decimal("0.01"))
    if new_val <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Selling price must be positive")
    if new_val == food.base_price:
        raise HTTPException(status_code=400, detail="New selling price matches current price")

    req = PriceChangeRequest(
        canteen_id=canteen_id,
        inventory_item_id=inventory_item_id,
        food_item_id=food.id,
        price_kind="selling_price",
        old_price=food.base_price,
        new_price=new_val,
        reason=reason.strip(),
        status="pending_approval",
        requested_by_user_id=actor_user_id,
    )
    db.add(req)
    _log_inv_audit(
        db,
        canteen_id=canteen_id,
        inventory_item_id=inventory_item_id,
        action="selling_price_requested",
        field_name=f"selling_price:{food.name}",
        old_value=str(food.base_price),
        new_value=str(new_val),
        actor_user_id=actor_user_id,
        reason=reason,
    )
    record_audit_log(
        db,
        action="inventory.selling_price_requested",
        entity_type="food_item",
        entity_id=str(food.id),
        actor_user_id=actor_user_id,
        details={"old_price": str(food.base_price), "new_price": str(new_val), "reason": reason},
    )
    db.commit()
    db.refresh(req)
    return {
        "id": str(req.id),
        "food_item_id": str(food.id),
        "food_item_name": food.name,
        "old_price": str(req.old_price),
        "new_price": str(req.new_price),
        "status": req.status,
    }


def review_selling_price_change(
    db: Session,
    request_id: UUID,
    *,
    decision: str,
    review_notes: Optional[str],
    actor_user_id: UUID,
) -> dict:
    req = db.scalar(select(PriceChangeRequest).where(PriceChangeRequest.id == request_id).with_for_update())
    if not req:
        raise HTTPException(status_code=404, detail="Price change request not found")
    if req.price_kind != "selling_price":
        raise HTTPException(status_code=400, detail="Only selling price requests require manager review")
    if req.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Request is already {req.status}")

    now = datetime.now(timezone.utc)
    req.reviewed_by_user_id = actor_user_id
    req.review_notes = (review_notes or "").strip() or None
    req.reviewed_at = now

    food = db.scalar(select(FoodItem).where(FoodItem.id == req.food_item_id).with_for_update()) if req.food_item_id else None
    if decision == "approve":
        if not food:
            raise HTTPException(status_code=404, detail="Target menu item not found")
        req.status = "approved"
        food.base_price = req.new_price
        action_name = "selling_price_approved"
    elif decision == "reject":
        req.status = "rejected"
        action_name = "selling_price_rejected"
    else:
        raise HTTPException(status_code=400, detail="Decision must be approve or reject")

    _log_inv_audit(
        db,
        canteen_id=req.canteen_id,
        inventory_item_id=req.inventory_item_id,
        action=action_name,
        field_name=f"selling_price:{food.name if food else req.food_item_id}",
        old_value=str(req.old_price),
        new_value=str(req.new_price),
        actor_user_id=actor_user_id,
        reason=review_notes or req.reason,
    )
    record_audit_log(
        db,
        action=f"inventory.{action_name}",
        entity_type="price_change_request",
        entity_id=str(req.id),
        actor_user_id=actor_user_id,
        details={"status": req.status, "new_price": str(req.new_price)},
    )
    db.commit()
    return {
        "id": str(req.id),
        "status": req.status,
        "food_item_id": str(req.food_item_id) if req.food_item_id else None,
        "current_menu_price": str(food.base_price) if food else None,
    }


def list_price_changes(
    db: Session,
    canteen_id: UUID,
    *,
    status_filter: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    stmt = (
        select(PriceChangeRequest)
        .where(PriceChangeRequest.canteen_id == canteen_id)
        .order_by(desc(PriceChangeRequest.created_at))
        .limit(limit)
    )
    if status_filter and status_filter != "all":
        stmt = stmt.where(PriceChangeRequest.status == status_filter)
    reqs = db.scalars(stmt).all()

    food_ids = {r.food_item_id for r in reqs if r.food_item_id}
    inv_ids = {r.inventory_item_id for r in reqs if r.inventory_item_id}
    user_ids = {u for r in reqs for u in (r.requested_by_user_id, r.reviewed_by_user_id) if u}

    food_map = {f.id: f.name for f in db.scalars(select(FoodItem).where(FoodItem.id.in_(food_ids))).all()} if food_ids else {}
    inv_rows = (
        db.execute(
            select(InventoryItem.id, Ingredient.name)
            .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
            .where(InventoryItem.id.in_(inv_ids))
        ).all()
        if inv_ids
        else []
    )
    inv_map = {iid: iname for iid, iname in inv_rows}
    user_map = (
        {u.id: (u.full_name or u.email or str(u.id)) for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
        if user_ids
        else {}
    )

    return [
        {
            "id": str(r.id),
            "canteen_id": str(r.canteen_id),
            "inventory_item_id": str(r.inventory_item_id) if r.inventory_item_id else None,
            "ingredient_name": inv_map.get(r.inventory_item_id) if r.inventory_item_id else None,
            "food_item_id": str(r.food_item_id) if r.food_item_id else None,
            "food_item_name": food_map.get(r.food_item_id) if r.food_item_id else None,
            "price_kind": r.price_kind,
            "old_price": str(r.old_price),
            "new_price": str(r.new_price),
            "reason": r.reason,
            "status": r.status,
            "requested_by_name": user_map.get(r.requested_by_user_id) if r.requested_by_user_id else None,
            "reviewed_by_name": user_map.get(r.reviewed_by_user_id) if r.reviewed_by_user_id else None,
            "review_notes": r.review_notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        }
        for r in reqs
    ]


def list_inventory_audit_logs(
    db: Session,
    canteen_id: UUID,
    *,
    inventory_item_id: Optional[UUID] = None,
    limit: int = 100,
) -> list[dict]:
    stmt = select(InventoryAuditLog).where(InventoryAuditLog.canteen_id == canteen_id)
    if inventory_item_id:
        stmt = stmt.where(InventoryAuditLog.inventory_item_id == inventory_item_id)
    logs = db.scalars(stmt.order_by(desc(InventoryAuditLog.created_at)).limit(limit)).all()

    inv_ids = {l.inventory_item_id for l in logs if l.inventory_item_id}
    user_ids = {l.changed_by_user_id for l in logs if l.changed_by_user_id}
    inv_map = (
        dict(
            db.execute(
                select(InventoryItem.id, Ingredient.name)
                .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
                .where(InventoryItem.id.in_(inv_ids))
            ).all()
        )
        if inv_ids
        else {}
    )
    user_map = (
        {u.id: (u.full_name or u.email or str(u.id)) for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
        if user_ids
        else {}
    )

    return [
        {
            "id": str(l.id),
            "inventory_item_id": str(l.inventory_item_id) if l.inventory_item_id else None,
            "ingredient_name": inv_map.get(l.inventory_item_id) if l.inventory_item_id else None,
            "action": l.action,
            "field_name": l.field_name,
            "old_value": l.old_value,
            "new_value": l.new_value,
            "reason": l.reason,
            "changed_by_name": user_map.get(l.changed_by_user_id) if l.changed_by_user_id else None,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]


def cancel_purchase_order(
    db: Session, po_id: UUID, actor_user_id: UUID, reason: Optional[str] = None
) -> dict:
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update())
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status == "received":
        raise HTTPException(status_code=409, detail="Received purchase order cannot be cancelled")
    if po.status == "cancelled":
        return {"id": str(po.id), "po_number": po.po_number, "status": "cancelled"}
    po.status = "cancelled"
    if reason:
        po.notes = f"{(po.notes or '').strip()} [Cancelled: {reason.strip()}]".strip()
    record_audit_log(
        db,
        action="purchase_order.cancelled",
        entity_type="purchase_order",
        entity_id=po.po_number,
        actor_user_id=actor_user_id,
        details={"reason": reason or "Cancelled by manager"},
    )
    db.commit()
    return {"id": str(po.id), "po_number": po.po_number, "status": po.status}


def list_wastage_records(
    db: Session,
    canteen_id: UUID,
    limit: int = 100,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    loss_type: Optional[str] = None,
    source_type: Optional[str] = None,
    responsible_staff_id: Optional[UUID] = None,
) -> list[dict]:
    stmt = (
        select(WastageRecord, InventoryItem, Ingredient.name, FoodItem.name)
        .outerjoin(InventoryItem, InventoryItem.id == WastageRecord.inventory_item_id)
        .outerjoin(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .outerjoin(FoodItem, FoodItem.id == WastageRecord.food_item_id)
        .where(or_(WastageRecord.canteen_id == canteen_id, InventoryItem.canteen_id == canteen_id))
    )
    if loss_type and loss_type != "all":
        stmt = stmt.where(WastageRecord.loss_type == loss_type)
    if source_type and source_type != "all":
        stmt = stmt.where(WastageRecord.source_type == source_type)
    if responsible_staff_id:
        stmt = stmt.where(WastageRecord.responsible_staff_id == responsible_staff_id)
    if start_date:
        stmt = stmt.where(
            or_(
                WastageRecord.waste_date >= start_date,
                WastageRecord.waste_date.is_(None),
            )
        )
    if end_date:
        stmt = stmt.where(
            or_(
                WastageRecord.waste_date <= end_date,
                WastageRecord.waste_date.is_(None),
            )
        )
    rows = db.execute(stmt.order_by(desc(WastageRecord.created_at)).limit(limit)).all()
    user_ids = {
        uid
        for wr, _, _, _ in rows
        for uid in (wr.recorded_by_user_id, wr.responsible_staff_id)
        if uid
    }
    user_map = (
        {u.id: (u.full_name or u.email or str(u.id)) for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
        if user_ids
        else {}
    )
    out = []
    for wr, inv, ing_name, food_name in rows:
        eff_date = wr.waste_date or (wr.created_at.date() if wr.created_at else None)
        if start_date and eff_date and eff_date < start_date:
            continue
        if end_date and eff_date and eff_date > end_date:
            continue
        out.append(
            {
                "id": str(wr.id),
                "inventory_item_id": str(wr.inventory_item_id) if wr.inventory_item_id else None,
                "food_item_id": str(wr.food_item_id) if wr.food_item_id else None,
                "source_type": wr.source_type or "ingredient",
                "ingredient_name": ing_name,
                "food_item_name": food_name,
                "item_name": food_name or ing_name or "Item",
                "unit": inv.unit if inv else "portions",
                "quantity": str(wr.quantity),
                "loss_type": wr.loss_type,
                "reason": wr.reason,
                "waste_date": eff_date.isoformat() if eff_date else None,
                "batch_id": str(wr.batch_id) if wr.batch_id else None,
                "estimated_loss": str(wr.estimated_loss),
                "responsible_staff_id": str(wr.responsible_staff_id) if wr.responsible_staff_id else None,
                "responsible_staff_name": user_map.get(wr.responsible_staff_id) if wr.responsible_staff_id else None,
                "recorded_by_name": user_map.get(wr.recorded_by_user_id) if wr.recorded_by_user_id else None,
                "created_at": wr.created_at.isoformat() if wr.created_at else None,
            }
        )
    return out


def list_stock_adjustments(db: Session, canteen_id: UUID, limit: int = 100) -> list[dict]:
    rows = db.execute(
        select(StockAdjustment, InventoryItem, Ingredient.name)
        .join(InventoryItem, InventoryItem.id == StockAdjustment.inventory_item_id)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id)
        .order_by(desc(StockAdjustment.created_at))
        .limit(limit)
    ).all()
    user_ids = {sa.adjusted_by_user_id for sa, _, _ in rows if sa.adjusted_by_user_id}
    user_map = (
        {u.id: (u.full_name or u.email or str(u.id)) for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
        if user_ids
        else {}
    )
    return [
        {
            "id": str(sa.id),
            "inventory_item_id": str(sa.inventory_item_id),
            "ingredient_name": ing_name,
            "unit": inv.unit,
            "quantity_delta": str(sa.quantity_delta),
            "reason": sa.reason,
            "adjusted_by_name": user_map.get(sa.adjusted_by_user_id) if sa.adjusted_by_user_id else None,
            "created_at": sa.created_at.isoformat() if sa.created_at else None,
        }
        for sa, inv, ing_name in rows
    ]


def get_inventory_report_data(db: Session, canteen_id: UUID) -> dict:
    from app.services import waste_service

    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    dashboard = get_inventory_dashboard(db, canteen_id)
    items = list_canteen_inventory(db, canteen_id, include_archived=True)
    alerts = get_inventory_alerts(db, canteen_id)
    price_changes = list_price_changes(db, canteen_id, limit=50)
    waste_analytics = waste_service.get_waste_analytics(db, canteen_id=canteen_id, period="daily")
    consumption = waste_service.get_consumption_report(db, canteen_id=canteen_id)
    recommendations = waste_service.get_waste_recommendations(db, canteen_id=canteen_id)
    return {
        "canteen_name": canteen.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dashboard": dashboard,
        "items": items,
        "alerts": alerts,
        "price_changes": price_changes,
        "waste_analytics": waste_analytics,
        "consumption": consumption,
        "waste_recommendations": recommendations,
    }


def export_inventory_csv(report: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    d = report["dashboard"]
    w.writerow(["CollegeBites Inventory & Price Audit Report"])
    w.writerow(["Canteen", report["canteen_name"]])
    w.writerow(["Generated At (UTC)", report["generated_at"]])
    w.writerow([])
    w.writerow(["KPI SUMMARY"])
    w.writerow(["Active Items", d["total_inventory_items"]])
    w.writerow(["Archived Items", d["archived_items"]])
    w.writerow(["Available Items", d["available_items"]])
    w.writerow(["Out of Stock Items", d["out_of_stock_items"]])
    w.writerow(["Low Stock Alerts", d["low_stock_alerts_count"]])
    w.writerow(["Expiring Within 7 Days", d["expiring_soon_count"]])
    w.writerow(["Expired Batches", d["expired_batches_count"]])
    w.writerow(["Total Stock Valuation (INR)", d["total_stock_valuation"]])
    w.writerow(["Total Loss Amount (INR)", d["total_loss_amount"]])
    w.writerow([])
    w.writerow(["LOSS BREAKDOWN", "Quantity", "Estimated Loss (INR)"])
    for kind, vals in d["loss_breakdown"].items():
        w.writerow([kind.upper(), vals["quantity"], vals["loss_amount"]])
    w.writerow([])
    w.writerow(["INVENTORY ITEMS", "SKU", "Category", "Unit", "Current Qty", "Reorder Level", "Purchase Cost", "Stock Value", "Status", "Storage", "Supplier", "Archived"])
    for it in report["items"]:
        w.writerow([
            it["name"],
            it["sku"],
            it["category"],
            it["unit"],
            it["current_quantity"],
            it["reorder_level"],
            it["unit_cost"],
            it["stock_value"],
            it["stock_status"],
            it["storage_location"] or "",
            it["preferred_supplier_name"] or "",
            "Yes" if it["is_archived"] else "No",
        ])
    w.writerow(["Unsold/Wastage Loss", d["loss_breakdown"].get("unsold", {}).get("loss_amount", "0.00")])
    wa = report.get("waste_analytics") or {}
    ws = wa.get("summary") or {}
    if ws:
        w.writerow([])
        w.writerow(["FOOD WASTE MANAGEMENT"])
        w.writerow(["Total Food Prepared (portions)", ws.get("total_food_prepared", 0)])
        w.writerow(["Total Food Sold (portions)", ws.get("total_food_sold", 0)])
        w.writerow(["Total Food Wasted (portions)", ws.get("total_food_wasted", 0)])
        w.writerow(["Food Wastage %", f"{ws.get('food_wastage_percent', 0)}%"])
        w.writerow(["Estimated Total Wastage Cost (INR)", ws.get("estimated_wastage_cost", "0.00")])
    w.writerow([])
    w.writerow(["PRICE CHANGES", "Kind", "Target", "Old Price", "New Price", "Status", "Reason", "Requested By", "Reviewed By"])
    for p in report["price_changes"]:
        target = p["food_item_name"] or p["ingredient_name"] or ""
        w.writerow([p["created_at"], p["price_kind"], target, p["old_price"], p["new_price"], p["status"], p["reason"], p["requested_by_name"] or "", p["reviewed_by_name"] or ""])
    cons = (report.get("consumption") or {}).get("items") or []
    if cons:
        w.writerow([])
        w.writerow(["CONSUMPTION REPORT", "Unit", "Stocked In", "Order Deducted", "Wasted", "Theoretical Recipe", "Actual Consumed", "Variance"])
        for c in cons:
            w.writerow([c["ingredient_name"], c["unit"], c["stocked_in"], c["order_deducted"], c["wasted"], c["theoretical_recipe_consumption"], c["actual_consumed"], c["variance_quantity"]])
    return buf.getvalue()


def export_inventory_pdf(report: dict) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _w, h = A4
    y = h - 40

    def ensure_space(needed: int = 24) -> None:
        nonlocal y
        if y - needed < 42:
            c.showPage()
            y = h - 42

    d = report["dashboard"]
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, f"CollegeBites Inventory Report - {report['canteen_name']}")
    y -= 18
    c.setFont("Helvetica", 9)
    c.drawString(40, y, f"Generated: {report['generated_at'][:19]} UTC")
    y -= 22

    def section(title: str, rows: list[tuple[str, object]]) -> None:
        nonlocal y
        ensure_space(36)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, title)
        y -= 15
        c.setFont("Helvetica", 9)
        for lbl, val in rows:
            ensure_space(14)
            c.drawString(50, y, f"{lbl}: {val}"[:96])
            y -= 13
        y -= 8

    section("Stock Summary", [
        ("Active Items / Archived", f"{d['total_inventory_items']} / {d['archived_items']}"),
        ("Available / Out of Stock / Low Stock", f"{d['available_items']} / {d['out_of_stock_items']} / {d['low_stock_alerts_count']}"),
        ("Expiring (7d) / Expired Batches", f"{d['expiring_soon_count']} / {d['expired_batches_count']}"),
        ("Total Stock Valuation", f"Rs.{d['total_stock_valuation']}"),
        ("Damaged Loss", f"Rs.{d['loss_breakdown']['damaged']['loss_amount']} ({d['loss_breakdown']['damaged']['quantity']})"),
        ("Expired Loss", f"Rs.{d['loss_breakdown']['expired']['loss_amount']} ({d['loss_breakdown']['expired']['quantity']})"),
        ("Wastage Loss", f"Rs.{d['loss_breakdown']['wastage']['loss_amount']} ({d['loss_breakdown']['wastage']['quantity']})"),
        ("Unsold Food Loss", f"Rs.{d['loss_breakdown'].get('unsold', {}).get('loss_amount', '0.00')} ({d['loss_breakdown'].get('unsold', {}).get('quantity', '0')})"),
        ("Pending Selling Price Approvals", d["pending_price_requests_count"]),
    ])

    ws = (report.get("waste_analytics") or {}).get("summary") or {}
    if ws:
        section("Food Waste Management (Last 14 Days)", [
            ("Prepared / Sold / Wasted (Portions)", f"{ws.get('total_food_prepared', 0)} / {ws.get('total_food_sold', 0)} / {ws.get('total_food_wasted', 0)}"),
            ("Food Wastage Percentage", f"{ws.get('food_wastage_percent', 0)}%"),
            ("Estimated Wastage Cost", f"Rs.{ws.get('estimated_wastage_cost', '0.00')}"),
        ])

    section("Inventory Stock Ledger", [
        (f"{it['name']} ({it['sku']})", f"{it['current_quantity']} {it['unit']} @ Rs.{it['unit_cost']} [{it['stock_status']}]")
        for it in report["items"][:35]
    ])

    if report["price_changes"]:
        section("Recent Price Changes & Requests", [
            (
                f"{p['price_kind']} - {p['food_item_name'] or p['ingredient_name']}",
                f"Rs.{p['old_price']} -> Rs.{p['new_price']} [{p['status']}]",
            )
            for p in report["price_changes"][:20]
        ])

    c.showPage()
    c.save()
    return buf.getvalue()
