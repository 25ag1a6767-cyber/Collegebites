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

from app.core.time_utils import today_college
from app.models.auth import User
from app.models.college import Canteen
from app.models.inventory import (
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
    WastageRecord,
)
from app.models.menu import FoodItem, Ingredient, Recipe, RecipeIngredient
from app.models.order import Order, OrderItem
from app.services.audit_service import record_audit_log
from app.websockets import emit_order_event_sync


@sa_event.listens_for(Session, "after_commit")
def _flush_inventory_ws_events(session: Session) -> None:
    pending = session.info.pop("_pending_inv_ws", None)
    if not pending:
        return
    for canteen_id, event_type, payload in pending:
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
        stmt = stmt.where(or_(StockBatch.expiry_date.is_(None), StockBatch.expiry_date >= today))
    remaining = qty
    for batch in db.scalars(stmt).all():
        if remaining <= Decimal("0.000"):
            break
        take = min(batch.remaining_quantity, remaining)
        batch.remaining_quantity -= take
        remaining -= take
        if take > 0:
            consumed.append((batch.id, take, batch.expiry_date, batch.unit_cost))
    return consumed


def _expired_batch_totals_map(db: Session, inv_ids: list[UUID]) -> dict[UUID, Decimal]:
    if not inv_ids:
        return {}
    today = today_college()
    rows = db.execute(
        select(StockBatch.inventory_item_id, func.coalesce(func.sum(StockBatch.remaining_quantity), 0))
        .where(
            StockBatch.inventory_item_id.in_(inv_ids),
            StockBatch.remaining_quantity > 0,
            StockBatch.expiry_date.is_not(None),
            StockBatch.expiry_date < today,
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
    for oi in order_items:
        if not oi.food_item_id:
            continue
        recipe = db.scalar(select(Recipe).where(Recipe.food_item_id == oi.food_item_id))
        if not recipe:
            continue
        req_rows = db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)).all()
        for req in req_rows:
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
        )
    except ImportError:
        pass


def refresh_food_item_ingredient_sufficiency(db: Session, canteen_id: UUID) -> list[str]:
    """Recompute FoodItem.insufficient_ingredients using unexpired, unreserved ingredient stock."""
    invs = db.scalars(select(InventoryItem).where(InventoryItem.canteen_id == canteen_id)).all()
    expired_map = _expired_batch_totals_map(db, [inv.id for inv in invs])
    inv_map = {
        inv.ingredient_id: get_unexpired_stock_quantity(
            db, inv, exclude_reserved=True, expired_map=expired_map
        )
        for inv in invs
    }
    items = db.scalars(select(FoodItem).where(FoodItem.canteen_id == canteen_id)).all()
    blocked_names: list[str] = []
    changed_foods: list[dict] = []
    for food in items:
        recipe = db.scalar(select(Recipe).where(Recipe.food_item_id == food.id))
        if not recipe:
            continue
        req_rows = db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)).all()
        if not req_rows:
            continue
        short = False
        for req in req_rows:
            avail = inv_map.get(req.ingredient_id, Decimal("0.000"))
            per_portion = req.quantity_required / Decimal(max(1, recipe.yield_portions))
            if avail < per_portion:
                short = True
                break
        if food.insufficient_ingredients != short:
            changed_foods.append(
                {
                    "food_item_id": str(food.id),
                    "name": food.name,
                    "insufficient_ingredients": short,
                }
            )
        food.insufficient_ingredients = short
        if short:
            blocked_names.append(food.name)
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
    refresh_food_item_ingredient_sufficiency(db, order.canteen_id)


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
            if inv.current_quantity <= inv.reorder_level:
                low_stock_targets.append((inv, ing_names.get(inv.ingredient_id, "Ingredient")))

    order.inventory_deducted = True
    refresh_food_item_ingredient_sufficiency(db, order.canteen_id)
    for inv_low, ing_name in low_stock_targets:
        _trigger_low_stock_alert_if_needed(db, inv_low, ing_name, canteen_id=order.canteen_id)


def list_suppliers(db: Session) -> list[Supplier]:
    return list(db.scalars(select(Supplier).order_by(Supplier.name)).all())


def create_supplier(db: Session, data: dict, actor_user_id: UUID) -> Supplier:
    sup = Supplier(**data)
    db.add(sup)
    record_audit_log(db, action="supplier.created", entity_type="supplier", entity_id=sup.name, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(sup)
    return sup


def update_supplier(db: Session, supplier_id: UUID, data: dict, actor_user_id: UUID) -> Supplier:
    sup = db.get(Supplier, supplier_id)
    if not sup:
        raise HTTPException(status_code=404, detail="Supplier not found")
    for k, v in data.items():
        if v is not None:
            setattr(sup, k, v)
    record_audit_log(db, action="supplier.updated", entity_type="supplier", entity_id=str(sup.id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(sup)
    return sup


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

        batches = db.scalars(
            select(StockBatch)
            .where(StockBatch.inventory_item_id == inv.id, StockBatch.remaining_quantity > 0)
            .order_by(StockBatch.expiry_date.asc().nulls_last())
        ).all()
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


def create_purchase_order(db: Session, data: dict, actor_user_id: UUID) -> dict:
    po_number = f"PO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6].upper()}"
    total = sum(
        (Decimal(str(it["quantity_ordered"])) * Decimal(str(it["unit_cost"])) for it in data["items"]),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))
    po = PurchaseOrder(
        po_number=po_number,
        canteen_id=data["canteen_id"],
        supplier_id=data["supplier_id"],
        status="ordered",
        total_cost=total,
        ordered_by_user_id=actor_user_id,
        notes=data.get("notes"),
    )
    db.add(po)
    db.flush()
    for it in data["items"]:
        db.add(
            PurchaseOrderItem(
                purchase_order_id=po.id,
                ingredient_id=it["ingredient_id"],
                quantity_ordered=Decimal(str(it["quantity_ordered"])),
                unit_cost=Decimal(str(it["unit_cost"])),
                expiry_date=it.get("expiry_date"),
            )
        )
    record_audit_log(db, action="purchase_order.created", entity_type="purchase_order", entity_id=po_number, actor_user_id=actor_user_id)
    db.commit()
    return {"id": str(po.id), "po_number": po.po_number, "status": po.status, "total_cost": str(po.total_cost)}


def receive_purchase_order(
    db: Session, po_id: UUID, actor_user_id: UUID, received_items: Optional[list[dict]] = None
) -> dict:
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == po_id).with_for_update())
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status == "cancelled":
        raise HTTPException(status_code=409, detail="Cancelled purchase order cannot be received")
    if po.status == "received":
        return {"id": str(po.id), "po_number": po.po_number, "status": "received"}

    po_items = db.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == po.id)).all()
    rec_map = {str(r["ingredient_id"]): r for r in (received_items or [])}
    now = datetime.now(timezone.utc)
    for poi in po_items:
        outstanding = max(Decimal("0.000"), poi.quantity_ordered - poi.quantity_received)
        if outstanding <= Decimal("0.000"):
            continue
        if received_items is not None:
            entry = rec_map.get(str(poi.ingredient_id))
            if not entry:
                continue
            receive_qty = min(outstanding, max(Decimal("0.000"), Decimal(str(entry["quantity_received"]))))
            expiry = entry.get("expiry_date") or poi.expiry_date
        else:
            receive_qty = outstanding
            expiry = poi.expiry_date
        if receive_qty <= Decimal("0.000"):
            continue

        poi.quantity_received += receive_qty
        inv = db.scalar(
            select(InventoryItem)
            .where(InventoryItem.canteen_id == po.canteen_id, InventoryItem.ingredient_id == poi.ingredient_id)
            .with_for_update()
        )
        if not inv:
            ing = db.get(Ingredient, poi.ingredient_id)
            inv = InventoryItem(
                canteen_id=po.canteen_id,
                ingredient_id=poi.ingredient_id,
                current_quantity=Decimal("0.000"),
                unit=ing.unit if ing else "grams",
                unit_cost=poi.unit_cost,
            )
            db.add(inv)
            db.flush()
        inv.current_quantity += receive_qty
        inv.unit_cost = poi.unit_cost
        batch = StockBatch(
            inventory_item_id=inv.id,
            supplier_id=po.supplier_id,
            batch_number=f"{po.po_number}-{str(poi.ingredient_id)[:4]}-{uuid4().hex[:3].upper()}",
            initial_quantity=receive_qty,
            remaining_quantity=receive_qty,
            unit_cost=poi.unit_cost,
            received_at=now,
            expiry_date=expiry,
        )
        db.add(batch)
        db.flush()
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
                notes=f"Received {receive_qty} from {po.po_number}",
            )
        )
    all_done = all(p.quantity_received >= p.quantity_ordered for p in po_items)
    any_done = any(p.quantity_received > 0 for p in po_items)
    po.status = "received" if all_done else ("partial" if any_done else po.status)
    if all_done:
        po.received_at = now
    refresh_food_item_ingredient_sufficiency(db, po.canteen_id)
    record_audit_log(
        db,
        action="purchase_order.received",
        entity_type="purchase_order",
        entity_id=po.po_number,
        actor_user_id=actor_user_id,
        details={"status": po.status},
    )
    db.commit()
    return {"id": str(po.id), "po_number": po.po_number, "status": po.status}


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
                inventory_item_id=inv.id,
                batch_id=used_batch_id,
                quantity=qty,
                loss_type=loss_type,
                reason=reason,
                estimated_loss=loss,
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
        .join(InventoryItem, InventoryItem.id == WastageRecord.inventory_item_id)
        .where(InventoryItem.canteen_id == canteen_id)
    ).all()
    loss_breakdown: dict[str, dict[str, Decimal]] = {
        "damaged": {"qty": Decimal("0.000"), "loss": Decimal("0.00")},
        "expired": {"qty": Decimal("0.000"), "loss": Decimal("0.00")},
        "wastage": {"qty": Decimal("0.000"), "loss": Decimal("0.00")},
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


def list_wastage_records(db: Session, canteen_id: UUID, limit: int = 100) -> list[dict]:
    rows = db.execute(
        select(WastageRecord, InventoryItem, Ingredient.name)
        .join(InventoryItem, InventoryItem.id == WastageRecord.inventory_item_id)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id)
        .order_by(desc(WastageRecord.created_at))
        .limit(limit)
    ).all()
    user_ids = {wr.recorded_by_user_id for wr, _, _ in rows if wr.recorded_by_user_id}
    user_map = (
        {u.id: (u.full_name or u.email or str(u.id)) for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
        if user_ids
        else {}
    )
    return [
        {
            "id": str(wr.id),
            "inventory_item_id": str(wr.inventory_item_id),
            "ingredient_name": ing_name,
            "unit": inv.unit,
            "quantity": str(wr.quantity),
            "loss_type": wr.loss_type,
            "reason": wr.reason,
            "estimated_loss": str(wr.estimated_loss),
            "recorded_by_name": user_map.get(wr.recorded_by_user_id) if wr.recorded_by_user_id else None,
            "created_at": wr.created_at.isoformat() if wr.created_at else None,
        }
        for wr, inv, ing_name in rows
    ]


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
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    dashboard = get_inventory_dashboard(db, canteen_id)
    items = list_canteen_inventory(db, canteen_id, include_archived=True)
    alerts = get_inventory_alerts(db, canteen_id)
    price_changes = list_price_changes(db, canteen_id, limit=50)
    return {
        "canteen_name": canteen.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dashboard": dashboard,
        "items": items,
        "alerts": alerts,
        "price_changes": price_changes,
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
    w.writerow([])
    w.writerow(["PRICE CHANGES", "Kind", "Target", "Old Price", "New Price", "Status", "Reason", "Requested By", "Reviewed By"])
    for p in report["price_changes"]:
        target = p["food_item_name"] or p["ingredient_name"] or ""
        w.writerow([p["created_at"], p["price_kind"], target, p["old_price"], p["new_price"], p["status"], p["reason"], p["requested_by_name"] or "", p["reviewed_by_name"] or ""])
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
        ("Pending Selling Price Approvals", d["pending_price_requests_count"]),
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
