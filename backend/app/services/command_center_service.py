import csv
import io
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.core.cache import NS_COMMAND_CENTER, cache_manager, invalidate_command_center
from app.core.permissions import ROLE_CANTEEN_MANAGER, ROLE_COLLEGE_ADMIN, ROLE_SUPER_ADMIN
from app.core.time_utils import today_college
from app.models.auth import StaffProfile, User
from app.models.campus_ops import (
    OperationalIncident,
    OperationalReportRecord,
    RootCauseInvestigation,
    SeatingZone,
)
from app.models.college import Canteen, Counter, Kitchen, KitchenStation
from app.models.engagement import NotificationDelivery
from app.models.enterprise import AIAssistantAuditLog, EquipmentTemperatureLog, FoodSafetyIncident
from app.models.inventory import InventoryItem, StockMovement
from app.models.menu import FoodItem, Ingredient
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PaymentReconciliation, QRVerificationEvent, ReceiptPrintJob
from app.models.staff import StaffAttendance, StaffShift
from app.models.system import SecurityAlert
from app.services import campus_intelligence_service, notification_service, queue_service
from app.services.audit_service import record_audit_log

FINANCE_ROLES = {ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER}

_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_BLOCKED_NL_PATTERNS = (
    r"\b(delete|drop|truncate|wipe|erase)\b",
    r"\b(refund|issue refund|process refund)\b",
    r"\b(cancel\s+order|force\s+cancel)\b",
    r"\b(approve\s+po|create\s+po|auto\s+order|transfer\s+money)\b",
    r"\b(change\s+price|update\s+price|set\s+price|apply\s+discount|add\s+coupon)\b",
    r"\b(disable\s+user|deactivate\s+user|grant\s+admin|reset\s+password)\b",
    r"\b(secret_key|razorpay_key_secret|webhook_secret|password_hash|api_key|credentials)\b",
)

VALID_INCIDENT_CATEGORIES = {
    "order_delay",
    "stock_shortage",
    "inventory_discrepancy",
    "payment_failure",
    "settlement_mismatch",
    "printer_failure",
    "qr_failure",
    "kitchen_bottleneck",
    "notification_failure",
    "seating_congestion",
    "automation_failure",
}

VALID_RCA_DOMAINS = {
    "order_delays",
    "stock_shortages",
    "inventory_discrepancies",
    "payment_failures",
    "settlement_mismatches",
    "printer_failures",
    "qr_failures",
    "kitchen_bottlenecks",
    "notification_failures",
}


def _safe_csv_cell(val: Any) -> str:
    txt = "" if val is None else str(val)
    if txt.startswith(_CSV_FORMULA_PREFIXES):
        return f"'{txt}"
    return txt


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


# =============================================================================
# FEATURE 10: UNIFIED OPERATIONAL INTELLIGENCE & OPERATIONAL INCIDENTS
# =============================================================================


def get_unified_operational_intelligence(db: Session, *, canteen_id: Optional[UUID] = None) -> dict[str, Any]:
    cache_ns = f"{NS_COMMAND_CENTER}:{canteen_id}" if canteen_id else NS_COMMAND_CENTER
    hit, cached = cache_manager.get_json(cache_ns, "unified", l1_ttl=3.0)
    if hit and isinstance(cached, dict):
        return cached

    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    crowd = campus_intelligence_service.get_live_crowd_intelligence(db, days=7, include_history=False)
    counters = [c for c in crowd["counters"] if not canteen_id or c["canteen_id"] == str(canteen_id)]
    seating = campus_intelligence_service.list_seating_availability(db, canteen_id=canteen_id)

    # SQL aggregates instead of hydrating all 24h Order / InventoryItem / FoodItem / Payment ORM rows
    ord_stmt = select(
        func.count(Order.id),
        func.coalesce(func.sum(case((Order.status == "COMPLETED", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Order.status.in_(("CANCELLED", "REJECTED")), 1), else_=0)), 0),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            Order.status.in_(("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING")),
                            Order.delayed_minutes > 0,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.count(func.distinct(Order.customer_id)),
        func.coalesce(func.sum(case((Order.is_guest.is_(True), 1), else_=0)), 0),
    ).where(Order.created_at >= since_24h)
    if canteen_id:
        ord_stmt = ord_stmt.where(Order.canteen_id == canteen_id)
    ord_agg = db.execute(ord_stmt).one()
    total_24h = int(ord_agg[0] or 0)
    completed_24h = int(ord_agg[1] or 0)
    cancelled_24h = int(ord_agg[2] or 0)
    delayed_active = int(ord_agg[3] or 0)
    active_customers_24h = int(ord_agg[4] or 0)
    guest_orders_24h = int(ord_agg[5] or 0)

    inv_stmt = select(
        func.count(InventoryItem.id),
        func.coalesce(func.sum(case((InventoryItem.current_quantity <= InventoryItem.reorder_level, 1), else_=0)), 0),
        func.coalesce(func.sum(case((InventoryItem.current_quantity <= 0, 1), else_=0)), 0),
    ).where(InventoryItem.is_archived.is_(False))
    if canteen_id:
        inv_stmt = inv_stmt.where(InventoryItem.canteen_id == canteen_id)
    inv_agg = db.execute(inv_stmt).one()
    inv_tracked_count = int(inv_agg[0] or 0)
    low_stock_count = int(inv_agg[1] or 0)
    out_of_stock_count = int(inv_agg[2] or 0)

    food_stmt = select(
        func.count(FoodItem.id),
        func.coalesce(
            func.sum(
                case(
                    (and_(FoodItem.is_available.is_(True), FoodItem.insufficient_ingredients.is_(False)), 1),
                    else_=0,
                )
            ),
            0,
        ),
    ).where(FoodItem.is_active.is_(True))
    if canteen_id:
        food_stmt = food_stmt.where(FoodItem.canteen_id == canteen_id)
    food_agg = db.execute(food_stmt).one()
    total_active_foods = int(food_agg[0] or 0)
    menu_avail_count = int(food_agg[1] or 0)
    menu_unavail_count = total_active_foods - menu_avail_count

    pay_stmt = select(
        func.coalesce(func.sum(case((Payment.status == "CONFIRMED", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Payment.status == "FAILED", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Payment.status == "PENDING", 1), else_=0)), 0),
    ).join(Order, Order.id == Payment.order_id).where(Payment.created_at >= since_24h)
    if canteen_id:
        pay_stmt = pay_stmt.where(Order.canteen_id == canteen_id)
    pay_agg = db.execute(pay_stmt).one()
    pay_confirmed = int(pay_agg[0] or 0)
    pay_failed = int(pay_agg[1] or 0)
    pay_pending = int(pay_agg[2] or 0)

    open_discrepancies = int(
        db.scalar(
            select(func.count(PaymentReconciliation.id)).where(
                PaymentReconciliation.status.in_(("open", "mismatch", "pending_review"))
            )
        )
        or 0
    )

    # Incidents across all modules
    open_ops_inc = int(
        db.scalar(
            select(func.count(OperationalIncident.id)).where(
                OperationalIncident.status.in_(("open", "investigating")),
                *([OperationalIncident.canteen_id == canteen_id] if canteen_id else []),
            )
        )
        or 0
    )
    open_fs_inc = int(
        db.scalar(
            select(func.count(FoodSafetyIncident.id)).where(
                FoodSafetyIncident.status.in_(("open", "investigating")),
                *([FoodSafetyIncident.canteen_id == canteen_id] if canteen_id else []),
            )
        )
        or 0
    )
    open_sec_alerts = int(
        db.scalar(
            select(func.count(SecurityAlert.id)).where(
                SecurityAlert.status == "open",
                *([SecurityAlert.canteen_id == canteen_id] if canteen_id else []),
            )
        )
        or 0
    )
    failed_prints_24h = int(
        db.scalar(
            select(func.count(ReceiptPrintJob.id)).where(
                ReceiptPrintJob.status == "failed",
                ReceiptPrintJob.created_at >= since_24h,
            )
        )
        or 0
    )

    # Cross-module correlated alerts
    critical_alerts: list[dict[str, Any]] = []
    if delayed_active > 0:
        critical_alerts.append(
            {
                "module": "kitchen_queue",
                "severity": "high" if delayed_active >= 3 else "medium",
                "title": f"{delayed_active} active order(s) currently delayed",
                "recommended_action": "Review kitchen workload and escalate delayed orders.",
            }
        )
    if out_of_stock_count > 0 or low_stock_count > 0:
        critical_alerts.append(
            {
                "module": "inventory",
                "severity": "high" if out_of_stock_count > 0 else "medium",
                "title": f"{out_of_stock_count} out-of-stock & {low_stock_count} low-stock ingredient(s)",
                "recommended_action": "Review automated draft PO recommendations and impacted menu items.",
            }
        )
    if open_discrepancies > 0 or pay_failed >= 3:
        critical_alerts.append(
            {
                "module": "payments_razorpay",
                "severity": "high" if open_discrepancies > 0 else "medium",
                "title": f"{open_discrepancies} payment discrepancy(ies); {pay_failed} failed Razorpay attempt(s) in 24h",
                "recommended_action": "Inspect reconciliation ledger and run root-cause payment investigation.",
            }
        )
    if open_ops_inc + open_fs_inc + open_sec_alerts > 0:
        critical_alerts.append(
            {
                "module": "incidents",
                "severity": "high" if (open_fs_inc + open_sec_alerts) > 0 else "medium",
                "title": f"{open_ops_inc} operational, {open_fs_inc} food-safety, and {open_sec_alerts} security alert(s) open",
                "recommended_action": "Assign and investigate open incidents in the Command Center.",
            }
        )

    health_status = "healthy"
    if any(a["severity"] == "high" for a in critical_alerts):
        health_status = "attention_required"
    elif critical_alerts:
        health_status = "degraded"

    result = {
        "operational_health": health_status,
        "counters": counters,
        "orders_24h": {
            "total": total_24h,
            "completed": completed_24h,
            "cancelled_or_rejected": cancelled_24h,
            "delayed_active": delayed_active,
            "unique_logged_in_customers": active_customers_24h,
            "guest_orders": guest_orders_24h,
        },
        "inventory": {
            "tracked_items": inv_tracked_count,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
        },
        "menu_availability": {
            "total_active": total_active_foods,
            "available_now": menu_avail_count,
            "unavailable_now": menu_unavail_count,
        },
        "payments_razorpay_24h": {
            "gateway": "razorpay",
            "confirmed": pay_confirmed,
            "pending": pay_pending,
            "failed": pay_failed,
            "open_reconciliation_discrepancies": open_discrepancies,
            "app_refunds_issued": 0,
            "refund_policy": "No in-app refunds; confirmed orders follow college finance policy.",
        },
        "printing_24h": {"failed_print_jobs": failed_prints_24h},
        "seating": seating["summary"],
        "incidents_summary": {
            "open_operational_incidents": open_ops_inc,
            "open_food_safety_incidents": open_fs_inc,
            "open_security_alerts": open_sec_alerts,
        },
        "critical_alerts": critical_alerts,
        "authoritative_source": "collegebites_primary_database",
        "last_updated_at": now.isoformat(),
    }
    cache_manager.set_json(cache_ns, "unified", result, ttl_seconds=15, l1_ttl=3.0)
    return result


def create_operational_incident(
    db: Session,
    *,
    canteen_id: Optional[UUID],
    category: str,
    severity: str,
    title: str,
    description: str,
    evidence: Optional[dict[str, Any]] = None,
    related_entity_type: Optional[str] = None,
    related_entity_id: Optional[str] = None,
    actor_user_id: Optional[UUID] = None,
) -> dict[str, Any]:
    cat = category.strip().lower()
    if cat not in VALID_INCIDENT_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid incident category '{cat}'")
    sev = severity.strip().lower()
    if sev not in ("low", "medium", "high", "critical"):
        raise HTTPException(status_code=400, detail="severity must be low, medium, high, or critical")

    now = datetime.now(timezone.utc)
    code = f"OPI-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:4].upper()}"
    inc = OperationalIncident(
        incident_code=code,
        canteen_id=canteen_id,
        category=cat,
        severity=sev,
        status="open",
        title=title.strip()[:200],
        description=description.strip(),
        evidence_json=evidence or {},
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        reported_by_user_id=actor_user_id,
    )
    db.add(inc)
    db.flush()
    record_audit_log(
        db,
        action="command_center.incident_created",
        entity_type="operational_incident",
        entity_id=code,
        actor_user_id=actor_user_id,
        details={"category": cat, "severity": sev, "title": inc.title},
    )
    notification_service.create_role_notifications(
        db,
        roles=["college_admin", "canteen_manager"],
        canteen_id=canteen_id,
        event_type="operational_incident",
        category="system",
        priority="critical" if sev in ("high", "critical") else "high",
        title=f"Operational Incident ({sev.upper()}) • {code}",
        message=f"{inc.title} ({cat.replace('_', ' ')})",
        event_id_base=f"ops_inc:{code}",
    )
    db.commit()
    db.refresh(inc)
    invalidate_command_center(canteen_id)
    return _serialize_incident(inc)


def _serialize_incident(inc: OperationalIncident) -> dict[str, Any]:
    return {
        "id": str(inc.id),
        "incident_code": inc.incident_code,
        "canteen_id": str(inc.canteen_id) if inc.canteen_id else None,
        "category": inc.category,
        "severity": inc.severity,
        "status": inc.status,
        "title": inc.title,
        "description": inc.description,
        "evidence": inc.evidence_json or {},
        "related_entity_type": inc.related_entity_type,
        "related_entity_id": inc.related_entity_id,
        "resolution_notes": inc.resolution_notes,
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
    }


def list_operational_incidents(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = (
        select(OperationalIncident)
        .order_by(OperationalIncident.created_at.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 200)))
    )
    if canteen_id:
        stmt = stmt.where((OperationalIncident.canteen_id == canteen_id) | (OperationalIncident.canteen_id.is_(None)))
    if status_filter:
        stmt = stmt.where(OperationalIncident.status == status_filter)
    if category:
        stmt = stmt.where(OperationalIncident.category == category)
    return [_serialize_incident(r) for r in db.scalars(stmt).all()]


def update_operational_incident(
    db: Session,
    incident_id: UUID,
    *,
    status: Optional[str] = None,
    resolution_notes: Optional[str] = None,
    actor_user_id: UUID,
) -> dict[str, Any]:
    inc = db.scalar(select(OperationalIncident).where(OperationalIncident.id == incident_id).with_for_update())
    if not inc:
        raise HTTPException(status_code=404, detail="Operational incident not found")
    if resolution_notes is not None:
        inc.resolution_notes = resolution_notes.strip()
    if status is not None:
        st = status.strip().lower()
        if st not in ("open", "investigating", "mitigated", "resolved", "closed"):
            raise HTTPException(status_code=400, detail="Invalid incident status")
        if inc.status == "closed" and st != "closed":
            raise HTTPException(status_code=409, detail="Closed incidents cannot be reopened")
        if st in ("resolved", "closed") and not inc.resolution_notes:
            raise HTTPException(status_code=400, detail="resolution_notes is required to resolve or close an incident")
        inc.status = st
        if st in ("resolved", "closed"):
            inc.resolved_at = datetime.now(timezone.utc)
    record_audit_log(
        db,
        action="command_center.incident_updated",
        entity_type="operational_incident",
        entity_id=inc.incident_code,
        actor_user_id=actor_user_id,
        details={"status": inc.status},
    )
    db.commit()
    db.refresh(inc)
    invalidate_command_center(inc.canteen_id)
    return _serialize_incident(inc)


# =============================================================================
# FEATURE 11: AI ROOT-CAUSE INVESTIGATION (CONFIRMED FACTS vs AI HYPOTHESES)
# =============================================================================


def run_root_cause_investigation(
    db: Session,
    *,
    target_domain: str,
    canteen_id: Optional[UUID] = None,
    incident_id: Optional[UUID] = None,
    lookback_hours: int = 24,
    actor_user_id: UUID,
) -> dict[str, Any]:
    domain = target_domain.strip().lower()
    if domain not in VALID_RCA_DOMAINS:
        raise HTTPException(status_code=400, detail=f"Unsupported investigation domain '{domain}'")
    hrs = max(1, min(int(lookback_hours or 24), 168))
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hrs)

    confirmed_facts: list[dict[str, Any]] = []
    ai_hypotheses: list[dict[str, Any]] = []
    recommended_actions: list[dict[str, Any]] = []

    if domain in ("order_delays", "kitchen_bottlenecks"):
        q = select(Order).where(Order.created_at >= since)
        if canteen_id:
            q = q.where(Order.canteen_id == canteen_id)
        ords = list(db.scalars(q.order_by(Order.created_at.desc()).limit(300)).all())
        delayed = [o for o in ords if int(o.delayed_minutes or 0) > 0]
        preparing = [o for o in ords if o.status == "PREPARING"]
        confirmed_facts.append(
            {
                "fact_type": "verified_db_query",
                "summary": f"Observed {len(delayed)} delayed order(s) out of {len(ords)} total orders in last {hrs}h ({len(preparing)} currently PREPARING).",
                "sample_orders": [
                    {
                        "order_number": o.order_number,
                        "status": o.status,
                        "delayed_minutes": o.delayed_minutes,
                        "delay_reason": o.delay_reason,
                        "created_at": o.created_at.isoformat() if o.created_at else None,
                    }
                    for o in delayed[:10]
                ],
                "observed_at": now.isoformat(),
            }
        )
        on_duty = (
            queue_service._canteen_on_duty_staff_count(db, canteen_id)
            if canteen_id
            else int(db.scalar(select(func.count(StaffProfile.id)).where(StaffProfile.is_on_duty.is_(True))) or 0)
        )
        confirmed_facts.append(
            {
                "fact_type": "verified_db_query",
                "summary": f"Recorded on-duty staff count: {on_duty}.",
                "observed_at": now.isoformat(),
            }
        )
        if delayed:
            ai_hypotheses.append(
                {
                    "classification": "ai_hypothesis_unverified",
                    "hypothesis": (
                        "Prep-station backlog relative to active staff capacity may be contributing to order delays."
                        if on_duty <= 2
                        else "Concurrent item prep complexity or specific delayed recipes may be causing kitchen queue buildup."
                    ),
                    "confidence": "medium",
                    "supporting_evidence": f"{len(delayed)} delayed orders with {on_duty} recorded on-duty staff.",
                }
            )
            recommended_actions.append(
                {
                    "action": "Inspect Kitchen Display item-grouped view and escalate overdue orders with documented priority.",
                    "requires_human_approval": True,
                }
            )

    elif domain in ("stock_shortages", "inventory_discrepancies"):
        inv_q = select(InventoryItem, Ingredient.name).join(Ingredient, Ingredient.id == InventoryItem.ingredient_id).where(
            InventoryItem.is_archived.is_(False),
            InventoryItem.current_quantity <= InventoryItem.reorder_level,
        )
        if canteen_id:
            inv_q = inv_q.where(InventoryItem.canteen_id == canteen_id)
        low_rows = db.execute(inv_q.limit(30)).all()
        confirmed_facts.append(
            {
                "fact_type": "verified_db_query",
                "summary": f"{len(low_rows)} active ingredient(s) at or below reorder threshold.",
                "items": [
                    {
                        "ingredient": nm,
                        "current_qty": str(inv.current_quantity),
                        "reserved_qty": str(inv.reserved_quantity),
                        "reorder_level": str(inv.reorder_level),
                    }
                    for inv, nm in low_rows[:12]
                ],
                "observed_at": now.isoformat(),
            }
        )
        mv_q = select(StockMovement).where(StockMovement.created_at >= since, StockMovement.movement_type.in_(("wastage", "adjustment")))
        mvs = list(db.scalars(mv_q.order_by(StockMovement.created_at.desc()).limit(25)).all())
        confirmed_facts.append(
            {
                "fact_type": "verified_db_query",
                "summary": f"{len(mvs)} wastage/manual stock adjustment movement(s) recorded in last {hrs}h.",
                "observed_at": now.isoformat(),
            }
        )
        if low_rows or mvs:
            ai_hypotheses.append(
                {
                    "classification": "ai_hypothesis_unverified",
                    "hypothesis": "Accelerated order consumption or unreplenished wastage adjustments may be driving stockouts.",
                    "confidence": "medium" if low_rows else "low",
                    "supporting_evidence": f"{len(low_rows)} low-stock items and {len(mvs)} wastage/adjustment logs.",
                }
            )
            recommended_actions.append(
                {
                    "action": "Review Draft-Only Purchase Order recommendations and perform physical cycle count before approving adjustments.",
                    "requires_human_approval": True,
                }
            )

    elif domain in ("payment_failures", "settlement_mismatches"):
        p_q = select(Payment, Order.order_number).join(Order, Order.id == Payment.order_id).where(Payment.created_at >= since)
        if canteen_id:
            p_q = p_q.where(Order.canteen_id == canteen_id)
        p_rows = db.execute(p_q.order_by(Payment.created_at.desc()).limit(200)).all()
        failed_p = [(p, onum) for p, onum in p_rows if p.status == "FAILED"]
        disc = list(
            db.scalars(
                select(PaymentReconciliation)
                .where(PaymentReconciliation.status.in_(("open", "mismatch", "pending_review")))
                .limit(20)
            ).all()
        )
        confirmed_facts.append(
            {
                "fact_type": "verified_db_query",
                "summary": f"{len(failed_p)} failed Razorpay payment(s) out of {len(p_rows)} attempts in last {hrs}h; {len(disc)} open reconciliation discrepancy(ies).",
                "sample_failures": [
                    {
                        "order_number": onum,
                        "amount": str(p.amount),
                        "failure_reason": p.failure_reason,
                        "created_at": p.created_at.isoformat() if p.created_at else None,
                    }
                    for p, onum in failed_p[:10]
                ],
                "observed_at": now.isoformat(),
            }
        )
        if failed_p or disc:
            ai_hypotheses.append(
                {
                    "classification": "ai_hypothesis_unverified",
                    "hypothesis": "Student UPI/network checkout abandonment or delayed Razorpay webhook settlement callbacks may explain failures/discrepancies.",
                    "confidence": "medium",
                    "supporting_evidence": f"{len(failed_p)} failed attempts, {len(disc)} open discrepancies.",
                }
            )
            recommended_actions.append(
                {
                    "action": "Run Razorpay payment sync on pending orders and review webhook signature logs in Reconciliation.",
                    "requires_human_approval": True,
                }
            )

    elif domain == "printer_failures":
        jobs = list(
            db.scalars(
                select(ReceiptPrintJob)
                .where(ReceiptPrintJob.created_at >= since, ReceiptPrintJob.status == "failed")
                .order_by(ReceiptPrintJob.created_at.desc())
                .limit(30)
            ).all()
        )
        confirmed_facts.append(
            {
                "fact_type": "verified_db_query",
                "summary": f"{len(jobs)} failed ESC/POS print job(s) recorded in last {hrs}h.",
                "sample_errors": [{"job_id": str(j.id), "job_type": j.job_type, "error": j.error_message} for j in jobs[:8]],
                "observed_at": now.isoformat(),
            }
        )
        if jobs:
            ai_hypotheses.append(
                {
                    "classification": "ai_hypothesis_unverified",
                    "hypothesis": "Thermal printer LAN connectivity or paper-out condition may be blocking TCP port 9100 delivery.",
                    "confidence": "medium",
                    "supporting_evidence": f"{len(jobs)} print job failure logs.",
                }
            )
            recommended_actions.append(
                {
                    "action": "Verify printer IP/power on campus LAN and fall back to browser receipt printing until restored.",
                    "requires_human_approval": False,
                }
            )

    elif domain == "qr_failures":
        q_ev = list(
            db.scalars(
                select(QRVerificationEvent)
                .where(QRVerificationEvent.created_at >= since, QRVerificationEvent.is_valid.is_(False))
                .order_by(QRVerificationEvent.created_at.desc())
                .limit(30)
            ).all()
        )
        confirmed_facts.append(
            {
                "fact_type": "verified_db_query",
                "summary": f"{len(q_ev)} invalid/rejected QR verification event(s) in last {hrs}h.",
                "sample_events": [{"result_code": e.result_code, "created_at": e.created_at.isoformat()} for e in q_ev[:10]],
                "observed_at": now.isoformat(),
            }
        )
        if q_ev:
            ai_hypotheses.append(
                {
                    "classification": "ai_hypothesis_unverified",
                    "hypothesis": "Repeated scans of already-collected tokens, wrong-counter scans, or damaged QR screens may be causing rejections.",
                    "confidence": "medium",
                    "supporting_evidence": f"{len(q_ev)} failed QR verification logs.",
                }
            )
            recommended_actions.append(
                {
                    "action": "Inspect Security Fraud Dashboard for duplicate-handover alerts and guide students to assigned counter.",
                    "requires_human_approval": False,
                }
            )

    elif domain == "notification_failures":
        nf = list(
            db.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.created_at >= since, NotificationDelivery.status == "failed")
                .order_by(NotificationDelivery.created_at.desc())
                .limit(30)
            ).all()
        )
        confirmed_facts.append(
            {
                "fact_type": "verified_db_query",
                "summary": f"{len(nf)} failed external notification delivery attempt(s) in last {hrs}h.",
                "sample_errors": [{"channel": d.channel, "provider": d.provider_name, "error": d.last_error} for d in nf[:10]],
                "observed_at": now.isoformat(),
            }
        )
        if nf:
            ai_hypotheses.append(
                {
                    "classification": "ai_hypothesis_unverified",
                    "hypothesis": "Unconfigured external email/SMS/push credentials or expired browser push subscriptions may be causing delivery failures.",
                    "confidence": "high",
                    "supporting_evidence": f"{len(nf)} failed NotificationDelivery records.",
                }
            )
            recommended_actions.append(
                {
                    "action": "Verify email/push provider settings and retry eligible failed deliveries from Notification Center.",
                    "requires_human_approval": False,
                }
            )

    if not ai_hypotheses:
        ai_hypotheses.append(
            {
                "classification": "ai_hypothesis_unverified",
                "hypothesis": f"No anomalous failure events were detected in '{domain}' over the last {hrs}h based on current database records.",
                "confidence": "high",
                "supporting_evidence": "Zero anomaly rows matched query window.",
            }
        )

    related_incs = list(
        db.scalars(
            select(OperationalIncident)
            .where(OperationalIncident.status.in_(("open", "investigating")))
            .order_by(OperationalIncident.created_at.desc())
            .limit(10)
        ).all()
    )
    linked_ids = [str(i.id) for i in related_incs]

    inv_row = RootCauseInvestigation(
        incident_id=incident_id,
        canteen_id=canteen_id,
        target_domain=domain,
        query_summary=f"Root-cause investigation for {domain.replace('_', ' ')} (last {hrs}h)",
        confirmed_facts_json=confirmed_facts,
        ai_hypotheses_json=ai_hypotheses,
        recommended_actions_json=recommended_actions,
        linked_incident_ids_json=linked_ids,
        status="open",
        created_by_user_id=actor_user_id,
    )
    db.add(inv_row)
    record_audit_log(
        db,
        action="command_center.rca_executed",
        entity_type="root_cause_investigation",
        entity_id=domain,
        actor_user_id=actor_user_id,
        details={"lookback_hours": hrs, "facts_count": len(confirmed_facts)},
    )
    db.commit()
    db.refresh(inv_row)
    return _serialize_rca(inv_row)


def _serialize_rca(r: RootCauseInvestigation) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "incident_id": str(r.incident_id) if r.incident_id else None,
        "canteen_id": str(r.canteen_id) if r.canteen_id else None,
        "target_domain": r.target_domain,
        "query_summary": r.query_summary,
        "confirmed_facts": r.confirmed_facts_json or [],
        "ai_hypotheses": r.ai_hypotheses_json or [],
        "recommended_actions": r.recommended_actions_json or [],
        "linked_incident_ids": r.linked_incident_ids_json or [],
        "status": r.status,
        "transparency_notice": "Confirmed facts come directly from recorded database tables; AI hypotheses require human verification.",
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
    }


def list_investigations(
    db: Session, *, canteen_id: Optional[UUID] = None, limit: int = 30, offset: int = 0
) -> list[dict[str, Any]]:
    stmt = (
        select(RootCauseInvestigation)
        .order_by(RootCauseInvestigation.created_at.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 100)))
    )
    if canteen_id:
        stmt = stmt.where((RootCauseInvestigation.canteen_id == canteen_id) | (RootCauseInvestigation.canteen_id.is_(None)))
    return [_serialize_rca(r) for r in db.scalars(stmt).all()]


def review_investigation(db: Session, investigation_id: UUID, *, status: str, actor_user_id: UUID) -> dict[str, Any]:
    rec = db.get(RootCauseInvestigation, investigation_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Investigation not found")
    st = status.strip().lower()
    if st not in ("reviewed", "closed"):
        raise HTTPException(status_code=400, detail="status must be 'reviewed' or 'closed'")
    rec.status = st
    rec.reviewed_by_user_id = actor_user_id
    rec.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rec)
    return _serialize_rca(rec)


# =============================================================================
# FEATURE 13: PREDICTIVE INCIDENT PREVENTION
# =============================================================================


def get_predictive_incident_prevention(db: Session, *, canteen_id: Optional[UUID] = None) -> dict[str, Any]:
    cache_ns = f"{NS_COMMAND_CENTER}:{canteen_id}" if canteen_id else NS_COMMAND_CENTER
    hit, cached = cache_manager.get_json(cache_ns, "incident_prev", l1_ttl=3.0)
    if hit and isinstance(cached, dict):
        return cached

    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_30d = now - timedelta(days=30)

    crowd = campus_intelligence_service.get_live_crowd_intelligence(db, days=7, include_history=True)
    counters = [c for c in crowd["counters"] if not canteen_id or c["canteen_id"] == str(canteen_id)]
    max_workload = max((c["workload_percent"] for c in counters), default=0)

    inv_q = select(
        func.count(InventoryItem.id),
        func.coalesce(func.sum(case((InventoryItem.current_quantity <= InventoryItem.reorder_level, 1), else_=0)), 0),
    ).where(InventoryItem.is_archived.is_(False))
    if canteen_id:
        inv_q = inv_q.where(InventoryItem.canteen_id == canteen_id)
    inv_total, inv_low = db.execute(inv_q).one()
    inv_total = int(inv_total or 0)
    inv_low = int(inv_low or 0)

    pay_q = select(
        func.count(Payment.id),
        func.coalesce(func.sum(case((Payment.status == "FAILED", 1), else_=0)), 0),
    ).join(Order, Order.id == Payment.order_id).where(Payment.created_at >= since_24h)
    if canteen_id:
        pay_q = pay_q.where(Order.canteen_id == canteen_id)
    pay_total, pay_failed = db.execute(pay_q).one()
    pay_total = int(pay_total or 0)
    pay_failed = int(pay_failed or 0)
    pay_fail_rate = round((pay_failed / pay_total) * 100, 1) if pay_total else None

    temp_violations_7d = int(
        db.scalar(
            select(func.count(EquipmentTemperatureLog.id)).where(
                EquipmentTemperatureLog.is_violation.is_(True),
                EquipmentTemperatureLog.recorded_at >= (now - timedelta(days=7)),
                *([EquipmentTemperatureLog.canteen_id == canteen_id] if canteen_id else []),
            )
        )
        or 0
    )
    hist_incidents_30d = int(
        db.scalar(
            select(func.count(OperationalIncident.id)).where(
                OperationalIncident.created_at >= since_30d,
                *([OperationalIncident.canteen_id == canteen_id] if canteen_id else []),
            )
        )
        or 0
    )

    risks: list[dict[str, Any]] = []
    # Kitchen overload risk
    k_score = min(100, max_workload)
    risks.append(
        {
            "category": "kitchen_congestion",
            "risk_level": "high" if k_score >= 75 else ("medium" if k_score >= 45 else "low"),
            "risk_score": k_score,
            "confidence": "high" if any(c["historical_orders_analyzed"] > 0 for c in counters) else "low",
            "evidence": f"Peak active counter workload is {max_workload}% across {len(counters)} counter(s).",
            "suggested_preventive_actions": [
                "Rebalance staff toward the higher-load counter.",
                "Monitor prep times and communicate updated estimates to students.",
            ],
        }
    )

    # Stockout risk
    if inv_total:
        s_ratio = round((inv_low / inv_total) * 100)
        risks.append(
            {
                "category": "inventory_stockout",
                "risk_level": "high" if s_ratio >= 30 or inv_low >= 5 else ("medium" if inv_low >= 1 else "low"),
                "risk_score": min(100, s_ratio),
                "confidence": "high",
                "evidence": f"{inv_low} of {inv_total} tracked ingredients are at/below reorder threshold.",
                "suggested_preventive_actions": [
                    "Review draft Purchase Orders in Automated Reordering.",
                    "Verify menu items linked to low-stock ingredients.",
                ],
            }
        )

    # Payment reliability risk
    if pay_fail_rate is not None:
        risks.append(
            {
                "category": "payment_failures",
                "risk_level": "high" if pay_fail_rate >= 20 else ("medium" if pay_fail_rate >= 8 else "low"),
                "risk_score": min(100, round(pay_fail_rate)),
                "confidence": "medium" if pay_total >= 5 else "low",
                "evidence": f"{pay_fail_rate}% Razorpay failure rate across {pay_total} payment attempt(s) in last 24h.",
                "suggested_preventive_actions": [
                    "Check Razorpay webhook logs and run sync on stale PENDING orders.",
                ],
            }
        )
    else:
        risks.append(
            {
                "category": "payment_failures",
                "risk_level": "insufficient_data",
                "risk_score": None,
                "confidence": "low",
                "evidence": "No payment attempts recorded in the last 24 hours.",
                "suggested_preventive_actions": ["No action needed; risk scoring activates once payment traffic occurs."],
            }
        )

    # Equipment temperature risk
    risks.append(
        {
            "category": "equipment_temperature",
            "risk_level": "high" if temp_violations_7d >= 2 else ("medium" if temp_violations_7d == 1 else "low"),
            "risk_score": min(100, temp_violations_7d * 35),
            "confidence": "medium" if temp_violations_7d > 0 else "low",
            "evidence": f"{temp_violations_7d} equipment temperature violation(s) logged in last 7 days.",
            "suggested_preventive_actions": [
                "Inspect cold-storage seals and calibrate kitchen refrigeration units."
                if temp_violations_7d > 0
                else "Continue scheduled temperature logging."
            ],
        }
    )

    result = {
        "risk_assessments": risks,
        "historical_incidents_30d": hist_incidents_30d,
        "disclaimer": (
            "Risk scores are transparent early-warning indicators computed strictly from recorded operational metrics. "
            "They do not guarantee incident prevention."
        ),
        "last_updated_at": now.isoformat(),
    }
    cache_manager.set_json(cache_ns, "incident_prev", result, ttl_seconds=15, l1_ttl=3.0)
    return result


# =============================================================================
# FEATURE 14: INTELLIGENT RESOURCE ALLOCATION (ADVISORY, APPROVAL-GATED)
# =============================================================================


def get_intelligent_resource_allocation(db: Session, *, canteen_id: Optional[UUID] = None) -> dict[str, Any]:
    cache_ns = f"{NS_COMMAND_CENTER}:{canteen_id}" if canteen_id else NS_COMMAND_CENTER
    hit, cached = cache_manager.get_json(cache_ns, "resource_alloc", l1_ttl=3.0)
    if hit and isinstance(cached, dict):
        return cached

    now = datetime.now(timezone.utc)
    today_d = today_college()
    crowd = campus_intelligence_service.get_live_crowd_intelligence(db, days=7, include_history=False)
    counters = [c for c in crowd["counters"] if not canteen_id or c["canteen_id"] == str(canteen_id)]

    # Actual staff records
    staff_rows = list(db.scalars(select(StaffProfile)).all())
    present_today = set(
        db.scalars(
            select(StaffAttendance.staff_user_id).where(
                StaffAttendance.attendance_date == today_d,
                StaffAttendance.status == "present",
                StaffAttendance.check_out_at.is_(None),
            )
        ).all()
    )
    shifts_today = list(db.scalars(select(StaffShift).where(StaffShift.shift_date == today_d)).all())

    # Station workloads
    station_rows = db.execute(
        select(KitchenStation.name, KitchenStation.station_type, func.count(OrderItem.id))
        .outerjoin(
            OrderItem,
            (OrderItem.station_id == KitchenStation.id) & (OrderItem.prep_status.in_(("PENDING", "PREPARING"))),
        )
        .where(KitchenStation.is_active.is_(True))
        .group_by(KitchenStation.id, KitchenStation.name, KitchenStation.station_type)
    ).all()

    counter_staff_view: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    for c in counters:
        cid = UUID(c["canteen_id"])
        assigned = [s for s in staff_rows if s.assigned_canteen_id == cid]
        on_duty_cnt = len({s.user_id for s in assigned if s.is_on_duty or s.user_id in present_today})
        counter_staff_view.append(
            {
                "counter_slot": c["counter_slot"],
                "canteen_id": c["canteen_id"],
                "canteen_name": c["canteen_name"],
                "active_orders": c["active_orders"],
                "workload_percent": c["workload_percent"],
                "assigned_staff_count": len(assigned),
                "on_duty_staff_count": on_duty_cnt,
            }
        )
        if c["workload_percent"] >= 60 and on_duty_cnt < 3:
            recommendations.append(
                {
                    "type": "staffing_rebalance",
                    "priority": "high",
                    "target": c["canteen_name"],
                    "recommendation": (
                        f"{c['canteen_name']} ({c['counter_slot']}) is at {c['workload_percent']}% workload with "
                        f"{on_duty_cnt} recorded on-duty staff. Consider assigning temporary peak-hour support."
                    ),
                    "requires_authorized_approval": True,
                }
            )

    if len(counter_staff_view) == 2:
        diff = abs(counter_staff_view[0]["workload_percent"] - counter_staff_view[1]["workload_percent"])
        if diff >= 30:
            busier = max(counter_staff_view, key=lambda x: x["workload_percent"])
            quieter = min(counter_staff_view, key=lambda x: x["workload_percent"])
            recommendations.append(
                {
                    "type": "counter_balancing",
                    "priority": "medium",
                    "target": f"{quieter['canteen_name']} -> {busier['canteen_name']}",
                    "recommendation": (
                        f"Workload imbalance of {diff}% between {busier['canteen_name']} ({busier['workload_percent']}%) "
                        f"and {quieter['canteen_name']} ({quieter['workload_percent']}%). Manager may temporarily cross-support prep/pickup."
                    ),
                    "requires_authorized_approval": True,
                }
            )

    # Stock replenishment priorities
    low_invs = db.execute(
        select(InventoryItem, Ingredient.name, Canteen.name)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .join(Canteen, Canteen.id == InventoryItem.canteen_id)
        .where(InventoryItem.is_archived.is_(False), InventoryItem.current_quantity <= InventoryItem.reorder_level)
        .order_by(InventoryItem.current_quantity.asc())
        .limit(8)
    ).all()
    if low_invs:
        recommendations.append(
            {
                "type": "stock_replenishment_priority",
                "priority": "high",
                "target": "Inventory & Procurement",
                "recommendation": f"Prioritize replenishment review for {len(low_invs)} low-stock ingredient(s): "
                + ", ".join(f"{nm} ({cn})" for _, nm, cn in low_invs[:5]),
                "requires_authorized_approval": True,
            }
        )

    result = {
        "two_counter_structure_preserved": True,
        "counters_allocation": counter_staff_view,
        "station_utilization": [
            {"station_name": r[0], "station_type": r[1], "active_items": int(r[2] or 0)} for r in station_rows
        ],
        "scheduled_shifts_today": len(shifts_today),
        "recommendations": recommendations,
        "governance_notice": (
            "All recommendations are advisory only and never automatically modify staff schedules, HR records, or counters."
        ),
        "last_updated_at": now.isoformat(),
    }
    cache_manager.set_json(cache_ns, "resource_alloc", result, ttl_seconds=15, l1_ttl=3.0)
    return result


# =============================================================================
# FEATURE 15: NATURAL LANGUAGE ADMINISTRATIVE COMMAND CENTER
# =============================================================================


def process_nl_admin_command(
    db: Session,
    *,
    question: str,
    canteen_id: Optional[UUID],
    actor_user_id: UUID,
    actor_roles: set[str],
) -> dict[str, Any]:
    clean_q = (question or "").strip()
    if not clean_q:
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    now = datetime.now(timezone.utc)
    low = clean_q.lower()
    can_view_finance = bool(actor_roles & FINANCE_ROLES)

    # Strict destructive & secret-exfiltration blocker
    for pat in _BLOCKED_NL_PATTERNS:
        if re.search(pat, low):
            db.add(
                AIAssistantAuditLog(
                    user_id=actor_user_id,
                    canteen_id=canteen_id,
                    user_roles=",".join(sorted(actor_roles)),
                    question=clean_q[:500],
                    resolved_intents="blocked_destructive_or_secret",
                    tools_invoked=[],
                    blocked_action_attempted=True,
                )
            )
            db.commit()
            return {
                "status": "blocked",
                "intent": "blocked_action",
                "answer": (
                    "Blocked for security & governance: Natural-language commands are strictly read-only and cannot "
                    "execute destructive actions, modify prices/orders/users, issue refunds, approve POs, or reveal credentials/secrets."
                ),
                "evidence": [],
                "suggested_investigations": [],
                "timestamp": now.isoformat(),
            }

    evidence: list[dict[str, Any]] = []
    suggested_investigations: list[str] = []
    tools_invoked: list[str] = []
    intent = "operational_overview"
    answer = ""

    # Resolve specific Counter 1 / Counter 2 mention if asked
    target_cid = canteen_id
    canteens = list(db.scalars(select(Canteen).where(Canteen.is_active.is_(True)).order_by(Canteen.code.asc())).all())
    if "counter 1" in low or "main canteen" in low:
        if len(canteens) >= 1:
            target_cid = canteens[0].id
    elif "counter 2" in low or "snacks" in low or "bakery" in low:
        if len(canteens) >= 2:
            target_cid = canteens[1].id

    if "delay" in low or "late" in low or "slow" in low:
        intent = "order_delays"
        tools_invoked.append("order_delay_query")
        q = select(Order).where(
            Order.status.in_(("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING")),
            Order.delayed_minutes > 0,
        )
        if target_cid:
            q = q.where(Order.canteen_id == target_cid)
        delayed = list(db.scalars(q.order_by(Order.delayed_minutes.desc()).limit(15)).all())
        if not delayed:
            answer = "There are currently 0 active delayed orders matching that counter scope."
        else:
            reasons = [o.delay_reason or "unspecified reason" for o in delayed[:5]]
            answer = (
                f"Found {len(delayed)} active delayed order(s). Longest delay: {delayed[0].delayed_minutes} min "
                f"(Order {delayed[0].order_number}). Recorded reasons: {', '.join(set(reasons))}."
            )
            evidence = [
                {
                    "order_number": o.order_number,
                    "status": o.status,
                    "delayed_minutes": o.delayed_minutes,
                    "delay_reason": o.delay_reason,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                }
                for o in delayed[:8]
            ]
            suggested_investigations.append("order_delays")

    elif "run out" in low or "ingredient" in low or "stock" in low:
        intent = "low_stock_ingredients"
        tools_invoked.append("inventory_low_stock_query")
        q = (
            select(InventoryItem, Ingredient.name, Canteen.name)
            .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
            .join(Canteen, Canteen.id == InventoryItem.canteen_id)
            .where(InventoryItem.is_archived.is_(False), InventoryItem.current_quantity <= InventoryItem.reorder_level)
        )
        if target_cid:
            q = q.where(InventoryItem.canteen_id == target_cid)
        rows = db.execute(q.order_by(InventoryItem.current_quantity.asc()).limit(15)).all()
        if not rows:
            answer = "All tracked ingredients are currently above their configured reorder levels."
        else:
            names = ", ".join(f"{nm} ({inv.current_quantity} left, reorder {inv.reorder_level})" for inv, nm, _ in rows[:6])
            answer = f"{len(rows)} ingredient(s) are at or below reorder threshold and may run out soon: {names}."
            evidence = [
                {"ingredient": nm, "canteen": cn, "current_quantity": str(inv.current_quantity), "reorder_level": str(inv.reorder_level)}
                for inv, nm, cn in rows
            ]
            suggested_investigations.append("stock_shortages")

    elif "unavailable" in low or "out of stock" in low or "menu" in low:
        intent = "unavailable_items"
        tools_invoked.append("menu_availability_query")
        q = select(FoodItem, Canteen.name).join(Canteen, Canteen.id == FoodItem.canteen_id).where(
            FoodItem.is_active.is_(True),
            (FoodItem.is_available.is_(False)) | (FoodItem.insufficient_ingredients.is_(True)),
        )
        if target_cid:
            q = q.where(FoodItem.canteen_id == target_cid)
        rows = db.execute(q.limit(25)).all()
        if not rows:
            answer = "All active menu items are currently available."
        else:
            answer = f"{len(rows)} menu item(s) are currently unavailable: " + ", ".join(f.name for f, _ in rows[:10]) + "."
            evidence = [
                {"item": f.name, "canteen": cn, "insufficient_ingredients": f.insufficient_ingredients, "is_available": f.is_available}
                for f, cn in rows
            ]

    elif "payment" in low or "discrepanc" in low or "reconcil" in low or "settlement" in low:
        intent = "payment_discrepancies"
        tools_invoked.append("reconciliation_query")
        if not can_view_finance:
            answer = "Financial and payment discrepancy details are restricted to authorized finance/admin roles."
        else:
            discs = list(
                db.scalars(
                    select(PaymentReconciliation)
                    .where(PaymentReconciliation.status.in_(("open", "mismatch", "pending_review")))
                    .order_by(PaymentReconciliation.created_at.desc())
                    .limit(15)
                ).all()
            )
            if not discs:
                answer = "There are currently 0 open Razorpay payment discrepancies requiring attention."
            else:
                answer = f"There are {len(discs)} open Razorpay reconciliation discrepancy(ies) requiring review."
                evidence = [
                    {
                        "id": str(d.id),
                        "discrepancy_type": d.discrepancy_type,
                        "status": d.status,
                        "created_at": d.created_at.isoformat() if d.created_at else None,
                    }
                    for d in discs
                ]
                suggested_investigations.append("settlement_mismatches")

    elif "incident" in low or "unresolved" in low or "issue" in low:
        intent = "unresolved_incidents"
        tools_invoked.append("incidents_query")
        ops_inc = list_operational_incidents(db, canteen_id=target_cid, status_filter="open", limit=15)
        fs_inc = list(
            db.scalars(
                select(FoodSafetyIncident)
                .where(FoodSafetyIncident.status.in_(("open", "investigating")))
                .limit(10)
            ).all()
        )
        total_open = len(ops_inc) + len(fs_inc)
        if total_open == 0:
            answer = "There are currently 0 unresolved operational or food-safety incidents."
        else:
            answer = f"There are {len(ops_inc)} open operational incident(s) and {len(fs_inc)} open food-safety incident(s)."
            evidence = [{"type": "operational", "code": i["incident_code"], "title": i["title"], "severity": i["severity"]} for i in ops_inc[:6]]
            evidence += [{"type": "food_safety", "code": f.incident_number, "title": f.title, "severity": f.severity} for f in fs_inc[:6]]

    elif "waiting" in low or "workload" in low or "kitchen" in low or "queue" in low:
        intent = "kitchen_workload"
        tools_invoked.append("live_crowd_intelligence")
        crowd = campus_intelligence_service.get_live_crowd_intelligence(db, days=7)
        scoped = [c for c in crowd["counters"] if not target_cid or c["canteen_id"] == str(target_cid)]
        total_waiting = sum(c["waiting_orders"] for c in scoped)
        total_prep = sum(c["preparing_orders"] for c in scoped)
        parts = [f"{c['canteen_name']}: {c['waiting_orders']} waiting, {c['preparing_orders']} preparing ({c['workload_percent']}% load)" for c in scoped]
        answer = f"Live kitchen queue: {total_waiting} waiting and {total_prep} preparing. " + "; ".join(parts) + "."
        evidence = scoped
        if any(c["workload_percent"] >= 65 for c in scoped):
            suggested_investigations.append("kitchen_bottlenecks")

    else:
        intent = "unified_summary"
        tools_invoked.append("unified_operational_intelligence")
        uni = get_unified_operational_intelligence(db, canteen_id=target_cid)
        answer = (
            f"Operational health is '{uni['operational_health']}'. Last 24h: {uni['orders_24h']['total']} orders "
            f"({uni['orders_24h']['completed']} completed, {uni['orders_24h']['delayed_active']} active delayed), "
            f"{uni['inventory']['low_stock_count']} low-stock ingredients, {uni['menu_availability']['unavailable_now']} unavailable items, "
            f"{uni['incidents_summary']['open_operational_incidents']} open operational incidents."
        )
        evidence = uni["critical_alerts"]

    db.add(
        AIAssistantAuditLog(
            user_id=actor_user_id,
            canteen_id=target_cid,
            user_roles=",".join(sorted(actor_roles)),
            question=clean_q[:500],
            resolved_intents=intent,
            tools_invoked=tools_invoked,
            blocked_action_attempted=False,
        )
    )
    db.commit()

    return {
        "status": "answered",
        "intent": intent,
        "answer": answer,
        "evidence": evidence,
        "suggested_investigations": suggested_investigations,
        "data_source": "collegebites_live_database",
        "timestamp": now.isoformat(),
    }


# =============================================================================
# FEATURE 16: LIVE DIGITAL CAFETERIA MAP
# =============================================================================


def get_live_cafeteria_map(db: Session, *, hours: int = 24) -> dict[str, Any]:
    lookback_h = max(1, min(int(hours or 24), 168))
    cache_key = f"cafeteria_map:h={lookback_h}"
    hit, cached = cache_manager.get_json(NS_COMMAND_CENTER, cache_key, l1_ttl=3.0)
    if hit and isinstance(cached, dict):
        return cached

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=lookback_h)

    crowd = campus_intelligence_service.get_live_crowd_intelligence(db, days=7, include_history=False)
    seating = campus_intelligence_service.list_seating_availability(db)
    kitchens = list(db.scalars(select(Kitchen).where(Kitchen.is_active.is_(True))).all())
    open_incidents = list_operational_incidents(db, status_filter="open", limit=30)

    # Single batched SQL aggregate for historical order volume per counter in window
    hist_map = {
        str(cid): int(cnt or 0)
        for cid, cnt in db.execute(
            select(Order.canteen_id, func.count(Order.id))
            .where(Order.created_at >= since, Order.status.notin_(("PAYMENT_FAILED", "CANCELLED")))
            .group_by(Order.canteen_id)
        ).all()
    }
    # Single batched SQL aggregate for kitchen active orders (eliminates N+1 per kitchen)
    kitchen_prep_by_canteen = {
        cid: int(cnt or 0)
        for cid, cnt in db.execute(
            select(Order.canteen_id, func.count(Order.id))
            .where(Order.status.in_(("ACCEPTED", "PREPARING")))
            .group_by(Order.canteen_id)
        ).all()
    }

    sections: list[dict[str, Any]] = []
    for idx, c in enumerate(crowd["counters"], start=1):
        cid_str = c["canteen_id"]
        c_alerts = [i for i in open_incidents if i["canteen_id"] == cid_str]
        sections.append(
            {
                "zone_id": f"counter_{idx}",
                "section_type": "counter",
                "label": f"{c['counter_slot']} — {c['canteen_name']}",
                "canteen_id": cid_str,
                "location": c["location"],
                "status": "paused" if c["ordering_paused"] else ("closed" if not c["is_open_now"] else c["activity_level"]),
                "workload_percent": c["workload_percent"],
                "active_orders": c["active_orders"],
                "waiting_orders": c["waiting_orders"],
                "preparing_orders": c["preparing_orders"],
                "ready_orders": c["ready_orders"],
                "historical_orders_window": hist_map.get(cid_str, 0),
                "alerts_count": len(c_alerts),
                "alerts": c_alerts[:5],
            }
        )

    for k in kitchens:
        k_prep = kitchen_prep_by_canteen.get(k.canteen_id, 0)
        k_pct = min(100, round((k_prep / max(1, int(k.max_active_orders or 35))) * 100))
        sections.append(
            {
                "zone_id": f"kitchen_{str(k.id)[:8]}",
                "section_type": "kitchen",
                "label": f"Kitchen — {k.name}",
                "canteen_id": str(k.canteen_id),
                "status": "busy" if k_pct >= 70 else ("moderate" if k_pct >= 35 else "low"),
                "workload_percent": k_pct,
                "active_orders": k_prep,
                "max_active_orders": k.max_active_orders,
                "alerts_count": 0,
            }
        )

    ready_total = sum(c["ready_orders"] for c in crowd["counters"])
    sections.append(
        {
            "zone_id": "pickup_area",
            "section_type": "pickup_area",
            "label": "Cafeteria Pickup & QR Handover Zone",
            "status": "busy" if ready_total >= 12 else ("moderate" if ready_total >= 5 else "low"),
            "ready_orders": ready_total,
            "workload_percent": min(100, ready_total * 8),
            "alerts_count": 0,
        }
    )

    for z in seating["zones"]:
        occ_pct = z["occupancy_percent"]
        sections.append(
            {
                "zone_id": z["zone_code"],
                "section_type": "seating",
                "label": z["zone_name"],
                "status": (
                    "unconfigured"
                    if occ_pct is None
                    else ("busy" if occ_pct >= 80 else ("moderate" if occ_pct >= 45 else "low"))
                ),
                "total_seats": z["total_seats"],
                "occupied_seats": z["occupied_seats"],
                "available_seats": z["available_seats"],
                "occupancy_percent": occ_pct,
                "data_source": z["data_source"],
                "last_measured_at": z["last_measured_at"],
            }
        )

    result = {
        "layout_source": "configured_cafeteria_entities",
        "two_counter_cafeteria": True,
        "historical_window_hours": lookback_h,
        "sections": sections,
        "seating_configured": seating["configured"],
        "transparency_notice": (
            "Map reflects actual configured cafeteria counters, kitchens, pickup area, and seating zones. "
            "Indicators are driven exclusively by live database metrics without decorative synthetic activity."
        ),
        "last_updated_at": now.isoformat(),
    }
    cache_manager.set_json(NS_COMMAND_CENTER, cache_key, result, ttl_seconds=15, l1_ttl=3.0)
    return result


# =============================================================================
# FEATURE 18: AUTOMATED DAILY / WEEKLY / MONTHLY OPERATIONS REPORTS
# =============================================================================


def generate_operational_report(
    db: Session,
    *,
    period_type: str = "daily",
    canteen_id: Optional[UUID] = None,
    actor_user_id: Optional[UUID] = None,
    generation_source: str = "manual",
) -> dict[str, Any]:
    pt = period_type.strip().lower()
    if pt not in ("daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail="period_type must be daily, weekly, or monthly")
    today_d = today_college()
    delta = 0 if pt == "daily" else (6 if pt == "weekly" else 29)
    start_d = today_d - timedelta(days=delta)
    start_dt = datetime.combine(start_d, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(today_d + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    q = select(Order).where(Order.created_at >= start_dt, Order.created_at < end_dt)
    if canteen_id:
        q = q.where(Order.canteen_id == canteen_id)
    orders = list(db.scalars(q).all())

    total_orders = len(orders)
    completed_orders = sum(1 for o in orders if o.status == "COMPLETED")
    cancelled_orders = sum(1 for o in orders if o.status in ("CANCELLED", "REJECTED"))
    delayed_orders = sum(1 for o in orders if int(o.delayed_minutes or 0) > 0)

    prep_durations: list[float] = []
    for o in orders:
        c_u, r_u = _as_utc(o.confirmed_at), _as_utc(o.ready_at)
        if c_u and r_u and r_u > c_u:
            prep_durations.append(round((r_u - c_u).total_seconds() / 60.0, 2))

    avg_prep = round(sum(prep_durations) / len(prep_durations), 2) if prep_durations else None
    median_prep = round(statistics.median(prep_durations), 2) if prep_durations else None

    canteens = list(db.scalars(select(Canteen).where(Canteen.is_active.is_(True)).order_by(Canteen.code.asc())).all())
    counter_breakdown = []
    for idx, c in enumerate(canteens, start=1):
        if canteen_id and c.id != canteen_id:
            continue
        c_ords = [o for o in orders if o.canteen_id == c.id]
        counter_breakdown.append(
            {
                "counter_slot": f"Counter {idx}",
                "canteen_id": str(c.id),
                "canteen_name": c.name,
                "total_orders": len(c_ords),
                "completed_orders": sum(1 for o in c_ords if o.status == "COMPLETED"),
                "cancelled_orders": sum(1 for o in c_ords if o.status in ("CANCELLED", "REJECTED")),
                "delayed_orders": sum(1 for o in c_ords if int(o.delayed_minutes or 0) > 0),
            }
        )

    inv_q = select(InventoryItem).where(InventoryItem.is_archived.is_(False))
    if canteen_id:
        inv_q = inv_q.where(InventoryItem.canteen_id == canteen_id)
    inv_rows = list(db.scalars(inv_q).all())
    low_stock_alerts = sum(1 for i in inv_rows if i.current_quantity <= i.reorder_level)

    food_q = select(FoodItem).where(FoodItem.is_active.is_(True))
    if canteen_id:
        food_q = food_q.where(FoodItem.canteen_id == canteen_id)
    foods = list(db.scalars(food_q).all())
    avail_foods = sum(1 for f in foods if f.is_available and not f.insufficient_ingredients)

    pay_q = select(Payment).join(Order, Order.id == Payment.order_id).where(Payment.created_at >= start_dt, Payment.created_at < end_dt)
    if canteen_id:
        pay_q = pay_q.where(Order.canteen_id == canteen_id)
    pays = list(db.scalars(pay_q).all())
    pay_summary = {
        "gateway": "razorpay",
        "confirmed_count": sum(1 for p in pays if p.status == "CONFIRMED"),
        "pending_count": sum(1 for p in pays if p.status == "PENDING"),
        "failed_count": sum(1 for p in pays if p.status == "FAILED"),
        "verified_revenue_inr": str(sum((Decimal(str(p.amount)) for p in pays if p.status == "CONFIRMED"), Decimal("0.00"))),
        "app_refunds_count": 0,
        "refund_policy": "No in-app refunds (college finance policy).",
    }

    unresolved_ops = int(
        db.scalar(select(func.count(OperationalIncident.id)).where(OperationalIncident.status.in_(("open", "investigating")))) or 0
    )
    unresolved_fs = int(
        db.scalar(select(func.count(FoodSafetyIncident.id)).where(FoodSafetyIncident.status.in_(("open", "investigating")))) or 0
    )

    recs: list[str] = []
    if delayed_orders > 0:
        recs.append(f"Investigate {delayed_orders} delayed order(s) recorded during this {pt} period.")
    if low_stock_alerts > 0:
        recs.append(f"Review {low_stock_alerts} low-stock ingredient(s) and approve pending draft POs if needed.")
    if pay_summary["failed_count"] > 0:
        recs.append(f"Audit {pay_summary['failed_count']} failed Razorpay payment attempt(s) in Reconciliation.")
    if unresolved_ops + unresolved_fs > 0:
        recs.append(f"Resolve {unresolved_ops} open operational and {unresolved_fs} open food-safety incident(s).")
    if not recs:
        recs.append("No critical operational exceptions recorded in this period.")

    payload = {
        "period_type": pt,
        "period_start": start_d.isoformat(),
        "period_end": today_d.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_integrity": "verified_database_records_only",
        "orders": {
            "total": total_orders,
            "completed": completed_orders,
            "cancelled_or_rejected": cancelled_orders,
            "delayed": delayed_orders,
            "recorded_prep_samples": len(prep_durations),
            "avg_actual_prep_minutes": avg_prep,
            "median_actual_prep_minutes": median_prep,
        },
        "counter_activity": counter_breakdown,
        "inventory_alerts": {"low_stock_count": low_stock_alerts, "total_tracked": len(inv_rows)},
        "menu_availability": {"available_now": avail_foods, "unavailable_now": len(foods) - avail_foods, "total_active": len(foods)},
        "payments_and_refunds": pay_summary,
        "unresolved_incidents": {"operational": unresolved_ops, "food_safety": unresolved_fs},
        "recommendations": recs,
    }

    rec = OperationalReportRecord(
        canteen_id=canteen_id,
        period_type=pt,
        period_start=start_d,
        period_end=today_d,
        report_payload_json=payload,
        generated_by_user_id=actor_user_id,
        generation_source=generation_source,
    )
    db.add(rec)
    record_audit_log(
        db,
        action="command_center.report_generated",
        entity_type="operational_report",
        entity_id=f"{pt}:{start_d.isoformat()}",
        actor_user_id=actor_user_id,
        details={"period_type": pt, "total_orders": total_orders},
    )
    db.commit()
    db.refresh(rec)
    return {"id": str(rec.id), "generation_source": rec.generation_source, **payload}


def list_operational_reports(db: Session, *, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(OperationalReportRecord)
            .order_by(OperationalReportRecord.created_at.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 100)))
        ).all()
    )
    return [
        {
            "id": str(r.id),
            "canteen_id": str(r.canteen_id) if r.canteen_id else None,
            "period_type": r.period_type,
            "period_start": r.period_start.isoformat(),
            "period_end": r.period_end.isoformat(),
            "generation_source": r.generation_source,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "summary": r.report_payload_json,
        }
        for r in rows
    ]


def export_operational_report_csv(db: Session, report_id: UUID) -> tuple[bytes, str]:
    rec = db.get(OperationalReportRecord, report_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Operational report not found")
    p = rec.report_payload_json or {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Section", "Metric", "Value"])
    w.writerow(["Period", "Type", _safe_csv_cell(rec.period_type)])
    w.writerow(["Period", "Range", f"{rec.period_start} to {rec.period_end}"])
    for k, v in (p.get("orders") or {}).items():
        w.writerow(["Orders", k, _safe_csv_cell(v)])
    for c in p.get("counter_activity") or []:
        w.writerow(["Counter", f"{c['counter_slot']} - {c['canteen_name']}", f"total={c['total_orders']}, completed={c['completed_orders']}, delayed={c['delayed_orders']}"])
    for k, v in (p.get("payments_and_refunds") or {}).items():
        w.writerow(["Payments", k, _safe_csv_cell(v)])
    for k, v in (p.get("inventory_alerts") or {}).items():
        w.writerow(["Inventory", k, _safe_csv_cell(v)])
    for k, v in (p.get("unresolved_incidents") or {}).items():
        w.writerow(["Incidents", k, _safe_csv_cell(v)])
    for idx, r_txt in enumerate(p.get("recommendations") or [], start=1):
        w.writerow(["Recommendation", f"#{idx}", _safe_csv_cell(r_txt)])
    return buf.getvalue().encode("utf-8"), f"collegebites_ops_report_{rec.period_type}_{rec.period_end}.csv"


def export_operational_report_xlsx(db: Session, report_id: UUID) -> tuple[bytes, str]:
    import openpyxl

    rec = db.get(OperationalReportRecord, report_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Operational report not found")
    p = rec.report_payload_json or {}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Operations Report"
    ws.append(["Section", "Metric", "Value"])
    ws.append(["Period", "Type", rec.period_type])
    ws.append(["Period", "Range", f"{rec.period_start} to {rec.period_end}"])
    for k, v in (p.get("orders") or {}).items():
        ws.append(["Orders", k, _safe_csv_cell(v)])
    for c in p.get("counter_activity") or []:
        ws.append(["Counter", f"{c['counter_slot']} - {c['canteen_name']}", f"total={c['total_orders']} completed={c['completed_orders']} delayed={c['delayed_orders']}"])
    for k, v in (p.get("payments_and_refunds") or {}).items():
        ws.append(["Payments", k, _safe_csv_cell(v)])
    for idx, r_txt in enumerate(p.get("recommendations") or [], start=1):
        ws.append(["Recommendation", f"#{idx}", _safe_csv_cell(r_txt)])
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue(), f"collegebites_ops_report_{rec.period_type}_{rec.period_end}.xlsx"


def export_operational_report_pdf(db: Session, report_id: UUID) -> tuple[bytes, str]:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    rec = db.get(OperationalReportRecord, report_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Operational report not found")
    p = rec.report_payload_json or {}
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 50
    c.setFont("Helvetica-Bold", 15)
    c.drawString(40, y, f"CollegeBites Automated Operations Report ({rec.period_type.title()})")
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Period: {rec.period_start} to {rec.period_end} | Verified Database Records Only")
    y -= 24

    def _line(label: str, val: Any) -> None:
        nonlocal y
        if y < 60:
            c.showPage()
            y = h - 50
            c.setFont("Helvetica", 10)
        c.drawString(46, y, f"{label}: {val}")
        y -= 15

    ords = p.get("orders") or {}
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Orders & Kitchen Performance")
    y -= 16
    c.setFont("Helvetica", 10)
    _line("Total Orders", ords.get("total"))
    _line("Completed Orders", ords.get("completed"))
    _line("Cancelled / Rejected Orders", ords.get("cancelled_or_rejected"))
    _line("Delayed Orders", ords.get("delayed"))
    _line("Avg Recorded Prep Time (min)", ords.get("avg_actual_prep_minutes") or "Insufficient data")

    y -= 8
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Counter-Wise Activity")
    y -= 16
    c.setFont("Helvetica", 10)
    for cnt in p.get("counter_activity") or []:
        _line(f"{cnt['counter_slot']} ({cnt['canteen_name']})", f"Total={cnt['total_orders']}, Completed={cnt['completed_orders']}, Delayed={cnt['delayed_orders']}")

    y -= 8
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Razorpay Payments, Inventory & Incidents")
    y -= 16
    c.setFont("Helvetica", 10)
    pay = p.get("payments_and_refunds") or {}
    _line("Confirmed Payments / Revenue (INR)", f"{pay.get('confirmed_count')} / INR {pay.get('verified_revenue_inr')}")
    _line("Pending / Failed Payments", f"{pay.get('pending_count')} / {pay.get('failed_count')}")
    _line("Refunds Status", f"{pay.get('app_refunds_count')} ({pay.get('refund_policy')})")
    inv = p.get("inventory_alerts") or {}
    _line("Low-Stock Alerts", f"{inv.get('low_stock_count')} / {inv.get('total_tracked')} tracked")
    inc = p.get("unresolved_incidents") or {}
    _line("Unresolved Incidents", f"Operational={inc.get('operational')}, Food Safety={inc.get('food_safety')}")

    y -= 8
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Operational Recommendations")
    y -= 16
    c.setFont("Helvetica", 10)
    for r_txt in p.get("recommendations") or []:
        _line("-", r_txt[:95])

    c.save()
    return buf.getvalue(), f"collegebites_ops_report_{rec.period_type}_{rec.period_end}.pdf"
