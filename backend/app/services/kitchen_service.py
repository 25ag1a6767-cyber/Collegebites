from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.auth import User
from app.models.college import Kitchen, KitchenStation
from app.models.engagement import Notification
from app.models.inventory import InventoryItem, StockBatch, StockMovement
from app.models.menu import FoodItem, Ingredient
from app.models.order import Order, OrderAssignment, OrderItem, OrderStatusHistory
from app.schemas.operations import DelayReportRequest, ItemUnavailableRequest
from app.schemas.order import OrderOut
from app.services.audit_service import record_audit_log
from app.services.inventory_service import refresh_food_item_ingredient_sufficiency
from app.services.notification_service import notify_customer_order_event
from app.services.order_service import cancel_or_reject_order, serialize_order, serialize_orders_batch, transition_order_status
from app.websockets import emit_order_event_sync, emit_user_notification_sync, ws_manager

KITCHEN_ACTIVE_STATUSES = ("PLACED", "ACCEPTED", "PREPARING", "READY")


def list_kitchen_orders(
    db: Session,
    canteen_id: UUID,
    status_filter: Optional[str] = None,
    kitchen_id: Optional[UUID] = None,
    station_id: Optional[UUID] = None,
) -> list[OrderOut]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.canteen_id == canteen_id)
        .order_by(Order.is_priority.desc(), Order.created_at.asc())
    )
    if kitchen_id:
        stmt = stmt.where(Order.kitchen_id == kitchen_id)
    if station_id:
        stmt = stmt.where(Order.id.in_(select(OrderItem.order_id).where(OrderItem.station_id == station_id)))
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    else:
        stmt = stmt.where(Order.status.in_(KITCHEN_ACTIVE_STATUSES))
    orders = db.scalars(stmt).all()
    return serialize_orders_batch(db, list(orders))


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
    notify_customer_order_event(
        db,
        order,
        event_type="order_accepted",
        title="Order Accepted by Kitchen",
        message=f"Your order {order.order_number} has been accepted and queued for preparation.",
    )
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
    notify_customer_order_event(
        db,
        order,
        event_type="order_preparing",
        title="Preparation Started",
        message=f"Chefs started preparing your order {order.order_number}.",
    )
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
    if order.payment_status != "CONFIRMED" or order.status not in KITCHEN_ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot delay order in status {order.status}")
    prev_status = order.status
    order.delayed_minutes += payload.additional_minutes
    order.delay_reason = payload.reason
    base_pickup = order.estimated_pickup_at or datetime.now(timezone.utc)
    order.estimated_pickup_at = base_pickup + timedelta(minutes=payload.additional_minutes)
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=prev_status,
            to_status=prev_status,
            changed_by_user_id=staff_user_id,
            reason=f"Delayed +{payload.additional_minutes}m: {payload.reason}",
        )
    )
    notify_customer_order_event(
        db,
        order,
        event_type="order_delayed",
        title=f"Order Delayed +{payload.additional_minutes} min",
        message=f"Order {order.order_number} delayed by {payload.additional_minutes} mins ({payload.reason}).",
        send_external=True,
        dedup_suffix=str(order.delayed_minutes),
    )
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
    if loaded.customer_id:
        emit_user_notification_sync(
            str(loaded.customer_id),
            "order_delayed",
            {"title": f"Order Delayed +{payload.additional_minutes} min", "order_number": loaded.order_number},
        )
    return serialize_order(db, loaded)


def toggle_order_priority(db: Session, order_id: UUID, is_priority: bool, staff_user_id: UUID) -> OrderOut:
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in KITCHEN_ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot change priority in status {order.status}")
    order.is_priority = is_priority
    record_audit_log(
        db,
        action="kitchen.order_priority_updated",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=staff_user_id,
        details={"is_priority": is_priority},
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
        "order.priority_updated",
        {"is_priority": is_priority},
    )
    return serialize_order(db, loaded)


def update_order_item_prep_status(
    db: Session, order_item_id: UUID, prep_status: str, staff_user_id: UUID
) -> OrderOut:
    item = db.scalar(select(OrderItem).where(OrderItem.id == order_item_id).with_for_update())
    if not item:
        raise HTTPException(status_code=404, detail="Order item not found")
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == item.order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in ("ACCEPTED", "PREPARING", "PLACED"):
        raise HTTPException(status_code=409, detail=f"Cannot update item prep status when order is {order.status}")
    item.prep_status = prep_status
    record_audit_log(
        db,
        action="kitchen.order_item_prep_status",
        entity_type="order_item",
        entity_id=str(item.id),
        actor_user_id=staff_user_id,
        details={"order_number": order.order_number, "item_name": item.item_name, "prep_status": prep_status},
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
        "order.item_updated",
        {"order_item_id": str(item.id), "prep_status": prep_status},
    )
    return serialize_order(db, loaded)


def toggle_item_availability_from_kitchen(
    db: Session, food_item_id: UUID, payload: ItemUnavailableRequest, staff_user_id: UUID
) -> dict:
    item = db.get(FoodItem, food_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    item.is_available = payload.is_available
    if not payload.is_available:
        for role_name in ("inventory_manager", "canteen_manager"):
            db.add(
                Notification(
                    role_target=role_name,
                    canteen_id=item.canteen_id,
                    channel="in_app",
                    title=f"Item Marked Unavailable • {item.name}",
                    message=f"Kitchen disabled {item.name}: {payload.reason}",
                    event_type="item_unavailable",
                    delivery_status="sent",
                )
            )
    record_audit_log(
        db,
        action="kitchen.item_availability_changed",
        entity_type="food_item",
        entity_id=str(item.id),
        actor_user_id=staff_user_id,
        details={"name": item.name, "is_available": payload.is_available, "reason": payload.reason},
    )
    db.commit()
    ws_manager.schedule_broadcast(
        f"board:{item.canteen_id}",
        {"event": "menu.availability_changed", "canteen_id": str(item.canteen_id), "data": {"food_item_id": str(item.id), "is_available": item.is_available}},
    )
    ws_manager.schedule_broadcast(
        f"kitchen:{item.canteen_id}",
        {"event": "menu.availability_changed", "canteen_id": str(item.canteen_id), "data": {"food_item_id": str(item.id), "is_available": item.is_available}},
    )
    return {"id": str(item.id), "name": item.name, "is_available": item.is_available}


def reject_order_from_kitchen(db: Session, order_id: UUID, reason: str, staff_user_id: UUID) -> OrderOut:
    """Reject an order from kitchen before handover while preserving immutable payment records (no refunds)."""
    out = cancel_or_reject_order(
        db,
        order_id,
        cancellation_type="rejected",
        reason=reason,
        actor_user_id=staff_user_id,
        is_staff=True,
    )
    order = db.get(Order, order_id)
    if order:
        notify_customer_order_event(
            db,
            order,
            event_type="order_rejected",
            title=f"Order {order.order_number} Rejected",
            message=f"Rejected by kitchen ({reason}). Payment record is retained; contact college finance for exceptional adjustments.",
            send_external=True,
        )
        db.commit()
        if order.customer_id:
            emit_user_notification_sync(
                str(order.customer_id),
                "order_rejected",
                {"title": f"Order {order.order_number} Rejected", "order_number": order.order_number},
            )
    return out


def list_canteen_ingredients_for_kitchen(db: Session, canteen_id: UUID) -> list[dict]:
    rows = db.execute(
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id, InventoryItem.is_archived.is_(False))
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
            "is_available": inv.is_available,
        }
        for inv, ing in rows
    ]


def report_ingredient_unavailable(db: Session, inventory_item_id: UUID, reason: str, staff_user_id: UUID) -> dict:
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    ing = db.get(Ingredient, inv.ingredient_id)
    prev_qty = inv.current_quantity
    delta = -prev_qty if prev_qty > 0 else Decimal("0.000")
    inv.current_quantity = Decimal("0.000")
    inv.is_available = False
    batches = db.scalars(
        select(StockBatch)
        .where(StockBatch.inventory_item_id == inv.id, StockBatch.remaining_quantity > 0)
        .with_for_update()
    ).all()
    for batch in batches:
        batch.remaining_quantity = Decimal("0.000")
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
    for role_name in ("inventory_manager", "canteen_manager"):
        db.add(
            Notification(
                role_target=role_name,
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
    ws_manager.schedule_broadcast(
        f"board:{inv.canteen_id}",
        {"event": "menu.availability_changed", "canteen_id": str(inv.canteen_id), "data": {"blocked_food_items": blocked}},
    )
    ws_manager.schedule_broadcast(
        f"kitchen:{inv.canteen_id}",
        {"event": "menu.availability_changed", "canteen_id": str(inv.canteen_id), "data": {"blocked_food_items": blocked}},
    )
    return {
        "inventory_item_id": str(inv.id),
        "ingredient_name": ing.name if ing else "",
        "current_quantity": "0.000",
        "is_available": inv.is_available,
        "blocked_food_items": blocked,
    }


def restore_ingredient_availability(db: Session, inventory_item_id: UUID, staff_user_id: UUID) -> dict:
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    ing = db.get(Ingredient, inv.ingredient_id)
    inv.is_available = True
    blocked = refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    record_audit_log(
        db,
        action="kitchen.ingredient_restored",
        entity_type="inventory_item",
        entity_id=str(inv.id),
        actor_user_id=staff_user_id,
        details={"ingredient": ing.name if ing else None, "blocked_items": blocked},
    )
    db.commit()
    ws_manager.schedule_broadcast(
        f"kitchen:{inv.canteen_id}",
        {"event": "menu.availability_changed", "canteen_id": str(inv.canteen_id), "data": {"blocked_food_items": blocked}},
    )
    return {
        "inventory_item_id": str(inv.id),
        "ingredient_name": ing.name if ing else "",
        "current_quantity": str(inv.current_quantity),
        "is_available": inv.is_available,
        "blocked_food_items": blocked,
    }


def list_canteen_stations_with_workload(db: Session, canteen_id: UUID) -> list[dict]:
    rows = db.execute(
        select(KitchenStation, Kitchen.name)
        .join(Kitchen, Kitchen.id == KitchenStation.kitchen_id)
        .where(Kitchen.canteen_id == canteen_id, KitchenStation.is_active.is_(True))
        .order_by(Kitchen.name, KitchenStation.name)
    ).all()
    if not rows:
        return []
    station_ids = [st.id for st, _ in rows]
    workload_rows = db.execute(
        select(OrderItem.station_id, func.count(OrderItem.id), func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            OrderItem.station_id.in_(station_ids),
            Order.canteen_id == canteen_id,
            Order.status.in_(("PLACED", "ACCEPTED", "PREPARING")),
            OrderItem.prep_status != "READY",
        )
        .group_by(OrderItem.station_id)
    ).all()
    wl_map = {sid: (int(line_cnt), int(qty_sum)) for sid, line_cnt, qty_sum in workload_rows}
    return [
        {
            "id": str(st.id),
            "kitchen_id": str(st.kitchen_id),
            "kitchen_name": k_name,
            "name": st.name,
            "station_type": st.station_type,
            "is_active": st.is_active,
            "pending_lines": wl_map.get(st.id, (0, 0))[0],
            "pending_units": wl_map.get(st.id, (0, 0))[1],
        }
        for st, k_name in rows
    ]


def assign_order_to_station_or_staff(
    db: Session,
    order_id: UUID,
    *,
    kitchen_id: Optional[UUID] = None,
    station_id: Optional[UUID] = None,
    staff_user_id: Optional[UUID] = None,
    role_scope: str = "kitchen",
    actor_user_id: UUID,
) -> dict:
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if kitchen_id:
        kit = db.get(Kitchen, kitchen_id)
        if not kit or kit.canteen_id != order.canteen_id:
            raise HTTPException(status_code=400, detail="Invalid kitchen for order canteen")
        order.kitchen_id = kitchen_id
    if station_id:
        st = db.scalar(
            select(KitchenStation)
            .join(Kitchen, Kitchen.id == KitchenStation.kitchen_id)
            .where(KitchenStation.id == station_id, Kitchen.canteen_id == order.canteen_id)
        )
        if not st:
            raise HTTPException(status_code=400, detail="Invalid kitchen station for order canteen")
        if not kitchen_id:
            order.kitchen_id = st.kitchen_id
    if staff_user_id:
        usr = db.get(User, staff_user_id)
        if not usr or not usr.is_active:
            raise HTTPException(status_code=404, detail="Assigned staff user not found")

    assignment = db.scalar(
        select(OrderAssignment).where(
            OrderAssignment.order_id == order.id,
            OrderAssignment.role_scope == role_scope,
        )
    )
    if assignment:
        if kitchen_id is not None or station_id is not None:
            assignment.kitchen_id = kitchen_id or order.kitchen_id
        if station_id is not None:
            assignment.station_id = station_id
        if staff_user_id is not None:
            assignment.staff_user_id = staff_user_id
    else:
        assignment = OrderAssignment(
            order_id=order.id,
            kitchen_id=kitchen_id or order.kitchen_id,
            station_id=station_id,
            staff_user_id=staff_user_id,
            role_scope=role_scope,
        )
        db.add(assignment)

    record_audit_log(
        db,
        action="kitchen.order_assigned",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=actor_user_id,
        details={
            "kitchen_id": str(assignment.kitchen_id) if assignment.kitchen_id else None,
            "station_id": str(assignment.station_id) if assignment.station_id else None,
            "staff_user_id": str(assignment.staff_user_id) if assignment.staff_user_id else None,
            "role_scope": role_scope,
        },
    )
    db.commit()
    db.refresh(assignment)
    emit_order_event_sync(
        str(order.canteen_id),
        str(order.id),
        "order.assigned",
        {
            "order_number": order.order_number,
            "station_id": str(assignment.station_id) if assignment.station_id else None,
            "kitchen_id": str(assignment.kitchen_id) if assignment.kitchen_id else None,
        },
    )
    return {
        "id": str(assignment.id),
        "order_id": str(assignment.order_id),
        "kitchen_id": str(assignment.kitchen_id) if assignment.kitchen_id else None,
        "station_id": str(assignment.station_id) if assignment.station_id else None,
        "staff_user_id": str(assignment.staff_user_id) if assignment.staff_user_id else None,
        "role_scope": assignment.role_scope,
    }
