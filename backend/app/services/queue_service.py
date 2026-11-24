from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.cache import NS_QUEUE, cache_manager, invalidate_board_and_queue
from app.core.redis_client import safe_redis
from app.core.time_utils import today_college
from app.models.auth import StaffProfile, User
from app.models.college import Canteen, Counter, Kitchen
from app.models.menu import FoodItem
from app.models.order import Order, OrderItem, PickupSlot
from app.models.payment import PickupToken
from app.models.staff import StaffAttendance
from app.services.audit_service import record_audit_log
from app.services.college_service import ACTIVE_CROWD_STATUSES, compute_canteen_live_status
from app.websockets import emit_order_event_sync

ACTIVE_QUEUE_WAITING_STATUSES = ("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING")
ACTIVE_COUNTER_LOAD_STATUSES = ("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING")


def _queue_sort_key(order: Order) -> tuple:
    anchor = order.confirmed_at or order.created_at
    if anchor and anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    created = order.created_at
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (0 if order.is_priority else 1, anchor, created, str(order.id))


def _canteen_on_duty_staff_count(db: Session, canteen_id: UUID) -> int:
    cache_ns = f"{NS_QUEUE}:{canteen_id}"
    hit, cached = cache_manager.get_json(cache_ns, "on_duty_staff", l1_ttl=2.0)
    if hit and isinstance(cached, int):
        return cached
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
    count = len(on_duty_ids | checked_in_ids)
    cache_manager.set_json(cache_ns, "on_duty_staff", count, ttl_seconds=15, l1_ttl=2.0)
    return count


def _canteen_avg_prep_minutes(db: Session, canteen_id: UUID, default_prep: float = 10.0) -> float:
    cache_ns = f"{NS_QUEUE}:{canteen_id}"
    hit, cached = cache_manager.get_json(cache_ns, "avg_prep", l1_ttl=2.0)
    if hit and isinstance(cached, (int, float)):
        return float(cached)
    ready_orders = db.execute(
        select(Order.confirmed_at, Order.ready_at)
        .where(Order.canteen_id == canteen_id, Order.confirmed_at.is_not(None), Order.ready_at.is_not(None))
        .order_by(Order.ready_at.desc())
        .limit(50)
    ).all()
    if not ready_orders:
        val = float(default_prep or 10.0)
    else:
        durations = [max(1.0, (r_at - c_at).total_seconds() / 60.0) for c_at, r_at in ready_orders]
        val = round(sum(durations) / len(durations), 1)
    cache_manager.set_json(cache_ns, "avg_prep", val, ttl_seconds=15, l1_ttl=2.0)
    return val


def compute_order_queue_metrics_map(
    db: Session,
    orders: list[Order],
    *,
    precomputed_waiting_by_canteen: Optional[dict[UUID, list[Order]]] = None,
    precomputed_canteens: Optional[dict[UUID, Canteen]] = None,
    precomputed_staff_counts: Optional[dict[UUID, int]] = None,
    precomputed_avg_prep: Optional[dict[UUID, float]] = None,
) -> dict[UUID, dict]:
    """Compute real-time queue position, orders ahead, counter position, and dynamic wait from DB."""
    if not orders:
        return {}

    now = datetime.now(timezone.utc)
    waiting_canteen_ids = list({o.canteen_id for o in orders if o.status in ACTIVE_QUEUE_WAITING_STATUSES})
    if precomputed_canteens is not None:
        canteens = precomputed_canteens
    else:
        canteens = (
            {c.id: c for c in db.scalars(select(Canteen).where(Canteen.id.in_(waiting_canteen_ids))).all()}
            if waiting_canteen_ids
            else {}
        )

    waiting_by_canteen: dict[UUID, list[Order]] = {}
    if waiting_canteen_ids:
        if precomputed_waiting_by_canteen is not None:
            for cid in waiting_canteen_ids:
                waiting_by_canteen[cid] = sorted(precomputed_waiting_by_canteen.get(cid, []), key=_queue_sort_key)
        else:
            all_waiting = db.scalars(
                select(Order).where(
                    Order.canteen_id.in_(waiting_canteen_ids),
                    Order.status.in_(ACTIVE_QUEUE_WAITING_STATUSES),
                )
            ).all()
            for wo in all_waiting:
                waiting_by_canteen.setdefault(wo.canteen_id, []).append(wo)
            for cid in waiting_by_canteen:
                waiting_by_canteen[cid].sort(key=_queue_sort_key)

    pos_lookup: dict[UUID, tuple[int, int, int]] = {}
    staff_cache: dict[UUID, int] = dict(precomputed_staff_counts or {})
    avg_prep_cache: dict[UUID, float] = dict(precomputed_avg_prep or {})
    for cid, q_list in waiting_by_canteen.items():
        counter_ranks: dict[UUID, int] = {}
        for idx, wo in enumerate(q_list, start=1):
            c_pos = counter_ranks.get(wo.counter_id, 0) + 1
            counter_ranks[wo.counter_id] = c_pos
            pos_lookup[wo.id] = (idx, idx - 1, c_pos)
        if cid not in staff_cache:
            staff_cache[cid] = max(1, _canteen_on_duty_staff_count(db, cid))
        if cid not in avg_prep_cache:
            c_obj = canteens.get(cid)
            avg_prep_cache[cid] = _canteen_avg_prep_minutes(db, cid, float(c_obj.default_prep_time_minutes if c_obj else 10))

    metrics: dict[UUID, dict] = {}
    for o in orders:
        if o.status == "READY":
            metrics[o.id] = {
                "queue_position": 0,
                "orders_ahead_count": 0,
                "counter_queue_position": 0,
                "dynamic_wait_minutes": 0,
            }
            continue
        if o.status not in ACTIVE_QUEUE_WAITING_STATUSES:
            metrics[o.id] = {
                "queue_position": None,
                "orders_ahead_count": None,
                "counter_queue_position": None,
                "dynamic_wait_minutes": 0 if o.status == "COMPLETED" else None,
            }
            continue

        q_pos, ahead_total, cnt_pos = pos_lookup.get(o.id, (1, 0, 1))
        cnt_ahead = max(0, cnt_pos - 1)
        staff_cnt = staff_cache.get(o.canteen_id, 1)
        avg_prep = avg_prep_cache.get(o.canteen_id, float(o.estimated_prep_minutes or 10))

        base_target = max(1, int(o.estimated_prep_minutes or 10) + int(o.delayed_minutes or 0))
        if o.status == "PREPARING" and o.preparing_at:
            prep_at = o.preparing_at if o.preparing_at.tzinfo else o.preparing_at.replace(tzinfo=timezone.utc)
            elapsed_prep = max(0.0, (now - prep_at).total_seconds() / 60.0)
            self_rem = max(1, round(base_target - elapsed_prep))
        else:
            self_rem = base_target

        per_order_factor = max(1.0, min(6.0, avg_prep / max(1, staff_cnt)))
        queue_delay = max(cnt_ahead, round(cnt_ahead * per_order_factor)) if cnt_ahead > 0 else 0
        dynamic_wait = max(1, int(self_rem + queue_delay))

        metrics[o.id] = {
            "queue_position": q_pos,
            "orders_ahead_count": ahead_total,
            "counter_queue_position": cnt_pos,
            "dynamic_wait_minutes": dynamic_wait,
        }
    return metrics


def select_optimal_counter(
    db: Session,
    *,
    canteen_id: UUID,
    explicit_counter_id: Optional[UUID] = None,
    food_preferred_counter_id: Optional[UUID] = None,
    is_express_eligible: bool = False,
) -> tuple[UUID, str]:
    """
    Dynamically route incoming orders across active canteen counters using live queue capacity
    and express-lane rules while respecting explicitly scanned counter QRs.
    """
    if explicit_counter_id:
        cnt = db.get(Counter, explicit_counter_id)
        if not cnt or cnt.canteen_id != canteen_id or not cnt.is_active:
            raise HTTPException(status_code=400, detail="Invalid pickup counter")
        return cnt.id, "explicit"

    counters = db.scalars(
        select(Counter).where(Counter.canteen_id == canteen_id, Counter.is_active.is_(True)).order_by(Counter.code.asc())
    ).all()
    if not counters:
        raise HTTPException(status_code=400, detail="No active pickup counter configured for this canteen")
    if len(counters) == 1:
        return counters[0].id, "single_counter"

    load_rows = db.execute(
        select(Order.counter_id, func.count(Order.id))
        .where(
            Order.canteen_id == canteen_id,
            Order.status.in_(ACTIVE_COUNTER_LOAD_STATUSES),
        )
        .group_by(Order.counter_id)
    ).all()
    loads = {cid: int(cnt or 0) for cid, cnt in load_rows}

    def _score(c: Counter) -> tuple[float, int, str]:
        active = loads.get(c.id, 0)
        cap = max(1, int(c.max_queue_capacity or 25))
        return (active / cap, active, c.code)

    if is_express_eligible:
        express_candidates = [
            c for c in counters if c.counter_type == "express" and loads.get(c.id, 0) < max(1, c.max_queue_capacity)
        ]
        if express_candidates:
            chosen = min(express_candidates, key=_score)
            return chosen.id, "express_lane"

    standard_with_cap = [
        c for c in counters if c.counter_type != "express" and loads.get(c.id, 0) < max(1, c.max_queue_capacity)
    ]
    pool = standard_with_cap or [c for c in counters if loads.get(c.id, 0) < max(1, c.max_queue_capacity)] or list(counters)

    min_active = min(loads.get(c.id, 0) for c in pool)
    if food_preferred_counter_id:
        pref = next((c for c in pool if c.id == food_preferred_counter_id), None)
        if pref:
            pref_active = loads.get(pref.id, 0)
            pref_cap = max(1, pref.max_queue_capacity)
            # Only stick to item's default counter if it isn't skewed or near capacity
            if (pref_active / pref_cap) < 0.8 and pref_active <= (min_active + 1):
                return pref.id, "food_default"

    chosen = min(pool, key=_score)
    return chosen.id, "load_balanced"


def assign_order_counter(
    db: Session,
    *,
    order_id: UUID,
    counter_id: UUID,
    actor_user_id: UUID,
) -> dict:
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status in ("COMPLETED", "CANCELLED", "REJECTED"):
        raise HTTPException(status_code=409, detail=f"Cannot reassign counter for order in status {order.status}")

    counter = db.get(Counter, counter_id)
    if not counter or counter.canteen_id != order.canteen_id or not counter.is_active:
        raise HTTPException(status_code=400, detail="Target counter is invalid or inactive for this canteen")

    old_counter = db.get(Counter, order.counter_id)
    order.counter_id = counter.id
    token_row = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id).with_for_update())
    if token_row:
        token_row.counter_id = counter.id

    record_audit_log(
        db,
        action="queue.counter_reassigned",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=actor_user_id,
        details={
            "from_counter_id": str(old_counter.id) if old_counter else None,
            "from_counter_name": old_counter.name if old_counter else None,
            "to_counter_id": str(counter.id),
            "to_counter_name": counter.name,
        },
    )
    db.commit()
    emit_order_event_sync(
        str(order.canteen_id),
        str(order.id),
        "queue.counter_reassigned",
        {"counter_id": str(counter.id), "counter_name": counter.name},
    )
    return get_live_queue_dashboard(db, order.canteen_id)


def escalate_overdue_orders(
    db: Session,
    *,
    canteen_id: UUID,
    actor_user_id: UUID,
) -> dict:
    canteen = db.get(Canteen, canteen_id)
    if not canteen or not canteen.is_active:
        raise HTTPException(status_code=404, detail="Canteen not found")

    now = datetime.now(timezone.utc)
    candidates = db.scalars(
        select(Order)
        .where(
            Order.canteen_id == canteen_id,
            Order.status.in_(ACTIVE_QUEUE_WAITING_STATUSES),
            Order.is_priority.is_(False),
        )
        .with_for_update()
    ).all()

    escalated_numbers: list[str] = []
    for o in candidates:
        anchor = o.confirmed_at or o.created_at
        if anchor and anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        elapsed_mins = (now - anchor).total_seconds() / 60.0
        sla_mins = int(o.estimated_prep_minutes or 12) + int(o.delayed_minutes or 0)
        if elapsed_mins > sla_mins:
            o.is_priority = True
            if not o.delay_reason:
                o.delay_reason = "Auto-escalated due to wait exceeding estimated prep window"
            escalated_numbers.append(o.order_number)

    if escalated_numbers:
        record_audit_log(
            db,
            action="queue.overdue_escalated",
            entity_type="canteen",
            entity_id=str(canteen_id),
            actor_user_id=actor_user_id,
            details={"escalated_order_numbers": escalated_numbers},
        )
        db.commit()
        emit_order_event_sync(
            str(canteen_id),
            "queue",
            "queue.escalated",
            {"escalated_count": len(escalated_numbers), "order_numbers": escalated_numbers},
        )

    return {
        "escalated_count": len(escalated_numbers),
        "escalated_order_numbers": escalated_numbers,
        "dashboard": get_live_queue_dashboard(db, canteen_id),
    }


def get_live_queue_dashboard(db: Session, canteen_id: UUID) -> dict:
    cache_ns = f"{NS_QUEUE}:{canteen_id}"
    hit, cached = cache_manager.get_json(cache_ns, "dashboard", l1_ttl=1.0)
    if hit and isinstance(cached, dict):
        return cached

    canteen = db.get(Canteen, canteen_id)
    if not canteen or not canteen.is_active:
        raise HTTPException(status_code=404, detail="Canteen not found")

    now = datetime.now(timezone.utc)
    fifteen_mins_ago = now - timedelta(minutes=15)

    # Fetch live non-completed orders once and derive all queue/status/delay counts in memory
    all_live_orders = list(
        db.scalars(
            select(Order).where(
                Order.canteen_id == canteen_id,
                Order.status.in_(("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING", "READY")),
            )
        ).all()
    )
    placed_count = sum(1 for o in all_live_orders if o.status == "PLACED")
    accepted_count = sum(1 for o in all_live_orders if o.status == "ACCEPTED")
    preparing_count = sum(1 for o in all_live_orders if o.status == "PREPARING")
    ready_count = sum(1 for o in all_live_orders if o.status == "READY")
    waiting_orders = [o for o in all_live_orders if o.status in ACTIVE_CROWD_STATUSES]
    active_count_pre = len(waiting_orders)
    delayed_count = sum(1 for o in waiting_orders if (o.delayed_minutes or 0) > 0)

    is_open, crowd, base_eta, active_count = compute_canteen_live_status(
        db, canteen, precomputed_active_count=active_count_pre
    )

    recent_15m = db.scalar(
        select(func.count(Order.id)).where(
            Order.canteen_id == canteen_id,
            Order.payment_status == "CONFIRMED",
            Order.created_at >= fifteen_mins_ago,
        )
    ) or 0
    orders_per_min = round(float(recent_15m) / 15.0, 2)
    avg_prep = _canteen_avg_prep_minutes(db, canteen_id, float(canteen.default_prep_time_minutes))
    on_duty_staff = _canteen_on_duty_staff_count(db, canteen_id)

    kitchens = db.scalars(select(Kitchen).where(Kitchen.canteen_id == canteen_id, Kitchen.is_active.is_(True))).all()
    total_kitchen_cap = sum(k.max_active_orders for k in kitchens) or canteen.max_concurrent_orders
    kitchen_workload_pct = round(min(100.0, (active_count / max(1, total_kitchen_cap)) * 100.0), 1)

    counters = db.scalars(select(Counter).where(Counter.canteen_id == canteen_id, Counter.is_active.is_(True)).order_by(Counter.code)).all()
    counter_map = {c.id: c for c in counters}

    active_orders = [o for o in all_live_orders if o.status in ("PLACED", "ACCEPTED", "PREPARING", "READY")]
    active_orders.sort(
        key=lambda o: (
            1 if o.status == "READY" else 0,
            0 if o.is_priority else 1,
            (o.confirmed_at or o.created_at).replace(tzinfo=timezone.utc) if (o.confirmed_at or o.created_at).tzinfo is None else (o.confirmed_at or o.created_at),
            str(o.id),
        )
    )
    metrics_map = compute_order_queue_metrics_map(
        db,
        active_orders,
        precomputed_waiting_by_canteen={canteen_id: waiting_orders},
        precomputed_canteens={canteen_id: canteen},
        precomputed_staff_counts={canteen_id: max(1, on_duty_staff)},
        precomputed_avg_prep={canteen_id: avg_prep},
    )

    active_order_ids = [o.id for o in active_orders]
    token_map = (
        {t.order_id: t.token_code for t in db.scalars(select(PickupToken).where(PickupToken.order_id.in_(active_order_ids))).all()}
        if active_order_ids
        else {}
    )
    cust_ids = list({o.customer_id for o in active_orders if o.customer_id is not None})
    user_names = (
        {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(cust_ids))).all()}
        if cust_ids
        else {}
    )
    item_counts: dict[UUID, int] = {}
    if active_order_ids:
        for oid, q_sum in db.execute(
            select(OrderItem.order_id, func.coalesce(func.sum(OrderItem.quantity), 0))
            .where(OrderItem.order_id.in_(active_order_ids))
            .group_by(OrderItem.order_id)
        ).all():
            item_counts[oid] = int(q_sum or 0)

    active_orders_queue = []
    delayed_orders = []
    waiting_waits: list[int] = []
    counter_waiting_counts: dict[UUID, int] = {}
    counter_ready_counts: dict[UUID, int] = {}

    for o in active_orders:
        m = metrics_map.get(o.id, {})
        if o.status == "READY":
            counter_ready_counts[o.counter_id] = counter_ready_counts.get(o.counter_id, 0) + 1
        elif o.status in ACTIVE_QUEUE_WAITING_STATUSES:
            counter_waiting_counts[o.counter_id] = counter_waiting_counts.get(o.counter_id, 0) + 1
            if m.get("dynamic_wait_minutes") is not None:
                waiting_waits.append(int(m["dynamic_wait_minutes"]))

        anchor = o.confirmed_at or o.created_at
        if anchor and anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        elapsed_mins = round(max(0.0, (now - anchor).total_seconds() / 60.0), 1)
        sla_mins = int(o.estimated_prep_minutes or 12) + int(o.delayed_minutes or 0)
        is_overdue = (o.status != "READY") and (elapsed_mins > sla_mins)
        cnt_obj = counter_map.get(o.counter_id)
        cust_label = user_names.get(o.customer_id) or (o.guest_name.strip() if o.guest_name else None) or "Walk-in / Guest"

        entry = {
            "order_id": str(o.id),
            "order_number": o.order_number,
            "token_code": token_map.get(o.id),
            "status": o.status,
            "counter_id": str(o.counter_id),
            "counter_name": cnt_obj.name if cnt_obj else "Counter",
            "counter_type": cnt_obj.counter_type if cnt_obj else "pickup",
            "customer_name": cust_label,
            "is_priority": bool(o.is_priority),
            "queue_position": m.get("queue_position"),
            "orders_ahead_count": m.get("orders_ahead_count"),
            "counter_queue_position": m.get("counter_queue_position"),
            "dynamic_wait_minutes": m.get("dynamic_wait_minutes"),
            "elapsed_minutes": elapsed_mins,
            "estimated_prep_minutes": int(o.estimated_prep_minutes or 12),
            "delayed_minutes": int(o.delayed_minutes or 0),
            "delay_reason": o.delay_reason,
            "is_overdue": is_overdue,
            "item_count": item_counts.get(o.id, 0),
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "confirmed_at": o.confirmed_at.isoformat() if o.confirmed_at else None,
        }
        active_orders_queue.append(entry)
        if o.delayed_minutes > 0 or is_overdue:
            delayed_orders.append(entry)

    counter_workloads = []
    for cnt in counters:
        waiting_cnt = counter_waiting_counts.get(cnt.id, 0)
        ready_cnt = counter_ready_counts.get(cnt.id, 0)
        cnt_total_active = waiting_cnt + ready_cnt
        cap = max(1, cnt.max_queue_capacity)
        util = round(min(100.0, (waiting_cnt / cap) * 100.0), 1)
        counter_workloads.append({
            "counter_id": str(cnt.id),
            "name": cnt.name,
            "code": cnt.code,
            "counter_type": cnt.counter_type,
            "waiting_orders": waiting_cnt,
            "ready_orders": ready_cnt,
            "active_orders": int(cnt_total_active),
            "max_queue_capacity": cnt.max_queue_capacity,
            "utilization_percent": util,
            "is_overloaded": waiting_cnt >= cnt.max_queue_capacity,
        })

    avg_wait_minutes = round(sum(waiting_waits) / len(waiting_waits), 1) if waiting_waits else float(base_eta)
    waiting_available = bool(is_open and not canteen.ordering_paused)
    waiting_msg = None if waiting_available else "Waiting time currently unavailable."

    result = {
        "canteen_id": str(canteen.id),
        "canteen_name": canteen.name,
        "is_open_now": is_open,
        "ordering_paused": canteen.ordering_paused,
        "pause_reason": canteen.pause_reason,
        "crowd_level": crowd,
        "data_classification": "estimated",
        "last_updated_at": now.isoformat(),
        "waiting_time_available": waiting_available,
        "waiting_time_message": waiting_msg,
        "active_order_count": active_count,
        "waiting_prep_count": int(placed_count + accepted_count),
        "placed_count": int(placed_count),
        "accepted_count": int(accepted_count),
        "preparing_count": int(preparing_count),
        "ready_count": int(ready_count),
        "delayed_order_count": max(int(delayed_count), len(delayed_orders)),
        "orders_per_minute": orders_per_min,
        "average_prep_time_minutes": avg_prep,
        "average_wait_minutes": avg_wait_minutes if waiting_available else None,
        "estimated_wait_minutes": base_eta if waiting_available else None,
        "kitchen_workload_percent": kitchen_workload_pct,
        "on_duty_staff_count": int(on_duty_staff),
        "max_concurrent_orders": canteen.max_concurrent_orders,
        "auto_throttle_enabled": canteen.auto_throttle_enabled,
        "counter_workloads": counter_workloads,
        "active_orders_queue": active_orders_queue,
        "delayed_orders": delayed_orders,
    }
    cache_manager.set_json(cache_ns, "dashboard", result, ttl_seconds=3, l1_ttl=1.0)
    return result


def estimate_prep_time(db: Session, canteen_id: UUID, item_ids: list[UUID]) -> dict:
    dash = get_live_queue_dashboard(db, canteen_id)
    canteen = db.get(Canteen, canteen_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    if not dash.get("waiting_time_available", True):
        return {
            "canteen_id": str(canteen_id),
            "crowd_level": dash["crowd_level"],
            "data_classification": "estimated",
            "waiting_time_available": False,
            "waiting_time_message": "Waiting time currently unavailable.",
            "estimated_minutes": None,
            "active_order_count": dash["active_order_count"],
            "on_duty_staff_count": dash["on_duty_staff_count"],
            "peak_buffer_minutes": 0,
            "last_updated_at": now_iso,
        }
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
    base_est = dash["estimated_wait_minutes"] or max_item_prep
    estimated = max(
        base_est,
        max(max_item_prep, hist_blend) + complexity_bonus + queue_penalty + peak_buffer,
    )
    return {
        "canteen_id": str(canteen_id),
        "crowd_level": dash["crowd_level"],
        "data_classification": "estimated",
        "waiting_time_available": True,
        "waiting_time_message": None,
        "estimated_minutes": int(estimated),
        "active_order_count": dash["active_order_count"],
        "on_duty_staff_count": dash["on_duty_staff_count"],
        "peak_buffer_minutes": int(peak_buffer),
        "last_updated_at": now_iso,
    }


def record_queue_estimate_for_order(db: Session, order: Order) -> None:
    """Persist initial wait estimate when an order is confirmed for accuracy auditing (never alters Order timestamps)."""
    from app.models.enterprise import QueueEstimateHistory

    existing = db.scalar(select(QueueEstimateHistory.id).where(QueueEstimateHistory.order_id == order.id))
    if existing:
        return
    canteen = db.get(Canteen, order.canteen_id)
    metrics = compute_order_queue_metrics_map(db, [order]).get(order.id, {})
    on_duty = _canteen_on_duty_staff_count(db, order.canteen_id)
    active_cnt = int(
        db.scalar(
            select(func.count(Order.id)).where(
                Order.canteen_id == order.canteen_id,
                Order.status.in_(ACTIVE_QUEUE_WAITING_STATUSES),
            )
        )
        or 0
    )
    est_wait = int(metrics.get("dynamic_wait_minutes") or order.estimated_prep_minutes or 10)
    db.add(
        QueueEstimateHistory(
            canteen_id=order.canteen_id,
            counter_id=order.counter_id,
            order_id=order.id,
            estimated_wait_minutes=est_wait,
            estimated_prep_minutes=int(order.estimated_prep_minutes or 10),
            queue_position_at_creation=int(metrics.get("queue_position") or 1),
            active_orders_at_creation=active_cnt,
            on_duty_staff_at_creation=max(1, on_duty),
            estimated_at=datetime.now(timezone.utc),
            data_classification="estimated",
        )
    )
    if canteen:
        _is_open, crowd, base_eta, _act = compute_canteen_live_status(db, canteen, precomputed_active_count=active_cnt)
        if crowd in ("HIGH", "VERY_HIGH"):
            try:
                from app.services.notification_service import notify_queue_congestion

                notify_queue_congestion(
                    db,
                    canteen_id=canteen.id,
                    canteen_name=canteen.name,
                    crowd_level=crowd,
                    active_orders=active_cnt,
                    est_wait_minutes=int(base_eta or est_wait),
                )
            except Exception:
                pass


def finalize_queue_estimate_for_order(db: Session, order: Order) -> None:
    """Record actual wait & prep duration when order becomes READY without altering historical Order timestamps."""
    from app.models.enterprise import QueueEstimateHistory

    row = db.scalar(select(QueueEstimateHistory).where(QueueEstimateHistory.order_id == order.id))
    if not row:
        return
    ready_at = order.ready_at or datetime.now(timezone.utc)
    if ready_at.tzinfo is None:
        ready_at = ready_at.replace(tzinfo=timezone.utc)
    est_at = row.estimated_at
    if est_at and est_at.tzinfo is None:
        est_at = est_at.replace(tzinfo=timezone.utc)
    confirm_anchor = order.confirmed_at or est_at or order.created_at
    if confirm_anchor and confirm_anchor.tzinfo is None:
        confirm_anchor = confirm_anchor.replace(tzinfo=timezone.utc)
    actual_wait = max(0.0, (ready_at - confirm_anchor).total_seconds() / 60.0)
    prep_anchor = order.preparing_at or confirm_anchor
    if prep_anchor and prep_anchor.tzinfo is None:
        prep_anchor = prep_anchor.replace(tzinfo=timezone.utc)
    actual_prep = max(0.0, (ready_at - prep_anchor).total_seconds() / 60.0)
    row.actual_ready_at = ready_at
    row.actual_wait_minutes = round(actual_wait, 2)
    row.actual_prep_minutes = round(actual_prep, 2)
    row.absolute_error_minutes = round(abs(float(row.estimated_wait_minutes) - actual_wait), 2)


def get_queue_accuracy_metrics(db: Session, canteen_id: UUID, days: int = 30) -> dict:
    """Compute real queue estimate vs actual ready-time error metrics from QueueEstimateHistory (zero fabrication)."""
    from app.models.enterprise import QueueEstimateHistory

    canteen = db.get(Canteen, canteen_id)
    if not canteen or not canteen.is_active:
        raise HTTPException(status_code=404, detail="Canteen not found")
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    rows = db.scalars(
        select(QueueEstimateHistory)
        .join(Order, Order.id == QueueEstimateHistory.order_id)
        .where(
            QueueEstimateHistory.canteen_id == canteen_id,
            QueueEstimateHistory.estimated_at >= since,
            QueueEstimateHistory.actual_wait_minutes.is_not(None),
            Order.status.in_(("READY", "COMPLETED")),
        )
        .order_by(QueueEstimateHistory.estimated_at.desc())
        .limit(1000)
    ).all()
    if not rows:
        return {
            "canteen_id": str(canteen_id),
            "canteen_name": canteen.name,
            "lookback_days": days,
            "sample_count": 0,
            "data_classification": "calculated",
            "status": "insufficient_data",
            "message": "Insufficient historical data to evaluate queue prediction accuracy.",
            "mae_minutes": None,
            "median_error_minutes": None,
            "within_5_min_percent": None,
            "average_estimated_minutes": None,
            "average_actual_minutes": None,
            "recent_samples": [],
        }

    errors = sorted(float(r.absolute_error_minutes or 0.0) for r in rows)
    n = len(errors)
    mae = round(sum(errors) / n, 2)
    median = round(errors[n // 2] if n % 2 == 1 else (errors[n // 2 - 1] + errors[n // 2]) / 2.0, 2)
    within_5 = round((sum(1 for e in errors if e <= 5.0) / n) * 100.0, 1)
    avg_est = round(sum(float(r.estimated_wait_minutes) for r in rows) / n, 2)
    avg_act = round(sum(float(r.actual_wait_minutes or 0.0) for r in rows) / n, 2)
    return {
        "canteen_id": str(canteen_id),
        "canteen_name": canteen.name,
        "lookback_days": days,
        "sample_count": n,
        "data_classification": "calculated",
        "status": "ok",
        "message": None,
        "mae_minutes": mae,
        "median_error_minutes": median,
        "within_5_min_percent": within_5,
        "average_estimated_minutes": avg_est,
        "average_actual_minutes": avg_act,
        "recent_samples": [
            {
                "order_id": str(r.order_id),
                "estimated_wait_minutes": r.estimated_wait_minutes,
                "actual_wait_minutes": float(r.actual_wait_minutes),
                "absolute_error_minutes": float(r.absolute_error_minutes),
                "queue_position": r.queue_position_at_creation,
                "estimated_at": r.estimated_at.isoformat() if r.estimated_at else None,
                "ready_at": r.actual_ready_at.isoformat() if r.actual_ready_at else None,
            }
            for r in rows[:25]
        ],
    }


def update_queue_controls(db: Session, canteen_id: UUID, updates: dict, actor_user_id: UUID) -> dict:
    canteen = db.get(Canteen, canteen_id)
    if not canteen or not canteen.is_active:
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
    invalidate_board_and_queue(canteen_id)
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
