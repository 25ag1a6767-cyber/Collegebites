import csv
import io
import statistics
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.cache import NS_MENU, cache_manager, invalidate_board_and_queue
from app.core.time_utils import now_college, today_college
from app.models.auth import User
from app.models.campus_ops import (
    AcademicTimetableSlot,
    CrowdActivitySnapshot,
    MenuAvailabilityEvent,
    OrderTrayVerification,
    SeatingOccupancyLog,
    SeatingZone,
)
from app.models.college import Canteen, CollegeHoliday, Counter, DiningTable, KitchenStation, OperatingHour
from app.models.enterprise import QueueEstimateHistory
from app.models.event import CollegeEvent
from app.models.inventory import InventoryItem
from app.models.menu import FoodCategory, FoodItem, Recipe, RecipeIngredient
from app.models.order import Order, OrderItem
from app.models.system import AuditLog
from app.services import college_service, notification_service, order_service, queue_service
from app.services.audit_service import record_audit_log
from app.services.menu_service import compute_schedule_availability_map

ACTIVE_WAITING_STATUSES = ("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED")
ACTIVE_PREPARING_STATUSES = ("PREPARING",)
ACTIVE_READY_STATUSES = ("READY",)
ALL_LIVE_STATUSES = ACTIVE_WAITING_STATUSES + ACTIVE_PREPARING_STATUSES + ACTIVE_READY_STATUSES

MAX_TIMETABLE_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_TIMETABLE_ROWS = 2000


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _activity_level_from_workload(workload_pct: int, active_orders: int, canteen: Canteen) -> str:
    if active_orders >= int(canteen.crowd_high_threshold or 30) or workload_pct >= 70:
        return "busy"
    if active_orders >= int(canteen.crowd_moderate_threshold or 15) or workload_pct >= 35:
        return "moderate"
    return "low"


# =============================================================================
# FEATURE 1: LIVE CAFETERIA CROWD INTELLIGENCE (TWO-COUNTER STRUCTURE)
# =============================================================================


def get_live_crowd_intelligence(db: Session, *, days: int = 7) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    lookback_days = max(1, min(int(days or 7), 60))
    since = now - timedelta(days=lookback_days)

    canteens = list(
        db.scalars(select(Canteen).where(Canteen.is_active.is_(True)).order_by(Canteen.code.asc())).all()
    )
    counters_out: list[dict[str, Any]] = []

    for idx, canteen in enumerate(canteens, start=1):
        live_rows = db.execute(
            select(Order.status, func.count(Order.id))
            .where(Order.canteen_id == canteen.id, Order.status.in_(ALL_LIVE_STATUSES))
            .group_by(Order.status)
        ).all()
        counts = {st: int(cnt or 0) for st, cnt in live_rows}
        waiting = sum(counts.get(s, 0) for s in ACTIVE_WAITING_STATUSES)
        preparing = sum(counts.get(s, 0) for s in ACTIVE_PREPARING_STATUSES)
        ready = sum(counts.get(s, 0) for s in ACTIVE_READY_STATUSES)
        active_total = waiting + preparing + ready
        cap = max(1, int(canteen.max_concurrent_orders or 50))
        workload_pct = min(100, round((active_total / cap) * 100))
        activity_level = _activity_level_from_workload(workload_pct, active_total, canteen)
        is_open, crowd_code, est_wait, _ = college_service.compute_canteen_live_status(
            db, canteen, precomputed_active_count=waiting + preparing
        )

        # Historical hourly order activity from actual orders
        hist_orders = db.scalars(
            select(Order.created_at).where(
                Order.canteen_id == canteen.id,
                Order.created_at >= since,
                Order.status.notin_(("PAYMENT_FAILED", "CANCELLED")),
            )
        ).all()
        hourly_counts: dict[int, int] = {h: 0 for h in range(7, 22)}
        for ts in hist_orders:
            local_ts = _as_utc(ts)
            if local_ts:
                # Approximate IST (+5:30) or college tz via now_college offset
                col_offset = now_college().utcoffset() or timedelta(0)
                hr = (local_ts + col_offset).hour
                if hr in hourly_counts:
                    hourly_counts[hr] += 1

        total_hist = sum(hourly_counts.values())
        hourly_trends = [
            {
                "hour": h,
                "label": f"{h:02d}:00",
                "total_orders": hourly_counts[h],
                "avg_orders_per_day": round(hourly_counts[h] / lookback_days, 2),
            }
            for h in range(7, 22)
        ]
        sorted_peaks = sorted(hourly_trends, key=lambda x: x["total_orders"], reverse=True)
        peak_periods = [p for p in sorted_peaks[:3] if p["total_orders"] > 0]

        snapshots = list(
            db.scalars(
                select(CrowdActivitySnapshot)
                .where(CrowdActivitySnapshot.canteen_id == canteen.id, CrowdActivitySnapshot.captured_at >= since)
                .order_by(CrowdActivitySnapshot.captured_at.desc())
                .limit(24)
            ).all()
        )

        counters_out.append(
            {
                "counter_slot": f"Counter {idx}",
                "canteen_id": str(canteen.id),
                "canteen_name": canteen.name,
                "slug": canteen.slug,
                "location": canteen.location,
                "is_open_now": is_open,
                "ordering_paused": canteen.ordering_paused,
                "active_orders": active_total,
                "waiting_orders": waiting,
                "preparing_orders": preparing,
                "ready_orders": ready,
                "max_concurrent_capacity": cap,
                "workload_percent": workload_pct,
                "activity_level": activity_level,
                "crowd_level": crowd_code,
                "estimated_wait_minutes": est_wait if is_open and not canteen.ordering_paused else None,
                "data_source": "order_based_estimate",
                "data_label": "Order-Based Activity Estimate",
                "physical_occupancy_sensors_available": False,
                "historical_orders_analyzed": total_hist,
                "peak_periods": peak_periods,
                "hourly_trends": hourly_trends,
                "recent_snapshots": [
                    {
                        "captured_at": s.captured_at.isoformat(),
                        "active_orders": s.active_orders,
                        "workload_percent": s.workload_percent,
                        "activity_level": s.activity_level,
                        "source_type": s.source_type,
                    }
                    for s in reversed(snapshots)
                ],
                "last_updated_at": now.isoformat(),
            }
        )

    lower_counter = None
    open_counters = [c for c in counters_out if c["is_open_now"] and not c["ordering_paused"]]
    if open_counters:
        best = min(open_counters, key=lambda c: (c["workload_percent"], c["active_orders"]))
        lower_counter = {
            "counter_slot": best["counter_slot"],
            "canteen_id": best["canteen_id"],
            "canteen_name": best["canteen_name"],
            "workload_percent": best["workload_percent"],
            "active_orders": best["active_orders"],
        }

    return {
        "counters_count": len(counters_out),
        "counters": counters_out,
        "recommended_lower_workload_counter": lower_counter,
        "lookback_days": lookback_days,
        "data_source": "order_based_estimate",
        "physical_occupancy_sensors_available": False,
        "disclaimer": (
            "Activity indicators are calculated from real active CollegeBites orders and queue records. "
            "Physical occupancy sensors are unavailable; order counts do not represent an exact physical headcount."
        ),
        "last_updated_at": now.isoformat(),
    }


def capture_crowd_snapshots(db: Session, *, actor_user_id: Optional[UUID] = None) -> list[dict[str, Any]]:
    live = get_live_crowd_intelligence(db, days=7)
    now = datetime.now(timezone.utc)
    created: list[dict[str, Any]] = []
    for c in live["counters"]:
        snap = CrowdActivitySnapshot(
            canteen_id=UUID(c["canteen_id"]),
            captured_at=now,
            active_orders=c["active_orders"],
            waiting_orders=c["waiting_orders"],
            preparing_orders=c["preparing_orders"],
            ready_orders=c["ready_orders"],
            workload_percent=c["workload_percent"],
            activity_level=c["activity_level"],
            source_type="order_based_estimate",
        )
        db.add(snap)
        created.append(
            {
                "canteen_id": c["canteen_id"],
                "canteen_name": c["canteen_name"],
                "active_orders": c["active_orders"],
                "workload_percent": c["workload_percent"],
                "activity_level": c["activity_level"],
                "captured_at": now.isoformat(),
            }
        )
    if actor_user_id:
        record_audit_log(
            db,
            action="campus_intelligence.crowd_snapshot_captured",
            entity_type="crowd_activity_snapshot",
            entity_id="all",
            actor_user_id=actor_user_id,
            details={"count": len(created)},
        )
    db.commit()
    return created


# =============================================================================
# FEATURE 2: AI SMART PICKUP TIME PREDICTION (STATISTICAL + CONDITIONAL ML)
# =============================================================================


def get_smart_pickup_prediction(
    db: Session,
    canteen_id: UUID,
    *,
    food_item_ids: Optional[list[UUID]] = None,
    order_id: Optional[UUID] = None,
) -> dict[str, Any]:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")

    now = datetime.now(timezone.utc)
    now_loc = now_college()
    order_obj = db.get(Order, order_id) if order_id else None

    active_orders = list(
        db.scalars(
            select(Order).where(
                Order.canteen_id == canteen_id,
                Order.status.in_(ACTIVE_WAITING_STATUSES + ACTIVE_PREPARING_STATUSES),
            )
        ).all()
    )
    pending_count = len(active_orders)
    preparing_count = sum(1 for o in active_orders if o.status == "PREPARING")
    staff_on_duty = max(1, queue_service._canteen_on_duty_staff_count(db, canteen_id))
    active_stations = int(
        db.scalar(
            select(func.count(KitchenStation.id))
            .join(Canteen, Canteen.id == canteen_id)
            .where(KitchenStation.is_active.is_(True))
        )
        or 0
    )
    active_counters = int(
        db.scalar(select(func.count(Counter.id)).where(Counter.canteen_id == canteen_id, Counter.is_active.is_(True)))
        or 1
    )

    # Item-specific prep time
    item_prep_mins = float(canteen.default_prep_time_minutes or 12)
    item_count = 1
    if order_obj:
        o_items = list(db.scalars(select(OrderItem).where(OrderItem.order_id == order_obj.id)).all())
        if o_items:
            item_count = max(1, sum(int(i.quantity or 1) for i in o_items))
            f_ids = [i.food_item_id for i in o_items if i.food_item_id]
            if f_ids:
                preps = [
                    int(p)
                    for p in db.scalars(select(FoodItem.prep_time_minutes).where(FoodItem.id.in_(f_ids))).all()
                    if p
                ]
                if preps:
                    item_prep_mins = float(max(preps))
    elif food_item_ids:
        preps = [
            int(p)
            for p in db.scalars(
                select(FoodItem.prep_time_minutes).where(
                    FoodItem.id.in_(food_item_ids), FoodItem.canteen_id == canteen_id
                )
            ).all()
            if p
        ]
        if preps:
            item_prep_mins = float(max(preps))
            item_count = len(food_item_ids)

    # Real historical actual prep durations (confirmed_at -> ready_at)
    since_60d = now - timedelta(days=60)
    hist_rows = db.execute(
        select(Order.confirmed_at, Order.ready_at, Order.estimated_prep_minutes, Order.delayed_minutes)
        .where(
            Order.canteen_id == canteen_id,
            Order.confirmed_at.is_not(None),
            Order.ready_at.is_not(None),
            Order.ready_at >= since_60d,
        )
        .order_by(Order.ready_at.asc())
        .limit(500)
    ).all()

    durations: list[float] = []
    features_x: list[list[float]] = []
    targets_y: list[float] = []
    for c_at, r_at, est_p, del_m in hist_rows:
        c_u, r_u = _as_utc(c_at), _as_utc(r_at)
        if not c_u or not r_u or r_u <= c_u:
            continue
        dur = min(120.0, max(1.0, (r_u - c_u).total_seconds() / 60.0))
        durations.append(dur)
        features_x.append([float(c_u.hour), float(c_u.weekday()), float(est_p or 10), float(del_m or 0)])
        targets_y.append(dur)

    sample_count = len(durations)
    is_open, crowd_level, _, _ = college_service.compute_canteen_live_status(
        db, canteen, precomputed_active_count=pending_count
    )
    available_now = bool(is_open and not canteen.ordering_paused and crowd_level != "TEMPORARILY_UNAVAILABLE")

    parallel_capacity = max(1, staff_on_duty + max(0, active_counters - 1) + min(2, active_stations // 2))
    median_hist = statistics.median(durations) if durations else item_prep_mins
    queue_factor = max(1.0, min(6.0, median_hist / parallel_capacity))
    stat_estimate = max(1.0, round(max(item_prep_mins, median_hist * 0.65) + (pending_count * queue_factor * 0.55), 1))

    prediction_method = "statistical"
    model_version = "pickup-statistical-v1"
    predicted_minutes = stat_estimate
    holdout_mae: Optional[float] = None
    confidence_score = 0.55 if sample_count >= 5 else (0.40 if sample_count >= 1 else 0.30)

    # Upgrade to real Ridge regression ONLY when >= 25 actual completed orders exist
    if sample_count >= 25:
        try:
            import numpy as np
            from sklearn.linear_model import Ridge

            X = np.array(features_x, dtype=float)
            y = np.array(targets_y, dtype=float)
            split = max(15, int(len(X) * 0.8))
            model = Ridge(alpha=2.0)
            model.fit(X[:split], y[:split])
            if split < len(X):
                preds_val = model.predict(X[split:])
                holdout_mae = round(float(np.mean(np.abs(y[split:] - preds_val))), 2)
            # Refit on all verified samples
            model.fit(X, y)
            x_now = np.array([[float(now_loc.hour), float(now_loc.weekday()), item_prep_mins, 0.0]], dtype=float)
            ml_base = max(1.0, float(model.predict(x_now)[0]))
            predicted_minutes = round(max(1.0, ml_base + (pending_count * queue_factor * 0.45)), 1)
            prediction_method = "ml_ridge"
            model_version = f"pickup-ridge-v1-n{sample_count}"
            err_penalty = min(0.35, (holdout_mae or 4.0) / 25.0)
            confidence_score = round(max(0.45, min(0.92, 0.88 - err_penalty)), 2)
        except Exception:
            prediction_method = "statistical"
            model_version = "pickup-statistical-v1"

    confidence_label = "high" if confidence_score >= 0.75 else ("medium" if confidence_score >= 0.52 else "low")
    accuracy = queue_service.get_queue_accuracy_metrics(db, canteen_id, days=30)
    est_int = max(1, int(round(predicted_minutes))) if available_now else None
    est_pickup_at = (now + timedelta(minutes=est_int)).isoformat() if est_int is not None else None

    return {
        "canteen_id": str(canteen.id),
        "canteen_name": canteen.name,
        "order_id": str(order_obj.id) if order_obj else None,
        "prediction_available": available_now,
        "predicted_wait_minutes": est_int,
        "predicted_pickup_at": est_pickup_at,
        "prediction_method": prediction_method,
        "model_version": model_version,
        "data_classification": "ai_predicted" if prediction_method == "ml_ridge" else "estimated",
        "confidence_score": confidence_score,
        "confidence_label": confidence_label,
        "historical_sample_count": sample_count,
        "ml_minimum_samples_required": 25,
        "holdout_mae_minutes": holdout_mae,
        "factors": {
            "pending_orders": pending_count,
            "preparing_orders": preparing_count,
            "item_base_prep_minutes": item_prep_mins,
            "item_count": item_count,
            "historical_median_prep_minutes": round(median_hist, 1) if durations else None,
            "staff_on_duty": staff_on_duty,
            "active_stations": active_stations,
            "active_counters": active_counters,
            "crowd_level": crowd_level,
        },
        "tracked_accuracy_30d": accuracy,
        "disclaimer": (
            "Pickup times are dynamic estimates derived from current kitchen workload and recorded history — "
            "they are not guaranteed."
        ),
        "last_updated_at": now.isoformat(),
    }


# =============================================================================
# FEATURE 3: VIRTUAL QUEUE & PRIORITY HISTORY
# =============================================================================


def get_virtual_queue_overview(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    counter_id: Optional[UUID] = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    canteens = (
        [db.get(Canteen, canteen_id)]
        if canteen_id
        else list(db.scalars(select(Canteen).where(Canteen.is_active.is_(True)).order_by(Canteen.code.asc())).all())
    )
    canteens = [c for c in canteens if c is not None]
    queues: list[dict[str, Any]] = []
    seen_order_ids: set[str] = set()

    for c in canteens:
        dash = queue_service.get_live_queue_dashboard(db, c.id)
        entries = []
        for entry in dash.get("active_orders_queue", []):
            oid = entry.get("order_id")
            if oid in seen_order_ids:
                continue
            seen_order_ids.add(oid)
            if status_filter and entry.get("status") != status_filter:
                continue
            if counter_id and entry.get("counter_id") != str(counter_id):
                continue
            entries.append(entry)
        queues.append(
            {
                "canteen_id": str(c.id),
                "canteen_name": c.name,
                "crowd_level": dash.get("crowd_level"),
                "kitchen_workload_percent": dash.get("kitchen_workload_percent"),
                "active_count": len(entries),
                "delayed_orders": dash.get("delayed_orders", []),
                "congestion_warnings": dash.get("congestion_warnings", []),
                "counter_workloads": dash.get("counter_workloads", []),
                "entries": entries,
            }
        )

    priority_logs = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action.in_(("queue.priority_updated", "queue.overdue_escalated", "queue.counter_reassigned")))
            .order_by(AuditLog.created_at.desc())
            .limit(40)
        ).all()
    )
    return {
        "queues": queues,
        "priority_and_queue_history": [
            {
                "id": str(a.id),
                "action": a.action,
                "entity_id": a.entity_id,
                "actor_user_id": str(a.actor_user_id) if a.actor_user_id else None,
                "details": a.details or {},
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in priority_logs
        ],
        "last_updated_at": now.isoformat(),
    }


def update_order_queue_priority(
    db: Session,
    *,
    order_id: UUID,
    is_priority: bool,
    reason: str,
    actor_user_id: UUID,
    assigned_canteen_id: Optional[UUID] = None,
) -> dict[str, Any]:
    clean_reason = (reason or "").strip()
    if len(clean_reason) < 3:
        raise HTTPException(status_code=400, detail="A documented reason (min 3 characters) is required for priority changes")
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if assigned_canteen_id and order.canteen_id != assigned_canteen_id:
        raise HTTPException(status_code=403, detail="Not authorized to modify queue priority for another canteen")
    if order.status not in ACTIVE_WAITING_STATUSES + ACTIVE_PREPARING_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot change priority for order in status {order.status}")

    prev = bool(order.is_priority)
    order.is_priority = bool(is_priority)
    record_audit_log(
        db,
        action="queue.priority_updated",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=actor_user_id,
        details={"previous_priority": prev, "new_priority": bool(is_priority), "reason": clean_reason},
    )
    db.commit()
    invalidate_board_and_queue(order.canteen_id)
    return {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "previous_priority": prev,
        "is_priority": order.is_priority,
        "reason": clean_reason,
    }


# =============================================================================
# FEATURE 4: AI ORDER-TO-TRAY VERIFICATION
# =============================================================================


def get_tray_verification_context(
    db: Session, order_id_or_number: str, *, assigned_canteen_id: Optional[UUID] = None
) -> dict[str, Any]:
    stmt = select(Order).options(selectinload(Order.items))
    try:
        oid = UUID(order_id_or_number)
        order = db.scalar(stmt.where(Order.id == oid))
    except ValueError:
        order = db.scalar(stmt.where(Order.order_number == order_id_or_number.strip().upper()))

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if assigned_canteen_id and order.canteen_id != assigned_canteen_id:
        raise HTTPException(status_code=403, detail="Not authorized for this canteen's orders")

    expected = [
        {
            "order_item_id": str(it.id),
            "food_item_id": str(it.food_item_id) if it.food_item_id else None,
            "item_name": it.item_name,
            "quantity": int(it.quantity),
            "prep_status": it.prep_status,
        }
        for it in order.items
    ]
    history = list(
        db.scalars(
            select(OrderTrayVerification)
            .where(OrderTrayVerification.order_id == order.id)
            .order_by(OrderTrayVerification.created_at.desc())
            .limit(20)
        ).all()
    )
    staff_ids = {h.verified_by_user_id for h in history if h.verified_by_user_id}
    u_map = (
        {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(staff_ids))).all()}
        if staff_ids
        else {}
    )
    return {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "canteen_id": str(order.canteen_id),
        "status": order.status,
        "payment_status": order.payment_status,
        "expected_items": expected,
        "cv_hardware_available": False,
        "camera_status": "unavailable",
        "hardware_notice": (
            "Camera and computer-vision recognition hardware is not connected. "
            "Use manual item-by-item staff checklist verification. No camera frames are stored."
        ),
        "history": [
            {
                "id": str(h.id),
                "verification_mode": h.verification_mode,
                "status": h.status,
                "missing_items": h.missing_items_json,
                "mismatched_items": h.mismatched_items_json,
                "cv_available": h.cv_available,
                "cv_confidence": float(h.cv_confidence) if h.cv_confidence is not None else None,
                "requires_human_review": h.requires_human_review,
                "verified_by_name": u_map.get(h.verified_by_user_id),
                "notes": h.notes,
                "verified_at": h.verified_at.isoformat() if h.verified_at else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in history
        ],
    }


def submit_tray_verification(
    db: Session,
    *,
    order_id: UUID,
    verified_items: list[dict[str, Any]],
    verification_mode: str = "manual_checklist",
    cv_confidence: Optional[float] = None,
    human_confirmed: bool = False,
    notes: Optional[str] = None,
    actor_user_id: UUID,
    assigned_canteen_id: Optional[UUID] = None,
) -> dict[str, Any]:
    order = db.scalar(select(Order).options(selectinload(Order.items)).where(Order.id == order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if assigned_canteen_id and order.canteen_id != assigned_canteen_id:
        raise HTTPException(status_code=403, detail="Not authorized to verify orders for another canteen")

    expected_by_name: dict[str, int] = {}
    expected_list: list[dict[str, Any]] = []
    for it in order.items:
        key = it.item_name.strip().lower()
        expected_by_name[key] = expected_by_name.get(key, 0) + int(it.quantity)
        expected_list.append({"item_name": it.item_name, "quantity": int(it.quantity)})

    detected_by_name: dict[str, int] = {}
    cleaned_verified: list[dict[str, Any]] = []
    for vi in verified_items:
        nm = str(vi.get("item_name") or "").strip()
        qty = max(0, int(vi.get("quantity") or 0))
        if not nm:
            continue
        key = nm.lower()
        detected_by_name[key] = detected_by_name.get(key, 0) + qty
        cleaned_verified.append(
            {
                "item_name": nm,
                "quantity": qty,
                "confidence": vi.get("confidence"),
            }
        )

    missing_items: list[dict[str, Any]] = []
    mismatched_items: list[dict[str, Any]] = []

    for exp_key, exp_qty in expected_by_name.items():
        got_qty = detected_by_name.get(exp_key, 0)
        if got_qty < exp_qty:
            missing_items.append({"item_name": exp_key, "expected_quantity": exp_qty, "detected_quantity": got_qty})
        elif got_qty > exp_qty:
            mismatched_items.append(
                {
                    "item_name": exp_key,
                    "reason": "excess_quantity",
                    "expected_quantity": exp_qty,
                    "detected_quantity": got_qty,
                }
            )

    for det_key, det_qty in detected_by_name.items():
        if det_key not in expected_by_name and det_qty > 0:
            mismatched_items.append(
                {
                    "item_name": det_key,
                    "reason": "unexpected_item",
                    "expected_quantity": 0,
                    "detected_quantity": det_qty,
                }
            )

    mode = "camera_assisted" if verification_mode == "camera_assisted" else "manual_checklist"
    low_conf = mode == "camera_assisted" and (cv_confidence is None or cv_confidence < 0.85)
    has_discrepancy = bool(missing_items or mismatched_items)
    requires_human_review = bool((low_conf or has_discrepancy) and not human_confirmed)

    if has_discrepancy and not human_confirmed:
        ver_status = "mismatch_flagged"
    elif low_conf and not human_confirmed:
        ver_status = "pending_review"
    elif has_discrepancy and human_confirmed:
        ver_status = "overridden"
    else:
        ver_status = "verified"

    now = datetime.now(timezone.utc)
    rec = OrderTrayVerification(
        order_id=order.id,
        canteen_id=order.canteen_id,
        verified_by_user_id=actor_user_id,
        verification_mode=mode,
        expected_items_json=expected_list,
        verified_items_json=cleaned_verified,
        missing_items_json=missing_items,
        mismatched_items_json=mismatched_items,
        cv_available=False,
        cv_confidence=Decimal(str(round(cv_confidence, 4))) if cv_confidence is not None else None,
        requires_human_review=requires_human_review,
        status=ver_status,
        notes=(notes or "").strip() or None,
        verified_at=now if ver_status in ("verified", "overridden") else None,
    )
    db.add(rec)
    record_audit_log(
        db,
        action="pickup.tray_verified",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=actor_user_id,
        details={
            "verification_mode": mode,
            "status": ver_status,
            "missing_count": len(missing_items),
            "mismatch_count": len(mismatched_items),
            "requires_human_review": requires_human_review,
        },
    )
    db.commit()
    db.refresh(rec)
    return {
        "id": str(rec.id),
        "order_id": str(order.id),
        "order_number": order.order_number,
        "verification_mode": rec.verification_mode,
        "status": rec.status,
        "expected_items": rec.expected_items_json,
        "verified_items": rec.verified_items_json,
        "missing_items": rec.missing_items_json,
        "mismatched_items": rec.mismatched_items_json,
        "cv_available": rec.cv_available,
        "cv_confidence": float(rec.cv_confidence) if rec.cv_confidence is not None else None,
        "requires_human_review": rec.requires_human_review,
        "human_review_policy": "Uncertain AI/CV predictions always require mandatory manual staff confirmation.",
        "notes": rec.notes,
        "verified_at": rec.verified_at.isoformat() if rec.verified_at else None,
    }


def list_tray_verifications(db: Session, *, canteen_id: Optional[UUID] = None, limit: int = 50) -> list[dict[str, Any]]:
    stmt = (
        select(OrderTrayVerification, Order.order_number)
        .join(Order, Order.id == OrderTrayVerification.order_id)
        .order_by(OrderTrayVerification.created_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    if canteen_id:
        stmt = stmt.where(OrderTrayVerification.canteen_id == canteen_id)
    rows = db.execute(stmt).all()
    staff_ids = {r[0].verified_by_user_id for r in rows if r[0].verified_by_user_id}
    u_map = (
        {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(staff_ids))).all()}
        if staff_ids
        else {}
    )
    return [
        {
            "id": str(v.id),
            "order_id": str(v.order_id),
            "order_number": ord_num,
            "canteen_id": str(v.canteen_id),
            "verification_mode": v.verification_mode,
            "status": v.status,
            "missing_count": len(v.missing_items_json or []),
            "mismatch_count": len(v.mismatched_items_json or []),
            "requires_human_review": v.requires_human_review,
            "cv_confidence": float(v.cv_confidence) if v.cv_confidence is not None else None,
            "verified_by_name": u_map.get(v.verified_by_user_id),
            "notes": v.notes,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v, ord_num in rows
    ]


# =============================================================================
# FEATURE 5: CLASS TIMETABLE-BASED FOOD DEMAND PREDICTION (CSV & EXCEL)
# =============================================================================

_DAY_MAP = {
    "0": 0, "mon": 0, "monday": 0,
    "1": 1, "tue": 1, "tuesday": 1,
    "2": 2, "wed": 2, "wednesday": 2,
    "3": 3, "thu": 3, "thursday": 3,
    "4": 4, "fri": 4, "friday": 4,
    "5": 5, "sat": 5, "saturday": 5,
    "6": 6, "sun": 6, "sunday": 6,
}


def _parse_hhmm(raw: Any) -> time:
    if isinstance(raw, time):
        return raw
    if isinstance(raw, datetime):
        return raw.time()
    txt = str(raw or "").strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p"):
        try:
            return datetime.strptime(txt, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Invalid time format: '{txt}' (expected HH:MM)")


def import_academic_timetable(
    db: Session,
    *,
    file_bytes: bytes,
    filename: str,
    canteen_id: Optional[UUID] = None,
    academic_term: Optional[str] = None,
    actor_user_id: UUID,
) -> dict[str, Any]:
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded timetable file is empty")
    if len(file_bytes) > MAX_TIMETABLE_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Timetable file exceeds maximum allowed size of 2 MB")

    fname = (filename or "").lower()
    raw_rows: list[dict[str, Any]] = []
    if fname.endswith(".csv"):
        try:
            text_body = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="CSV file must be valid UTF-8 encoded") from exc
        reader = csv.DictReader(io.StringIO(text_body))
        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV header row is missing")
        for r in reader:
            raw_rows.append({(k or "").strip().lower(): v for k, v in r.items()})
    elif fname.endswith(".xlsx"):
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            header = next(rows_iter, None)
            if not header:
                raise HTTPException(status_code=400, detail="Excel sheet is empty")
            keys = [str(h or "").strip().lower() for h in header]
            for vals in rows_iter:
                if not any(v is not None and str(v).strip() != "" for v in vals):
                    continue
                raw_rows.append({keys[i]: vals[i] if i < len(vals) else None for i in range(len(keys))})
            wb.close()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid Excel (.xlsx) timetable file: {type(exc).__name__}") from exc
    else:
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx academic timetable files are supported")

    if not raw_rows:
        raise HTTPException(status_code=400, detail="No timetable rows found in uploaded file")
    if len(raw_rows) > MAX_TIMETABLE_ROWS:
        raise HTTPException(status_code=400, detail=f"Timetable exceeds row limit ({MAX_TIMETABLE_ROWS})")

    batch_id = f"TT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6].upper()}"
    inserted = 0
    errors: list[str] = []

    for row_idx, r in enumerate(raw_rows, start=2):
        dept = str(r.get("department") or "").strip()
        dow_raw = str(r.get("day_of_week") or r.get("day") or "").strip().lower()
        slot_type = str(r.get("slot_type") or "class").strip().lower()
        if slot_type not in ("class", "short_break", "lunch_break", "exam"):
            errors.append(f"Row {row_idx}: invalid slot_type '{slot_type}'")
            continue
        if not dept or dow_raw not in _DAY_MAP:
            errors.append(f"Row {row_idx}: missing/invalid department or day_of_week")
            continue
        try:
            st = _parse_hhmm(r.get("start_time"))
            et = _parse_hhmm(r.get("end_time"))
            if et <= st:
                raise ValueError("end_time must be after start_time")
        except ValueError as ve:
            errors.append(f"Row {row_idx}: {ve}")
            continue
        cohort_raw = r.get("estimated_cohort_size") or r.get("cohort_size") or r.get("students")
        cohort_val: Optional[int] = None
        if cohort_raw is not None and str(cohort_raw).strip() != "":
            try:
                cohort_val = max(0, int(float(str(cohort_raw).strip())))
            except ValueError:
                errors.append(f"Row {row_idx}: invalid cohort size '{cohort_raw}'")
                continue

        db.add(
            AcademicTimetableSlot(
                canteen_id=canteen_id,
                department=dept[:120],
                academic_term=(academic_term or str(r.get("academic_term") or "").strip() or None),
                day_of_week=_DAY_MAP[dow_raw],
                slot_type=slot_type,
                start_time=st,
                end_time=et,
                estimated_cohort_size=cohort_val,
                label=str(r.get("label") or f"{dept} {slot_type.replace('_', ' ').title()}")[:160],
                import_batch_id=batch_id,
                uploaded_by_user_id=actor_user_id,
                is_active=True,
            )
        )
        inserted += 1

    if inserted == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No valid timetable rows could be imported. Sample errors: {'; '.join(errors[:5])}",
        )

    record_audit_log(
        db,
        action="campus_intelligence.timetable_imported",
        entity_type="academic_timetable_slot",
        entity_id=batch_id,
        actor_user_id=actor_user_id,
        details={"filename": filename, "inserted": inserted, "skipped_errors": len(errors)},
    )
    db.commit()
    return {
        "import_batch_id": batch_id,
        "inserted_slots": inserted,
        "skipped_rows": len(errors),
        "errors": errors[:20],
    }


def list_timetable_slots(
    db: Session, *, canteen_id: Optional[UUID] = None, day_of_week: Optional[int] = None
) -> list[dict[str, Any]]:
    stmt = (
        select(AcademicTimetableSlot)
        .where(AcademicTimetableSlot.is_active.is_(True))
        .order_by(AcademicTimetableSlot.day_of_week.asc(), AcademicTimetableSlot.start_time.asc())
    )
    if canteen_id:
        stmt = stmt.where(
            (AcademicTimetableSlot.canteen_id == canteen_id) | (AcademicTimetableSlot.canteen_id.is_(None))
        )
    if day_of_week is not None:
        stmt = stmt.where(AcademicTimetableSlot.day_of_week == day_of_week)
    rows = db.scalars(stmt.limit(500)).all()
    return [
        {
            "id": str(s.id),
            "canteen_id": str(s.canteen_id) if s.canteen_id else None,
            "department": s.department,
            "academic_term": s.academic_term,
            "day_of_week": s.day_of_week,
            "slot_type": s.slot_type,
            "start_time": s.start_time.strftime("%H:%M"),
            "end_time": s.end_time.strftime("%H:%M"),
            "estimated_cohort_size": s.estimated_cohort_size,
            "label": s.label,
            "import_batch_id": s.import_batch_id,
        }
        for s in rows
    ]


def delete_timetable_slot(db: Session, slot_id: UUID, actor_user_id: UUID) -> None:
    slot = db.get(AcademicTimetableSlot, slot_id)
    if not slot:
        raise HTTPException(status_code=404, detail="Timetable slot not found")
    slot.is_active = False
    record_audit_log(
        db,
        action="campus_intelligence.timetable_slot_deleted",
        entity_type="academic_timetable_slot",
        entity_id=str(slot.id),
        actor_user_id=actor_user_id,
    )
    db.commit()


def get_timetable_demand_prediction(
    db: Session, *, canteen_id: Optional[UUID] = None, target_date: Optional[date] = None
) -> dict[str, Any]:
    tgt = target_date or today_college()
    dow = tgt.weekday()
    now = datetime.now(timezone.utc)
    since_30d = now - timedelta(days=30)

    # Check holidays & college events
    holidays = list(
        db.scalars(
            select(CollegeHoliday).where(
                CollegeHoliday.is_active.is_(True),
                CollegeHoliday.holiday_date == tgt,
            )
        ).all()
    )
    events = list(
        db.scalars(
            select(CollegeEvent).where(
                CollegeEvent.event_date == tgt,
                CollegeEvent.is_active.is_(True),
            )
        ).all()
    )

    slots = list(
        db.scalars(
            select(AcademicTimetableSlot)
            .where(
                AcademicTimetableSlot.is_active.is_(True),
                AcademicTimetableSlot.day_of_week == dow,
                *(
                    [(AcademicTimetableSlot.canteen_id == canteen_id) | (AcademicTimetableSlot.canteen_id.is_(None))]
                    if canteen_id
                    else []
                ),
            )
            .order_by(AcademicTimetableSlot.start_time.asc())
        ).all()
    )

    # Actual historical orders for the same weekday over last 30 days
    ord_stmt = select(Order.created_at, Order.id).where(
        Order.created_at >= since_30d,
        Order.status.notin_(("PAYMENT_FAILED", "CANCELLED")),
    )
    if canteen_id:
        ord_stmt = ord_stmt.where(Order.canteen_id == canteen_id)
    hist_orders = db.execute(ord_stmt).all()

    col_offset = now_college().utcoffset() or timedelta(0)
    interval_actuals: dict[int, int] = {}  # 30-min buckets (0..47)
    distinct_same_dow_dates: set[date] = set()
    for ts, _oid in hist_orders:
        u = _as_utc(ts)
        if not u:
            continue
        loc = u + col_offset
        if loc.weekday() == dow:
            distinct_same_dow_dates.add(loc.date())
            bucket = loc.hour * 2 + (1 if loc.minute >= 30 else 0)
            interval_actuals[bucket] = interval_actuals.get(bucket, 0) + 1

    observed_days = max(1, len(distinct_same_dow_dates))
    total_same_dow_orders = sum(interval_actuals.values())

    # Aggregate break windows (short_break + lunch_break)
    break_windows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for s in slots:
        if s.slot_type not in ("short_break", "lunch_break"):
            continue
        key = (s.start_time.strftime("%H:%M"), s.end_time.strftime("%H:%M"), s.slot_type)
        entry = break_windows.setdefault(
            key,
            {
                "start_time": key[0],
                "end_time": key[1],
                "slot_type": key[2],
                "departments": [],
                "reported_cohort_size": 0,
            },
        )
        if s.department not in entry["departments"]:
            entry["departments"].append(s.department)
        entry["reported_cohort_size"] += int(s.estimated_cohort_size or 0)

    is_full_holiday = any(h.is_full_day for h in holidays)
    predictions: list[dict[str, Any]] = []
    for (_st_s, _et_s, _stype), bw in sorted(break_windows.items()):
        sh, sm = map(int, bw["start_time"].split(":"))
        eh, em = map(int, bw["end_time"].split(":"))
        b_start = sh * 2 + (1 if sm >= 30 else 0)
        b_end = max(b_start, eh * 2 + (1 if em >= 30 else 0))
        actual_total_in_win = sum(interval_actuals.get(b, 0) for b in range(b_start, b_end + 1))
        actual_avg = round(actual_total_in_win / observed_days, 1) if total_same_dow_orders > 0 else 0.0

        # Do NOT assume every student buys food: estimate strictly from observed order history (or honest conservative range if cohort exists)
        if is_full_holiday:
            forecast_orders = 0.0
            demand_level = "holiday_closed"
            confidence = "high"
        elif total_same_dow_orders >= 5:
            event_boost = 1.15 if events else 1.0
            forecast_orders = round(actual_avg * event_boost, 1)
            demand_level = "high" if forecast_orders >= 20 else ("moderate" if forecast_orders >= 8 else "low")
            confidence = "medium" if len(distinct_same_dow_dates) >= 2 else "low"
        else:
            forecast_orders = None
            demand_level = "insufficient_historical_orders"
            confidence = "low"

        predictions.append(
            {
                **bw,
                "actual_historical_avg_orders": actual_avg if total_same_dow_orders > 0 else None,
                "forecast_estimated_orders": forecast_orders,
                "data_classification": "forecast_estimate" if forecast_orders is not None else "insufficient_data",
                "demand_level": demand_level,
                "confidence": confidence,
                "note": (
                    "Holiday closure active."
                    if is_full_holiday
                    else (
                        "Forecast calibrated from recorded weekday order velocity; never assumes 100% student purchase rate."
                        if forecast_orders is not None
                        else "Timetable break identified, but insufficient historical weekday orders exist to forecast exact order volume."
                    )
                ),
            }
        )

    # Top historically ordered items for preparation suggestions (read-only guidance, never auto-purchasing!)
    top_item_stmt = (
        select(OrderItem.item_name, func.sum(OrderItem.quantity).label("qty"))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.created_at >= since_30d, Order.status.notin_(("PAYMENT_FAILED", "CANCELLED")))
        .group_by(OrderItem.item_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(8)
    )
    if canteen_id:
        top_item_stmt = top_item_stmt.where(Order.canteen_id == canteen_id)
    top_items = [{"item_name": r[0], "historical_30d_qty": int(r[1] or 0)} for r in db.execute(top_item_stmt).all()]

    low_stock_stmt = select(func.count(InventoryItem.id)).where(
        InventoryItem.is_archived.is_(False),
        InventoryItem.current_quantity <= InventoryItem.reorder_level,
    )
    if canteen_id:
        low_stock_stmt = low_stock_stmt.where(InventoryItem.canteen_id == canteen_id)
    low_stock_count = int(db.scalar(low_stock_stmt) or 0)

    return {
        "target_date": tgt.isoformat(),
        "day_of_week": dow,
        "timetable_slots_count": len(slots),
        "break_windows_analyzed": len(predictions),
        "holidays": [{"title": h.title, "is_full_day": h.is_full_day} for h in holidays],
        "academic_events": [{"title": e.title, "expected_attendees": e.expected_attendees} for e in events],
        "historical_same_weekday_days_observed": len(distinct_same_dow_dates),
        "historical_same_weekday_orders": total_same_dow_orders,
        "predicted_break_periods": predictions,
        "historical_top_items": top_items,
        "low_stock_ingredient_warnings": low_stock_count,
        "governance_notice": (
            "Preparation suggestions are advisory forecasts distinct from actual sales. "
            "No stock purchases or menu availability changes are executed automatically."
        ),
    }


# =============================================================================
# FEATURE 6: INTELLIGENT MENU AVAILABILITY DISPLAY
# =============================================================================


def get_intelligent_menu_availability(
    db: Session, canteen_id: UUID, *, include_history: bool = True
) -> dict[str, Any]:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")

    items = list(
        db.scalars(
            select(FoodItem)
            .where(FoodItem.canteen_id == canteen_id, FoodItem.is_active.is_(True))
            .order_by(FoodItem.name.asc())
        ).all()
    )
    f_map = {it.id: it for it in items}
    sched_map = compute_schedule_availability_map(db, list(f_map.keys()), food_items_map=f_map)

    # Check verified recipe linkage
    recipes = {
        r.food_item_id: r
        for r in db.scalars(select(Recipe).where(Recipe.food_item_id.in_(list(f_map.keys())))).all()
    } if f_map else {}

    out_items: list[dict[str, Any]] = []
    available_count = 0
    stock_blocked_count = 0
    manual_off_count = 0
    schedule_off_count = 0

    for it in items:
        sched_ok = bool(sched_map.get(it.id, True))
        eff_available = bool(it.is_available and not it.insufficient_ingredients and sched_ok)
        if eff_available:
            available_count += 1
        elif it.insufficient_ingredients:
            stock_blocked_count += 1
        elif not it.is_available:
            manual_off_count += 1
        else:
            schedule_off_count += 1

        rec = recipes.get(it.id)
        out_items.append(
            {
                "food_item_id": str(it.id),
                "name": it.name,
                "base_price": str(it.base_price),
                "is_veg": it.is_veg,
                "prep_time_minutes": it.prep_time_minutes,
                "effective_available": eff_available,
                "manual_is_available": it.is_available,
                "insufficient_ingredients": it.insufficient_ingredients,
                "schedule_active_now": sched_ok,
                "pending_restore_approval": it.pending_restore_approval,
                "has_verified_recipe": bool(rec and rec.is_verified),
                "available_from_time": it.available_from_time.strftime("%H:%M") if it.available_from_time else None,
                "available_until_time": it.available_until_time.strftime("%H:%M") if it.available_until_time else None,
                "unavailable_reason": (
                    None
                    if eff_available
                    else (
                        "Out of required recipe ingredients"
                        if it.insufficient_ingredients
                        else ("Temporarily paused by manager" if not it.is_available else "Outside scheduled serving window")
                    )
                ),
            }
        )

    history: list[dict[str, Any]] = []
    if include_history:
        ev_rows = db.execute(
            select(MenuAvailabilityEvent, FoodItem.name)
            .join(FoodItem, FoodItem.id == MenuAvailabilityEvent.food_item_id)
            .where(MenuAvailabilityEvent.canteen_id == canteen_id)
            .order_by(MenuAvailabilityEvent.created_at.desc())
            .limit(40)
        ).all()
        history = [
            {
                "id": str(ev.id),
                "food_item_id": str(ev.food_item_id),
                "item_name": fname,
                "previous_available": ev.previous_available,
                "new_available": ev.new_available,
                "reason_type": ev.reason_type,
                "reason_detail": ev.reason_detail,
                "actor_user_id": str(ev.actor_user_id) if ev.actor_user_id else None,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev, fname in ev_rows
        ]

    return {
        "canteen_id": str(canteen.id),
        "canteen_name": canteen.name,
        "summary": {
            "total_active_items": len(out_items),
            "available_now": available_count,
            "stock_blocked": stock_blocked_count,
            "manually_paused": manual_off_count,
            "outside_schedule": schedule_off_count,
        },
        "items": out_items,
        "availability_history": history,
        "last_updated_at": datetime.now(timezone.utc).isoformat(),
    }


def override_menu_item_availability(
    db: Session,
    *,
    food_item_id: UUID,
    is_available: bool,
    reason: str,
    actor_user_id: UUID,
    assigned_canteen_id: Optional[UUID] = None,
) -> dict[str, Any]:
    clean_reason = (reason or "").strip()
    if len(clean_reason) < 3:
        raise HTTPException(status_code=400, detail="Documented reason is required for manual availability overrides")
    item = db.scalar(select(FoodItem).where(FoodItem.id == food_item_id).with_for_update())
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    if assigned_canteen_id and item.canteen_id != assigned_canteen_id:
        raise HTTPException(status_code=403, detail="Not authorized to override menu availability for another canteen")

    prev = bool(item.is_available)
    item.is_available = bool(is_available)
    ev = MenuAvailabilityEvent(
        food_item_id=item.id,
        canteen_id=item.canteen_id,
        previous_available=prev,
        new_available=bool(is_available),
        reason_type="manual_override",
        reason_detail=clean_reason[:300],
        actor_user_id=actor_user_id,
    )
    db.add(ev)
    record_audit_log(
        db,
        action="menu.availability_manual_override",
        entity_type="food_item",
        entity_id=str(item.id),
        actor_user_id=actor_user_id,
        details={"item_name": item.name, "previous": prev, "new": bool(is_available), "reason": clean_reason},
    )
    if not is_available and prev:
        notification_service.create_role_notifications(
            db,
            roles=["canteen_manager", "kitchen_staff"],
            canteen_id=item.canteen_id,
            event_type="menu_item_unavailable",
            category="inventory",
            priority="normal",
            title=f"Menu Item Paused • {item.name}",
            message=f"{item.name} was marked unavailable ({clean_reason}).",
            event_id_base=f"menu_avail:{item.id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
        )
    db.commit()
    cache_manager.invalidate_namespace(f"{NS_MENU}:{item.canteen_id}")
    return {
        "food_item_id": str(item.id),
        "item_name": item.name,
        "previous_available": prev,
        "is_available": item.is_available,
        "reason": clean_reason,
    }


# =============================================================================
# FEATURE 7: LIVE ORDER JOURNEY TRACKING (6-STAGE + INDEPENDENT PAYMENT STATUS)
# =============================================================================


def get_live_order_journey(
    db: Session,
    order_number: str,
    *,
    user_id: Optional[UUID] = None,
    guest_access_token: Optional[str] = None,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
) -> dict[str, Any]:
    ord_out = order_service.get_order_authorized(
        db,
        order_number,
        user_id=user_id,
        guest_access_token=guest_access_token,
        is_staff=is_staff,
        staff_canteen_id=staff_canteen_id,
    )
    st = ord_out.status
    pay_st = ord_out.payment_status

    hist_times: dict[str, Optional[str]] = {}
    for h in ord_out.status_history:
        if h.to_status not in hist_times:
            hist_times[h.to_status] = h.created_at.isoformat() if h.created_at else None

    stage_order = ["CREATED", "PAYMENT_CONFIRMED", "ACCEPTED", "PREPARING", "READY", "COMPLETED"]
    rank_map = {
        "CREATED": 0,
        "PAYMENT_PENDING": 0,
        "PAYMENT_FAILED": 0,
        "PAYMENT_CONFIRMED": 1,
        "PLACED": 1,
        "ACCEPTED": 2,
        "PREPARING": 3,
        "READY": 4,
        "COMPLETED": 5,
    }
    cur_rank = rank_map.get(st, -1)
    is_cancelled_or_failed = st in ("CANCELLED", "REJECTED", "PAYMENT_FAILED")

    stages = [
        {
            "step": 1,
            "key": "order_placed",
            "label": "Order Placed",
            "completed": True,
            "current": st in ("CREATED", "PAYMENT_PENDING"),
            "timestamp": ord_out.created_at.isoformat() if ord_out.created_at else None,
        },
        {
            "step": 2,
            "key": "payment_verification",
            "label": "Payment Verification (Razorpay)",
            "completed": pay_st == "CONFIRMED",
            "current": st == "PAYMENT_PENDING",
            "failed": pay_st == "FAILED",
            "timestamp": (ord_out.confirmed_at.isoformat() if ord_out.confirmed_at else hist_times.get("PAYMENT_CONFIRMED")),
        },
        {
            "step": 3,
            "key": "order_accepted",
            "label": "Order Accepted",
            "completed": (not is_cancelled_or_failed) and cur_rank >= 2,
            "current": st == "ACCEPTED",
            "timestamp": (ord_out.accepted_at.isoformat() if ord_out.accepted_at else hist_times.get("ACCEPTED")),
        },
        {
            "step": 4,
            "key": "preparing",
            "label": "Preparing",
            "completed": (not is_cancelled_or_failed) and cur_rank >= 3,
            "current": st == "PREPARING",
            "timestamp": (ord_out.preparing_at.isoformat() if ord_out.preparing_at else hist_times.get("PREPARING")),
        },
        {
            "step": 5,
            "key": "ready_for_pickup",
            "label": "Ready for Pickup",
            "completed": (not is_cancelled_or_failed) and cur_rank >= 4,
            "current": st == "READY",
            "timestamp": (ord_out.ready_at.isoformat() if ord_out.ready_at else hist_times.get("READY")),
        },
        {
            "step": 6,
            "key": "collected",
            "label": "Collected",
            "completed": st == "COMPLETED",
            "current": st == "COMPLETED",
            "timestamp": (ord_out.completed_at.isoformat() if ord_out.completed_at else hist_times.get("COMPLETED")),
        },
    ]

    prediction = None
    if st in ACTIVE_WAITING_STATUSES + ACTIVE_PREPARING_STATUSES:
        prediction = get_smart_pickup_prediction(db, ord_out.canteen_id, order_id=ord_out.id)

    return {
        "order": ord_out.model_dump(mode="json"),
        "payment_status_independent": pay_st,
        "preparation_status": st,
        "is_terminal_exception": is_cancelled_or_failed,
        "stages": stages,
        "pickup_prediction": prediction,
        "last_updated_at": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# FEATURE 8: SMART SEATING AVAILABILITY INTELLIGENCE
# =============================================================================


def list_seating_availability(db: Session, *, canteen_id: Optional[UUID] = None) -> dict[str, Any]:
    stmt = select(SeatingZone).where(SeatingZone.is_active.is_(True)).order_by(SeatingZone.zone_code.asc())
    if canteen_id:
        stmt = stmt.where((SeatingZone.canteen_id == canteen_id) | (SeatingZone.canteen_id.is_(None)))
    zones = list(db.scalars(stmt).all())

    # Also report total DiningTable capacity if no SeatingZone has been configured yet (never invent occupied count!)
    table_capacity = int(
        db.scalar(
            select(func.coalesce(func.sum(DiningTable.capacity), 0)).where(
                DiningTable.is_active.is_(True),
                *([DiningTable.canteen_id == canteen_id] if canteen_id else []),
            )
        )
        or 0
    )

    zones_out: list[dict[str, Any]] = []
    total_seats = 0
    known_occupied = 0
    known_capacity = 0
    has_measured = False

    for z in zones:
        total_seats += int(z.total_seats)
        occ = z.occupied_seats
        avail = (z.total_seats - occ) if occ is not None else None
        pct = round((occ / max(1, z.total_seats)) * 100, 1) if occ is not None else None
        if occ is not None:
            has_measured = True
            known_occupied += int(occ)
            known_capacity += int(z.total_seats)
        zones_out.append(
            {
                "id": str(z.id),
                "canteen_id": str(z.canteen_id) if z.canteen_id else None,
                "zone_code": z.zone_code,
                "zone_name": z.zone_name,
                "total_seats": z.total_seats,
                "occupied_seats": occ,
                "available_seats": avail,
                "occupancy_percent": pct,
                "data_source": z.data_source,
                "sensor_status": z.sensor_status,
                "layout": {"x": z.layout_x, "y": z.layout_y, "w": z.layout_w, "h": z.layout_h},
                "last_measured_at": z.last_measured_at.isoformat() if z.last_measured_at else None,
            }
        )

    return {
        "configured": len(zones_out) > 0,
        "zones": zones_out,
        "registered_dining_table_seats": table_capacity,
        "summary": {
            "total_configured_seats": total_seats,
            "occupied_seats": known_occupied if has_measured else None,
            "available_seats": (known_capacity - known_occupied) if has_measured else None,
            "occupancy_percent": round((known_occupied / max(1, known_capacity)) * 100, 1) if has_measured else None,
            "measurement_status": "measured" if has_measured else "unmeasured_no_sensor_or_manual_update",
        },
        "privacy_notice": "No facial recognition, video identity tracking, or individual student tracking is used.",
        "last_updated_at": datetime.now(timezone.utc).isoformat(),
    }


def upsert_seating_zone(
    db: Session,
    *,
    zone_code: str,
    zone_name: str,
    total_seats: int,
    canteen_id: Optional[UUID] = None,
    layout_x: int = 0,
    layout_y: int = 0,
    layout_w: int = 200,
    layout_h: int = 120,
    actor_user_id: UUID,
) -> dict[str, Any]:
    code = zone_code.strip().upper()[:32]
    if total_seats < 1 or total_seats > 2000:
        raise HTTPException(status_code=400, detail="total_seats must be between 1 and 2000")
    existing = db.scalar(select(SeatingZone).where(SeatingZone.zone_code == code))
    if existing:
        existing.zone_name = zone_name.strip()[:120]
        existing.total_seats = total_seats
        existing.canteen_id = canteen_id
        existing.layout_x = layout_x
        existing.layout_y = layout_y
        existing.layout_w = layout_w
        existing.layout_h = layout_h
        existing.is_active = True
        existing.updated_by_user_id = actor_user_id
        zone = existing
    else:
        zone = SeatingZone(
            canteen_id=canteen_id,
            zone_code=code,
            zone_name=zone_name.strip()[:120],
            total_seats=total_seats,
            occupied_seats=None,
            data_source="unconfigured",
            sensor_status="unavailable",
            layout_x=layout_x,
            layout_y=layout_y,
            layout_w=layout_w,
            layout_h=layout_h,
            updated_by_user_id=actor_user_id,
            is_active=True,
        )
        db.add(zone)
        db.flush()

    record_audit_log(
        db,
        action="seating.zone_configured",
        entity_type="seating_zone",
        entity_id=zone.zone_code,
        actor_user_id=actor_user_id,
        details={"zone_name": zone.zone_name, "total_seats": total_seats},
    )
    db.commit()
    db.refresh(zone)
    return {
        "id": str(zone.id),
        "zone_code": zone.zone_code,
        "zone_name": zone.zone_name,
        "total_seats": zone.total_seats,
        "occupied_seats": zone.occupied_seats,
        "data_source": zone.data_source,
        "sensor_status": zone.sensor_status,
    }


def update_seating_occupancy(
    db: Session,
    *,
    zone_id: UUID,
    occupied_seats: int,
    data_source: str = "manual",
    notes: Optional[str] = None,
    actor_user_id: UUID,
) -> dict[str, Any]:
    zone = db.scalar(select(SeatingZone).where(SeatingZone.id == zone_id).with_for_update())
    if not zone or not zone.is_active:
        raise HTTPException(status_code=404, detail="Seating zone not found")
    if occupied_seats < 0 or occupied_seats > zone.total_seats:
        raise HTTPException(
            status_code=400, detail=f"occupied_seats must be between 0 and total_seats ({zone.total_seats})"
        )
    src = data_source if data_source in ("manual", "sensor", "estimated") else "manual"
    now = datetime.now(timezone.utc)
    avail = zone.total_seats - occupied_seats
    pct = Decimal(str(round((occupied_seats / max(1, zone.total_seats)) * 100, 2)))

    zone.occupied_seats = occupied_seats
    zone.data_source = src
    zone.sensor_status = "online" if src == "sensor" else zone.sensor_status
    zone.updated_by_user_id = actor_user_id
    zone.last_measured_at = now

    log = SeatingOccupancyLog(
        zone_id=zone.id,
        total_seats=zone.total_seats,
        occupied_seats=occupied_seats,
        available_seats=avail,
        occupancy_percent=pct,
        data_source=src,
        recorded_by_user_id=actor_user_id,
        notes=(notes or "").strip()[:300] or None,
        recorded_at=now,
    )
    db.add(log)
    record_audit_log(
        db,
        action="seating.occupancy_updated",
        entity_type="seating_zone",
        entity_id=zone.zone_code,
        actor_user_id=actor_user_id,
        details={"occupied_seats": occupied_seats, "total_seats": zone.total_seats, "data_source": src},
    )
    db.commit()
    return {
        "zone_id": str(zone.id),
        "zone_code": zone.zone_code,
        "zone_name": zone.zone_name,
        "total_seats": zone.total_seats,
        "occupied_seats": occupied_seats,
        "available_seats": avail,
        "occupancy_percent": float(pct),
        "data_source": src,
        "last_measured_at": now.isoformat(),
    }


def get_seating_analytics(db: Session, *, days: int = 14, canteen_id: Optional[UUID] = None) -> dict[str, Any]:
    lookback = max(1, min(int(days or 14), 90))
    since = datetime.now(timezone.utc) - timedelta(days=lookback)
    stmt = (
        select(SeatingOccupancyLog, SeatingZone.zone_name, SeatingZone.zone_code)
        .join(SeatingZone, SeatingZone.id == SeatingOccupancyLog.zone_id)
        .where(SeatingOccupancyLog.recorded_at >= since)
        .order_by(SeatingOccupancyLog.recorded_at.asc())
    )
    if canteen_id:
        stmt = stmt.where((SeatingZone.canteen_id == canteen_id) | (SeatingZone.canteen_id.is_(None)))
    rows = db.execute(stmt.limit(1000)).all()
    if not rows:
        return {
            "lookback_days": lookback,
            "has_data": False,
            "sample_count": 0,
            "peak_hours": [],
            "recent_logs": [],
            "message": "No recorded seating occupancy measurements found for this period.",
        }

    col_offset = now_college().utcoffset() or timedelta(0)
    by_hour: dict[int, list[float]] = {}
    for log, _zname, _zcode in rows:
        u = _as_utc(log.recorded_at)
        if u:
            hr = (u + col_offset).hour
            by_hour.setdefault(hr, []).append(float(log.occupancy_percent))

    hourly = [
        {
            "hour": h,
            "label": f"{h:02d}:00",
            "avg_occupancy_percent": round(sum(vals) / len(vals), 1),
            "measurements": len(vals),
        }
        for h, vals in sorted(by_hour.items())
    ]
    peaks = sorted(hourly, key=lambda x: x["avg_occupancy_percent"], reverse=True)[:3]
    return {
        "lookback_days": lookback,
        "has_data": True,
        "sample_count": len(rows),
        "hourly_trends": hourly,
        "peak_hours": peaks,
        "recent_logs": [
            {
                "zone_code": zcode,
                "zone_name": zname,
                "occupied_seats": log.occupied_seats,
                "total_seats": log.total_seats,
                "available_seats": log.available_seats,
                "occupancy_percent": float(log.occupancy_percent),
                "data_source": log.data_source,
                "recorded_at": log.recorded_at.isoformat(),
            }
            for log, zname, zcode in rows[-30:]
        ],
    }
