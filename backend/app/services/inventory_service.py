from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.core.time_utils import today_college
from app.models.inventory import (
    InventoryItem,
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


def refresh_food_item_ingredient_sufficiency(db: Session, canteen_id: UUID) -> list[str]:
    """Recompute FoodItem.insufficient_ingredients for all items with recipes in a canteen."""
    inv_map = {
        inv.ingredient_id: inv.current_quantity
        for inv in db.scalars(select(InventoryItem).where(InventoryItem.canteen_id == canteen_id)).all()
    }
    items = db.scalars(select(FoodItem).where(FoodItem.canteen_id == canteen_id)).all()
    blocked_names: list[str] = []
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
        food.insufficient_ingredients = short
        if short:
            blocked_names.append(food.name)
    return blocked_names


def deduct_inventory_for_order(db: Session, order: Order, actor_user_id: Optional[UUID] = None) -> None:
    """Deduct ingredients for an order exactly once using FEFO batches and row locks."""
    if order.inventory_deducted:
        return
    already = db.scalar(
        select(StockMovement.id).where(StockMovement.reference_type == "order", StockMovement.reference_id == str(order.id))
    )
    if already:
        order.inventory_deducted = True
        return

    order_items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    for oi in order_items:
        if not oi.food_item_id:
            continue
        recipe = db.scalar(select(Recipe).where(Recipe.food_item_id == oi.food_item_id))
        if not recipe:
            continue
        req_rows = db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)).all()
        for req in req_rows:
            needed = (req.quantity_required * Decimal(oi.quantity)) / Decimal(max(1, recipe.yield_portions))
            needed = needed.quantize(Decimal("0.001"))
            inv = db.scalar(
                select(InventoryItem)
                .where(InventoryItem.canteen_id == order.canteen_id, InventoryItem.ingredient_id == req.ingredient_id)
                .with_for_update()
            )
            if not inv:
                continue
            inv.current_quantity = max(Decimal("0.000"), inv.current_quantity - needed)

            # Consume non-expired batches FEFO (earliest expiry first) with row locks
            _consume_batches(db, inv.id, needed, exclude_expired=True)

            db.add(
                StockMovement(
                    inventory_item_id=inv.id,
                    movement_type="order_deduct",
                    quantity_delta=-needed,
                    balance_after=inv.current_quantity,
                    reference_type="order",
                    reference_id=str(order.id),
                    created_by_user_id=actor_user_id,
                    notes=f"Deducted for order {order.order_number}",
                )
            )

    order.inventory_deducted = True
    refresh_food_item_ingredient_sufficiency(db, order.canteen_id)


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
    if data.get("reorder_level") is not None:
        inv.reorder_level = Decimal(str(data["reorder_level"]))
    if data.get("unit_cost") is not None:
        inv.unit_cost = Decimal(str(data["unit_cost"]))
    if data.get("unit"):
        inv.unit = data["unit"]
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
    dup = db.scalar(
        select(Ingredient).where(Ingredient.canteen_id == data["canteen_id"], Ingredient.sku == data["sku"])
    )
    if dup:
        raise HTTPException(status_code=409, detail="Ingredient SKU already exists in this canteen")
    ing = Ingredient(
        canteen_id=data["canteen_id"],
        name=data["name"],
        sku=data["sku"],
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
        unit_cost=Decimal(str(data.get("unit_cost", "0.00"))),
    )
    db.add(inv)
    db.flush()
    if inv.current_quantity > 0:
        db.add(
            StockBatch(
                inventory_item_id=inv.id,
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
    return {"ingredient_id": str(ing.id), "inventory_item_id": str(inv.id), "name": ing.name, "sku": ing.sku}


def list_canteen_inventory(db: Session, canteen_id: UUID) -> list[dict]:
    rows = db.execute(
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id)
        .order_by(Ingredient.name)
    ).all()
    result = []
    for inv, ing in rows:
        batches = db.scalars(
            select(StockBatch)
            .where(StockBatch.inventory_item_id == inv.id, StockBatch.remaining_quantity > 0)
            .order_by(StockBatch.expiry_date.asc().nulls_last())
        ).all()
        result.append({
            "inventory_item_id": str(inv.id),
            "ingredient_id": str(ing.id),
            "name": ing.name,
            "sku": ing.sku,
            "unit": inv.unit,
            "current_quantity": str(inv.current_quantity),
            "reorder_level": str(inv.reorder_level),
            "unit_cost": str(inv.unit_cost),
            "is_low_stock": inv.current_quantity <= inv.reorder_level,
            "batches": [
                {
                    "id": str(b.id),
                    "batch_number": b.batch_number,
                    "remaining_quantity": str(b.remaining_quantity),
                    "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
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
) -> dict:
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    if is_wastage:
        qty = abs(quantity_delta)
        consumed = _consume_batches(db, inv.id, qty, exclude_expired=False, batch_id=batch_id)
        used_batch_id = consumed[0][0] if consumed else batch_id
        inv.current_quantity = max(Decimal("0.000"), inv.current_quantity - qty)
        loss = (qty * inv.unit_cost).quantize(Decimal("0.01"))
        w = WastageRecord(
            inventory_item_id=inv.id,
            batch_id=used_batch_id,
            quantity=qty,
            reason=reason,
            estimated_loss=loss,
            recorded_by_user_id=actor_user_id,
        )
        db.add(w)
        db.add(
            StockMovement(
                inventory_item_id=inv.id,
                batch_id=used_batch_id,
                movement_type="wastage",
                quantity_delta=-qty,
                balance_after=inv.current_quantity,
                reference_type="wastage",
                reference_id=str(inv.id),
                created_by_user_id=actor_user_id,
                notes=reason,
            )
        )
    else:
        used_batch_id = batch_id
        if quantity_delta < Decimal("0.000"):
            consumed = _consume_batches(db, inv.id, abs(quantity_delta), exclude_expired=False, batch_id=batch_id)
            used_batch_id = consumed[0][0] if consumed else batch_id
        elif quantity_delta > Decimal("0.000"):
            adj_batch = StockBatch(
                inventory_item_id=inv.id,
                batch_number=f"ADJ-{uuid4().hex[:6].upper()}",
                initial_quantity=quantity_delta,
                remaining_quantity=quantity_delta,
                unit_cost=inv.unit_cost,
                received_at=datetime.now(timezone.utc),
            )
            db.add(adj_batch)
            db.flush()
            used_batch_id = adj_batch.id
        inv.current_quantity = max(Decimal("0.000"), inv.current_quantity + quantity_delta)
        db.add(
            StockAdjustment(
                inventory_item_id=inv.id,
                quantity_delta=quantity_delta,
                reason=reason,
                adjusted_by_user_id=actor_user_id,
            )
        )
        db.add(
            StockMovement(
                inventory_item_id=inv.id,
                batch_id=used_batch_id,
                movement_type="adjustment",
                quantity_delta=quantity_delta,
                balance_after=inv.current_quantity,
                reference_type="adjustment",
                reference_id=str(inv.id),
                created_by_user_id=actor_user_id,
                notes=reason,
            )
        )

    blocked = refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    db.commit()
    return {"inventory_item_id": str(inv.id), "current_quantity": str(inv.current_quantity), "blocked_items": blocked}


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
    src = db.scalar(
        select(InventoryItem)
        .where(InventoryItem.canteen_id == from_canteen_id, InventoryItem.ingredient_id == ingredient_id)
        .with_for_update()
    )
    if not src or src.current_quantity < quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock in source canteen")
    has_batches = db.scalar(select(StockBatch.id).where(StockBatch.inventory_item_id == src.id).limit(1))
    consumed_slices = _consume_batches(db, src.id, quantity, exclude_expired=True)
    taken_total = sum((t[1] for t in consumed_slices), Decimal("0.000"))
    if has_batches and taken_total < quantity:
        db.rollback()
        raise HTTPException(status_code=400, detail="Insufficient non-expired batch stock in source canteen")
    src.current_quantity -= quantity

    src_ing = db.get(Ingredient, ingredient_id)
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

    dst = db.scalar(
        select(InventoryItem)
        .where(InventoryItem.canteen_id == to_canteen_id, InventoryItem.ingredient_id == dst_ing.id)
        .with_for_update()
    )
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
    dst.current_quantity += quantity

    now = datetime.now(timezone.utc)
    if consumed_slices:
        for _bid, taken, exp, ucost in consumed_slices:
            db.add(
                StockBatch(
                    inventory_item_id=dst.id,
                    batch_number=f"TRF-{uuid4().hex[:6].upper()}",
                    initial_quantity=taken,
                    remaining_quantity=taken,
                    unit_cost=ucost,
                    received_at=now,
                    expiry_date=exp,
                )
            )
    else:
        db.add(
            StockBatch(
                inventory_item_id=dst.id,
                batch_number=f"TRF-{uuid4().hex[:6].upper()}",
                initial_quantity=quantity,
                remaining_quantity=quantity,
                unit_cost=src.unit_cost,
                received_at=now,
            )
        )

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
            movement_type="transfer_in",
            quantity_delta=quantity,
            balance_after=dst.current_quantity,
            reference_type="transfer",
            reference_id=str(from_canteen_id),
            created_by_user_id=actor_user_id,
            notes=notes,
        )
    )
    refresh_food_item_ingredient_sufficiency(db, from_canteen_id)
    refresh_food_item_ingredient_sufficiency(db, to_canteen_id)
    db.commit()
    return {"id": str(tr.id), "status": "transferred", "quantity": str(quantity)}


def get_inventory_alerts(db: Session, canteen_id: UUID, expiring_within_days: int = 7) -> dict:
    low_stock = []
    rows = db.execute(
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id, InventoryItem.current_quantity <= InventoryItem.reorder_level)
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
