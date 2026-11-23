import csv
import io
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.time_utils import get_college_tz, today_college
from app.models.auth import StaffProfile, User
from app.models.college import Canteen
from app.models.inventory import (
    DailyFoodPrepLog,
    InventoryAuditLog,
    InventoryItem,
    StockBatch,
    StockMovement,
    WastageRecord,
)
from app.models.menu import FoodItem, Ingredient, Recipe, RecipeIngredient
from app.models.order import Order, OrderItem
from app.services.audit_service import record_activity_log

EXCLUDED_ORDER_STATUSES = ("CANCELLED", "REJECTED", "PAYMENT_FAILED", "CREATED", "PAYMENT_PENDING")


def _to_local_date(dt: Optional[datetime], tz) -> Optional[date]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).date()


def _resolve_default_dish_unit_cost(db: Session, canteen_id: UUID, food_item: FoodItem) -> Decimal:
    recipe = db.scalar(select(Recipe).where(Recipe.food_item_id == food_item.id))
    if recipe:
        rows = db.execute(
            select(RecipeIngredient.quantity_required, InventoryItem.unit_cost)
            .join(
                InventoryItem,
                (InventoryItem.ingredient_id == RecipeIngredient.ingredient_id)
                & (InventoryItem.canteen_id == canteen_id),
            )
            .where(RecipeIngredient.recipe_id == recipe.id)
        ).all()
        if rows:
            total = sum((Decimal(str(qty)) * Decimal(str(cost)) for qty, cost in rows), Decimal("0.00"))
            portions = max(1, int(recipe.yield_portions or 1))
            if total > Decimal("0.00"):
                return (total / Decimal(portions)).quantize(Decimal("0.01"))
    return (Decimal(str(food_item.base_price or 0)) * Decimal("0.40")).quantize(Decimal("0.01"))


def _sold_quantities_map(
    db: Session,
    canteen_id: UUID,
    start_date: date,
    end_date: date,
) -> dict[tuple[UUID, date], int]:
    tz = get_college_tz()
    s_dt = datetime.combine(start_date, time.min, tzinfo=tz) - timedelta(days=1)
    e_dt = datetime.combine(end_date, time.max, tzinfo=tz) + timedelta(days=1)

    rows = db.execute(
        select(OrderItem.food_item_id, OrderItem.quantity, Order.confirmed_at, Order.created_at)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.canteen_id == canteen_id,
            Order.payment_status == "CONFIRMED",
            Order.status.notin_(EXCLUDED_ORDER_STATUSES),
            Order.created_at >= s_dt,
            Order.created_at <= e_dt,
            OrderItem.food_item_id.is_not(None),
        )
    ).all()

    sold_map: dict[tuple[UUID, date], int] = defaultdict(int)
    for food_id, qty, confirmed_at, created_at in rows:
        d = _to_local_date(confirmed_at or created_at, tz)
        if d and start_date <= d <= end_date and food_id:
            sold_map[(food_id, d)] += int(qty or 0)
    return sold_map


def list_canteen_staff_for_select(db: Session, canteen_id: UUID) -> list[dict]:
    rows = db.execute(
        select(User.id, User.full_name, StaffProfile.employee_code, StaffProfile.designation)
        .join(StaffProfile, StaffProfile.user_id == User.id)
        .where(StaffProfile.assigned_canteen_id == canteen_id, User.is_active.is_(True))
        .order_by(User.full_name)
    ).all()
    return [
        {
            "user_id": str(uid),
            "full_name": full_name,
            "employee_code": emp_code,
            "designation": designation,
        }
        for uid, full_name, emp_code, designation in rows
    ]


def upsert_daily_food_prep_log(
    db: Session,
    *,
    canteen_id: UUID,
    food_item_id: UUID,
    prep_date: date,
    meal_session: str,
    prepared_quantity: int,
    unit_cost: Optional[Decimal] = None,
    responsible_staff_id: Optional[UUID] = None,
    notes: Optional[str] = None,
    actor_user_id: UUID,
) -> dict:
    food = db.get(FoodItem, food_item_id)
    if not food or food.canteen_id != canteen_id:
        raise HTTPException(status_code=404, detail="Food item not found in this canteen")
    if prepared_quantity < 0:
        raise HTTPException(status_code=400, detail="Prepared quantity cannot be negative")

    existing = db.scalar(
        select(DailyFoodPrepLog).where(
            DailyFoodPrepLog.canteen_id == canteen_id,
            DailyFoodPrepLog.food_item_id == food_item_id,
            DailyFoodPrepLog.prep_date == prep_date,
            DailyFoodPrepLog.meal_session == meal_session,
        )
    )
    resolved_cost = (
        unit_cost.quantize(Decimal("0.01"))
        if unit_cost is not None
        else _resolve_default_dish_unit_cost(db, canteen_id, food)
    )

    if existing:
        if prepared_quantity < existing.unsold_wasted_quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Prepared quantity cannot be less than already wasted portions ({existing.unsold_wasted_quantity})",
            )
        existing.prepared_quantity = prepared_quantity
        existing.unit_cost = resolved_cost
        if responsible_staff_id is not None:
            existing.responsible_staff_id = responsible_staff_id
        if notes is not None:
            existing.notes = notes
        existing.recorded_by_user_id = actor_user_id
        log_row = existing
    else:
        log_row = DailyFoodPrepLog(
            canteen_id=canteen_id,
            food_item_id=food_item_id,
            prep_date=prep_date,
            meal_session=meal_session,
            prepared_quantity=prepared_quantity,
            unsold_wasted_quantity=0,
            unit_cost=resolved_cost,
            responsible_staff_id=responsible_staff_id,
            recorded_by_user_id=actor_user_id,
            notes=notes,
        )
        db.add(log_row)

    db.flush()
    record_activity_log(
        db,
        activity_type="waste.food_prep_logged",
        description=f"Prepared {prepared_quantity} x {food.name} on {prep_date.isoformat()} ({meal_session})",
        user_id=actor_user_id,
        canteen_id=canteen_id,
        metadata={"food_item_id": str(food_item_id), "prepared_quantity": prepared_quantity},
    )
    queue = db.info.setdefault("_pending_inv_ws", [])
    queue.append((str(canteen_id), "inventory.updated", {"canteen_id": str(canteen_id), "food_prep_log_id": str(log_row.id)}))
    db.commit()
    db.refresh(log_row)

    rows = list_daily_food_prep_logs(db, canteen_id=canteen_id, start_date=prep_date, end_date=prep_date)
    match = next((r for r in rows if r["id"] == str(log_row.id)), None)
    return match or {
        "id": str(log_row.id),
        "canteen_id": str(canteen_id),
        "food_item_id": str(food_item_id),
        "food_item_name": food.name,
        "prep_date": prep_date.isoformat(),
        "meal_session": meal_session,
        "prepared_quantity": log_row.prepared_quantity,
        "sold_quantity": 0,
        "unsold_quantity": log_row.prepared_quantity,
        "unsold_wasted_quantity": log_row.unsold_wasted_quantity,
        "remaining_unlogged_unsold": max(0, log_row.prepared_quantity - log_row.unsold_wasted_quantity),
        "unit_cost": f"{log_row.unit_cost:.2f}",
    }


def list_daily_food_prep_logs(
    db: Session,
    *,
    canteen_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    meal_session: Optional[str] = None,
) -> list[dict]:
    today = today_college()
    s_date = start_date or (today - timedelta(days=13))
    e_date = end_date or today

    stmt = (
        select(DailyFoodPrepLog, FoodItem.name, FoodItem.base_price)
        .join(FoodItem, FoodItem.id == DailyFoodPrepLog.food_item_id)
        .where(
            DailyFoodPrepLog.canteen_id == canteen_id,
            DailyFoodPrepLog.prep_date >= s_date,
            DailyFoodPrepLog.prep_date <= e_date,
        )
    )
    if meal_session and meal_session != "all":
        stmt = stmt.where(DailyFoodPrepLog.meal_session == meal_session)
    rows = db.execute(stmt.order_by(DailyFoodPrepLog.prep_date.desc(), FoodItem.name.asc())).all()
    if not rows:
        return []

    sold_map = _sold_quantities_map(db, canteen_id, s_date, e_date)
    user_ids = {
        uid
        for log, _, _ in rows
        for uid in (log.responsible_staff_id, log.recorded_by_user_id)
        if uid
    }
    user_map = (
        {u.id: (u.full_name or u.email or str(u.id)) for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
        if user_ids
        else {}
    )

    session_order = {"breakfast": 1, "lunch": 2, "evening": 3, "dinner": 4, "all_day": 5}
    # Apportion daily sold qty deterministically if a dish has multiple session prep logs on the same date
    by_dish_date: dict[tuple[UUID, date], list[tuple[DailyFoodPrepLog, str, Decimal]]] = defaultdict(list)
    for item in rows:
        by_dish_date[(item[0].food_item_id, item[0].prep_date)].append(item)

    allocated_sold: dict[UUID, int] = {}
    for (fid, d), group in by_dish_date.items():
        ordered_group = sorted(group, key=lambda t: session_order.get(t[0].meal_session, 9))
        remaining = sold_map.get((fid, d), 0)
        for idx, (log, _, _) in enumerate(ordered_group):
            if idx == len(ordered_group) - 1:
                take = remaining
            else:
                take = min(log.prepared_quantity, remaining)
            allocated_sold[log.id] = take
            remaining = max(0, remaining - take)

    result = []
    for log, food_name, base_price in rows:
        sold_qty = allocated_sold.get(log.id, 0)
        unsold_qty = max(0, log.prepared_quantity - sold_qty)
        rem_unlogged = max(0, unsold_qty - log.unsold_wasted_quantity)
        waste_pct = round((log.unsold_wasted_quantity / log.prepared_quantity) * 100, 1) if log.prepared_quantity > 0 else 0.0
        est_waste_cost = (Decimal(log.unsold_wasted_quantity) * log.unit_cost).quantize(Decimal("0.01"))
        result.append(
            {
                "id": str(log.id),
                "canteen_id": str(log.canteen_id),
                "food_item_id": str(log.food_item_id),
                "food_item_name": food_name,
                "base_price": f"{base_price:.2f}",
                "prep_date": log.prep_date.isoformat(),
                "meal_session": log.meal_session,
                "prepared_quantity": log.prepared_quantity,
                "sold_quantity": sold_qty,
                "unsold_quantity": unsold_qty,
                "unsold_wasted_quantity": log.unsold_wasted_quantity,
                "remaining_unlogged_unsold": rem_unlogged,
                "wastage_percent": waste_pct,
                "unit_cost": f"{log.unit_cost:.2f}",
                "estimated_waste_cost": f"{est_waste_cost:.2f}",
                "waste_reason": log.waste_reason,
                "responsible_staff_id": str(log.responsible_staff_id) if log.responsible_staff_id else None,
                "responsible_staff_name": user_map.get(log.responsible_staff_id) if log.responsible_staff_id else None,
                "recorded_by_name": user_map.get(log.recorded_by_user_id) if log.recorded_by_user_id else None,
                "notes": log.notes,
            }
        )
    return result


def record_prepared_food_waste(
    db: Session,
    *,
    canteen_id: UUID,
    food_item_id: Optional[UUID] = None,
    prep_log_id: Optional[UUID] = None,
    waste_date: Optional[date] = None,
    quantity: Decimal,
    reason: str,
    loss_type: str = "unsold",
    responsible_staff_id: Optional[UUID] = None,
    actor_user_id: UUID,
    unit_cost: Optional[Decimal] = None,
) -> dict:
    qty_int = int(quantity)
    if Decimal(qty_int) != quantity or qty_int <= 0:
        raise HTTPException(status_code=400, detail="Prepared food waste quantity must be a positive whole number of portions")

    prep_log: Optional[DailyFoodPrepLog] = None
    if prep_log_id:
        prep_log = db.scalar(select(DailyFoodPrepLog).where(DailyFoodPrepLog.id == prep_log_id).with_for_update())
        if not prep_log or prep_log.canteen_id != canteen_id:
            raise HTTPException(status_code=404, detail="Daily food prep log not found")
        food_item_id = prep_log.food_item_id
        sold_map = _sold_quantities_map(db, canteen_id, prep_log.prep_date, prep_log.prep_date)
        sold_today = sold_map.get((prep_log.food_item_id, prep_log.prep_date), 0)
        max_wasteable = max(0, prep_log.prepared_quantity - sold_today - prep_log.unsold_wasted_quantity)
        if qty_int > max_wasteable:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot record {qty_int} unsold portions: maximum remaining unsold is {max_wasteable} "
                    f"(prepared {prep_log.prepared_quantity}, sold {sold_today}, already wasted {prep_log.unsold_wasted_quantity})"
                ),
            )
        prep_log.unsold_wasted_quantity += qty_int
        prep_log.waste_reason = reason
        if responsible_staff_id is not None:
            prep_log.responsible_staff_id = responsible_staff_id
        w_date = waste_date or prep_log.prep_date
    else:
        if not food_item_id:
            raise HTTPException(status_code=400, detail="Either prep_log_id or food_item_id is required")
        w_date = waste_date or today_college()

    food = db.get(FoodItem, food_item_id)
    if not food or food.canteen_id != canteen_id:
        raise HTTPException(status_code=404, detail="Food item not found in this canteen")

    resolved_cost = (
        unit_cost.quantize(Decimal("0.01"))
        if unit_cost is not None
        else (prep_log.unit_cost if prep_log else _resolve_default_dish_unit_cost(db, canteen_id, food))
    )
    est_loss = (Decimal(qty_int) * resolved_cost).quantize(Decimal("0.01"))
    wr = WastageRecord(
        canteen_id=canteen_id,
        inventory_item_id=None,
        food_item_id=food.id,
        batch_id=None,
        source_type="prepared_food",
        quantity=Decimal(qty_int),
        loss_type=loss_type or "unsold",
        reason=reason,
        waste_date=w_date,
        estimated_loss=est_loss,
        responsible_staff_id=responsible_staff_id,
        recorded_by_user_id=actor_user_id,
    )
    db.add(wr)
    db.add(
        InventoryAuditLog(
            canteen_id=canteen_id,
            inventory_item_id=None,
            action="prepared_food_waste",
            field_name="unsold_wasted_quantity",
            old_value=food.name,
            new_value=str(qty_int),
            reason=reason,
            changed_by_user_id=actor_user_id,
        )
    )
    record_activity_log(
        db,
        activity_type="waste.prepared_food_recorded",
        description=f"Recorded {qty_int} portions {loss_type} waste for {food.name}: {reason}",
        user_id=actor_user_id,
        canteen_id=canteen_id,
        metadata={"food_item_id": str(food.id), "estimated_loss": str(est_loss), "waste_date": w_date.isoformat()},
    )
    queue = db.info.setdefault("_pending_inv_ws", [])
    queue.append((str(canteen_id), "inventory.updated", {"canteen_id": str(canteen_id), "food_item_id": str(food.id)}))
    db.commit()
    db.refresh(wr)
    return {
        "id": str(wr.id),
        "canteen_id": str(canteen_id),
        "food_item_id": str(food.id),
        "food_item_name": food.name,
        "source_type": wr.source_type,
        "quantity": str(wr.quantity),
        "loss_type": wr.loss_type,
        "reason": wr.reason,
        "waste_date": w_date.isoformat(),
        "estimated_loss": f"{est_loss:.2f}",
        "responsible_staff_id": str(responsible_staff_id) if responsible_staff_id else None,
    }


def get_waste_analytics(
    db: Session,
    *,
    canteen_id: UUID,
    period: str = "daily",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, Any]:
    today = today_college()
    default_days = 179 if period == "monthly" else 55 if period == "weekly" else 13
    s_date = start_date or (today - timedelta(days=default_days))
    e_date = end_date or today
    if s_date > e_date:
        s_date, e_date = e_date, s_date

    prep_rows = db.execute(
        select(DailyFoodPrepLog, FoodItem.name)
        .join(FoodItem, FoodItem.id == DailyFoodPrepLog.food_item_id)
        .where(
            DailyFoodPrepLog.canteen_id == canteen_id,
            DailyFoodPrepLog.prep_date >= s_date,
            DailyFoodPrepLog.prep_date <= e_date,
        )
    ).all()

    sold_map = _sold_quantities_map(db, canteen_id, s_date, e_date)
    tz = get_college_tz()

    wastage_rows = db.execute(
        select(WastageRecord, InventoryItem, Ingredient.name, FoodItem.name)
        .outerjoin(InventoryItem, InventoryItem.id == WastageRecord.inventory_item_id)
        .outerjoin(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .outerjoin(FoodItem, FoodItem.id == WastageRecord.food_item_id)
        .where(or_(WastageRecord.canteen_id == canteen_id, InventoryItem.canteen_id == canteen_id))
    ).all()

    # Filter waste rows accurately in [s_date, e_date] using waste_date or local created_at date
    filtered_waste: list[tuple[WastageRecord, Optional[InventoryItem], Optional[str], Optional[str], date]] = []
    for wr, inv, ing_name, food_name in wastage_rows:
        w_date = wr.waste_date or _to_local_date(wr.created_at, tz)
        if w_date and s_date <= w_date <= e_date:
            filtered_waste.append((wr, inv, ing_name, food_name, w_date))

    staff_ids = {wr.responsible_staff_id for wr, _, _, _, _ in filtered_waste if wr.responsible_staff_id}
    staff_map = (
        {u.id: (u.full_name or u.email or str(u.id)) for u in db.scalars(select(User).where(User.id.in_(staff_ids))).all()}
        if staff_ids
        else {}
    )

    total_food_prepared = sum((int(log.prepared_quantity) for log, _ in prep_rows), 0)
    total_food_sold = sum(sold_map.values())
    total_prep_sold = sum(
        min(
            sum(log.prepared_quantity for log, _ in prep_rows if log.food_item_id == fid and log.prep_date == d),
            qty,
        )
        for (fid, d), qty in sold_map.items()
    ) if prep_rows else 0
    # Compute unsold strictly per (food_item_id, date) from prep logs minus actual sales
    prep_by_dish_date: dict[tuple[UUID, date], int] = defaultdict(int)
    for log, _ in prep_rows:
        prep_by_dish_date[(log.food_item_id, log.prep_date)] += int(log.prepared_quantity)
    unsold_food_qty = sum(
        max(0, prep_qty - sold_map.get((fid, d), 0))
        for (fid, d), prep_qty in prep_by_dish_date.items()
    )

    prepared_wasted_qty = Decimal("0.000")
    ingredient_wasted_qty = Decimal("0.000")
    prepared_waste_cost = Decimal("0.00")
    ingredient_waste_cost = Decimal("0.00")

    daily_map: dict[date, dict[str, Any]] = {}
    cur = s_date
    while cur <= e_date:
        daily_map[cur] = {
            "date": cur.isoformat(),
            "label": cur.strftime("%d %b"),
            "prepared_qty": 0,
            "sold_qty": 0,
            "food_wasted_qty": 0.0,
            "ingredient_wasted_qty": 0.0,
            "estimated_loss": 0.0,
        }
        cur += timedelta(days=1)

    for log, _ in prep_rows:
        if log.prep_date in daily_map:
            daily_map[log.prep_date]["prepared_qty"] += int(log.prepared_quantity)
    for (_fid, d), sq in sold_map.items():
        if d in daily_map:
            daily_map[d]["sold_qty"] += int(sq)

    item_agg: dict[str, dict[str, Any]] = {}
    reason_agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"reason": "", "count": 0, "estimated_loss": Decimal("0.00")})
    staff_agg: dict[str, dict[str, Any]] = {}

    for wr, inv, ing_name, food_name, w_date in filtered_waste:
        est = Decimal(str(wr.estimated_loss or 0))
        qty = Decimal(str(wr.quantity or 0))
        if wr.source_type == "prepared_food" or (wr.food_item_id and not wr.inventory_item_id):
            prepared_wasted_qty += qty
            prepared_waste_cost += est
            if w_date in daily_map:
                daily_map[w_date]["food_wasted_qty"] += float(qty)
            item_key = f"food:{wr.food_item_id or food_name}"
            item_name = food_name or "Prepared Dish"
            unit = "portions"
            src = "prepared_food"
        else:
            ingredient_wasted_qty += qty
            ingredient_waste_cost += est
            if w_date in daily_map:
                daily_map[w_date]["ingredient_wasted_qty"] += float(qty)
            item_key = f"ing:{wr.inventory_item_id or ing_name}"
            item_name = ing_name or "Ingredient"
            unit = inv.unit if inv else "units"
            src = "ingredient"

        if w_date in daily_map:
            daily_map[w_date]["estimated_loss"] = round(daily_map[w_date]["estimated_loss"] + float(est), 2)

        entry = item_agg.setdefault(
            item_key,
            {
                "item_name": item_name,
                "source_type": src,
                "unit": unit,
                "total_quantity": Decimal("0.000"),
                "estimated_loss": Decimal("0.00"),
                "waste_count": 0,
                "reasons": defaultdict(Decimal),
            },
        )
        entry["total_quantity"] += qty
        entry["estimated_loss"] += est
        entry["waste_count"] += 1
        entry["reasons"][wr.reason] += est

        r_key = f"{wr.loss_type}:{wr.reason}"
        reason_agg[r_key]["reason"] = wr.reason
        reason_agg[r_key]["loss_type"] = wr.loss_type
        reason_agg[r_key]["count"] += 1
        reason_agg[r_key]["estimated_loss"] += est

        if wr.responsible_staff_id:
            s_key = str(wr.responsible_staff_id)
            s_entry = staff_agg.setdefault(
                s_key,
                {
                    "staff_user_id": s_key,
                    "staff_name": staff_map.get(wr.responsible_staff_id, "Staff"),
                    "events_count": 0,
                    "estimated_loss": Decimal("0.00"),
                },
            )
            s_entry["events_count"] += 1
            s_entry["estimated_loss"] += est

    # Denominator for percentage: total food prepared (or total sold + wasted if prep logs absent)
    pct_denom = Decimal(total_food_prepared) if total_food_prepared > 0 else (Decimal(total_food_sold) + prepared_wasted_qty)
    food_wastage_percent = (
        float(((prepared_wasted_qty / pct_denom) * Decimal("100")).quantize(Decimal("0.01")))
        if pct_denom > Decimal("0")
        else 0.0
    )

    daily_trend = list(daily_map.values())

    weekly_buckets: dict[str, dict[str, Any]] = {}
    monthly_buckets: dict[str, dict[str, Any]] = {}
    for row in daily_trend:
        d = date.fromisoformat(row["date"])
        iso = d.isocalendar()
        w_key = f"{iso.year}-W{iso.week:02d}"
        m_key = d.strftime("%Y-%m")
        for target_map, key, lbl in ((weekly_buckets, w_key, w_key), (monthly_buckets, m_key, d.strftime("%b %Y"))):
            b = target_map.setdefault(
                key,
                {
                    "date": key,
                    "label": lbl,
                    "prepared_qty": 0,
                    "sold_qty": 0,
                    "food_wasted_qty": 0.0,
                    "ingredient_wasted_qty": 0.0,
                    "estimated_loss": 0.0,
                },
            )
            b["prepared_qty"] += row["prepared_qty"]
            b["sold_qty"] += row["sold_qty"]
            b["food_wasted_qty"] = round(b["food_wasted_qty"] + row["food_wasted_qty"], 3)
            b["ingredient_wasted_qty"] = round(b["ingredient_wasted_qty"] + row["ingredient_wasted_qty"], 3)
            b["estimated_loss"] = round(b["estimated_loss"] + row["estimated_loss"], 2)

    weekly_trend = [weekly_buckets[k] for k in sorted(weekly_buckets.keys())]
    monthly_trend = [monthly_buckets[k] for k in sorted(monthly_buckets.keys())]

    most_wasted_items = [
        {
            "item_name": v["item_name"],
            "source_type": v["source_type"],
            "unit": v["unit"],
            "total_quantity": f"{v['total_quantity']:.3f}",
            "estimated_loss": f"{v['estimated_loss']:.2f}",
            "waste_count": v["waste_count"],
            "top_reason": max(v["reasons"].items(), key=lambda kv: kv[1])[0] if v["reasons"] else None,
        }
        for v in sorted(item_agg.values(), key=lambda x: (-x["estimated_loss"], -x["total_quantity"]))[:15]
    ]

    total_est_cost = (prepared_waste_cost + ingredient_waste_cost).quantize(Decimal("0.01"))
    return {
        "canteen_id": str(canteen_id),
        "period": period,
        "start_date": s_date.isoformat(),
        "end_date": e_date.isoformat(),
        "summary": {
            "total_food_prepared": total_food_prepared,
            "total_food_sold": total_food_sold,
            "tracked_prep_sold": total_prep_sold,
            "unsold_food_quantity": unsold_food_qty,
            "total_food_wasted": int(prepared_wasted_qty),
            "food_wastage_percent": food_wastage_percent,
            "ingredient_wasted_quantity": f"{ingredient_wasted_qty:.3f}",
            "prepared_food_waste_cost": f"{prepared_waste_cost:.2f}",
            "ingredient_waste_cost": f"{ingredient_waste_cost:.2f}",
            "estimated_wastage_cost": f"{total_est_cost:.2f}",
            "total_waste_events": len(filtered_waste),
        },
        "most_wasted_items": most_wasted_items,
        "daily_trend": daily_trend,
        "weekly_trend": weekly_trend,
        "monthly_trend": monthly_trend,
        "trend_series": monthly_trend if period == "monthly" else weekly_trend if period == "weekly" else daily_trend,
        "reason_breakdown": [
            {
                "reason": r["reason"],
                "loss_type": r["loss_type"],
                "count": r["count"],
                "estimated_loss": f"{r['estimated_loss']:.2f}",
            }
            for r in sorted(reason_agg.values(), key=lambda x: -x["estimated_loss"])[:12]
        ],
        "staff_breakdown": [
            {
                "staff_user_id": s["staff_user_id"],
                "staff_name": s["staff_name"],
                "events_count": s["events_count"],
                "estimated_loss": f"{s['estimated_loss']:.2f}",
            }
            for s in sorted(staff_agg.values(), key=lambda x: -x["estimated_loss"])[:12]
        ],
    }


def get_consumption_report(
    db: Session,
    *,
    canteen_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    inventory_item_id: Optional[UUID] = None,
) -> dict[str, Any]:
    tz = get_college_tz()
    today = today_college()
    s_date = start_date or (today - timedelta(days=29))
    e_date = end_date or today
    s_dt = datetime.combine(s_date, time.min, tzinfo=tz)
    e_dt = datetime.combine(e_date, time.max, tzinfo=tz)

    inv_stmt = (
        select(InventoryItem, Ingredient.name)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id, InventoryItem.is_archived.is_(False))
        .order_by(Ingredient.name)
    )
    if inventory_item_id:
        inv_stmt = inv_stmt.where(InventoryItem.id == inventory_item_id)
    inv_rows = db.execute(inv_stmt).all()
    if not inv_rows:
        return {"start_date": s_date.isoformat(), "end_date": e_date.isoformat(), "items": []}

    inv_ids = [inv.id for inv, _ in inv_rows]
    ing_to_inv = {inv.ingredient_id: inv.id for inv, _ in inv_rows}

    mv_rows = db.scalars(
        select(StockMovement).where(
            StockMovement.inventory_item_id.in_(inv_ids),
            StockMovement.created_at >= s_dt,
            StockMovement.created_at <= e_dt,
        )
    ).all()

    agg: dict[UUID, dict[str, Decimal]] = {
        inv_id: {
            "stocked_in": Decimal("0.000"),
            "order_deducted": Decimal("0.000"),
            "wasted": Decimal("0.000"),
            "transferred_out": Decimal("0.000"),
            "net_adjustment": Decimal("0.000"),
            "theoretical_used": Decimal("0.000"),
        }
        for inv_id in inv_ids
    }
    for mv in mv_rows:
        bucket = agg[mv.inventory_item_id]
        delta = Decimal(str(mv.quantity_delta or 0))
        mtype = mv.movement_type
        if mtype in ("opening", "purchase", "restock", "transfer_in"):
            bucket["stocked_in"] += max(Decimal("0.000"), delta)
        elif mtype in ("order_deduct", "order_deduction"):
            bucket["order_deducted"] += abs(delta)
        elif mtype in ("damaged", "expired", "wastage"):
            bucket["wasted"] += abs(delta)
        elif mtype == "transfer_out":
            bucket["transferred_out"] += abs(delta)
        else:
            bucket["net_adjustment"] += delta

    # Theoretical consumption derived from confirmed non-cancelled orders x active dish recipes
    oi_rows = db.execute(
        select(OrderItem.food_item_id, func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.canteen_id == canteen_id,
            Order.payment_status == "CONFIRMED",
            Order.status.notin_(EXCLUDED_ORDER_STATUSES),
            Order.created_at >= s_dt,
            Order.created_at <= e_dt,
            OrderItem.food_item_id.is_not(None),
        )
        .group_by(OrderItem.food_item_id)
    ).all()
    if oi_rows:
        food_qty_map = {fid: int(q) for fid, q in oi_rows if fid and int(q or 0) > 0}
        if food_qty_map:
            rec_rows = db.execute(
                select(Recipe.food_item_id, Recipe.yield_portions, RecipeIngredient.ingredient_id, RecipeIngredient.quantity_required)
                .join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id)
                .where(
                    Recipe.food_item_id.in_(list(food_qty_map.keys())),
                    RecipeIngredient.ingredient_id.in_(list(ing_to_inv.keys())),
                )
            ).all()
            for fid, y_port, ing_id, req_qty in rec_rows:
                inv_id = ing_to_inv.get(ing_id)
                if inv_id:
                    used = (Decimal(food_qty_map[fid]) * Decimal(str(req_qty))) / Decimal(max(1, int(y_port or 1)))
                    agg[inv_id]["theoretical_used"] += used

    items = []
    for inv, ing_name in inv_rows:
        b = agg[inv.id]
        actual_consumed = b["order_deducted"] + b["wasted"] + max(Decimal("0.000"), -b["net_adjustment"])
        variance = actual_consumed - b["theoretical_used"]
        waste_ratio = round(float(b["wasted"] / actual_consumed * Decimal("100")), 1) if actual_consumed > Decimal("0") else 0.0
        items.append(
            {
                "inventory_item_id": str(inv.id),
                "ingredient_name": ing_name,
                "unit": inv.unit,
                "current_quantity": f"{inv.current_quantity:.3f}",
                "stocked_in": f"{b['stocked_in']:.3f}",
                "order_deducted": f"{b['order_deducted']:.3f}",
                "wasted": f"{b['wasted']:.3f}",
                "transferred_out": f"{b['transferred_out']:.3f}",
                "theoretical_recipe_consumption": f"{b['theoretical_used']:.3f}",
                "actual_consumed": f"{actual_consumed:.3f}",
                "variance_quantity": f"{variance:.3f}",
                "waste_share_percent": waste_ratio,
                "estimated_waste_cost": f"{(b['wasted'] * inv.unit_cost).quantize(Decimal('0.01')):.2f}",
            }
        )

    items.sort(key=lambda r: (-Decimal(r["estimated_waste_cost"]), -Decimal(r["actual_consumed"])))
    return {
        "canteen_id": str(canteen_id),
        "start_date": s_date.isoformat(),
        "end_date": e_date.isoformat(),
        "items": items,
    }


def get_waste_recommendations(db: Session, *, canteen_id: UUID, lookback_days: int = 30) -> list[dict]:
    today = today_college()
    s_date = today - timedelta(days=max(1, lookback_days) - 1)
    recommendations: list[dict] = []

    prep_rows = db.execute(
        select(DailyFoodPrepLog, FoodItem.name)
        .join(FoodItem, FoodItem.id == DailyFoodPrepLog.food_item_id)
        .where(DailyFoodPrepLog.canteen_id == canteen_id, DailyFoodPrepLog.prep_date >= s_date)
    ).all()
    sold_map = _sold_quantities_map(db, canteen_id, s_date, today)

    dish_stats: dict[UUID, dict[str, Any]] = {}
    for log, food_name in prep_rows:
        st = dish_stats.setdefault(
            log.food_item_id,
            {"name": food_name, "prepared": 0, "sold": 0, "wasted": 0, "days": set(), "cost": Decimal("0.00")},
        )
        st["prepared"] += int(log.prepared_quantity)
        st["wasted"] += int(log.unsold_wasted_quantity)
        st["days"].add(log.prep_date)
        st["cost"] += Decimal(log.unsold_wasted_quantity) * log.unit_cost
    for (fid, d), sq in sold_map.items():
        if fid in dish_stats and d in dish_stats[fid]["days"]:
            dish_stats[fid]["sold"] += int(sq)

    for fid, st in dish_stats.items():
        if st["prepared"] <= 0:
            continue
        unsold = max(0, st["prepared"] - st["sold"])
        effective_waste = max(st["wasted"], unsold)
        pct = round((effective_waste / st["prepared"]) * 100, 1)
        if pct >= 15.0:
            days_count = max(1, len(st["days"]))
            avg_sold = st["sold"] / days_count
            suggested_cap = max(1, math.ceil(avg_sold * 1.1)) if avg_sold > 0 else max(1, st["prepared"] // 2)
            recommendations.append(
                {
                    "id": f"prep-cap-{fid}",
                    "severity": "high" if pct >= 30.0 else "medium",
                    "category": "prep_optimization",
                    "title": f"Reduce daily prep batch for {st['name']}",
                    "detail": (
                        f"{pct}% of prepared {st['name']} went unsold/wasted ({effective_waste}/{st['prepared']} portions) "
                        f"over {days_count} prep day(s). Recommended daily cap: ~{suggested_cap} portions."
                    ),
                    "potential_savings": f"{st['cost']:.2f}",
                }
            )

    # Near-expiry batch overstock recommendation based on actual 14-day ingredient burn rate
    soon_cutoff = today + timedelta(days=5)
    expiring = db.execute(
        select(StockBatch, InventoryItem, Ingredient.name)
        .join(InventoryItem, InventoryItem.id == StockBatch.inventory_item_id)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(
            InventoryItem.canteen_id == canteen_id,
            InventoryItem.is_archived.is_(False),
            StockBatch.remaining_quantity > 0,
            StockBatch.expiry_date.is_not(None),
            StockBatch.expiry_date >= today,
            StockBatch.expiry_date <= soon_cutoff,
        )
    ).all()
    if expiring:
        inv_ids = list({inv.id for _, inv, _ in expiring})
        burn_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        burn_rows = db.execute(
            select(StockMovement.inventory_item_id, func.coalesce(func.sum(func.abs(StockMovement.quantity_delta)), 0))
            .where(
                StockMovement.inventory_item_id.in_(inv_ids),
                StockMovement.movement_type.in_(("order_deduct", "order_deduction")),
                StockMovement.created_at >= burn_cutoff,
            )
            .group_by(StockMovement.inventory_item_id)
        ).all()
        burn_per_day = {iid: Decimal(str(tot)) / Decimal("14") for iid, tot in burn_rows}
        for batch, inv, ing_name in expiring:
            days_left = max(1, (batch.expiry_date - today).days)
            projected = burn_per_day.get(inv.id, Decimal("0.000")) * Decimal(days_left)
            if batch.remaining_quantity > projected:
                excess = batch.remaining_quantity - projected
                risk_loss = (excess * batch.unit_cost).quantize(Decimal("0.01"))
                recommendations.append(
                    {
                        "id": f"expiry-{batch.id}",
                        "severity": "high",
                        "category": "expiry_mitigation",
                        "title": f"Prioritize {ing_name} batch {batch.batch_number} before {batch.expiry_date.isoformat()}",
                        "detail": (
                            f"{batch.remaining_quantity} {inv.unit} expires in {days_left} day(s) vs projected "
                            f"{projected:.1f} {inv.unit} usage. Feature linked dishes in today's special or transfer excess."
                        ),
                        "potential_savings": f"{risk_loss:.2f}",
                    }
                )

    # Top historical loss reasons & recurring ingredients
    analytics = get_waste_analytics(db, canteen_id=canteen_id, period="daily", start_date=s_date, end_date=today)
    for item in analytics["most_wasted_items"][:2]:
        if Decimal(item["estimated_loss"]) > Decimal("0.00"):
            recommendations.append(
                {
                    "id": f"top-loss-{item['item_name']}",
                    "severity": "medium",
                    "category": "loss_driver",
                    "title": f"Audit handling & portioning for {item['item_name']}",
                    "detail": (
                        f"Lost Rs.{item['estimated_loss']} across {item['waste_count']} event(s) "
                        f"({item['total_quantity']} {item['unit']}). Primary reason: {item['top_reason'] or 'unspecified'}."
                    ),
                    "potential_savings": item["estimated_loss"],
                }
            )

    return recommendations


def export_wastage_csv(db: Session, *, canteen_id: UUID, analytics: dict, wastage_records: list[dict]) -> str:
    canteen = db.get(Canteen, canteen_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    s = analytics["summary"]
    w.writerow(["CollegeBites Food Waste & Consumption Report"])
    w.writerow(["Canteen", canteen.name if canteen else str(canteen_id)])
    w.writerow(["Date Window", f"{analytics['start_date']} to {analytics['end_date']}"])
    w.writerow([])
    w.writerow(["FOOD WASTE KPI SUMMARY"])
    w.writerow(["Total Food Prepared (portions)", s["total_food_prepared"]])
    w.writerow(["Total Food Sold (portions)", s["total_food_sold"]])
    w.writerow(["Total Food Wasted (portions)", s["total_food_wasted"]])
    w.writerow(["Food Wastage %", f"{s['food_wastage_percent']}%"])
    w.writerow(["Ingredient Wasted Qty", s["ingredient_wasted_quantity"]])
    w.writerow(["Estimated Total Wastage Cost (INR)", s["estimated_wastage_cost"]])
    w.writerow([])
    w.writerow(["WASTE RECORDS", "Date", "Source", "Item", "Loss Type", "Qty", "Est Loss (INR)", "Reason", "Responsible Staff", "Recorded By"])
    for r in wastage_records:
        w.writerow([
            r["created_at"],
            r.get("waste_date") or "",
            r.get("source_type") or "ingredient",
            r.get("food_item_name") or r.get("ingredient_name") or "",
            r["loss_type"],
            f"{r['quantity']} {r.get('unit') or ''}".strip(),
            r["estimated_loss"],
            r["reason"],
            r.get("responsible_staff_name") or "",
            r.get("recorded_by_name") or "",
        ])
    return buf.getvalue()
