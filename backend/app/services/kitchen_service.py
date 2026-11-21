from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.engagement import Notification
from app.models.inventory import InventoryItem, StockMovement
from app.models.menu import FoodItem, Ingredient
from app.models.order import Order, OrderItem
from app.schemas.operations import DelayReportRequest, ItemUnavailableRequest
from app.schemas.order import OrderOut
from app.services.audit_service import record_audit_log
from app.services.inventory_service import refresh_food_item_ingredient_sufficiency
from app.services.order_service import cancel_or_reject_order, serialize_order, transition_order_status
from app.websockets import emit_order_event_sync

KITCHEN_ACTIVE_STATUSES = ("PLACED", "ACCEPTED", "PREPARING", "READY")


def list_kitchen_orders(db: Session, canteen_id: UUID, status_filter: Optional[str] = None) -> list[OrderOut]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.canteen_id == canteen_id)
        .order_by(Order.created_at.asc())
    )
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    else:
        stmt = stmt.where(Order.status.in_(KITCHEN_ACTIVE_STATUSES))
    orders = db.scalars(stmt).all()
    return [serialize_order(db, o) for o in orders]


def accept_order(db: Session, order_id: UUID, staff_user_id: UUID) -> OrderOut:
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    transition_order_status(db, order, "ACCEPTED", actor_user_id=staff_user_id, reason="Accepted by kitchen")
    record_audit_log(db, action="kitchen.order_accepted", entity_type="order", entity_id=order.order_number, actor_user_id=staff_user_id)
    db.commit()
    db.expire_all()
    loaded = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order.id)
    )
    emit_order_event_sync(str(order.canteen_id), str(order.id), "order.accepted", {"status": "ACCEPTED"})
    return serialize_order(db, loaded)


def start_preparing_order(db: Session, order_id: UUID, staff_user_id: UUID) -> OrderOut:
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    transition_order_status(db, order, "PREPARING", actor_user_id=staff_user_id, reason="Kitchen started preparation")
    record_audit_log(db, action="kitchen.order_preparing", entity_type="order", entity_id=order.order_number, actor_user_id=staff_user_id)
    db.commit()
    db.expire_all()
    loaded = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order.id)
    )
    emit_order_event_sync(str(order.canteen_id), str(order.id), "order.preparing", {"status": "PREPARING"})
    return serialize_order(db, loaded)


def mark_order_ready(db: Session, order_id: UUID, staff_user_id: UUID) -> OrderOut:
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    transition_order_status(db, order, "READY", actor_user_id=staff_user_id, reason="Order ready for pickup")

    try:
        from app.services.notification_service import notify_order_ready
        notify_order_ready(db, order)
    except ImportError:
        pass

    record_audit_log(db, action="kitchen.order_ready", entity_type="order", entity_id=order.order_number, actor_user_id=staff_user_id)
    db.commit()
    db.expire_all()
    loaded = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order.id)
    )
    emit_order_event_sync(str(order.canteen_id), str(order.id), "order.ready", {"status": "READY"})
    return serialize_order(db, loaded)


def report_order_delay(db: Session, order_id: UUID, payload: DelayReportRequest, staff_user_id: UUID) -> OrderOut:
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.delayed_minutes += payload.additional_minutes
    order.delay_reason = payload.reason
    base_pickup = order.estimated_pickup_at or datetime.now(timezone.utc)
    order.estimated_pickup_at = base_pickup + timedelta(minutes=payload.additional_minutes)
    record_audit_log(
        db,
        action="kitchen.order_delayed",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=staff_user_id,
        details={"additional_minutes": payload.additional_minutes, "reason": payload.reason},
    )
    db.commit()
    db.expire_all()
    loaded = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order.id)
    )
    emit_order_event_sync(
        str(order.canteen_id),
        str(order.id),
        "order.delayed",
        {"delayed_minutes": order.delayed_minutes, "reason": payload.reason},
    )
    return serialize_order(db, loaded)


def toggle_item_availability_from_kitchen(
    db: Session, food_item_id: UUID, payload: ItemUnavailableRequest, staff_user_id: UUID
) -> dict:
    item = db.get(FoodItem, food_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    item.is_available = payload.is_available
    record_audit_log(
        db,
        action="kitchen.item_availability_changed",
        entity_type="food_item",
        entity_id=str(item.id),
        actor_user_id=staff_user_id,
        details={"name": item.name, "is_available": payload.is_available, "reason": payload.reason},
    )
    db.commit()
    return {"id": str(item.id), "name": item.name, "is_available": item.is_available}


def reject_order_from_kitchen(db: Session, order_id: UUID, reason: str, staff_user_id: UUID) -> OrderOut:
    """Reject an order from kitchen before handover while preserving immutable payment records (no refunds)."""
    return cancel_or_reject_order(
        db,
        order_id,
        cancellation_type="rejected",
        reason=reason,
        actor_user_id=staff_user_id,
        is_staff=True,
    )


def list_canteen_ingredients_for_kitchen(db: Session, canteen_id: UUID) -> list[dict]:
    rows = db.execute(
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id)
        .order_by(Ingredient.name)
    ).all()
    return [
        {
            "inventory_item_id": str(inv.id),
            "ingredient_id": str(ing.id),
            "name": ing.name,
            "sku": ing.sku,
            "unit": inv.unit,
            "current_quantity": str(inv.current_quantity),
            "reorder_level": str(inv.reorder_level),
        }
        for inv, ing in rows
    ]


def report_ingredient_unavailable(db: Session, inventory_item_id: UUID, reason: str, staff_user_id: UUID) -> dict:
    inv = db.get(InventoryItem, inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    ing = db.get(Ingredient, inv.ingredient_id)
    prev_qty = inv.current_quantity
    delta = -prev_qty if prev_qty > 0 else Decimal("0.000")
    inv.current_quantity = Decimal("0.000")
    if delta != 0:
        db.add(
            StockMovement(
                inventory_item_id=inv.id,
                movement_type="kitchen_depleted",
                quantity_delta=delta,
                balance_after=inv.current_quantity,
                reference_type="kitchen_report",
                reference_id=str(inv.id),
                created_by_user_id=staff_user_id,
                notes=reason,
            )
        )
    blocked = refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    db.add(
        Notification(
            role_target="inventory_manager",
            canteen_id=inv.canteen_id,
            channel="in_app",
            title=f"Kitchen Ingredient Out of Stock • {ing.name if ing else inv.id}",
            message=f"Reported unavailable by kitchen: {reason}. Blocked dishes: {', '.join(blocked) or 'None'}",
            event_type="ingredient_unavailable",
            delivery_status="sent",
        )
    )
    record_audit_log(
        db,
        action="kitchen.ingredient_unavailable",
        entity_type="inventory_item",
        entity_id=str(inv.id),
        actor_user_id=staff_user_id,
        details={"ingredient": ing.name if ing else None, "reason": reason, "blocked_items": blocked},
    )
    db.commit()
    return {
        "inventory_item_id": str(inv.id),
        "ingredient_name": ing.name if ing else "",
        "current_quantity": "0.000",
        "blocked_food_items": blocked,
    }
