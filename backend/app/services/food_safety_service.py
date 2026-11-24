"""
Phase 3: Food Safety & Hygiene Compliance Service.
Strict Zero-Fabrication Policy:
- Equipment temperature ranges MUST be explicitly configured by admin/manager (min_temp_c < max_temp_c).
- Dashboard reports strictly ACTUAL recorded DB counts (never fabricates compliance percentages when no inspections exist).
- Expiry monitoring reuses existing StockBatch + InventoryItem tables (zero duplication).
"""

import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.time_utils import today_college
from app.models.auth import User
from app.models.college import Canteen
from app.models.enterprise import (
    CleaningSchedule,
    CleaningTaskLog,
    EquipmentTemperatureConfig,
    EquipmentTemperatureLog,
    FoodSafetyChecklistTemplate,
    FoodSafetyIncident,
    FoodSafetyInspection,
    FoodSafetyInspectionItem,
)
from app.models.inventory import InventoryItem, StockBatch, StockMovement, WastageRecord
from app.models.menu import Ingredient
from app.services.audit_service import record_audit_log
from app.services.notification_service import notify_food_safety_event, notify_inventory_expiry_alert

DEFAULT_HYGIENE_CHECKLIST_ITEMS: list[dict[str, Any]] = [
    {"code": "KITCHEN_CLEAN", "title": "Kitchen floor, counters & prep stations sanitized", "category": "kitchen", "required": True},
    {"code": "EQUIP_SANITIZED", "title": "Cooking vessels, knives & cutting boards sanitized", "category": "equipment", "required": True},
    {"code": "TEMP_VERIFIED", "title": "Refrigerator, freezer & hot-holding temperatures verified", "category": "temperature", "required": True},
    {"code": "STORAGE_HYGIENE", "title": "Raw & cooked food separated, labeled & covered in storage", "category": "storage", "required": True},
    {"code": "STAFF_HYGIENE", "title": "Staff wearing clean uniforms, hairnets, aprons & gloves", "category": "staff_hygiene", "required": True},
    {"code": "WATER_SAFETY", "title": "Potable water supply & filtration unit verified", "category": "water_safety", "required": True},
    {"code": "WASTE_DISPOSAL", "title": "Covered garbage bins emptied & waste area sanitized", "category": "waste_disposal", "required": True},
    {"code": "PEST_CONTROL", "title": "No signs of pests; fly catchers & mesh screens intact", "category": "pest_control", "required": True},
    {"code": "EXPIRY_CHECK", "title": "Perishable ingredients checked for expiry & FEFO rotation", "category": "storage", "required": True},
    {"code": "COUNTER_HYGIENE", "title": "Serving counter, sneeze guards & pickup trays sanitized", "category": "serving_counter", "required": True},
]

VALID_INCIDENT_STATUSES = ("open", "under_investigation", "resolved", "closed")
VALID_SEVERITIES = ("low", "medium", "high", "critical")
VALID_FREQUENCIES = ("daily", "weekly", "monthly")
VALID_EQUIP_TYPES = ("refrigerator", "freezer", "storage_unit", "prep_equipment", "holding_equipment")


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _user_name_map(db: Session, user_ids: set[UUID]) -> dict[UUID, str]:
    if not user_ids:
        return {}
    return {u.id: (u.full_name or u.email) for u in db.scalars(select(User).where(User.id.in_(list(user_ids)))).all()}


# =============================================================================
# 1. CHECKLIST TEMPLATES & DAILY HYGIENE INSPECTIONS
# =============================================================================


def list_checklist_templates(db: Session, canteen_id: Optional[UUID] = None, *, seed_default_if_empty: bool = False) -> list[dict]:
    stmt = select(FoodSafetyChecklistTemplate).where(FoodSafetyChecklistTemplate.is_active.is_(True))
    if canteen_id:
        stmt = stmt.where((FoodSafetyChecklistTemplate.canteen_id == canteen_id) | (FoodSafetyChecklistTemplate.canteen_id.is_(None)))
    rows = list(db.scalars(stmt.order_by(FoodSafetyChecklistTemplate.created_at.desc())).all())
    if not rows and seed_default_if_empty and canteen_id:
        tpl = FoodSafetyChecklistTemplate(
            canteen_id=canteen_id,
            name="Standard Daily Canteen Hygiene Checklist",
            category="daily_hygiene",
            items_json=DEFAULT_HYGIENE_CHECKLIST_ITEMS,
            is_active=True,
        )
        db.add(tpl)
        db.commit()
        db.refresh(tpl)
        rows = [tpl]
    return [
        {
            "id": str(t.id),
            "canteen_id": str(t.canteen_id) if t.canteen_id else None,
            "name": t.name,
            "category": t.category,
            "items": list(t.items_json or []),
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]


def create_checklist_template(
    db: Session,
    *,
    canteen_id: Optional[UUID],
    name: str,
    category: str,
    items: list[dict],
    actor_user_id: UUID,
) -> dict:
    if not items:
        raise HTTPException(status_code=400, detail="Checklist template must contain at least one inspection item")
    cleaned = []
    for idx, it in enumerate(items, start=1):
        code = str(it.get("code") or f"CHK_{idx:02d}").strip().upper()[:64]
        title = str(it.get("title") or "").strip()[:200]
        if not title:
            raise HTTPException(status_code=400, detail="Each checklist item must include a title")
        cleaned.append(
            {
                "code": code,
                "title": title,
                "category": str(it.get("category") or category or "general")[:64],
                "required": bool(it.get("required", True)),
            }
        )
    tpl = FoodSafetyChecklistTemplate(
        canteen_id=canteen_id,
        name=name.strip(),
        category=(category or "daily_hygiene").strip()[:64],
        items_json=cleaned,
        is_active=True,
        created_by_user_id=actor_user_id,
    )
    db.add(tpl)
    record_audit_log(
        db,
        action="food_safety.template_created",
        entity_type="food_safety_checklist_template",
        entity_id=tpl.name,
        actor_user_id=actor_user_id,
        details={"canteen_id": str(canteen_id) if canteen_id else None, "items_count": len(cleaned)},
    )
    db.commit()
    db.refresh(tpl)
    return {
        "id": str(tpl.id),
        "canteen_id": str(tpl.canteen_id) if tpl.canteen_id else None,
        "name": tpl.name,
        "category": tpl.category,
        "items": list(tpl.items_json or []),
        "is_active": tpl.is_active,
        "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
    }


def _serialize_inspection(insp: FoodSafetyInspection, inspector_name: Optional[str] = None) -> dict:
    evaluated = insp.passed_items + insp.failed_items
    pass_rate = round((insp.passed_items / evaluated) * 100.0, 1) if evaluated > 0 else None
    return {
        "id": str(insp.id),
        "inspection_number": insp.inspection_number,
        "canteen_id": str(insp.canteen_id),
        "template_id": str(insp.template_id) if insp.template_id else None,
        "inspector_user_id": str(insp.inspector_user_id) if insp.inspector_user_id else None,
        "inspector_name": inspector_name,
        "inspected_at": insp.inspected_at.isoformat() if insp.inspected_at else None,
        "overall_status": insp.overall_status,
        "total_items": insp.total_items,
        "passed_items": insp.passed_items,
        "failed_items": insp.failed_items,
        "na_items": insp.na_items,
        "pass_rate_percent": pass_rate,
        "notes": insp.notes,
        "photo_urls": list(insp.photo_urls or []),
        "data_classification": "actual",
        "items": [
            {
                "id": str(it.id),
                "item_code": it.item_code,
                "item_title": it.item_title,
                "category": it.category,
                "result": it.result,
                "notes": it.notes,
                "photo_url": it.photo_url,
            }
            for it in (insp.items or [])
        ],
    }


def create_inspection(
    db: Session,
    *,
    canteen_id: UUID,
    template_id: Optional[UUID],
    items: list[dict],
    notes: Optional[str],
    photo_urls: Optional[list[str]],
    inspected_at: Optional[datetime],
    actor_user_id: UUID,
) -> dict:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    if not items:
        raise HTTPException(status_code=400, detail="Inspection requires at least one checklist item result")

    passed = failed = na = 0
    item_models: list[FoodSafetyInspectionItem] = []
    failed_titles: list[str] = []
    for raw in items:
        res = str(raw.get("result") or "").strip().lower()
        if res not in ("pass", "fail", "not_applicable"):
            raise HTTPException(status_code=400, detail=f"Invalid item result '{res}'; expected pass, fail, or not_applicable")
        if res == "pass":
            passed += 1
        elif res == "fail":
            failed += 1
            failed_titles.append(str(raw.get("item_title") or raw.get("item_code") or "Item"))
        else:
            na += 1
        item_models.append(
            FoodSafetyInspectionItem(
                item_code=str(raw.get("item_code") or "CHK")[:64],
                item_title=str(raw.get("item_title") or "Checklist Item")[:200],
                category=str(raw.get("category") or "general")[:64],
                result=res,
                notes=raw.get("notes"),
                photo_url=raw.get("photo_url"),
            )
        )

    overall = "fail" if failed > 0 else ("pass" if passed > 0 else "partial")
    now = _ensure_utc(inspected_at) or datetime.now(timezone.utc)
    insp_no = f"FSI-CHK-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:4].upper()}"
    insp = FoodSafetyInspection(
        inspection_number=insp_no,
        canteen_id=canteen_id,
        template_id=template_id,
        inspector_user_id=actor_user_id,
        inspected_at=now,
        overall_status=overall,
        total_items=len(item_models),
        passed_items=passed,
        failed_items=failed,
        na_items=na,
        notes=notes,
        photo_urls=list(photo_urls or []),
        items=item_models,
    )
    db.add(insp)
    db.flush()

    record_audit_log(
        db,
        action="food_safety.inspection_recorded",
        entity_type="food_safety_inspection",
        entity_id=insp_no,
        actor_user_id=actor_user_id,
        details={"overall_status": overall, "passed": passed, "failed": failed, "na": na},
    )

    if failed > 0:
        notify_food_safety_event(
            db,
            canteen_id=canteen_id,
            event_type="food_safety_inspection_failed",
            ref_id=insp_no,
            title=f"Hygiene Inspection Failed • {insp_no}",
            message=f"{failed} of {len(item_models)} items failed at {canteen.name}: {', '.join(failed_titles[:4])}.",
            priority="critical" if failed >= 3 else "high",
        )
    db.commit()
    loaded = db.scalar(
        select(FoodSafetyInspection)
        .options(selectinload(FoodSafetyInspection.items))
        .where(FoodSafetyInspection.id == insp.id)
    )
    u_map = _user_name_map(db, {actor_user_id})
    return _serialize_inspection(loaded, inspector_name=u_map.get(actor_user_id))


def list_inspections(db: Session, canteen_id: UUID, *, limit: int = 50) -> list[dict]:
    rows = list(
        db.scalars(
            select(FoodSafetyInspection)
            .options(selectinload(FoodSafetyInspection.items))
            .where(FoodSafetyInspection.canteen_id == canteen_id)
            .order_by(FoodSafetyInspection.inspected_at.desc())
            .limit(max(1, min(limit, 200)))
        ).all()
    )
    u_ids = {r.inspector_user_id for r in rows if r.inspector_user_id}
    u_map = _user_name_map(db, u_ids)
    return [_serialize_inspection(r, inspector_name=u_map.get(r.inspector_user_id)) for r in rows]


def export_inspection_pdf(db: Session, inspection_id: UUID) -> bytes:
    insp = db.scalar(
        select(FoodSafetyInspection)
        .options(selectinload(FoodSafetyInspection.items))
        .where(FoodSafetyInspection.id == inspection_id)
    )
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")
    canteen = db.get(Canteen, insp.canteen_id)
    inspector = db.get(User, insp.inspector_user_id) if insp.inspector_user_id else None

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _w, h = A4
    y = h - 45

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, f"CollegeBites Food Safety Inspection Report — {insp.inspection_number}")
    y -= 20
    c.setFont("Helvetica", 9)
    c.drawString(
        40,
        y,
        f"Canteen: {canteen.name if canteen else insp.canteen_id} | Status: {insp.overall_status.upper()} | Date: {insp.inspected_at.isoformat()[:19]}",
    )
    y -= 15
    c.drawString(
        40,
        y,
        f"Inspector: {inspector.full_name if inspector else 'Staff'} | Summary: {insp.passed_items} Pass / {insp.failed_items} Fail / {insp.na_items} N/A",
    )
    y -= 22

    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, y, "Code")
    c.drawString(125, y, "Checklist Item")
    c.drawString(390, y, "Result")
    c.drawString(455, y, "Notes")
    y -= 14
    c.setFont("Helvetica", 8)
    for it in insp.items:
        if y < 60:
            c.showPage()
            y = h - 45
            c.setFont("Helvetica", 8)
        c.drawString(40, y, it.item_code[:14])
        c.drawString(125, y, it.item_title[:48])
        c.drawString(390, y, it.result.upper())
        c.drawString(455, y, (it.notes or "-")[:22])
        y -= 14

    if insp.notes:
        y -= 12
        c.setFont("Helvetica-Bold", 9)
        c.drawString(40, y, f"Inspector Notes: {insp.notes[:100]}")

    c.showPage()
    c.save()
    return buf.getvalue()


# =============================================================================
# 2. EQUIPMENT TEMPERATURE CONFIGURATION & LOGGING
# =============================================================================


def upsert_equipment_config(
    db: Session,
    *,
    canteen_id: UUID,
    equipment_name: str,
    equipment_code: str,
    equipment_type: str,
    location: Optional[str],
    min_temp_c: Decimal,
    max_temp_c: Decimal,
    standard_reference: Optional[str],
    actor_user_id: UUID,
) -> dict:
    if min_temp_c >= max_temp_c:
        raise HTTPException(status_code=400, detail="min_temp_c must be strictly less than max_temp_c")
    eq_type = (equipment_type or "refrigerator").strip().lower()
    if eq_type not in VALID_EQUIP_TYPES:
        raise HTTPException(status_code=400, detail=f"equipment_type must be one of {', '.join(VALID_EQUIP_TYPES)}")
    code = equipment_code.strip().upper()[:48]
    existing = db.scalar(
        select(EquipmentTemperatureConfig).where(
            EquipmentTemperatureConfig.canteen_id == canteen_id,
            EquipmentTemperatureConfig.equipment_code == code,
        )
    )
    if existing:
        existing.equipment_name = equipment_name.strip()
        existing.equipment_type = eq_type
        existing.location = location
        existing.min_temp_c = min_temp_c
        existing.max_temp_c = max_temp_c
        existing.standard_reference = standard_reference
        existing.is_active = True
        existing.configured_by_user_id = actor_user_id
        cfg = existing
    else:
        cfg = EquipmentTemperatureConfig(
            canteen_id=canteen_id,
            equipment_name=equipment_name.strip(),
            equipment_code=code,
            equipment_type=eq_type,
            location=location,
            min_temp_c=min_temp_c,
            max_temp_c=max_temp_c,
            standard_reference=standard_reference,
            is_active=True,
            configured_by_user_id=actor_user_id,
        )
        db.add(cfg)
    record_audit_log(
        db,
        action="food_safety.equipment_temp_configured",
        entity_type="equipment_temperature_config",
        entity_id=code,
        actor_user_id=actor_user_id,
        details={"min_temp_c": str(min_temp_c), "max_temp_c": str(max_temp_c), "standard": standard_reference},
    )
    db.commit()
    db.refresh(cfg)
    return _serialize_equipment_config(cfg)


def _serialize_equipment_config(cfg: EquipmentTemperatureConfig) -> dict:
    return {
        "id": str(cfg.id),
        "canteen_id": str(cfg.canteen_id),
        "equipment_name": cfg.equipment_name,
        "equipment_code": cfg.equipment_code,
        "equipment_type": cfg.equipment_type,
        "location": cfg.location,
        "min_temp_c": float(cfg.min_temp_c),
        "max_temp_c": float(cfg.max_temp_c),
        "standard_reference": cfg.standard_reference,
        "is_active": cfg.is_active,
    }


def list_equipment_configs(db: Session, canteen_id: UUID) -> list[dict]:
    rows = db.scalars(
        select(EquipmentTemperatureConfig)
        .where(EquipmentTemperatureConfig.canteen_id == canteen_id, EquipmentTemperatureConfig.is_active.is_(True))
        .order_by(EquipmentTemperatureConfig.equipment_code.asc())
    ).all()
    return [_serialize_equipment_config(r) for r in rows]


def record_temperature_log(
    db: Session,
    *,
    equipment_id: UUID,
    recorded_temp_c: Decimal,
    notes: Optional[str],
    corrective_action: Optional[str],
    recorded_at: Optional[datetime],
    actor_user_id: UUID,
) -> dict:
    cfg = db.get(EquipmentTemperatureConfig, equipment_id)
    if not cfg or not cfg.is_active:
        raise HTTPException(status_code=404, detail="Equipment temperature configuration not found")

    is_violation = (recorded_temp_c < cfg.min_temp_c) or (recorded_temp_c > cfg.max_temp_c)
    ts = _ensure_utc(recorded_at) or datetime.now(timezone.utc)
    log = EquipmentTemperatureLog(
        canteen_id=cfg.canteen_id,
        equipment_id=cfg.id,
        recorded_temp_c=recorded_temp_c,
        min_allowed_c=cfg.min_temp_c,
        max_allowed_c=cfg.max_temp_c,
        is_violation=is_violation,
        recorded_by_user_id=actor_user_id,
        recorded_at=ts,
        notes=notes,
        corrective_action=corrective_action,
    )
    db.add(log)
    db.flush()

    record_audit_log(
        db,
        action="food_safety.temperature_logged",
        entity_type="equipment_temperature_log",
        entity_id=str(log.id),
        actor_user_id=actor_user_id,
        details={
            "equipment_code": cfg.equipment_code,
            "recorded_temp_c": str(recorded_temp_c),
            "allowed_range": f"{cfg.min_temp_c}..{cfg.max_temp_c}",
            "is_violation": is_violation,
        },
    )
    if is_violation:
        notify_food_safety_event(
            db,
            canteen_id=cfg.canteen_id,
            event_type="temperature_violation",
            ref_id=str(log.id),
            title=f"Temperature Violation • {cfg.equipment_name} ({cfg.equipment_code})",
            message=f"Recorded {recorded_temp_c}°C is outside configured safe range {cfg.min_temp_c}°C to {cfg.max_temp_c}°C.",
            priority="critical",
        )
    db.commit()
    db.refresh(log)
    u_map = _user_name_map(db, {actor_user_id})
    return _serialize_temp_log(log, cfg=cfg, recorder_name=u_map.get(actor_user_id))


def _serialize_temp_log(
    log: EquipmentTemperatureLog,
    *,
    cfg: Optional[EquipmentTemperatureConfig] = None,
    recorder_name: Optional[str] = None,
) -> dict:
    return {
        "id": str(log.id),
        "canteen_id": str(log.canteen_id),
        "equipment_id": str(log.equipment_id),
        "equipment_name": cfg.equipment_name if cfg else None,
        "equipment_code": cfg.equipment_code if cfg else None,
        "equipment_type": cfg.equipment_type if cfg else None,
        "recorded_temp_c": float(log.recorded_temp_c),
        "min_allowed_c": float(log.min_allowed_c),
        "max_allowed_c": float(log.max_allowed_c),
        "is_violation": bool(log.is_violation),
        "recorded_by_name": recorder_name,
        "recorded_at": log.recorded_at.isoformat() if log.recorded_at else None,
        "notes": log.notes,
        "corrective_action": log.corrective_action,
        "data_classification": "actual",
    }


def list_temperature_logs(
    db: Session,
    canteen_id: UUID,
    *,
    equipment_id: Optional[UUID] = None,
    violations_only: bool = False,
    limit: int = 100,
) -> list[dict]:
    stmt = select(EquipmentTemperatureLog).where(EquipmentTemperatureLog.canteen_id == canteen_id)
    if equipment_id:
        stmt = stmt.where(EquipmentTemperatureLog.equipment_id == equipment_id)
    if violations_only:
        stmt = stmt.where(EquipmentTemperatureLog.is_violation.is_(True))
    rows = list(
        db.scalars(stmt.order_by(EquipmentTemperatureLog.recorded_at.desc()).limit(max(1, min(limit, 300)))).all()
    )
    eq_ids = {r.equipment_id for r in rows}
    eq_map = (
        {e.id: e for e in db.scalars(select(EquipmentTemperatureConfig).where(EquipmentTemperatureConfig.id.in_(list(eq_ids)))).all()}
        if eq_ids
        else {}
    )
    u_map = _user_name_map(db, {r.recorded_by_user_id for r in rows if r.recorded_by_user_id})
    return [
        _serialize_temp_log(r, cfg=eq_map.get(r.equipment_id), recorder_name=u_map.get(r.recorded_by_user_id))
        for r in rows
    ]


# =============================================================================
# 3. EXPIRY MONITORING & SAFE DISPOSAL (REUSES StockBatch)
# =============================================================================


def get_expiry_monitoring(db: Session, canteen_id: UUID, *, soon_days: int = 7) -> dict:
    today = today_college()
    soon_cutoff = today + timedelta(days=max(1, min(soon_days, 90)))
    rows = db.execute(
        select(StockBatch, InventoryItem, Ingredient)
        .join(InventoryItem, InventoryItem.id == StockBatch.inventory_item_id)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(
            InventoryItem.canteen_id == canteen_id,
            InventoryItem.is_archived.is_(False),
            StockBatch.remaining_quantity > 0,
        )
        .order_by(StockBatch.expiry_date.asc().nulls_last(), StockBatch.received_at.asc())
    ).all()

    expired = []
    approaching = []
    safe_batches = []
    no_expiry = []
    for b, inv, ing in rows:
        entry = {
            "batch_id": str(b.id),
            "inventory_item_id": str(inv.id),
            "batch_number": b.batch_number,
            "ingredient_name": ing.name,
            "unit": inv.unit,
            "remaining_quantity": str(b.remaining_quantity),
            "manufacturing_date": b.manufacturing_date.isoformat() if b.manufacturing_date else None,
            "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
            "received_at": b.received_at.isoformat() if b.received_at else None,
            "storage_location": b.storage_location,
            "quality_status": b.quality_status,
            "days_remaining": (b.expiry_date - today).days if b.expiry_date else None,
        }
        if b.expiry_date is None:
            no_expiry.append(entry)
        elif b.expiry_date < today:
            expired.append(entry)
        elif b.expiry_date <= soon_cutoff:
            approaching.append(entry)
        else:
            safe_batches.append(entry)

    return {
        "canteen_id": str(canteen_id),
        "as_of_date": today.isoformat(),
        "soon_window_days": soon_days,
        "data_classification": "actual",
        "expired_count": len(expired),
        "approaching_expiry_count": len(approaching),
        "expired_batches": expired,
        "approaching_expiry_batches": approaching,
        "no_expiry_date_batches_count": len(no_expiry),
        "healthy_batches_count": len(safe_batches),
    }


def dispose_expired_batch(db: Session, batch_id: UUID, *, reason: str, actor_user_id: UUID) -> dict:
    batch = db.scalar(select(StockBatch).where(StockBatch.id == batch_id).with_for_update())
    if not batch:
        raise HTTPException(status_code=404, detail="Stock batch not found")
    inv = db.scalar(select(InventoryItem).where(InventoryItem.id == batch.inventory_item_id).with_for_update())
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    if batch.remaining_quantity <= Decimal("0.000"):
        raise HTTPException(status_code=409, detail="Batch already has zero remaining quantity")

    qty = batch.remaining_quantity
    batch.remaining_quantity = Decimal("0.000")
    batch.wasted_quantity = (batch.wasted_quantity or Decimal("0.000")) + qty
    batch.quality_status = "blocked"
    batch.block_reason = f"Disposed: {reason}"[:255]

    inv.current_quantity = max(Decimal("0.000"), inv.current_quantity - qty)
    loss = (qty * batch.unit_cost).quantize(Decimal("0.01"))
    db.add(
        WastageRecord(
            canteen_id=inv.canteen_id,
            inventory_item_id=inv.id,
            batch_id=batch.id,
            source_type="ingredient",
            quantity=qty,
            loss_type="expired",
            reason=reason,
            waste_date=today_college(),
            estimated_loss=loss,
            recorded_by_user_id=actor_user_id,
        )
    )
    db.add(
        StockMovement(
            inventory_item_id=inv.id,
            batch_id=batch.id,
            movement_type="expired",
            quantity_delta=-qty,
            balance_after=inv.current_quantity,
            reference_type="food_safety_disposal",
            reference_id=str(batch.id),
            created_by_user_id=actor_user_id,
            notes=reason,
        )
    )
    from app.services.inventory_service import refresh_food_item_ingredient_sufficiency

    refresh_food_item_ingredient_sufficiency(db, inv.canteen_id)
    record_audit_log(
        db,
        action="food_safety.expired_batch_disposed",
        entity_type="stock_batch",
        entity_id=batch.batch_number,
        actor_user_id=actor_user_id,
        details={"disposed_quantity": str(qty), "loss_amount": str(loss), "reason": reason},
    )
    ing = db.get(Ingredient, inv.ingredient_id)
    notify_inventory_expiry_alert(
        db,
        canteen_id=inv.canteen_id,
        batch_id=batch.id,
        batch_number=batch.batch_number,
        ingredient_name=ing.name if ing else "Ingredient",
        expiry_date_str=batch.expiry_date.isoformat() if batch.expiry_date else today_college().isoformat(),
        is_expired=True,
    )
    db.commit()
    return {
        "batch_id": str(batch.id),
        "batch_number": batch.batch_number,
        "disposed_quantity": str(qty),
        "recorded_loss": str(loss),
        "quality_status": batch.quality_status,
    }


# =============================================================================
# 4. CLEANING SCHEDULES & SANITATION TASK LOGS
# =============================================================================


def create_cleaning_schedule(
    db: Session,
    *,
    canteen_id: UUID,
    area_name: str,
    frequency: str,
    instructions: Optional[str],
    assigned_staff_user_id: Optional[UUID],
    initial_due_at: Optional[datetime],
    actor_user_id: UUID,
) -> dict:
    freq = (frequency or "daily").strip().lower()
    if freq not in VALID_FREQUENCIES:
        raise HTTPException(status_code=400, detail=f"frequency must be one of {', '.join(VALID_FREQUENCIES)}")
    sched = CleaningSchedule(
        canteen_id=canteen_id,
        area_name=area_name.strip(),
        frequency=freq,
        instructions=instructions,
        assigned_staff_user_id=assigned_staff_user_id,
        is_active=True,
        created_by_user_id=actor_user_id,
    )
    db.add(sched)
    db.flush()

    due_dt = _ensure_utc(initial_due_at) or (datetime.now(timezone.utc) + timedelta(hours=4))
    task = CleaningTaskLog(
        schedule_id=sched.id,
        canteen_id=canteen_id,
        assigned_staff_user_id=assigned_staff_user_id,
        due_at=due_dt,
        status="pending",
    )
    db.add(task)
    record_audit_log(
        db,
        action="food_safety.cleaning_schedule_created",
        entity_type="cleaning_schedule",
        entity_id=str(sched.id),
        actor_user_id=actor_user_id,
        details={"area_name": sched.area_name, "frequency": freq},
    )
    db.commit()
    db.refresh(sched)
    db.refresh(task)
    return {
        "schedule": _serialize_cleaning_schedule(sched),
        "initial_task": _serialize_cleaning_task(task, area_name=sched.area_name, frequency=sched.frequency),
    }


def _serialize_cleaning_schedule(s: CleaningSchedule) -> dict:
    return {
        "id": str(s.id),
        "canteen_id": str(s.canteen_id),
        "area_name": s.area_name,
        "frequency": s.frequency,
        "instructions": s.instructions,
        "assigned_staff_user_id": str(s.assigned_staff_user_id) if s.assigned_staff_user_id else None,
        "is_active": s.is_active,
    }


def _serialize_cleaning_task(
    t: CleaningTaskLog,
    *,
    area_name: Optional[str] = None,
    frequency: Optional[str] = None,
    completed_by_name: Optional[str] = None,
) -> dict:
    now = datetime.now(timezone.utc)
    due = _ensure_utc(t.due_at)
    is_overdue = bool(t.status != "completed" and due and due < now)
    return {
        "id": str(t.id),
        "schedule_id": str(t.schedule_id),
        "canteen_id": str(t.canteen_id),
        "area_name": area_name,
        "frequency": frequency,
        "assigned_staff_user_id": str(t.assigned_staff_user_id) if t.assigned_staff_user_id else None,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "status": t.status,
        "is_overdue": is_overdue,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "completed_by_name": completed_by_name,
        "evidence_url": t.evidence_url,
        "notes": t.notes,
    }


def list_cleaning_schedules_and_tasks(db: Session, canteen_id: UUID) -> dict:
    schedules = list(
        db.scalars(
            select(CleaningSchedule)
            .where(CleaningSchedule.canteen_id == canteen_id, CleaningSchedule.is_active.is_(True))
            .order_by(CleaningSchedule.area_name.asc())
        ).all()
    )
    sched_map = {s.id: s for s in schedules}
    tasks = list(
        db.scalars(
            select(CleaningTaskLog)
            .where(CleaningTaskLog.canteen_id == canteen_id)
            .order_by(CleaningTaskLog.due_at.desc())
            .limit(150)
        ).all()
    )
    u_map = _user_name_map(db, {t.completed_by_user_id for t in tasks if t.completed_by_user_id})
    serialized_tasks = [
        _serialize_cleaning_task(
            t,
            area_name=sched_map[t.schedule_id].area_name if t.schedule_id in sched_map else "Area",
            frequency=sched_map[t.schedule_id].frequency if t.schedule_id in sched_map else "daily",
            completed_by_name=u_map.get(t.completed_by_user_id),
        )
        for t in tasks
    ]
    overdue_count = sum(1 for t in serialized_tasks if t["is_overdue"])
    return {
        "schedules": [_serialize_cleaning_schedule(s) for s in schedules],
        "tasks": serialized_tasks,
        "overdue_count": overdue_count,
    }


def update_cleaning_task(
    db: Session,
    task_id: UUID,
    *,
    status: str,
    evidence_url: Optional[str],
    notes: Optional[str],
    actor_user_id: UUID,
) -> dict:
    task = db.scalar(select(CleaningTaskLog).where(CleaningTaskLog.id == task_id).with_for_update())
    if not task:
        raise HTTPException(status_code=404, detail="Cleaning task not found")
    st = status.strip().lower()
    if st not in ("pending", "in_progress", "completed"):
        raise HTTPException(status_code=400, detail="Cleaning task status must be pending, in_progress, or completed")
    task.status = st
    if evidence_url is not None:
        task.evidence_url = evidence_url
    if notes is not None:
        task.notes = notes
    if st == "completed":
        task.completed_at = datetime.now(timezone.utc)
        task.completed_by_user_id = actor_user_id
    record_audit_log(
        db,
        action="food_safety.cleaning_task_updated",
        entity_type="cleaning_task_log",
        entity_id=str(task.id),
        actor_user_id=actor_user_id,
        details={"status": st},
    )
    db.commit()
    db.refresh(task)
    sched = db.get(CleaningSchedule, task.schedule_id)
    u_map = _user_name_map(db, {task.completed_by_user_id} if task.completed_by_user_id else set())
    return _serialize_cleaning_task(
        task,
        area_name=sched.area_name if sched else None,
        frequency=sched.frequency if sched else None,
        completed_by_name=u_map.get(task.completed_by_user_id),
    )


def notify_overdue_cleaning_tasks(db: Session, canteen_id: UUID) -> dict:
    now = datetime.now(timezone.utc)
    overdue = list(
        db.scalars(
            select(CleaningTaskLog).where(
                CleaningTaskLog.canteen_id == canteen_id,
                CleaningTaskLog.status != "completed",
                CleaningTaskLog.due_at < now,
            )
        ).all()
    )
    notified = 0
    for t in overdue:
        sched = db.get(CleaningSchedule, t.schedule_id)
        notify_food_safety_event(
            db,
            canteen_id=canteen_id,
            event_type="cleaning_task_overdue",
            ref_id=f"{t.id}:{today_college().isoformat()}",
            title=f"Overdue Sanitation Task • {sched.area_name if sched else 'Kitchen Area'}",
            message=f"Cleaning task due at {t.due_at.isoformat()[:16]} is still {t.status}.",
            priority="high",
        )
        notified += 1
    if notified:
        db.commit()
    return {"overdue_tasks_found": len(overdue), "reminders_dispatched": notified}


# =============================================================================
# 5. FOOD SAFETY INCIDENTS
# =============================================================================


def create_incident(
    db: Session,
    *,
    canteen_id: UUID,
    title: str,
    description: str,
    severity: str,
    occurred_at: Optional[datetime],
    assigned_to_user_id: Optional[UUID],
    evidence_urls: Optional[list[str]],
    actor_user_id: UUID,
) -> dict:
    sev = (severity or "medium").strip().lower()
    if sev not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity must be one of {', '.join(VALID_SEVERITIES)}")
    now = datetime.now(timezone.utc)
    inc_no = f"FSI-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:4].upper()}"
    inc = FoodSafetyIncident(
        incident_number=inc_no,
        canteen_id=canteen_id,
        title=title.strip(),
        description=description.strip(),
        severity=sev,
        status="open",
        occurred_at=_ensure_utc(occurred_at) or now,
        reported_by_user_id=actor_user_id,
        assigned_to_user_id=assigned_to_user_id,
        evidence_urls=list(evidence_urls or []),
    )
    db.add(inc)
    db.flush()
    record_audit_log(
        db,
        action="food_safety.incident_reported",
        entity_type="food_safety_incident",
        entity_id=inc_no,
        actor_user_id=actor_user_id,
        details={"severity": sev, "title": inc.title},
    )
    notify_food_safety_event(
        db,
        canteen_id=canteen_id,
        event_type="food_safety_incident",
        ref_id=inc_no,
        title=f"Food Safety Incident ({sev.upper()}) • {inc_no}",
        message=f"{inc.title}: {inc.description[:180]}",
        priority="critical" if sev in ("high", "critical") else "high",
    )
    db.commit()
    db.refresh(inc)
    return _serialize_incident(inc)


def update_incident(
    db: Session,
    incident_id: UUID,
    *,
    status: Optional[str],
    corrective_action: Optional[str],
    resolution_notes: Optional[str],
    assigned_to_user_id: Optional[UUID],
    actor_user_id: UUID,
) -> dict:
    inc = db.scalar(select(FoodSafetyIncident).where(FoodSafetyIncident.id == incident_id).with_for_update())
    if not inc:
        raise HTTPException(status_code=404, detail="Food safety incident not found")
    now = datetime.now(timezone.utc)
    if status is not None:
        st = status.strip().lower()
        if st not in VALID_INCIDENT_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(VALID_INCIDENT_STATUSES)}")
        inc.status = st
        if st == "resolved":
            inc.resolved_at = now
        elif st == "closed":
            inc.closed_at = now
    if corrective_action is not None:
        inc.corrective_action = corrective_action
    if resolution_notes is not None:
        inc.resolution_notes = resolution_notes
    if assigned_to_user_id is not None:
        inc.assigned_to_user_id = assigned_to_user_id
    record_audit_log(
        db,
        action="food_safety.incident_updated",
        entity_type="food_safety_incident",
        entity_id=inc.incident_number,
        actor_user_id=actor_user_id,
        details={"status": inc.status, "corrective_action": bool(inc.corrective_action)},
    )
    db.commit()
    db.refresh(inc)
    return _serialize_incident(inc)


def _serialize_incident(inc: FoodSafetyIncident) -> dict:
    return {
        "id": str(inc.id),
        "incident_number": inc.incident_number,
        "canteen_id": str(inc.canteen_id),
        "title": inc.title,
        "description": inc.description,
        "severity": inc.severity,
        "status": inc.status,
        "occurred_at": inc.occurred_at.isoformat() if inc.occurred_at else None,
        "reported_by_user_id": str(inc.reported_by_user_id) if inc.reported_by_user_id else None,
        "assigned_to_user_id": str(inc.assigned_to_user_id) if inc.assigned_to_user_id else None,
        "evidence_urls": list(inc.evidence_urls or []),
        "corrective_action": inc.corrective_action,
        "resolution_notes": inc.resolution_notes,
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
        "closed_at": inc.closed_at.isoformat() if inc.closed_at else None,
    }


def list_incidents(db: Session, canteen_id: UUID, *, status_filter: Optional[str] = None) -> list[dict]:
    stmt = select(FoodSafetyIncident).where(FoodSafetyIncident.canteen_id == canteen_id)
    if status_filter and status_filter != "all":
        stmt = stmt.where(FoodSafetyIncident.status == status_filter)
    rows = db.scalars(stmt.order_by(FoodSafetyIncident.occurred_at.desc()).limit(150)).all()
    return [_serialize_incident(r) for r in rows]


# =============================================================================
# 6. FOOD SAFETY DASHBOARD (STRICT ACTUAL METRICS ONLY)
# =============================================================================


def get_food_safety_dashboard(db: Session, canteen_id: UUID, *, days: int = 30) -> dict:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=max(1, min(days, 365)))
    inspections = list(
        db.scalars(
            select(FoodSafetyInspection)
            .where(FoodSafetyInspection.canteen_id == canteen_id, FoodSafetyInspection.inspected_at >= since)
            .order_by(FoodSafetyInspection.inspected_at.desc())
        ).all()
    )
    completed_inspections = len(inspections)
    failed_inspections = sum(1 for i in inspections if i.overall_status == "fail")
    passed_inspections = sum(1 for i in inspections if i.overall_status == "pass")
    inspection_pass_rate = (
        round((passed_inspections / completed_inspections) * 100.0, 1) if completed_inspections > 0 else None
    )

    temp_logs = list(
        db.scalars(
            select(EquipmentTemperatureLog).where(
                EquipmentTemperatureLog.canteen_id == canteen_id,
                EquipmentTemperatureLog.recorded_at >= since,
            )
        ).all()
    )
    temp_violations = sum(1 for t in temp_logs if t.is_violation)

    cleaning_tasks = list(
        db.scalars(
            select(CleaningTaskLog).where(
                CleaningTaskLog.canteen_id == canteen_id,
                CleaningTaskLog.due_at >= since,
            )
        ).all()
    )
    overdue_cleaning = sum(
        1
        for t in cleaning_tasks
        if t.status != "completed" and _ensure_utc(t.due_at) is not None and _ensure_utc(t.due_at) < now
    )
    completed_cleaning = sum(1 for t in cleaning_tasks if t.status == "completed")

    incidents = list(
        db.scalars(
            select(FoodSafetyIncident).where(
                FoodSafetyIncident.canteen_id == canteen_id,
                FoodSafetyIncident.occurred_at >= since,
            )
        ).all()
    )
    open_incidents = sum(1 for i in incidents if i.status in ("open", "under_investigation"))
    resolved_incidents = sum(1 for i in incidents if i.status in ("resolved", "closed"))

    expiry = get_expiry_monitoring(db, canteen_id, soon_days=7)

    # Real daily inspection trend from actual records only
    trend_map: dict[str, dict[str, int]] = {}
    for i in inspections:
        day_str = i.inspected_at.strftime("%Y-%m-%d")
        b = trend_map.setdefault(day_str, {"date": day_str, "inspections": 0, "passed": 0, "failed": 0})
        b["inspections"] += 1
        if i.overall_status == "pass":
            b["passed"] += 1
        elif i.overall_status == "fail":
            b["failed"] += 1

    has_any_data = any(
        [
            completed_inspections > 0,
            len(temp_logs) > 0,
            len(cleaning_tasks) > 0,
            len(incidents) > 0,
            expiry["expired_count"] > 0,
            expiry["approaching_expiry_count"] > 0,
        ]
    )

    return {
        "canteen_id": str(canteen_id),
        "canteen_name": canteen.name,
        "lookback_days": days,
        "data_classification": "actual",
        "empty": not has_any_data,
        "message": None if has_any_data else "No food safety records recorded for the selected period.",
        "completed_inspections_count": completed_inspections,
        "passed_inspections_count": passed_inspections,
        "failed_inspections_count": failed_inspections,
        "inspection_pass_rate_percent": inspection_pass_rate,
        "temperature_logs_count": len(temp_logs),
        "temperature_violations_count": temp_violations,
        "cleaning_tasks_total": len(cleaning_tasks),
        "cleaning_tasks_completed": completed_cleaning,
        "overdue_cleaning_tasks_count": overdue_cleaning,
        "expired_batches_count": expiry["expired_count"],
        "approaching_expiry_batches_count": expiry["approaching_expiry_count"],
        "open_incidents_count": open_incidents,
        "resolved_incidents_count": resolved_incidents,
        "daily_inspection_trend": [trend_map[k] for k in sorted(trend_map.keys())],
        "last_updated_at": now.isoformat(),
    }
