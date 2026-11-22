from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.redis_client import safe_redis
from app.core.time_utils import today_college
from app.models.auth import StaffProfile
from app.models.college import Canteen, Counter, Kitchen
from app.models.menu import FoodItem
from app.models.order import Order, PickupSlot
from app.models.staff import StaffAttendance
from app.services.audit_service import record_audit_log
from app.services.college_service import ACTIVE_CROWD_STATUSES, compute_canteen_live_status


def get_live_queue_dashboard(db: Session, canteen_id: UUID) -> dict:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")

    is_open, crowd, base_eta, active_count = compute_canteen_live_status(db, canteen)
    now = datetime.now(timezone.utc)
    fifteen_mins_ago = now - timedelta(minutes=15)

    placed_count = db.scalar(select(func.count(Order.id)).where(Order.canteen_id == canteen_id, Order.status == "PLACED")) or 0
    accepted_count = db.scalar(select(func.count(Order.id)).where(Order.canteen_id == canteen_id, Order.status == "ACCEPTED")) or 0
    preparing_count = db.scalar(select(func.count(Order.id)).where(Order.canteen_id == canteen_id, Order.status == "PREPARING")) or 0
    ready_count = db.scalar(select(func.count(Order.id)).where(Order.canteen_id == canteen_id, Order.status == "READY")) or 0
    delayed_count = db.scalar(
        select(func.count(Order.id)).where(
            Order.canteen_id == canteen_id,
            Order.status.in_(ACTIVE_CROWD_STATUSES),
            Order.delayed_minutes > 0,
        )
    ) or 0

    recent_15m = db.scalar(
        select(func.count(Order.id)).where(
            Order.canteen_id == canteen_id,
            Order.payment_status == "CONFIRMED",
            Order.created_at >= fifteen_mins_ago,
        )
    ) or 0
    orders_per_min = round(float(recent_15m) / 15.0, 2)

    # Historical average prep time from completed/ready orders
    ready_orders = db.execute(
        select(Order.confirmed_at, Order.ready_at)
        .where(Order.canteen_id == canteen_id, Order.confirmed_at.is_not(None), Order.ready_at.is_not(None))
        .order_by(Order.ready_at.desc())
        .limit(50)
    ).all()
    if ready_orders:
        durations = [max(1.0, (r_at - c_at).total_seconds() / 60.0) for c_at, r_at in ready_orders]
        avg_prep = round(sum(durations) / len(durations), 1)
    else:
        avg_prep = float(canteen.default_prep_time_minutes)

    kitchens = db.scalars(select(Kitchen).where(Kitchen.canteen_id == canteen_id, Kitchen.is_active.is_(True))).all()
    total_kitchen_cap = sum(k.max_active_orders for k in kitchens) or canteen.max_concurrent_orders
    kitchen_workload_pct = round(min(100.0, (active_count / max(1, total_kitchen_cap)) * 100.0), 1)

    counters = db.scalars(select(Counter).where(Counter.canteen_id == canteen_id, Counter.is_active.is_(True)).order_by(Counter.code)).all()
    counter_workloads = []
    for cnt in counters:
        cnt_active = db.scalar(
            select(func.count(Order.id)).where(
                Order.counter_id == cnt.id,
                Order.status.in_(("PLACED", "ACCEPTED", "PREPARING", "READY")),
            )
        ) or 0
        counter_workloads.append({
            "counter_id": str(cnt.id),
            "name": cnt.name,
            "code": cnt.code,
            "active_orders": int(cnt_active),
            "max_queue_capacity": cnt.max_queue_capacity,
            "utilization_percent": round(min(100.0, (int(cnt_active) / max(1, cnt.max_queue_capacity)) * 100.0), 1),
        })

    local_today = today_college()
    on_duty_ids = set(
        db.scalars(
            select(StaffProfile.user_id).where(
                StaffProfile.assigned_canteen_id == canteen_id, StaffProfile.is_on_duty.is_(True)
            )
        ).all()
    )
    checked_in_ids = set(
        db.scalars(
            select(StaffAttendance.staff_user_id).where(
                StaffAttendance.canteen_id == canteen_id,
                StaffAttendance.attendance_date == local_today,
                StaffAttendance.status == "present",
                StaffAttendance.check_out_at.is_(None),
            )
        ).all()
    )
    on_duty_staff = len(on_duty_ids | checked_in_ids)

    # Store live metrics snapshot in Redis for fast reads (non-blocking if Redis unavailable)
    safe_redis(
        lambda r: r.hset(
            f"cb:queue:{canteen_id}",
            mapping={
                "active": str(active_count),
                "crowd": crowd,
                "eta": str(base_eta),
                "orders_per_min": str(orders_per_min),
            },
        )
    )

    return {
        "canteen_id": str(canteen.id),
        "canteen_name": canteen.name,
        "is_open_now": is_open,
        "ordering_paused": canteen.ordering_paused,
        "pause_reason": canteen.pause_reason,
        "crowd_level": crowd,
        "active_order_count": active_count,
        "placed_count": int(placed_count),
        "accepted_count": int(accepted_count),
        "preparing_count": int(preparing_count),
        "ready_count": int(ready_count),
        "delayed_order_count": int(delayed_count),
        "orders_per_minute": orders_per_min,
        "average_prep_time_minutes": avg_prep,
        "estimated_wait_minutes": base_eta,
        "kitchen_workload_percent": kitchen_workload_pct,
        "on_duty_staff_count": int(on_duty_staff),
        "max_concurrent_orders": canteen.max_concurrent_orders,
        "auto_throttle_enabled": canteen.auto_throttle_enabled,
        "counter_workloads": counter_workloads,
    }


def estimate_prep_time(db: Session, canteen_id: UUID, item_ids: list[UUID]) -> dict:
    dash = get_live_queue_dashboard(db, canteen_id)
    canteen = db.get(Canteen, canteen_id)
    max_item_prep = canteen.default_prep_time_minutes if canteen else 5
    complexity_bonus = 0
    if item_ids:
        items = db.scalars(select(FoodItem).where(FoodItem.id.in_(item_ids))).all()
        if items:
            max_item_prep = max(i.prep_time_minutes for i in items)
            complexity_bonus = min(15, max(0, len(items) - 1) * 2)
    staff_factor = max(1, dash["on_duty_staff_count"])
    queue_penalty = int(dash["active_order_count"] / staff_factor) * 2
    peak_buffer = (
        canteen.peak_hour_buffer_minutes
        if (canteen and dash["crowd_level"] in ("HIGH", "VERY_HIGH"))
        else 0
    )
    hist_blend = round(dash["average_prep_time_minutes"]) if dash["active_order_count"] > 0 else max_item_prep
    estimated = max(
        dash["estimated_wait_minutes"],
        max(max_item_prep, hist_blend) + complexity_bonus + queue_penalty + peak_buffer,
    )
    return {
        "canteen_id": str(canteen_id),
        "crowd_level": dash["crowd_level"],
        "estimated_minutes": int(estimated),
        "active_order_count": dash["active_order_count"],
        "on_duty_staff_count": dash["on_duty_staff_count"],
        "peak_buffer_minutes": int(peak_buffer),
    }


def update_queue_controls(db: Session, canteen_id: UUID, updates: dict, actor_user_id: UUID) -> dict:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    allowed = {
        "ordering_paused",
        "pause_reason",
        "max_concurrent_orders",
        "orders_per_slot_capacity",
        "default_prep_time_minutes",
        "peak_hour_buffer_minutes",
        "crowd_moderate_threshold",
        "crowd_high_threshold",
        "crowd_very_high_threshold",
        "auto_throttle_enabled",
    }
    for k, v in updates.items():
        if k in allowed and v is not None:
            setattr(canteen, k, v)
    record_audit_log(
        db,
        action="queue.controls_updated",
        entity_type="canteen",
        entity_id=str(canteen_id),
        actor_user_id=actor_user_id,
        details={k: v for k, v in updates.items() if k in allowed and v is not None},
    )
    db.commit()
    return get_live_queue_dashboard(db, canteen_id)


def upsert_pickup_slot(
    db: Session,
    *,
    canteen_id: UUID,
    slot_date: date,
    start_time: time,
    end_time: time,
    capacity: int,
    is_active: bool = True,
) -> PickupSlot:
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="Pickup slot end_time must be after start_time")
    if is_active and slot_date < today_college():
        raise HTTPException(status_code=400, detail="Cannot create or activate a pickup slot in the past")
    slot = db.scalar(
        select(PickupSlot).where(
            PickupSlot.canteen_id == canteen_id,
            PickupSlot.slot_date == slot_date,
            PickupSlot.start_time == start_time,
        )
    )
    if slot:
        slot.end_time = end_time
        slot.capacity = capacity
        slot.is_active = is_active
    else:
        slot = PickupSlot(
            canteen_id=canteen_id,
            slot_date=slot_date,
            start_time=start_time,
            end_time=end_time,
            capacity=capacity,
            is_active=is_active,
        )
        db.add(slot)
    db.commit()
    db.refresh(slot)
    safe_redis(lambda r: r.set(f"cb:slot:{slot.id}:reserved", slot.reserved_count, ex=86400))
    return slot
