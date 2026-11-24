"""
Phase 6: Automated Reordering System Service.
Safety & Non-Negotiable Rules:
- Uses ONLY real unexpired/unreserved inventory, actual incoming open PO quantities, actual 14-day
  consumption movements, verified recipes + ML forecasts (if available), lead time & safety stock.
- NEVER automatically approves purchase orders or transfers money!
- Generates Draft Purchase Orders ONLY after explicit staff/manager trigger, with strict idempotency
  preventing duplicate POs for the same recommendation.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time_utils import today_college
from app.models.enterprise import DemandForecast, ForecastModel, ReorderRecommendation, ReorderRule
from app.models.inventory import InventoryItem, PurchaseOrder, PurchaseOrderItem, StockMovement, Supplier
from app.models.menu import Ingredient, Recipe, RecipeIngredient
from app.services.audit_service import record_audit_log
from app.services.inventory_service import create_purchase_order, get_unexpired_stock_quantity
from app.services.notification_service import notify_procurement_event


def _serialize_rule(rule: ReorderRule, *, ingredient_name: Optional[str] = None, unit: Optional[str] = None, supplier_name: Optional[str] = None) -> dict:
    return {
        "id": str(rule.id),
        "canteen_id": str(rule.canteen_id),
        "inventory_item_id": str(rule.inventory_item_id),
        "ingredient_name": ingredient_name,
        "unit": unit,
        "preferred_supplier_id": str(rule.preferred_supplier_id) if rule.preferred_supplier_id else None,
        "preferred_supplier_name": supplier_name,
        "min_stock_level": str(rule.min_stock_level),
        "reorder_level": str(rule.reorder_level),
        "safety_stock": str(rule.safety_stock),
        "supplier_lead_time_days": rule.supplier_lead_time_days,
        "target_days_of_cover": rule.target_days_of_cover,
        "is_active": rule.is_active,
    }


def list_reorder_rules(db: Session, canteen_id: UUID) -> list[dict]:
    invs = db.execute(
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id, InventoryItem.is_archived.is_(False))
        .order_by(Ingredient.name.asc())
    ).all()
    inv_ids = [inv.id for inv, _ in invs]
    rules = {
        r.inventory_item_id: r
        for r in db.scalars(select(ReorderRule).where(ReorderRule.inventory_item_id.in_(inv_ids))).all()
    } if inv_ids else {}
    sup_ids = {inv.preferred_supplier_id for inv, _ in invs if inv.preferred_supplier_id} | {
        r.preferred_supplier_id for r in rules.values() if r.preferred_supplier_id
    }
    sup_map = {s.id: s for s in db.scalars(select(Supplier).where(Supplier.id.in_(list(sup_ids)))).all()} if sup_ids else {}

    out = []
    for inv, ing in invs:
        rule = rules.get(inv.id)
        if rule:
            sup = sup_map.get(rule.preferred_supplier_id or inv.preferred_supplier_id)
            out.append(_serialize_rule(rule, ingredient_name=ing.name, unit=inv.unit, supplier_name=sup.name if sup else None))
        else:
            sup = sup_map.get(inv.preferred_supplier_id)
            out.append(
                {
                    "id": None,
                    "canteen_id": str(canteen_id),
                    "inventory_item_id": str(inv.id),
                    "ingredient_name": ing.name,
                    "unit": inv.unit,
                    "preferred_supplier_id": str(inv.preferred_supplier_id) if inv.preferred_supplier_id else None,
                    "preferred_supplier_name": sup.name if sup else None,
                    "min_stock_level": "0.000",
                    "reorder_level": str(inv.reorder_level),
                    "safety_stock": "0.000",
                    "supplier_lead_time_days": int(sup.lead_time_days) if sup else 2,
                    "target_days_of_cover": 7,
                    "is_active": True,
                }
            )
    return out


def upsert_reorder_rule(
    db: Session,
    *,
    inventory_item_id: UUID,
    min_stock_level: Decimal,
    reorder_level: Decimal,
    safety_stock: Decimal,
    supplier_lead_time_days: int,
    target_days_of_cover: int,
    preferred_supplier_id: Optional[UUID],
    is_active: bool,
    actor_user_id: UUID,
) -> dict:
    inv = db.get(InventoryItem, inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    if min_stock_level < 0 or reorder_level < 0 or safety_stock < 0:
        raise HTTPException(status_code=400, detail="Thresholds cannot be negative")
    if supplier_lead_time_days < 0 or target_days_of_cover < 1:
        raise HTTPException(status_code=400, detail="Invalid lead time or target days of cover")

    eff_sup_id = preferred_supplier_id or inv.preferred_supplier_id
    if eff_sup_id:
        sup = db.get(Supplier, eff_sup_id)
        if not sup:
            raise HTTPException(status_code=404, detail="Preferred supplier not found")

    rule = db.scalar(select(ReorderRule).where(ReorderRule.inventory_item_id == inv.id))
    if rule:
        rule.min_stock_level = min_stock_level
        rule.reorder_level = reorder_level
        rule.safety_stock = safety_stock
        rule.supplier_lead_time_days = supplier_lead_time_days
        rule.target_days_of_cover = target_days_of_cover
        rule.preferred_supplier_id = eff_sup_id
        rule.is_active = is_active
        rule.updated_by_user_id = actor_user_id
    else:
        rule = ReorderRule(
            canteen_id=inv.canteen_id,
            inventory_item_id=inv.id,
            preferred_supplier_id=eff_sup_id,
            min_stock_level=min_stock_level,
            reorder_level=reorder_level,
            safety_stock=safety_stock,
            supplier_lead_time_days=supplier_lead_time_days,
            target_days_of_cover=target_days_of_cover,
            is_active=is_active,
            updated_by_user_id=actor_user_id,
        )
        db.add(rule)
    inv.reorder_level = reorder_level
    if eff_sup_id:
        inv.preferred_supplier_id = eff_sup_id
    record_audit_log(
        db,
        action="reordering.rule_upserted",
        entity_type="inventory_item",
        entity_id=str(inv.id),
        actor_user_id=actor_user_id,
        details={"reorder_level": str(reorder_level), "safety_stock": str(safety_stock), "lead_time_days": supplier_lead_time_days},
    )
    db.commit()
    db.refresh(rule)
    ing = db.get(Ingredient, inv.ingredient_id)
    sup = db.get(Supplier, rule.preferred_supplier_id) if rule.preferred_supplier_id else None
    return _serialize_rule(rule, ingredient_name=ing.name if ing else None, unit=inv.unit, supplier_name=sup.name if sup else None)


def _serialize_recommendation(
    rec: ReorderRecommendation,
    *,
    ingredient_name: Optional[str] = None,
    unit: Optional[str] = None,
    supplier_name: Optional[str] = None,
    po_number: Optional[str] = None,
) -> dict:
    return {
        "id": str(rec.id),
        "recommendation_number": rec.recommendation_number,
        "canteen_id": str(rec.canteen_id),
        "inventory_item_id": str(rec.inventory_item_id),
        "ingredient_name": ingredient_name,
        "unit": unit,
        "recommended_supplier_id": str(rec.recommended_supplier_id) if rec.recommended_supplier_id else None,
        "recommended_supplier_name": supplier_name,
        "status": rec.status,
        "current_stock": str(rec.current_stock),
        "available_stock": str(rec.available_stock),
        "reserved_stock": str(rec.reserved_stock),
        "incoming_po_stock": str(rec.incoming_po_stock),
        "avg_daily_consumption": str(rec.avg_daily_consumption) if rec.avg_daily_consumption is not None else None,
        "forecasted_demand_qty": str(rec.forecasted_demand_qty) if rec.forecasted_demand_qty is not None else None,
        "lead_time_days": rec.lead_time_days,
        "safety_stock": str(rec.safety_stock),
        "recommended_quantity": str(rec.recommended_quantity),
        "verified_unit_cost": str(rec.verified_unit_cost) if rec.verified_unit_cost is not None else None,
        "estimated_total_cost": str(rec.estimated_total_cost) if rec.estimated_total_cost is not None else None,
        "trigger_reasons": list(rec.trigger_reasons or []),
        "data_classification": rec.data_classification,
        "purchase_order_id": str(rec.purchase_order_id) if rec.purchase_order_id else None,
        "po_number": po_number,
        "notes": rec.notes,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def _forecasted_ingredient_demand_7d(db: Session, canteen_id: UUID) -> dict[UUID, Decimal]:
    """Convert active 7-day DemandForecast predictions into ingredient demand via verified recipes ONLY."""
    active_model = db.scalar(
        select(ForecastModel)
        .where(ForecastModel.canteen_id == canteen_id, ForecastModel.is_active.is_(True))
        .order_by(ForecastModel.trained_at.desc())
        .limit(1)
    )
    if not active_model:
        return {}
    today = today_college()
    end_d = today + timedelta(days=7)
    fc_rows = list(
        db.scalars(
            select(DemandForecast).where(
                DemandForecast.model_id == active_model.id,
                DemandForecast.forecast_date >= today,
                DemandForecast.forecast_date <= end_d,
            )
        ).all()
    )
    if not fc_rows:
        return {}
    food_demand: dict[UUID, Decimal] = {}
    for f in fc_rows:
        food_demand[f.food_item_id] = food_demand.get(f.food_item_id, Decimal("0")) + Decimal(str(f.predicted_quantity))
    recipes = list(
        db.scalars(
            select(Recipe).where(
                Recipe.food_item_id.in_(list(food_demand.keys())),
                Recipe.is_verified.is_(True),
            )
        ).all()
    )
    if not recipes:
        return {}
    rec_by_id = {r.id: r for r in recipes}
    reqs = db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(list(rec_by_id.keys())))).all()
    ing_demand: dict[UUID, Decimal] = {}
    for req in reqs:
        rec = rec_by_id[req.recipe_id]
        f_qty = food_demand.get(rec.food_item_id, Decimal("0"))
        needed = (req.quantity_required * f_qty) / Decimal(max(1, rec.yield_portions))
        ing_demand[req.ingredient_id] = (ing_demand.get(req.ingredient_id, Decimal("0")) + needed).quantize(Decimal("0.001"))
    return ing_demand


def generate_reorder_recommendations(db: Session, canteen_id: UUID, *, actor_user_id: UUID) -> dict:
    invs = db.execute(
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.canteen_id == canteen_id, InventoryItem.is_archived.is_(False))
        .order_by(Ingredient.name.asc())
    ).all()
    if not invs:
        return {"generated_count": 0, "recommendations": [], "message": "No active inventory items configured."}

    inv_ids = [inv.id for inv, _ in invs]
    ing_ids = [inv.ingredient_id for inv, _ in invs]
    rules_map = {
        r.inventory_item_id: r
        for r in db.scalars(select(ReorderRule).where(ReorderRule.inventory_item_id.in_(inv_ids))).all()
    }

    # Incoming verified PO quantities (approved / ordered / partial — excludes draft & cancelled!)
    incoming_by_ing: dict[UUID, Decimal] = {}
    for ing_id, outstanding in db.execute(
        select(
            PurchaseOrderItem.ingredient_id,
            func.coalesce(func.sum(PurchaseOrderItem.quantity_ordered - PurchaseOrderItem.quantity_received), 0),
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
        .where(
            PurchaseOrder.canteen_id == canteen_id,
            PurchaseOrder.status.in_(("approved", "ordered", "partial")),
            PurchaseOrderItem.ingredient_id.in_(ing_ids),
        )
        .group_by(PurchaseOrderItem.ingredient_id)
    ).all():
        incoming_by_ing[ing_id] = max(Decimal("0.000"), Decimal(str(outstanding or 0)))

    # Pending draft / awaiting-approval PO quantities (prevent cross-day duplicate draft POs)
    pending_draft_by_ing: dict[UUID, Decimal] = {}
    for ing_id, qty_draft in db.execute(
        select(
            PurchaseOrderItem.ingredient_id,
            func.coalesce(func.sum(PurchaseOrderItem.quantity_ordered), 0),
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
        .where(
            PurchaseOrder.canteen_id == canteen_id,
            PurchaseOrder.status.in_(("draft", "pending_approval")),
            PurchaseOrderItem.ingredient_id.in_(ing_ids),
        )
        .group_by(PurchaseOrderItem.ingredient_id)
    ).all():
        pending_draft_by_ing[ing_id] = max(Decimal("0.000"), Decimal(str(qty_draft or 0)))

    # Actual 14-day and 3-day consumption rates from real StockMovement records (detects consumption spikes!)
    now_utc = datetime.now(timezone.utc)
    since_14d = now_utc - timedelta(days=14)
    since_3d = now_utc - timedelta(days=3)
    consumed_14d: dict[UUID, Decimal] = {}
    for iid, total_used in db.execute(
        select(StockMovement.inventory_item_id, func.coalesce(func.sum(func.abs(StockMovement.quantity_delta)), 0))
        .where(
            StockMovement.inventory_item_id.in_(inv_ids),
            StockMovement.movement_type.in_(("order_deduct", "production_use")),
            StockMovement.created_at >= since_14d,
        )
        .group_by(StockMovement.inventory_item_id)
    ).all():
        consumed_14d[iid] = Decimal(str(total_used or 0))

    consumed_3d: dict[UUID, Decimal] = {}
    for iid, total_used in db.execute(
        select(StockMovement.inventory_item_id, func.coalesce(func.sum(func.abs(StockMovement.quantity_delta)), 0))
        .where(
            StockMovement.inventory_item_id.in_(inv_ids),
            StockMovement.movement_type.in_(("order_deduct", "production_use")),
            StockMovement.created_at >= since_3d,
        )
        .group_by(StockMovement.inventory_item_id)
    ).all():
        consumed_3d[iid] = Decimal(str(total_used or 0))

    # Items that already have an open unfulfilled draft_po_created recommendation
    open_draft_rec_inv_ids = set(
        db.scalars(
            select(ReorderRecommendation.inventory_item_id).where(
                ReorderRecommendation.canteen_id == canteen_id,
                ReorderRecommendation.status == "draft_po_created",
            )
        ).all()
    )

    fc_demand_7d = _forecasted_ingredient_demand_7d(db, canteen_id)
    today_str = today_college().isoformat()

    created_recs: list[ReorderRecommendation] = []
    for inv, ing in invs:
        rule = rules_map.get(inv.id)
        if rule and not rule.is_active:
            continue

        sup_id = (rule.preferred_supplier_id if rule else None) or inv.preferred_supplier_id
        sup = db.get(Supplier, sup_id) if sup_id else None
        lead_days = int(rule.supplier_lead_time_days) if rule else (int(sup.lead_time_days) if sup else 2)
        target_cover = int(rule.target_days_of_cover) if rule else 7
        reorder_lvl = rule.reorder_level if rule else inv.reorder_level
        safety_stk = rule.safety_stock if rule else Decimal("0.000")
        min_lvl = rule.min_stock_level if rule else Decimal("0.000")

        usable = get_unexpired_stock_quantity(db, inv, exclude_reserved=True)
        incoming = incoming_by_ing.get(inv.ingredient_id, Decimal("0.000"))
        effective_stock = usable + incoming

        used_14 = consumed_14d.get(inv.id, Decimal("0.000"))
        avg_daily = (used_14 / Decimal("14")).quantize(Decimal("0.001")) if used_14 > 0 else None
        used_3 = consumed_3d.get(inv.id, Decimal("0.000"))
        avg_3d = (used_3 / Decimal("3")).quantize(Decimal("0.001")) if used_3 > 0 else Decimal("0.000")
        is_consumption_spike = bool(
            used_3 > 0
            and (
                (avg_daily is not None and avg_daily > 0 and avg_3d >= (avg_daily * Decimal("1.5")))
                or (avg_daily is None and avg_3d > 0)
            )
        )
        fc_7d = fc_demand_7d.get(inv.ingredient_id)
        fc_daily = (fc_7d / Decimal("7")).quantize(Decimal("0.001")) if fc_7d is not None else None
        demand_daily = max(
            avg_daily or Decimal("0.000"),
            avg_3d if is_consumption_spike else Decimal("0.000"),
            fc_daily or Decimal("0.000"),
        )

        lead_time_need = (demand_daily * Decimal(max(1, lead_days))).quantize(Decimal("0.001"))
        reasons: list[str] = []
        if effective_stock <= min_lvl and min_lvl > 0:
            reasons.append(f"Effective stock ({effective_stock} {inv.unit}) at/below min stock ({min_lvl})")
        if effective_stock <= reorder_lvl:
            reasons.append(f"Effective stock ({effective_stock} {inv.unit}, incl. {incoming} incoming) <= reorder level ({reorder_lvl})")
        if is_consumption_spike and effective_stock < (lead_time_need + safety_stk):
            reasons.append(
                f"Verified consumption spike (3d avg {avg_3d}/day vs 14d avg {avg_daily or Decimal('0.000')}/day)"
            )
        elif demand_daily > 0 and effective_stock < (lead_time_need + safety_stk):
            reasons.append(f"Lead-time demand ({lead_time_need}) + safety stock ({safety_stk}) exceeds effective stock")
        if not reasons:
            continue

        # Prevent cross-day duplicate recommendations when a draft/pending PO already covers this shortfall
        pending_draft = pending_draft_by_ing.get(inv.ingredient_id, Decimal("0.000"))
        if (inv.id in open_draft_rec_inv_ids or pending_draft > Decimal("0.000")) and (effective_stock + pending_draft) >= max(
            reorder_lvl, lead_time_need + safety_stk
        ):
            continue

        target_stock = max(reorder_lvl + safety_stk, (demand_daily * Decimal(max(1, target_cover))) + safety_stk)
        rec_qty = max(Decimal("1.000"), (target_stock - effective_stock).quantize(Decimal("0.001")))

        idem_key = f"reorder:{inv.id}:{today_str}"
        existing = db.scalar(
            select(ReorderRecommendation).where(
                ReorderRecommendation.idempotency_key == idem_key,
                ReorderRecommendation.status.in_(("pending_review", "draft_po_created")),
            )
        )
        if existing:
            if existing.status == "pending_review":
                existing.current_stock = inv.current_quantity
                existing.available_stock = usable
                existing.reserved_stock = inv.reserved_quantity
                existing.incoming_po_stock = incoming
                existing.recommended_quantity = rec_qty
                existing.trigger_reasons = reasons
                if inv.unit_cost and inv.unit_cost > 0:
                    existing.verified_unit_cost = inv.unit_cost
                    existing.estimated_total_cost = (rec_qty * inv.unit_cost).quantize(Decimal("0.01"))
            continue

        unit_cost = inv.unit_cost if (inv.unit_cost and inv.unit_cost > 0) else None
        est_total = (rec_qty * unit_cost).quantize(Decimal("0.01")) if unit_cost is not None else None
        now = datetime.now(timezone.utc)
        rec = ReorderRecommendation(
            recommendation_number=f"RDR-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:4].upper()}",
            idempotency_key=idem_key,
            canteen_id=canteen_id,
            inventory_item_id=inv.id,
            recommended_supplier_id=sup.id if sup and sup.is_active else None,
            status="pending_review",
            current_stock=inv.current_quantity,
            available_stock=usable,
            reserved_stock=inv.reserved_quantity,
            incoming_po_stock=incoming,
            avg_daily_consumption=avg_daily,
            forecasted_demand_qty=fc_7d,
            lead_time_days=lead_days,
            safety_stock=safety_stk,
            recommended_quantity=rec_qty,
            verified_unit_cost=unit_cost,
            estimated_total_cost=est_total,
            trigger_reasons=reasons,
            data_classification="calculated",
        )
        db.add(rec)
        created_recs.append(rec)

    if created_recs:
        record_audit_log(
            db,
            action="reordering.recommendations_generated",
            entity_type="canteen",
            entity_id=str(canteen_id),
            actor_user_id=actor_user_id,
            details={"generated_count": len(created_recs)},
        )
        notify_procurement_event(
            db,
            canteen_id=canteen_id,
            event_type="reorder_recommendations_ready",
            po_number=f"RDR-BATCH-{today_str}-{len(created_recs)}",
            title=f"{len(created_recs)} Reorder Recommendation(s) Ready for Review",
            message="Low-stock / lead-time reorder recommendations generated. Review and approve draft purchase orders before ordering.",
            priority="high",
        )
    db.commit()
    all_recs = list_reorder_recommendations(db, canteen_id, status_filter="pending_review")
    return {
        "generated_count": len(created_recs),
        "pending_review_count": len(all_recs),
        "recommendations": all_recs,
    }


def list_reorder_recommendations(
    db: Session, canteen_id: UUID, *, status_filter: Optional[str] = None
) -> list[dict]:
    stmt = select(ReorderRecommendation).where(ReorderRecommendation.canteen_id == canteen_id)
    if status_filter and status_filter != "all":
        stmt = stmt.where(ReorderRecommendation.status == status_filter)
    rows = list(db.scalars(stmt.order_by(ReorderRecommendation.created_at.desc()).limit(150)).all())
    if not rows:
        return []
    inv_ids = {r.inventory_item_id for r in rows}
    inv_rows = db.execute(
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.id.in_(list(inv_ids)))
    ).all()
    inv_info = {inv.id: (ing.name, inv.unit) for inv, ing in inv_rows}
    sup_ids = {r.recommended_supplier_id for r in rows if r.recommended_supplier_id}
    sup_map = {s.id: s.name for s in db.scalars(select(Supplier).where(Supplier.id.in_(list(sup_ids)))).all()} if sup_ids else {}
    po_ids = {r.purchase_order_id for r in rows if r.purchase_order_id}
    po_map = {p.id: p.po_number for p in db.scalars(select(PurchaseOrder).where(PurchaseOrder.id.in_(list(po_ids)))).all()} if po_ids else {}

    return [
        _serialize_recommendation(
            r,
            ingredient_name=inv_info.get(r.inventory_item_id, ("Ingredient", "units"))[0],
            unit=inv_info.get(r.inventory_item_id, ("Ingredient", "units"))[1],
            supplier_name=sup_map.get(r.recommended_supplier_id),
            po_number=po_map.get(r.purchase_order_id),
        )
        for r in rows
    ]


def create_draft_po_from_recommendation(
    db: Session,
    recommendation_id: UUID,
    *,
    supplier_id: Optional[UUID],
    quantity_override: Optional[Decimal],
    unit_cost_override: Optional[Decimal],
    notes: Optional[str],
    actor_user_id: UUID,
) -> dict:
    """Create a DRAFT Purchase Order ONLY (never auto-approved, never transfers funds, duplicate-safe)."""
    rec = db.scalar(
        select(ReorderRecommendation).where(ReorderRecommendation.id == recommendation_id).with_for_update()
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Reorder recommendation not found")
    if rec.status == "dismissed":
        raise HTTPException(status_code=409, detail="Dismissed recommendation cannot create a purchase order")
    if rec.purchase_order_id or rec.status == "draft_po_created":
        raise HTTPException(
            status_code=409,
            detail="A draft purchase order has already been created for this recommendation (duplicate PO blocked)",
        )

    inv = db.get(InventoryItem, rec.inventory_item_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    ing = db.get(Ingredient, inv.ingredient_id)

    eff_sup_id = supplier_id or rec.recommended_supplier_id or inv.preferred_supplier_id
    if not eff_sup_id:
        raise HTTPException(status_code=400, detail="A verified active supplier_id must be selected before creating a draft PO")
    eff_qty = quantity_override if quantity_override is not None else rec.recommended_quantity
    if eff_qty <= Decimal("0.000"):
        raise HTTPException(status_code=400, detail="Order quantity must be greater than zero")
    eff_cost = unit_cost_override if unit_cost_override is not None else (rec.verified_unit_cost or inv.unit_cost)
    if eff_cost is None or eff_cost < Decimal("0.00"):
        raise HTTPException(status_code=400, detail="A verified unit cost is required to create a draft PO")

    po_payload = {
        "canteen_id": rec.canteen_id,
        "supplier_id": eff_sup_id,
        "initial_status": "draft",  # STRICTLY DRAFT — NEVER AUTO-APPROVED!
        "expected_delivery_date": today_college() + timedelta(days=max(1, rec.lead_time_days)),
        "notes": notes or f"Draft PO generated from reorder recommendation {rec.recommendation_number} (requires authorized manager approval)",
        "items": [
            {
                "ingredient_id": inv.ingredient_id,
                "item_name": ing.name if ing else "Ingredient",
                "unit": inv.unit,
                "quantity_ordered": eff_qty,
                "unit_cost": eff_cost,
                "tax_rate_percent": Decimal("0.00"),
            }
        ],
    }
    # Atomic transaction: keep FOR UPDATE lock on rec until both draft PO and recommendation link commit
    po_out = create_purchase_order(db, po_payload, actor_user_id=actor_user_id, can_approve=False, commit=False)

    rec.status = "draft_po_created"
    rec.purchase_order_id = UUID(po_out["id"])
    rec.reviewed_by_user_id = actor_user_id
    rec.reviewed_at = datetime.now(timezone.utc)
    rec.notes = notes
    db.commit()
    db.refresh(rec)

    return {
        "recommendation": _serialize_recommendation(
            rec,
            ingredient_name=ing.name if ing else None,
            unit=inv.unit,
            po_number=po_out["po_number"],
        ),
        "draft_purchase_order": po_out,
        "approval_required": True,
    }


def dismiss_recommendation(db: Session, recommendation_id: UUID, *, notes: Optional[str], actor_user_id: UUID) -> dict:
    rec = db.scalar(select(ReorderRecommendation).where(ReorderRecommendation.id == recommendation_id).with_for_update())
    if not rec:
        raise HTTPException(status_code=404, detail="Reorder recommendation not found")
    if rec.status == "draft_po_created":
        raise HTTPException(status_code=409, detail="Cannot dismiss a recommendation that already generated a draft PO")
    rec.status = "dismissed"
    rec.reviewed_by_user_id = actor_user_id
    rec.reviewed_at = datetime.now(timezone.utc)
    if notes:
        rec.notes = notes
    record_audit_log(
        db,
        action="reordering.recommendation_dismissed",
        entity_type="reorder_recommendation",
        entity_id=rec.recommendation_number,
        actor_user_id=actor_user_id,
        details={"notes": notes},
    )
    db.commit()
    db.refresh(rec)
    return _serialize_recommendation(rec)
