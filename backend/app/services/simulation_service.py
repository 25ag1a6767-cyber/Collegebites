import csv
import io
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.auth import StaffProfile
from app.models.campus_ops import SimulationScenario
from app.models.college import Canteen
from app.models.menu import FoodItem, Ingredient, Recipe, RecipeIngredient
from app.models.order import Order
from app.services.audit_service import record_audit_log


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def run_what_if_simulation(
    db: Session,
    *,
    name: str,
    description: Optional[str],
    canteen_id: Optional[UUID],
    parameters: dict[str, Any],
    actor_user_id: UUID,
) -> dict[str, Any]:
    """
    Strictly isolated What-If Simulation Engine.
    Reads historical production baselines into memory ONLY and NEVER mutates orders,
    payments, inventory, menu items, or customer records.
    """
    now = datetime.now(timezone.utc)
    since_30d = now - timedelta(days=30)

    canteens = (
        [db.get(Canteen, canteen_id)]
        if canteen_id
        else list(db.scalars(select(Canteen).where(Canteen.is_active.is_(True)).order_by(Canteen.code.asc())).all())
    )
    canteens = [c for c in canteens if c is not None]
    if not canteens:
        raise HTTPException(status_code=404, detail="No active cafeteria counter found for simulation")

    # Read-only historical baseline
    ord_q = select(Order).where(Order.created_at >= since_30d, Order.status.notin_(("PAYMENT_FAILED", "CANCELLED")))
    if canteen_id:
        ord_q = ord_q.where(Order.canteen_id == canteen_id)
    hist_orders = list(db.scalars(ord_q.limit(2000)).all())

    prep_samples: list[float] = []
    for o in hist_orders:
        c_u, r_u = _as_utc(o.confirmed_at), _as_utc(o.ready_at)
        if c_u and r_u and r_u > c_u:
            prep_samples.append(min(120.0, max(1.0, (r_u - c_u).total_seconds() / 60.0)))

    default_prep = sum(int(c.default_prep_time_minutes or 12) for c in canteens) / len(canteens)
    base_prep_min = round(statistics.median(prep_samples), 2) if prep_samples else round(default_prep, 2)
    base_daily_orders = round(len(hist_orders) / 30.0, 1) if hist_orders else 0.0
    base_peak_hourly_orders = round(max(1.0, base_daily_orders * 0.32), 1) if base_daily_orders > 0 else 10.0

    staff_q = select(func.count(StaffProfile.id)).where(StaffProfile.is_on_duty.is_(True))
    if canteen_id:
        staff_q = staff_q.where(StaffProfile.assigned_canteen_id == canteen_id)
    base_staff = max(1, int(db.scalar(staff_q) or 2))

    # Sanitized simulation levers
    staff_delta = max(-5, min(15, int(parameters.get("staff_delta", 0))))
    prep_cap_mult = max(0.3, min(3.0, float(parameters.get("prep_capacity_multiplier", 1.0))))
    demand_mult = max(0.2, min(4.0, float(parameters.get("demand_multiplier", 1.0))))
    prep_time_delta = max(-8.0, min(20.0, float(parameters.get("prep_time_delta_minutes", 0.0))))
    counter_shift_pct = max(-40.0, min(40.0, float(parameters.get("counter_shift_percent", 0.0))))
    schedule_ext_mins = max(-120, min(240, int(parameters.get("schedule_extension_minutes", 0))))
    shortage_ids_raw = parameters.get("shortage_ingredient_ids") or []

    # Simulated menu impact for simulated ingredient shortages (read-only lookup!)
    impacted_items: list[str] = []
    valid_ing_ids: list[UUID] = []
    for raw_id in shortage_ids_raw:
        try:
            valid_ing_ids.append(UUID(str(raw_id)))
        except ValueError:
            continue
    if valid_ing_ids:
        impacted_items = list(
            db.scalars(
                select(FoodItem.name)
                .join(Recipe, Recipe.food_item_id == FoodItem.id)
                .join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id)
                .where(RecipeIngredient.ingredient_id.in_(valid_ing_ids), FoodItem.is_active.is_(True))
                .distinct()
            ).all()
        )

    sim_staff = max(1, base_staff + staff_delta)
    sim_prep_min = max(2.0, round(base_prep_min + prep_time_delta, 2))
    # Throughput capacity (orders/hour) scales with staff ratio and prep speed
    base_throughput_hr = round((base_staff * 60.0) / max(2.0, base_prep_min), 1)
    sim_throughput_hr = round(((sim_staff * prep_cap_mult) * 60.0) / max(2.0, sim_prep_min), 1)
    sim_peak_demand_hr = round(base_peak_hourly_orders * demand_mult, 1)

    # Shift imbalance penalty across the 2 counters
    shift_factor = 1.0 + (abs(counter_shift_pct) / 100.0) * 0.45
    effective_utilization = (sim_peak_demand_hr * shift_factor) / max(1.0, sim_throughput_hr)
    # Schedule extension spreads peak pressure slightly
    if schedule_ext_mins > 0:
        effective_utilization = max(0.1, effective_utilization * (1.0 - min(0.18, schedule_ext_mins / 1200.0)))

    # M/M/1-inspired wait estimate with safe bounded range
    if effective_utilization >= 0.95:
        est_wait_mid = round(sim_prep_min * (2.5 + min(3.0, effective_utilization - 0.95) * 2.0), 1)
        bottleneck_risk = "high"
    elif effective_utilization >= 0.70:
        est_wait_mid = round(sim_prep_min * (1.35 + (effective_utilization - 0.70) * 3.5), 1)
        bottleneck_risk = "moderate"
    else:
        est_wait_mid = round(sim_prep_min * (1.0 + effective_utilization * 0.4), 1)
        bottleneck_risk = "low"

    est_wait_low = max(1.0, round(est_wait_mid * 0.82, 1))
    est_wait_high = round(est_wait_mid * 1.22, 1)

    baseline = {
        "historical_orders_30d": len(hist_orders),
        "historical_prep_samples": len(prep_samples),
        "baseline_avg_daily_orders": base_daily_orders,
        "baseline_peak_hourly_orders": base_peak_hourly_orders,
        "baseline_median_prep_minutes": base_prep_min,
        "baseline_on_duty_staff": base_staff,
        "baseline_throughput_orders_per_hour": base_throughput_hr,
        "uses_real_historical_baseline": len(hist_orders) > 0,
    }
    outcomes = {
        "is_simulated": True,
        "label": "SIMULATED ESTIMATE — PRODUCTION DATA UNTOUCHED",
        "simulated_staff_count": sim_staff,
        "simulated_prep_minutes": sim_prep_min,
        "simulated_peak_demand_per_hour": sim_peak_demand_hr,
        "simulated_throughput_per_hour": sim_throughput_hr,
        "simulated_utilization_percent": round(min(250.0, effective_utilization * 100.0), 1),
        "estimated_wait_minutes": {
            "low": est_wait_low,
            "expected": est_wait_mid,
            "high": est_wait_high,
        },
        "bottleneck_risk": bottleneck_risk,
        "simulated_unavailable_menu_items": impacted_items,
        "confidence_level": "medium" if len(prep_samples) >= 10 else "low",
    }

    scenario = SimulationScenario(
        canteen_id=canteen_id,
        name=name.strip()[:160],
        description=(description or "").strip() or None,
        parameters_json={
            "staff_delta": staff_delta,
            "prep_capacity_multiplier": prep_cap_mult,
            "demand_multiplier": demand_mult,
            "prep_time_delta_minutes": prep_time_delta,
            "counter_shift_percent": counter_shift_pct,
            "schedule_extension_minutes": schedule_ext_mins,
            "shortage_ingredient_ids": [str(x) for x in valid_ing_ids],
        },
        baseline_snapshot_json=baseline,
        simulated_outcomes_json=outcomes,
        created_by_user_id=actor_user_id,
    )
    db.add(scenario)
    record_audit_log(
        db,
        action="command_center.simulation_executed",
        entity_type="simulation_scenario",
        entity_id=scenario.name,
        actor_user_id=actor_user_id,
        details={"is_simulated": True, "bottleneck_risk": bottleneck_risk},
    )
    db.commit()
    db.refresh(scenario)
    return _serialize_scenario(scenario)


def _serialize_scenario(s: SimulationScenario) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "canteen_id": str(s.canteen_id) if s.canteen_id else None,
        "name": s.name,
        "description": s.description,
        "parameters": s.parameters_json or {},
        "baseline_assumptions": s.baseline_snapshot_json or {},
        "simulated_outcomes": s.simulated_outcomes_json or {},
        "is_simulated": True,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def list_simulations(db: Session, *, limit: int = 30) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(SimulationScenario).order_by(SimulationScenario.created_at.desc()).limit(max(1, min(limit, 100)))
        ).all()
    )
    return [_serialize_scenario(r) for r in rows]


def export_simulation_csv(db: Session, scenario_id: UUID) -> tuple[bytes, str]:
    s = db.get(SimulationScenario, scenario_id)
    if not s:
        raise HTTPException(status_code=404, detail="Simulation scenario not found")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Notice", "SIMULATED SCENARIO REPORT — NO PRODUCTION DATA WAS MODIFIED"])
    w.writerow(["Scenario Name", s.name])
    w.writerow(["Section", "Field", "Value"])
    for k, v in (s.parameters_json or {}).items():
        w.writerow(["Parameter", k, str(v)])
    for k, v in (s.baseline_snapshot_json or {}).items():
        w.writerow(["Baseline", k, str(v)])
    for k, v in (s.simulated_outcomes_json or {}).items():
        w.writerow(["Simulated Outcome", k, str(v)])
    return buf.getvalue().encode("utf-8"), f"collegebites_simulation_{str(s.id)[:8]}.csv"


def export_simulation_pdf(db: Session, scenario_id: UUID) -> tuple[bytes, str]:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    s = db.get(SimulationScenario, scenario_id)
    if not s:
        raise HTTPException(status_code=404, detail="Simulation scenario not found")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, f"CollegeBites What-If Simulation Report: {s.name}")
    y -= 18
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "SIMULATED VALUES ONLY — ZERO PRODUCTION ORDERS, INVENTORY, OR PAYMENTS MODIFIED")
    y -= 24
    c.setFont("Helvetica", 10)
    for title, block in (
        ("Parameters", s.parameters_json or {}),
        ("Historical Baseline Assumptions", s.baseline_snapshot_json or {}),
        ("Simulated Outcomes", s.simulated_outcomes_json or {}),
    ):
        c.setFont("Helvetica-Bold", 11)
        c.drawString(40, y, title)
        y -= 16
        c.setFont("Helvetica", 10)
        for k, v in block.items():
            if y < 60:
                c.showPage()
                y = h - 50
            c.drawString(48, y, f"{k}: {v}")
            y -= 14
        y -= 8
    c.save()
    return buf.getvalue(), f"collegebites_simulation_{str(s.id)[:8]}.pdf"
