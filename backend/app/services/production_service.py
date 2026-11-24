"""
Phase 5: Kitchen & Food Production Management Service.
- Reuses existing FoodItem, Recipe, RecipeIngredient, InventoryItem, StockBatch, Order, EventBulkOrder.
- Never invents recipes; computes exact verified ingredient requirements and highlights shortages.
- Separates confirmed orders, event bulk orders, and AI demand forecasts to eliminate double-counting.
- Enforces strict 8-state production batch workflow, atomic FIFO/FEFO allocation via traceability_service,
  mandatory Quality Control before completion, and duplicate-deduction protection.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.time_utils import now_college, today_college
from app.models.college import Canteen
from app.models.enterprise import (
    DemandForecast,
    ForecastModel,
    ProductionBatch,
    ProductionBatchIngredient,
    ProductionPlan,
    ProductionQualityCheck,
    TraceabilityRecord,
)
from app.models.event import CollegeEvent, EventBulkOrder, EventBulkOrderItem
from app.models.inventory import InventoryItem, StockBatch, StockMovement, WastageRecord
from app.models.menu import FoodItem, Ingredient, Recipe, RecipeIngredient
from app.models.order import Order, OrderItem
from app.services.audit_service import record_audit_log
from app.services.inventory_service import get_unexpired_stock_quantity, refresh_food_item_ingredient_sufficiency
from app.services.notification_service import notify_food_safety_event
from app.services.traceability_service import allocate_stock_batches

ALLOWED_BATCH_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"ingredients_allocated", "cancelled"},
    "ingredients_allocated": {"ready_for_preparation", "cancelled"},
    "ready_for_preparation": {"preparing", "cancelled"},
    "preparing": {"prepared", "cancelled"},
    "prepared": {"quality_checked", "cancelled"},
    "quality_checked": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _latest_quality_check(checks: list[ProductionQualityCheck]) -> Optional[ProductionQualityCheck]:
    if not checks:
        return None
    return max(checks, key=lambda qc: _ensure_utc(qc.checked_at) or datetime.min.replace(tzinfo=timezone.utc))


# =============================================================================
# 1. VERIFIED RECIPE MANAGEMENT & INGREDIENT REQUIREMENT CHECKS
# =============================================================================


def list_recipes(db: Session, canteen_id: UUID) -> list[dict]:
    foods = list(
        db.scalars(
            select(FoodItem)
            .where(FoodItem.canteen_id == canteen_id, FoodItem.is_active.is_(True))
            .order_by(FoodItem.name.asc())
        ).all()
    )
    if not foods:
        return []
    food_ids = [f.id for f in foods]
    recipes = {r.food_item_id: r for r in db.scalars(select(Recipe).where(Recipe.food_item_id.in_(food_ids))).all()}
    recipe_ids = [r.id for r in recipes.values()]
    reqs_by_recipe: dict[UUID, list[RecipeIngredient]] = {}
    ing_ids: set[UUID] = set()
    if recipe_ids:
        for req in db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(recipe_ids))).all():
            reqs_by_recipe.setdefault(req.recipe_id, []).append(req)
            ing_ids.add(req.ingredient_id)
    ing_map = (
        {i.id: i for i in db.scalars(select(Ingredient).where(Ingredient.id.in_(list(ing_ids)))).all()}
        if ing_ids
        else {}
    )
    inv_map = (
        {
            inv.ingredient_id: inv
            for inv in db.scalars(
                select(InventoryItem).where(
                    InventoryItem.canteen_id == canteen_id,
                    InventoryItem.ingredient_id.in_(list(ing_ids)),
                )
            ).all()
        }
        if ing_ids
        else {}
    )

    out = []
    for f in foods:
        rec = recipes.get(f.id)
        if not rec:
            out.append(
                {
                    "food_item_id": str(f.id),
                    "food_item_name": f.name,
                    "recipe_id": None,
                    "has_recipe": False,
                    "is_verified": False,
                    "yield_portions": None,
                    "instructions": None,
                    "ingredients": [],
                }
            )
            continue
        ing_rows = []
        for req in reqs_by_recipe.get(rec.id, []):
            ing = ing_map.get(req.ingredient_id)
            inv = inv_map.get(req.ingredient_id)
            usable = get_unexpired_stock_quantity(db, inv, exclude_reserved=True) if inv else Decimal("0.000")
            ing_rows.append(
                {
                    "ingredient_id": str(req.ingredient_id),
                    "ingredient_name": ing.name if ing else "Ingredient",
                    "quantity_required": str(req.quantity_required),
                    "unit": ing.unit if ing else (inv.unit if inv else "grams"),
                    "usable_stock": str(usable),
                }
            )
        out.append(
            {
                "food_item_id": str(f.id),
                "food_item_name": f.name,
                "recipe_id": str(rec.id),
                "has_recipe": True,
                "is_verified": bool(rec.is_verified),
                "verified_at": rec.verified_at.isoformat() if rec.verified_at else None,
                "yield_portions": rec.yield_portions,
                "instructions": rec.notes,
                "ingredients": ing_rows,
            }
        )
    return out


def upsert_recipe(
    db: Session,
    *,
    food_item_id: UUID,
    yield_portions: int,
    instructions: Optional[str],
    ingredients: list[dict],
    verify: bool,
    can_verify: bool = True,
    actor_user_id: UUID,
) -> dict:
    food = db.get(FoodItem, food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    if yield_portions < 1:
        raise HTTPException(status_code=400, detail="yield_portions must be >= 1")
    if not ingredients:
        raise HTTPException(status_code=400, detail="Recipe must define at least one real ingredient")
    if verify and not can_verify:
        raise HTTPException(
            status_code=403,
            detail="Only College Admin, Canteen Manager, or Food Safety Inspector can verify recipes",
        )

    rec = db.scalar(select(Recipe).where(Recipe.food_item_id == food.id))
    now = datetime.now(timezone.utc)
    if not rec:
        rec = Recipe(
            food_item_id=food.id,
            yield_portions=yield_portions,
            notes=instructions,
            is_verified=bool(verify and can_verify),
            verified_by_user_id=actor_user_id if (verify and can_verify) else None,
            verified_at=now if (verify and can_verify) else None,
        )
        db.add(rec)
        db.flush()
    else:
        rec.yield_portions = yield_portions
        rec.notes = instructions
        if verify and can_verify:
            rec.is_verified = True
            rec.verified_by_user_id = actor_user_id
            rec.verified_at = now
        else:
            rec.is_verified = False
            rec.verified_by_user_id = None
            rec.verified_at = None
        existing_reqs = list(db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == rec.id)).all())
        for er in existing_reqs:
            db.delete(er)
        db.flush()

    seen_ings: set[UUID] = set()
    for item in ingredients:
        ing_id = UUID(str(item["ingredient_id"]))
        if ing_id in seen_ings:
            raise HTTPException(status_code=400, detail="Duplicate ingredient in recipe")
        seen_ings.add(ing_id)
        ing = db.get(Ingredient, ing_id)
        if not ing:
            raise HTTPException(status_code=404, detail=f"Ingredient {ing_id} not found")
        qty = Decimal(str(item["quantity_required"]))
        if qty <= Decimal("0.000"):
            raise HTTPException(status_code=400, detail="Recipe ingredient quantity must be > 0")
        db.add(
            RecipeIngredient(
                recipe_id=rec.id,
                ingredient_id=ing.id,
                quantity_required=qty,
            )
        )
    db.flush()
    refresh_food_item_ingredient_sufficiency(db, food.canteen_id)
    record_audit_log(
        db,
        action="production.recipe_upserted",
        entity_type="recipe",
        entity_id=str(rec.id),
        actor_user_id=actor_user_id,
        details={"food_item": food.name, "is_verified": rec.is_verified, "ingredients_count": len(seen_ings)},
    )
    db.commit()
    return compute_recipe_requirements(db, food.id, quantity=yield_portions)


def verify_recipe(db: Session, food_item_id: UUID, *, actor_user_id: UUID) -> dict:
    rec = db.scalar(select(Recipe).where(Recipe.food_item_id == food_item_id))
    if not rec:
        raise HTTPException(status_code=404, detail="No recipe configured for this food item")
    reqs = db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == rec.id)).all()
    if not reqs:
        raise HTTPException(status_code=400, detail="Cannot verify an empty recipe with no ingredients")
    rec.is_verified = True
    rec.verified_by_user_id = actor_user_id
    rec.verified_at = datetime.now(timezone.utc)
    record_audit_log(
        db,
        action="production.recipe_verified",
        entity_type="recipe",
        entity_id=str(rec.id),
        actor_user_id=actor_user_id,
    )
    db.commit()
    return compute_recipe_requirements(db, food_item_id, quantity=rec.yield_portions)


def compute_recipe_requirements(db: Session, food_item_id: UUID, *, quantity: int) -> dict:
    food = db.get(FoodItem, food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    rec = db.scalar(select(Recipe).where(Recipe.food_item_id == food.id))
    if not rec:
        return {
            "food_item_id": str(food.id),
            "food_item_name": food.name,
            "has_recipe": False,
            "is_verified": False,
            "target_quantity": quantity,
            "can_produce": False,
            "shortages_count": 0,
            "message": "No verified recipe configured for this item. Please configure recipe ingredients first.",
            "requirements": [],
        }

    reqs = list(db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == rec.id)).all())
    rows = []
    shortages = 0
    for req in reqs:
        ing = db.get(Ingredient, req.ingredient_id)
        inv = db.scalar(
            select(InventoryItem).where(
                InventoryItem.canteen_id == food.canteen_id,
                InventoryItem.ingredient_id == req.ingredient_id,
            )
        )
        needed = ((req.quantity_required * Decimal(quantity)) / Decimal(max(1, rec.yield_portions))).quantize(
            Decimal("0.001")
        )
        usable = get_unexpired_stock_quantity(db, inv, exclude_reserved=True) if inv else Decimal("0.000")
        deficit = max(Decimal("0.000"), needed - usable)
        if deficit > Decimal("0.000"):
            shortages += 1
        rows.append(
            {
                "ingredient_id": str(req.ingredient_id),
                "inventory_item_id": str(inv.id) if inv else None,
                "ingredient_name": ing.name if ing else "Ingredient",
                "unit": ing.unit if ing else (inv.unit if inv else "grams"),
                "required_quantity": str(needed),
                "usable_stock": str(usable),
                "deficit_quantity": str(deficit),
                "is_short": deficit > Decimal("0.000"),
            }
        )
    return {
        "food_item_id": str(food.id),
        "food_item_name": food.name,
        "recipe_id": str(rec.id),
        "has_recipe": True,
        "is_verified": bool(rec.is_verified),
        "yield_portions": rec.yield_portions,
        "target_quantity": quantity,
        "can_produce": bool(rec.is_verified and shortages == 0 and len(rows) > 0),
        "shortages_count": shortages,
        "message": None if shortages == 0 else f"{shortages} ingredient shortage(s) detected against usable stock.",
        "requirements": rows,
    }


# =============================================================================
# 2. PRODUCTION PLANNING DASHBOARD (NO DOUBLE COUNTING)
# =============================================================================


def get_production_planning_overview(db: Session, canteen_id: UUID, *, plan_date: Optional[date] = None) -> dict:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    target_date = plan_date or today_college()

    foods = list(
        db.scalars(
            select(FoodItem)
            .where(FoodItem.canteen_id == canteen_id, FoodItem.is_active.is_(True))
            .order_by(FoodItem.name.asc())
        ).all()
    )

    # 1. Actual confirmed active kitchen orders (NEVER mixed with forecasts)
    active_orders_by_food: dict[UUID, int] = {}
    for fid, q_sum in db.execute(
        select(OrderItem.food_item_id, func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.canteen_id == canteen_id,
            Order.payment_status == "CONFIRMED",
            Order.status.in_(("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING")),
            OrderItem.food_item_id.is_not(None),
        )
        .group_by(OrderItem.food_item_id)
    ).all():
        active_orders_by_food[fid] = int(q_sum or 0)

    # 2. Verified Event Bulk Orders scheduled for target_date
    bulk_by_food: dict[UUID, int] = {}
    for fid, q_sum in db.execute(
        select(EventBulkOrderItem.food_item_id, func.coalesce(func.sum(EventBulkOrderItem.quantity), 0))
        .join(EventBulkOrder, EventBulkOrder.id == EventBulkOrderItem.bulk_order_id)
        .join(CollegeEvent, CollegeEvent.id == EventBulkOrder.event_id)
        .where(
            EventBulkOrder.canteen_id == canteen_id,
            EventBulkOrder.status.in_(("approved", "preparing")),
            EventBulkOrder.payment_status == "CONFIRMED",
            EventBulkOrderItem.food_item_id.is_not(None),
            or_(
                CollegeEvent.event_date == target_date,
                func.date(EventBulkOrder.scheduled_prep_at) == target_date,
            ),
        )
        .group_by(EventBulkOrderItem.food_item_id)
    ).all():
        bulk_by_food[fid] = int(q_sum or 0)

    # 3. Already planned / active production batches for target_date (plan_date -> planned_prep_at -> created_at in college TZ)
    college_tz = now_college().tzinfo
    planned_by_food: dict[UUID, int] = {}
    batch_rows = db.execute(
        select(ProductionBatch, ProductionPlan.plan_date)
        .outerjoin(ProductionPlan, ProductionPlan.id == ProductionBatch.production_plan_id)
        .where(
            ProductionBatch.canteen_id == canteen_id,
            ProductionBatch.status.not_in(["cancelled"]),
        )
    ).all()
    for pb, linked_plan_date in batch_rows:
        if linked_plan_date is not None:
            eff_date = linked_plan_date
        elif pb.planned_prep_at is not None:
            eff_date = _ensure_utc(pb.planned_prep_at).astimezone(college_tz).date()
        elif pb.created_at is not None:
            eff_date = _ensure_utc(pb.created_at).astimezone(college_tz).date()
        else:
            continue
        if eff_date == target_date:
            planned_by_food[pb.food_item_id] = planned_by_food.get(pb.food_item_id, 0) + int(pb.planned_quantity or 0)

    # 4. Active ML Demand Forecast for target_date (strictly labeled ai_predicted)
    forecast_by_food: dict[UUID, float] = {}
    active_model = db.scalar(
        select(ForecastModel)
        .where(ForecastModel.canteen_id == canteen_id, ForecastModel.is_active.is_(True))
        .order_by(ForecastModel.trained_at.desc())
        .limit(1)
    )
    if active_model:
        for fc in db.scalars(
            select(DemandForecast).where(
                DemandForecast.model_id == active_model.id,
                DemandForecast.forecast_date == target_date,
            )
        ).all():
            forecast_by_food[fc.food_item_id] = float(fc.predicted_quantity)

    recipe_map = {
        r.food_item_id: r
        for r in db.scalars(select(Recipe).where(Recipe.food_item_id.in_([f.id for f in foods]))).all()
    } if foods else {}

    items = []
    for f in foods:
        confirmed_active = active_orders_by_food.get(f.id, 0)
        event_bulk = bulk_by_food.get(f.id, 0)
        already_planned = planned_by_food.get(f.id, 0)
        fc_val = forecast_by_food.get(f.id)
        # Prevent double counting: suggested additional prep covers forecast above already confirmed + planned demand
        committed_actual = confirmed_active + event_bulk
        baseline_covered = max(committed_actual, already_planned)
        suggested_additional = (
            max(0, round(fc_val) - baseline_covered) if fc_val is not None else max(0, committed_actual - already_planned)
        )
        rec = recipe_map.get(f.id)
        items.append(
            {
                "food_item_id": str(f.id),
                "food_item_name": f.name,
                "has_verified_recipe": bool(rec and rec.is_verified),
                "confirmed_active_orders_qty": confirmed_active,
                "confirmed_event_bulk_qty": event_bulk,
                "already_planned_batches_qty": already_planned,
                "ai_forecasted_qty": round(fc_val, 1) if fc_val is not None else None,
                "forecast_status": "ai_predicted" if fc_val is not None else "unavailable",
                "suggested_additional_prep_qty": int(suggested_additional),
            }
        )

    return {
        "canteen_id": str(canteen_id),
        "canteen_name": canteen.name,
        "plan_date": target_date.isoformat(),
        "active_forecast_model_version": active_model.model_version if active_model else None,
        "double_counting_guard": "Confirmed active orders, event bulk orders, planned batches, and AI demand forecasts are displayed separately. Suggested additional prep subtracts already confirmed/planned quantities.",
        "items": items,
    }


# =============================================================================
# 3. PRODUCTION PLANS, BATCHES, ALLOCATION & QUALITY CONTROL
# =============================================================================


def create_production_plan(
    db: Session,
    *,
    canteen_id: UUID,
    plan_date: date,
    meal_session: str,
    notes: Optional[str],
    actor_user_id: UUID,
) -> dict:
    now = datetime.now(timezone.utc)
    plan_no = f"PLAN-{plan_date.strftime('%Y%m%d')}-{uuid4().hex[:4].upper()}"
    plan = ProductionPlan(
        plan_number=plan_no,
        canteen_id=canteen_id,
        plan_date=plan_date,
        meal_session=(meal_session or "all_day").strip()[:32],
        status="active",
        notes=notes,
        created_by_user_id=actor_user_id,
    )
    db.add(plan)
    record_audit_log(
        db,
        action="production.plan_created",
        entity_type="production_plan",
        entity_id=plan_no,
        actor_user_id=actor_user_id,
        details={"plan_date": plan_date.isoformat(), "meal_session": plan.meal_session},
    )
    db.commit()
    db.refresh(plan)
    return _serialize_plan(plan)


def _serialize_plan(p: ProductionPlan) -> dict:
    return {
        "id": str(p.id),
        "plan_number": p.plan_number,
        "canteen_id": str(p.canteen_id),
        "plan_date": p.plan_date.isoformat() if p.plan_date else None,
        "meal_session": p.meal_session,
        "status": p.status,
        "notes": p.notes,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def list_production_plans(db: Session, canteen_id: UUID) -> list[dict]:
    rows = db.scalars(
        select(ProductionPlan)
        .where(ProductionPlan.canteen_id == canteen_id)
        .order_by(ProductionPlan.plan_date.desc(), ProductionPlan.created_at.desc())
        .limit(60)
    ).all()
    return [_serialize_plan(r) for r in rows]


def _serialize_batch(db: Session, b: ProductionBatch, food_name: Optional[str] = None) -> dict:
    if food_name is None:
        fi = db.get(FoodItem, b.food_item_id)
        food_name = fi.name if fi else "Food Item"
    duration_min = None
    if b.started_at and b.completed_at:
        s_at = _ensure_utc(b.started_at)
        c_at = _ensure_utc(b.completed_at)
        duration_min = round(max(0.0, (c_at - s_at).total_seconds() / 60.0), 1)
    total_ing_cost = sum(
        (Decimal(str(a.quantity_used)) * Decimal(str(a.unit_cost)) for a in (b.ingredient_allocations or [])),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))
    return {
        "id": str(b.id),
        "batch_code": b.batch_code,
        "idempotency_key": b.idempotency_key,
        "production_plan_id": str(b.production_plan_id) if b.production_plan_id else None,
        "canteen_id": str(b.canteen_id),
        "food_item_id": str(b.food_item_id),
        "food_item_name": food_name,
        "recipe_id": str(b.recipe_id) if b.recipe_id else None,
        "status": b.status,
        "planned_quantity": b.planned_quantity,
        "actual_quantity": b.actual_quantity,
        "sold_quantity": b.sold_quantity,
        "remaining_quantity": b.remaining_quantity,
        "waste_quantity": b.waste_quantity,
        "allocation_strategy": b.allocation_strategy,
        "assigned_staff_user_id": str(b.assigned_staff_user_id) if b.assigned_staff_user_id else None,
        "planned_prep_at": b.planned_prep_at.isoformat() if b.planned_prep_at else None,
        "started_at": b.started_at.isoformat() if b.started_at else None,
        "completed_at": b.completed_at.isoformat() if b.completed_at else None,
        "prep_duration_minutes": duration_min,
        "allocated_ingredient_cost": str(total_ing_cost),
        "notes": b.notes,
        "ingredient_allocations": [
            {
                "id": str(a.id),
                "ingredient_id": str(a.ingredient_id),
                "stock_batch_id": str(a.stock_batch_id),
                "quantity_used": str(a.quantity_used),
                "unit": a.unit,
                "unit_cost": str(a.unit_cost),
                "override_reason": a.override_reason,
            }
            for a in (b.ingredient_allocations or [])
        ],
        "quality_checks": [
            {
                "id": str(qc.id),
                "appearance_ok": qc.appearance_ok,
                "preparation_ok": qc.preparation_ok,
                "hygiene_ok": qc.hygiene_ok,
                "temperature_c": float(qc.temperature_c) if qc.temperature_c is not None else None,
                "status": qc.status,
                "notes": qc.notes,
                "evidence_url": qc.evidence_url,
                "corrective_action": qc.corrective_action,
                "approved_by_user_id": str(qc.approved_by_user_id) if qc.approved_by_user_id else None,
                "checked_at": qc.checked_at.isoformat() if qc.checked_at else None,
            }
            for qc in (b.quality_checks or [])
        ],
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


def create_production_batch(
    db: Session,
    *,
    canteen_id: UUID,
    food_item_id: UUID,
    planned_quantity: int,
    allocation_strategy: str,
    production_plan_id: Optional[UUID],
    assigned_staff_user_id: Optional[UUID],
    planned_prep_at: Optional[datetime],
    notes: Optional[str],
    idempotency_key: Optional[str],
    actor_user_id: UUID,
) -> dict:
    if idempotency_key:
        existing = db.scalar(
            select(ProductionBatch)
            .options(selectinload(ProductionBatch.ingredient_allocations), selectinload(ProductionBatch.quality_checks))
            .where(ProductionBatch.idempotency_key == idempotency_key)
        )
        if existing:
            res = _serialize_batch(db, existing)
            res["idempotent_replay"] = True
            return res

    food = db.get(FoodItem, food_item_id)
    if not food or food.canteen_id != canteen_id:
        raise HTTPException(status_code=404, detail="Food item not found for this canteen")
    if planned_quantity < 1:
        raise HTTPException(status_code=400, detail="planned_quantity must be >= 1")
    strat = (allocation_strategy or "FEFO").strip().upper()
    if strat not in ("FEFO", "FIFO"):
        raise HTTPException(status_code=400, detail="allocation_strategy must be FEFO or FIFO")

    rec = db.scalar(select(Recipe).where(Recipe.food_item_id == food.id))
    now = datetime.now(timezone.utc)
    code = f"PROD-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:4].upper()}"
    batch = ProductionBatch(
        batch_code=code,
        idempotency_key=idempotency_key,
        production_plan_id=production_plan_id,
        canteen_id=canteen_id,
        food_item_id=food.id,
        recipe_id=rec.id if rec else None,
        status="planned",
        planned_quantity=planned_quantity,
        actual_quantity=0,
        sold_quantity=0,
        remaining_quantity=0,
        waste_quantity=0,
        allocation_strategy=strat,
        assigned_staff_user_id=assigned_staff_user_id,
        planned_prep_at=_ensure_utc(planned_prep_at),
        notes=notes,
        created_by_user_id=actor_user_id,
    )
    db.add(batch)
    record_audit_log(
        db,
        action="production.batch_created",
        entity_type="production_batch",
        entity_id=code,
        actor_user_id=actor_user_id,
        details={"food_item": food.name, "planned_quantity": planned_quantity, "strategy": strat},
    )
    db.commit()
    loaded = db.scalar(
        select(ProductionBatch)
        .options(selectinload(ProductionBatch.ingredient_allocations), selectinload(ProductionBatch.quality_checks))
        .where(ProductionBatch.id == batch.id)
    )
    return _serialize_batch(db, loaded, food_name=food.name)


def list_production_batches(db: Session, canteen_id: UUID, *, status_filter: Optional[str] = None, limit: int = 80) -> list[dict]:
    stmt = (
        select(ProductionBatch)
        .options(selectinload(ProductionBatch.ingredient_allocations), selectinload(ProductionBatch.quality_checks))
        .where(ProductionBatch.canteen_id == canteen_id)
    )
    if status_filter and status_filter != "all":
        stmt = stmt.where(ProductionBatch.status == status_filter)
    rows = list(db.scalars(stmt.order_by(ProductionBatch.created_at.desc()).limit(max(1, min(limit, 200)))).all())
    food_ids = list({r.food_item_id for r in rows})
    food_map = (
        {f.id: f.name for f in db.scalars(select(FoodItem).where(FoodItem.id.in_(food_ids))).all()}
        if food_ids
        else {}
    )
    return [_serialize_batch(db, r, food_name=food_map.get(r.food_item_id)) for r in rows]


def transition_production_batch(
    db: Session,
    batch_id: UUID,
    *,
    target_status: str,
    actual_quantity: Optional[int] = None,
    allow_batch_override: bool = False,
    override_reason: Optional[str] = None,
    can_override: bool = False,
    notes: Optional[str] = None,
    actor_user_id: UUID,
) -> dict:
    batch = db.scalar(
        select(ProductionBatch)
        .options(selectinload(ProductionBatch.ingredient_allocations), selectinload(ProductionBatch.quality_checks))
        .where(ProductionBatch.id == batch_id)
        .with_for_update()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Production batch not found")

    target = target_status.strip().lower()
    allowed = ALLOWED_BATCH_TRANSITIONS.get(batch.status, set())
    if target not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid production batch transition '{batch.status}' -> '{target}'. Allowed: {sorted(allowed)}",
        )

    now = datetime.now(timezone.utc)

    # Atomic ingredient allocation when entering ingredients_allocated (duplicate-protected)
    if target == "ingredients_allocated":
        if batch.ingredient_allocations:
            raise HTTPException(status_code=409, detail="Ingredients have already been allocated for this batch")
        rec = db.scalar(select(Recipe).where(Recipe.food_item_id == batch.food_item_id))
        if not rec or not rec.is_verified:
            raise HTTPException(
                status_code=400,
                detail="Cannot allocate ingredients: a verified recipe is required for this food item",
            )
        reqs = list(db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == rec.id)).all())
        if not reqs:
            raise HTTPException(status_code=400, detail="Recipe has no ingredients configured")

        batch.recipe_id = rec.id
        for req in reqs:
            inv = db.scalar(
                select(InventoryItem).where(
                    InventoryItem.canteen_id == batch.canteen_id,
                    InventoryItem.ingredient_id == req.ingredient_id,
                )
            )
            if not inv:
                ing = db.get(Ingredient, req.ingredient_id)
                raise HTTPException(
                    status_code=409,
                    detail=f"No inventory record found for required ingredient '{ing.name if ing else req.ingredient_id}'",
                )
            needed = ((req.quantity_required * Decimal(batch.planned_quantity)) / Decimal(max(1, rec.yield_portions))).quantize(
                Decimal("0.001")
            )
            allocs = allocate_stock_batches(
                db,
                inventory_item_id=inv.id,
                required_qty=needed,
                strategy=batch.allocation_strategy,
                allow_override=allow_batch_override,
                override_reason=override_reason,
                can_override=can_override,
                actor_user_id=actor_user_id,
                reference_type="production_batch",
                reference_id=str(batch.id),
            )
            for al in allocs:
                db.add(
                    ProductionBatchIngredient(
                        production_batch_id=batch.id,
                        ingredient_id=al["ingredient_id"],
                        inventory_item_id=al["inventory_item_id"],
                        stock_batch_id=al["stock_batch_id"],
                        quantity_used=al["quantity_used"],
                        unit=al["unit"],
                        unit_cost=al["unit_cost"],
                        override_approved_by=actor_user_id if al["override_used"] else None,
                        override_reason=al["override_reason"],
                    )
                )
                missing = []
                if not al["supplier_id"]:
                    missing.append("supplier_id")
                if not al["purchase_order_id"]:
                    missing.append("purchase_order_id")
                if not al["goods_receipt_id"]:
                    missing.append("goods_receipt_id")
                missing.append("order_id")
                db.add(
                    TraceabilityRecord(
                        canteen_id=batch.canteen_id,
                        supplier_id=al["supplier_id"],
                        purchase_order_id=al["purchase_order_id"],
                        goods_receipt_id=al["goods_receipt_id"],
                        stock_batch_id=al["stock_batch_id"],
                        recipe_id=rec.id,
                        production_batch_id=batch.id,
                        food_item_id=batch.food_item_id,
                        trace_completeness="partial",
                        missing_links=missing,
                        notes=f"Allocated {al['quantity_used']} {al['unit']} to production batch {batch.batch_code}",
                    )
                )
        refresh_food_item_ingredient_sufficiency(db, batch.canteen_id)

    elif target == "preparing":
        batch.started_at = batch.started_at or now
    elif target == "prepared":
        if actual_quantity is not None:
            if actual_quantity < 0:
                raise HTTPException(status_code=400, detail="actual_quantity cannot be negative")
            batch.actual_quantity = actual_quantity
        elif batch.actual_quantity == 0:
            batch.actual_quantity = batch.planned_quantity
        batch.remaining_quantity = max(0, batch.actual_quantity - batch.sold_quantity - batch.waste_quantity)
    elif target == "quality_checked":
        latest_qc = _latest_quality_check(batch.quality_checks or [])
        passed_qc = bool(
            latest_qc
            and (
                latest_qc.status == "passed"
                or (latest_qc.status == "corrective_action_required" and latest_qc.approved_by_user_id is not None)
            )
        )
        if not passed_qc:
            raise HTTPException(
                status_code=400,
                detail="The latest quality check must be passed (or have authorized corrective action approval) before marking quality_checked",
            )
    elif target == "completed":
        latest_qc = _latest_quality_check(batch.quality_checks or [])
        passed_qc = bool(
            latest_qc
            and (
                latest_qc.status == "passed"
                or (latest_qc.status == "corrective_action_required" and latest_qc.approved_by_user_id is not None)
            )
        )
        if not passed_qc:
            raise HTTPException(status_code=400, detail="Production batch cannot be completed without passing latest quality control")
        batch.completed_at = now
        if actual_quantity is not None and actual_quantity >= 0:
            batch.actual_quantity = actual_quantity
        batch.remaining_quantity = max(0, batch.actual_quantity - batch.sold_quantity - batch.waste_quantity)
    elif target == "cancelled" and batch.status in ("ingredients_allocated", "ready_for_preparation") and batch.ingredient_allocations:
        # Return un-cooked allocated ingredient stock back to original stock batches & inventory
        for al in batch.ingredient_allocations:
            qty_ret = Decimal(str(al.quantity_used or "0"))
            if qty_ret <= Decimal("0.000"):
                continue
            sb = db.scalar(select(StockBatch).where(StockBatch.id == al.stock_batch_id).with_for_update())
            inv = db.scalar(select(InventoryItem).where(InventoryItem.id == al.inventory_item_id).with_for_update())
            if sb:
                sb.remaining_quantity += qty_ret
                sb.allocated_quantity = max(Decimal("0.000"), (sb.allocated_quantity or Decimal("0.000")) - qty_ret)
                sb.consumed_quantity = max(Decimal("0.000"), (sb.consumed_quantity or Decimal("0.000")) - qty_ret)
            if inv:
                inv.current_quantity += qty_ret
                db.add(
                    StockMovement(
                        inventory_item_id=inv.id,
                        batch_id=sb.id if sb else None,
                        movement_type="production_cancel_return",
                        quantity_delta=qty_ret,
                        balance_after=inv.current_quantity,
                        reference_type="production_batch_cancelled",
                        reference_id=str(batch.id),
                        created_by_user_id=actor_user_id,
                        notes=f"Returned allocated ingredients from cancelled batch {batch.batch_code}",
                    )
                )
        refresh_food_item_ingredient_sufficiency(db, batch.canteen_id)

    prev = batch.status
    batch.status = target
    if notes:
        batch.notes = f"{(batch.notes or '').strip()} [{target}: {notes.strip()}]".strip()

    record_audit_log(
        db,
        action=f"production.batch_{target}",
        entity_type="production_batch",
        entity_id=batch.batch_code,
        actor_user_id=actor_user_id,
        details={"from_status": prev, "to_status": target, "actual_quantity": batch.actual_quantity},
    )
    db.commit()
    loaded = db.scalar(
        select(ProductionBatch)
        .options(selectinload(ProductionBatch.ingredient_allocations), selectinload(ProductionBatch.quality_checks))
        .where(ProductionBatch.id == batch.id)
    )
    return _serialize_batch(db, loaded)


def record_quality_check(
    db: Session,
    batch_id: UUID,
    *,
    appearance_ok: bool,
    preparation_ok: bool,
    hygiene_ok: bool,
    temperature_c: Optional[Decimal],
    status: str,
    notes: Optional[str],
    evidence_url: Optional[str],
    corrective_action: Optional[str],
    approve_corrective_action: bool,
    can_approve: bool,
    actor_user_id: UUID,
) -> dict:
    batch = db.scalar(
        select(ProductionBatch)
        .options(selectinload(ProductionBatch.ingredient_allocations), selectinload(ProductionBatch.quality_checks))
        .where(ProductionBatch.id == batch_id)
        .with_for_update()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Production batch not found")
    if batch.status not in ("prepared", "quality_checked"):
        raise HTTPException(
            status_code=409,
            detail=f"Quality checks can only be recorded for prepared or quality_checked batches (current: {batch.status})",
        )
    st = status.strip().lower()
    if st not in ("passed", "failed", "corrective_action_required"):
        raise HTTPException(status_code=400, detail="status must be passed, failed, or corrective_action_required")
    if st == "passed" and not (appearance_ok and preparation_ok and hygiene_ok):
        raise HTTPException(status_code=400, detail="Cannot mark quality check as passed when an inspection check failed")
    if (st == "corrective_action_required" or approve_corrective_action) and not (corrective_action and corrective_action.strip()):
        raise HTTPException(status_code=400, detail="corrective_action description is required")
    if approve_corrective_action and not can_approve:
        raise HTTPException(status_code=403, detail="Only manager, admin, or food safety inspector may approve corrective actions")

    qc = ProductionQualityCheck(
        production_batch_id=batch.id,
        appearance_ok=appearance_ok,
        preparation_ok=preparation_ok,
        hygiene_ok=hygiene_ok,
        temperature_c=temperature_c,
        status=st,
        notes=notes,
        evidence_url=evidence_url,
        corrective_action=corrective_action,
        checked_by_user_id=actor_user_id,
        approved_by_user_id=actor_user_id if (approve_corrective_action and can_approve) else None,
        checked_at=datetime.now(timezone.utc),
    )
    db.add(qc)
    db.flush()
    record_audit_log(
        db,
        action="production.quality_check_recorded",
        entity_type="production_batch",
        entity_id=batch.batch_code,
        actor_user_id=actor_user_id,
        details={"qc_status": st, "temperature_c": str(temperature_c) if temperature_c is not None else None},
    )
    if st == "failed":
        notify_food_safety_event(
            db,
            canteen_id=batch.canteen_id,
            event_type="production_qc_failed",
            ref_id=f"{batch.batch_code}:{qc.id}",
            title=f"Production Quality Control Failed • {batch.batch_code}",
            message=f"Quality check FAILED for batch {batch.batch_code}. Notes: {(notes or 'Review required')[:150]}",
            priority="critical",
        )
    db.commit()
    loaded = db.scalar(
        select(ProductionBatch)
        .options(selectinload(ProductionBatch.ingredient_allocations), selectinload(ProductionBatch.quality_checks))
        .where(ProductionBatch.id == batch.id)
    )
    return _serialize_batch(db, loaded)


def update_batch_quantities(
    db: Session,
    batch_id: UUID,
    *,
    actual_quantity: Optional[int],
    sold_quantity: Optional[int],
    waste_quantity: Optional[int],
    waste_reason: Optional[str],
    actor_user_id: UUID,
) -> dict:
    batch = db.scalar(
        select(ProductionBatch)
        .options(selectinload(ProductionBatch.ingredient_allocations), selectinload(ProductionBatch.quality_checks))
        .where(ProductionBatch.id == batch_id)
        .with_for_update()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Production batch not found")

    prev_waste = batch.waste_quantity
    if actual_quantity is not None:
        if actual_quantity < 0:
            raise HTTPException(status_code=400, detail="actual_quantity cannot be negative")
        batch.actual_quantity = actual_quantity
    if sold_quantity is not None:
        if sold_quantity < 0:
            raise HTTPException(status_code=400, detail="sold_quantity cannot be negative")
        batch.sold_quantity = sold_quantity
    if waste_quantity is not None:
        if waste_quantity < 0:
            raise HTTPException(status_code=400, detail="waste_quantity cannot be negative")
        batch.waste_quantity = waste_quantity

    max_producible = batch.actual_quantity if batch.actual_quantity > 0 else batch.planned_quantity
    if (batch.sold_quantity + batch.waste_quantity) > max_producible:
        raise HTTPException(status_code=400, detail="sold_quantity + waste_quantity cannot exceed produced quantity")
    batch.remaining_quantity = max(0, batch.actual_quantity - batch.sold_quantity - batch.waste_quantity)

    # Record verified wastage entry ONLY for actual delta > 0
    waste_delta = batch.waste_quantity - prev_waste
    if waste_delta > 0:
        fi = db.get(FoodItem, batch.food_item_id)
        per_unit_cost = Decimal("0.00")
        if batch.ingredient_allocations and max(1, batch.actual_quantity) > 0:
            tot_cost = sum(
                (Decimal(str(a.quantity_used)) * Decimal(str(a.unit_cost)) for a in batch.ingredient_allocations),
                Decimal("0.00"),
            )
            per_unit_cost = (tot_cost / Decimal(max(1, batch.actual_quantity))).quantize(Decimal("0.01"))
        db.add(
            WastageRecord(
                canteen_id=batch.canteen_id,
                food_item_id=batch.food_item_id,
                source_type="prepared_food",
                quantity=Decimal(waste_delta),
                loss_type="unsold",
                reason=(waste_reason or f"Production batch {batch.batch_code} recorded waste")[:255],
                waste_date=today_college(),
                estimated_loss=(per_unit_cost * Decimal(waste_delta)).quantize(Decimal("0.01")),
                recorded_by_user_id=actor_user_id,
            )
        )

    record_audit_log(
        db,
        action="production.batch_quantities_updated",
        entity_type="production_batch",
        entity_id=batch.batch_code,
        actor_user_id=actor_user_id,
        details={
            "actual": batch.actual_quantity,
            "sold": batch.sold_quantity,
            "waste": batch.waste_quantity,
            "remaining": batch.remaining_quantity,
        },
    )
    db.commit()
    return _serialize_batch(db, batch)


def report_production_delay(
    db: Session,
    batch_id: UUID,
    *,
    delay_minutes: int,
    reason: str,
    actor_user_id: UUID,
) -> dict:
    batch = db.scalar(
        select(ProductionBatch)
        .options(selectinload(ProductionBatch.ingredient_allocations), selectinload(ProductionBatch.quality_checks))
        .where(ProductionBatch.id == batch_id)
        .with_for_update()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Production batch not found")
    if batch.status in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Cannot report delay on {batch.status} batch")
    batch.notes = f"{(batch.notes or '').strip()} [DELAY +{delay_minutes}m: {reason.strip()}]".strip()
    record_audit_log(
        db,
        action="production.batch_delayed",
        entity_type="production_batch",
        entity_id=batch.batch_code,
        actor_user_id=actor_user_id,
        details={"delay_minutes": delay_minutes, "reason": reason.strip()},
    )
    from app.services.notification_service import create_role_notifications

    create_role_notifications(
        db,
        canteen_id=batch.canteen_id,
        roles=["canteen_manager", "college_admin", "kitchen_staff"],
        event_type="production_delay",
        category="order",
        title=f"Production Batch Delayed • {batch.batch_code} (+{delay_minutes}m)",
        message=f"Batch {batch.batch_code} delayed by {delay_minutes} min: {reason.strip()[:160]}",
        priority="high",
        event_id_base=f"prod_delay:{batch.id}:{delay_minutes}:{reason.strip()[:32]}",
    )
    db.commit()
    return _serialize_batch(db, batch)


def get_production_report(db: Session, canteen_id: UUID, *, days: int = 30) -> dict:
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    batches = list(
        db.scalars(
            select(ProductionBatch)
            .options(selectinload(ProductionBatch.ingredient_allocations), selectinload(ProductionBatch.quality_checks))
            .where(ProductionBatch.canteen_id == canteen_id, ProductionBatch.created_at >= since)
            .order_by(ProductionBatch.created_at.desc())
        ).all()
    )
    if not batches:
        return {
            "canteen_id": str(canteen_id),
            "lookback_days": days,
            "data_classification": "actual",
            "empty": True,
            "message": "No production batches recorded for the selected period.",
            "total_batches": 0,
            "completed_batches": 0,
            "total_planned_qty": 0,
            "total_actual_qty": 0,
            "total_sold_qty": 0,
            "total_remaining_qty": 0,
            "total_waste_qty": 0,
            "total_ingredient_cost": "0.00",
            "average_prep_duration_minutes": None,
            "by_item": [],
            "ingredient_consumption": [],
        }

    food_ids = list({b.food_item_id for b in batches})
    food_map = {f.id: f.name for f in db.scalars(select(FoodItem).where(FoodItem.id.in_(food_ids))).all()}
    ing_ids = list({a.ingredient_id for b in batches for a in (b.ingredient_allocations or [])})
    ing_map = {i.id: i.name for i in db.scalars(select(Ingredient).where(Ingredient.id.in_(ing_ids))).all()} if ing_ids else {}
    tot_planned = tot_actual = tot_sold = tot_rem = tot_waste = completed = 0
    tot_cost = Decimal("0.00")
    durations: list[float] = []
    by_item: dict[UUID, dict] = {}
    by_ingredient: dict[UUID, dict] = {}

    for b in batches:
        if b.status == "cancelled":
            continue
        if b.status == "completed":
            completed += 1
        tot_planned += b.planned_quantity
        tot_actual += b.actual_quantity
        tot_sold += b.sold_quantity
        tot_rem += b.remaining_quantity
        tot_waste += b.waste_quantity
        b_cost = Decimal("0.00")
        for a in (b.ingredient_allocations or []):
            qty_u = Decimal(str(a.quantity_used or "0"))
            line_c = qty_u * Decimal(str(a.unit_cost or "0"))
            b_cost += line_c
            irow = by_ingredient.setdefault(
                a.ingredient_id,
                {
                    "ingredient_id": str(a.ingredient_id),
                    "ingredient_name": ing_map.get(a.ingredient_id, "Ingredient"),
                    "unit": a.unit,
                    "quantity_consumed": Decimal("0.000"),
                    "total_cost": Decimal("0.00"),
                },
            )
            irow["quantity_consumed"] += qty_u
            irow["total_cost"] += line_c
        tot_cost += b_cost
        if b.started_at and b.completed_at:
            durations.append(max(0.0, (_ensure_utc(b.completed_at) - _ensure_utc(b.started_at)).total_seconds() / 60.0))
        row = by_item.setdefault(
            b.food_item_id,
            {
                "food_item_id": str(b.food_item_id),
                "food_item_name": food_map.get(b.food_item_id, "Item"),
                "batches_count": 0,
                "planned_quantity": 0,
                "actual_quantity": 0,
                "sold_quantity": 0,
                "remaining_quantity": 0,
                "waste_quantity": 0,
                "ingredient_cost": Decimal("0.00"),
            },
        )
        row["batches_count"] += 1
        row["planned_quantity"] += b.planned_quantity
        row["actual_quantity"] += b.actual_quantity
        row["sold_quantity"] += b.sold_quantity
        row["remaining_quantity"] += b.remaining_quantity
        row["waste_quantity"] += b.waste_quantity
        row["ingredient_cost"] += b_cost

    return {
        "canteen_id": str(canteen_id),
        "lookback_days": days,
        "data_classification": "actual",
        "empty": False,
        "message": None,
        "total_batches": len(batches),
        "completed_batches": completed,
        "total_planned_qty": tot_planned,
        "total_actual_qty": tot_actual,
        "total_sold_qty": tot_sold,
        "total_remaining_qty": tot_rem,
        "total_waste_qty": tot_waste,
        "total_ingredient_cost": f"{tot_cost.quantize(Decimal('0.01')):.2f}",
        "average_prep_duration_minutes": round(sum(durations) / len(durations), 1) if durations else None,
        "by_item": [
            {**v, "ingredient_cost": f"{v['ingredient_cost'].quantize(Decimal('0.01')):.2f}"}
            for v in sorted(by_item.values(), key=lambda x: -x["planned_quantity"])
        ],
        "ingredient_consumption": [
            {
                **v,
                "quantity_consumed": str(v["quantity_consumed"].quantize(Decimal("0.001"))),
                "total_cost": f"{v['total_cost'].quantize(Decimal('0.01')):.2f}",
            }
            for v in sorted(by_ingredient.values(), key=lambda x: -x["total_cost"])
        ],
    }
