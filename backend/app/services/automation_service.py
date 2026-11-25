from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.cache import NS_COMMAND_CENTER, cache_manager
from app.core.permissions import ROLE_CANTEEN_MANAGER, ROLE_COLLEGE_ADMIN, ROLE_SUPER_ADMIN
from app.models.campus_ops import (
    AutomationExecution,
    AutomationGovernanceState,
    AutomationWorkflow,
)
from app.models.college import Canteen
from app.models.engagement import Notification
from app.services import command_center_service, maintenance_service, notification_service, queue_service, reconciliation_service, reorder_service
from app.services.audit_service import record_audit_log

SENSITIVE_ACTION_TYPES = {
    "refund_review",
    "payment_modification",
    "inventory_adjustment",
    "menu_price_change",
    "order_cancel_override",
    "staff_permission_change",
    "draft_po_approval",
    "destructive_operation",
}

DEFAULT_WORKFLOWS: list[dict[str, Any]] = [
    {
        "workflow_key": "wf_low_stock_alerts",
        "name": "Automatic Low-Stock & Expiry Alerts",
        "description": "Scans active canteens for low-stock and expiring batches and dispatches deduplicated staff notifications.",
        "trigger_type": "low_stock",
        "action_type": "scan_inventory_alerts",
        "responsible_role": "inventory_manager",
        "requires_approval": False,
        "is_sensitive": False,
        "cooldown_minutes": 30,
    },
    {
        "workflow_key": "wf_delayed_order_escalation",
        "name": "Delayed Order Escalation",
        "description": "Identifies overdue kitchen orders and flags priority escalation with audit logs.",
        "trigger_type": "delayed_order",
        "action_type": "escalate_overdue_orders",
        "responsible_role": "canteen_manager",
        "requires_approval": False,
        "is_sensitive": False,
        "cooldown_minutes": 10,
    },
    {
        "workflow_key": "wf_payment_reconciliation_alerts",
        "name": "Razorpay Payment Reconciliation Alerts",
        "description": "Runs automated Razorpay ledger reconciliation and raises alerts on discrepancies.",
        "trigger_type": "payment_reconciliation",
        "action_type": "run_reconciliation",
        "responsible_role": "college_admin",
        "requires_approval": False,
        "is_sensitive": False,
        "cooldown_minutes": 30,
    },
    {
        "workflow_key": "wf_scheduled_daily_report",
        "name": "Scheduled Daily Operations Report",
        "description": "Generates verified daily operations summary across Counter 1 and Counter 2.",
        "trigger_type": "daily_report",
        "action_type": "generate_daily_report",
        "responsible_role": "college_admin",
        "requires_approval": False,
        "is_sensitive": False,
        "cooldown_minutes": 60,
    },
    {
        "workflow_key": "wf_notification_retry",
        "name": "Failed Notification Retry Sweep",
        "description": "Retries eligible failed external email/push notification deliveries.",
        "trigger_type": "notification_retry",
        "action_type": "retry_failed_notifications",
        "responsible_role": "canteen_manager",
        "requires_approval": False,
        "is_sensitive": False,
        "cooldown_minutes": 15,
    },
    {
        "workflow_key": "wf_inventory_replenishment_drafts",
        "name": "Inventory Replenishment Recommendations (Draft-Only)",
        "description": "Generates draft reorder recommendations; human approval required before creating or approving POs.",
        "trigger_type": "inventory_replenishment",
        "action_type": "generate_reorder_recommendations",
        "responsible_role": "inventory_manager",
        "requires_approval": False,
        "is_sensitive": False,
        "cooldown_minutes": 60,
    },
    {
        "workflow_key": "wf_queue_warning_notifications",
        "name": "Counter Queue Workload Warnings",
        "description": "Notifies managers when either counter exceeds high workload thresholds.",
        "trigger_type": "queue_warning",
        "action_type": "emit_queue_warnings",
        "responsible_role": "canteen_manager",
        "requires_approval": False,
        "is_sensitive": False,
        "cooldown_minutes": 15,
    },
    {
        "workflow_key": "wf_sensitive_inventory_adjustment",
        "name": "Approval-Gated Inventory Adjustment Task",
        "description": "Queues proposed inventory discrepancy write-offs for explicit manager authorization before any change.",
        "trigger_type": "approval_task",
        "action_type": "inventory_adjustment",
        "responsible_role": "canteen_manager",
        "requires_approval": True,
        "is_sensitive": True,
        "cooldown_minutes": 5,
    },
    {
        "workflow_key": "wf_sensitive_incident_escalation",
        "name": "Operational Incident Creation & Manager Approval",
        "description": "Creates an audited operational incident record and queues manager sign-off for sensitive overrides.",
        "trigger_type": "incident_creation",
        "action_type": "order_cancel_override",
        "responsible_role": "college_admin",
        "requires_approval": True,
        "is_sensitive": True,
        "cooldown_minutes": 5,
    },
]


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def get_or_create_governance_state(db: Session) -> AutomationGovernanceState:
    state = db.scalar(select(AutomationGovernanceState).limit(1))
    if not state:
        state = AutomationGovernanceState(global_automation_enabled=True)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def get_governance_overview(db: Session) -> dict[str, Any]:
    state = get_or_create_governance_state(db)
    pending_count = int(
        db.scalar(
            select(func.count(AutomationExecution.id)).where(AutomationExecution.status == "pending_approval")
        )
        or 0
    )
    return {
        "global_automation_enabled": state.global_automation_enabled,
        "emergency_disabled_at": state.emergency_disabled_at.isoformat() if state.emergency_disabled_at else None,
        "emergency_reason": state.emergency_reason,
        "pending_approvals_count": pending_count,
        "sensitive_operations_requiring_human_approval": sorted(SENSITIVE_ACTION_TYPES),
    }


def toggle_emergency_automation(
    db: Session, *, enabled: bool, reason: str, actor_user_id: UUID
) -> dict[str, Any]:
    clean_reason = (reason or "").strip()
    if len(clean_reason) < 3:
        raise HTTPException(status_code=400, detail="Documented reason (min 3 characters) is required")
    state = get_or_create_governance_state(db)
    now = datetime.now(timezone.utc)
    state.global_automation_enabled = bool(enabled)
    state.emergency_reason = clean_reason[:300]
    if not enabled:
        state.emergency_disabled_at = now
        state.emergency_disabled_by_user_id = actor_user_id
    else:
        state.emergency_disabled_at = None
        state.emergency_disabled_by_user_id = None
    record_audit_log(
        db,
        action="automation.emergency_override_toggled",
        entity_type="automation_governance",
        entity_id="global",
        actor_user_id=actor_user_id,
        details={"global_automation_enabled": bool(enabled), "reason": clean_reason},
    )
    notification_service.create_role_notifications(
        db,
        roles=["college_admin", "canteen_manager"],
        canteen_id=None,
        event_type="automation_governance_changed",
        category="system",
        priority="critical" if not enabled else "high",
        title="Emergency Automation Override Active" if not enabled else "Automation Re-Enabled",
        message=f"Global automation set to {'ENABLED' if enabled else 'DISABLED'}. Reason: {clean_reason}",
        event_id_base=f"auto_gov:{now.strftime('%Y%m%d%H%M%S')}",
    )
    db.commit()
    return get_governance_overview(db)


def ensure_default_workflows(db: Session) -> list[AutomationWorkflow]:
    hit, seeded = cache_manager.get_json(NS_COMMAND_CENTER, "wf_seeded", l1_ttl=60.0)
    if hit and seeded:
        rows = list(db.scalars(select(AutomationWorkflow).order_by(AutomationWorkflow.name.asc())).all())
        if len(rows) >= len(DEFAULT_WORKFLOWS):
            return rows
    existing_keys = set(db.scalars(select(AutomationWorkflow.workflow_key)).all())
    added = False
    for spec in DEFAULT_WORKFLOWS:
        if spec["workflow_key"] not in existing_keys:
            db.add(AutomationWorkflow(**spec, trigger_config_json={}, action_config_json={}, is_enabled=True))
            added = True
    if added:
        db.commit()
    cache_manager.set_json(NS_COMMAND_CENTER, "wf_seeded", True, ttl_seconds=300, l1_ttl=60.0)
    return list(db.scalars(select(AutomationWorkflow).order_by(AutomationWorkflow.name.asc())).all())


def _serialize_workflow(w: AutomationWorkflow) -> dict[str, Any]:
    return {
        "id": str(w.id),
        "workflow_key": w.workflow_key,
        "name": w.name,
        "description": w.description,
        "trigger_type": w.trigger_type,
        "action_type": w.action_type,
        "canteen_id": str(w.canteen_id) if w.canteen_id else None,
        "trigger_config": w.trigger_config_json or {},
        "action_config": w.action_config_json or {},
        "responsible_role": w.responsible_role,
        "requires_approval": w.requires_approval,
        "is_sensitive": w.is_sensitive,
        "is_enabled": w.is_enabled,
        "cooldown_minutes": w.cooldown_minutes,
        "last_run_at": w.last_run_at.isoformat() if w.last_run_at else None,
    }


def _serialize_execution(e: AutomationExecution, wf_name: Optional[str] = None) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "workflow_id": str(e.workflow_id),
        "workflow_name": wf_name,
        "canteen_id": str(e.canteen_id) if e.canteen_id else None,
        "dedup_key": e.dedup_key,
        "status": e.status,
        "trigger_evidence": e.trigger_evidence_json or {},
        "proposed_action": e.proposed_action_json or {},
        "execution_result": e.execution_result_json,
        "error_message": e.error_message,
        "retry_count": e.retry_count,
        "approved_by_user_id": str(e.approved_by_user_id) if e.approved_by_user_id else None,
        "approved_at": e.approved_at.isoformat() if e.approved_at else None,
        "executed_at": e.executed_at.isoformat() if e.executed_at else None,
        "approval_notes": e.approval_notes,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def list_workflows(db: Session) -> list[dict[str, Any]]:
    rows = ensure_default_workflows(db)
    return [_serialize_workflow(r) for r in rows]


def update_workflow(
    db: Session,
    workflow_id: UUID,
    *,
    is_enabled: Optional[bool] = None,
    requires_approval: Optional[bool] = None,
    cooldown_minutes: Optional[int] = None,
    trigger_config: Optional[dict[str, Any]] = None,
    action_config: Optional[dict[str, Any]] = None,
    actor_user_id: UUID,
) -> dict[str, Any]:
    wf = db.get(AutomationWorkflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if is_enabled is not None:
        wf.is_enabled = bool(is_enabled)
    if requires_approval is not None:
        if wf.is_sensitive and not requires_approval:
            raise HTTPException(
                status_code=400,
                detail="Sensitive operational/financial workflows cannot disable human approval requirements",
            )
        wf.requires_approval = bool(requires_approval)
    if cooldown_minutes is not None:
        wf.cooldown_minutes = max(1, min(1440, int(cooldown_minutes)))
    if trigger_config is not None:
        wf.trigger_config_json = trigger_config
    if action_config is not None:
        wf.action_config_json = action_config
    wf.updated_by_user_id = actor_user_id
    record_audit_log(
        db,
        action="automation.workflow_updated",
        entity_type="automation_workflow",
        entity_id=wf.workflow_key,
        actor_user_id=actor_user_id,
        details={"is_enabled": wf.is_enabled, "requires_approval": wf.requires_approval},
    )
    db.commit()
    db.refresh(wf)
    return _serialize_workflow(wf)


def _run_safe_action(
    db: Session,
    wf: AutomationWorkflow,
    *,
    canteen_id: Optional[UUID],
    actor_user_id: Optional[UUID],
) -> dict[str, Any]:
    act = wf.action_type
    if act == "scan_inventory_alerts":
        return maintenance_service.scan_inventory_alerts(db)
    if act == "escalate_overdue_orders":
        canteens = (
            [db.get(Canteen, canteen_id)]
            if canteen_id
            else list(db.scalars(select(Canteen).where(Canteen.is_active.is_(True))).all())
        )
        total_esc = 0
        for c in [x for x in canteens if x is not None]:
            res = queue_service.escalate_overdue_orders(db, c.id, actor_user_id=actor_user_id)
            total_esc += int(res.get("escalated_count", 0))
        return {"escalated_orders": total_esc}
    if act == "run_reconciliation":
        res = reconciliation_service.run_auto_reconciliation(db, trigger="workflow", actor_user_id=actor_user_id)
        return {"total_checked": res["total_checked"], "discrepancies": res["discrepancy_count"]}
    if act == "generate_daily_report":
        rep = command_center_service.generate_operational_report(
            db, period_type="daily", canteen_id=canteen_id, actor_user_id=actor_user_id, generation_source="scheduled"
        )
        return {"report_id": rep["id"], "total_orders": rep["orders"]["total"]}
    if act == "retry_failed_notifications":
        failed = list(
            db.scalars(
                select(Notification).where(Notification.delivery_status == "failed").limit(10)
            ).all()
        )
        retried = 0
        for n in failed:
            if actor_user_id:
                notification_service.retry_failed_notification(db, n.id, actor_user_id)
                retried += 1
        return {"retried_notifications": retried}
    if act == "generate_reorder_recommendations":
        canteens = (
            [db.get(Canteen, canteen_id)]
            if canteen_id
            else list(db.scalars(select(Canteen).where(Canteen.is_active.is_(True))).all())
        )
        recs_count = 0
        for c in [x for x in canteens if x is not None]:
            recs = reorder_service.generate_reorder_recommendations(db, c.id, actor_user_id=actor_user_id)
            recs_count += len(recs)
        return {"draft_recommendations_generated": recs_count}
    if act == "emit_queue_warnings":
        from app.services import campus_intelligence_service

        crowd = campus_intelligence_service.get_live_crowd_intelligence(db, days=7, include_history=False)
        warned = 0
        for c in crowd["counters"]:
            if c["workload_percent"] >= 65:
                notification_service.create_role_notifications(
                    db,
                    roles=["canteen_manager", "kitchen_staff"],
                    canteen_id=UUID(c["canteen_id"]),
                    event_type="queue_workload_warning",
                    category="queue",
                    priority="high",
                    title=f"High Counter Workload • {c['canteen_name']}",
                    message=f"{c['canteen_name']} is at {c['workload_percent']}% workload ({c['active_orders']} active orders).",
                    event_id_base=f"qwarn:{c['canteen_id']}:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}",
                )
                warned += 1
        return {"counters_warned": warned}
    return {"acknowledged": True, "action_type": act}


def execute_workflow(
    db: Session,
    workflow_id: UUID,
    *,
    canteen_id: Optional[UUID] = None,
    dedup_key: Optional[str] = None,
    proposed_payload: Optional[dict[str, Any]] = None,
    actor_user_id: Optional[UUID] = None,
) -> dict[str, Any]:
    ensure_default_workflows(db)
    wf = db.get(AutomationWorkflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    gov = get_or_create_governance_state(db)
    now = datetime.now(timezone.utc)

    # 1. Duplicate execution prevention
    if dedup_key:
        existing_exec = db.scalar(select(AutomationExecution).where(AutomationExecution.dedup_key == dedup_key))
        if existing_exec:
            return {
                "duplicate_prevented": True,
                **_serialize_execution(existing_exec, wf.name),
            }

    # 2. Emergency kill-switch check
    if not gov.global_automation_enabled:
        ex = AutomationExecution(
            workflow_id=wf.id,
            canteen_id=canteen_id or wf.canteen_id,
            dedup_key=dedup_key,
            status="disabled_by_override",
            trigger_evidence_json={"emergency_reason": gov.emergency_reason},
            proposed_action_json=proposed_payload or {"action_type": wf.action_type},
            requested_by_user_id=actor_user_id,
        )
        db.add(ex)
        db.commit()
        db.refresh(ex)
        return _serialize_execution(ex, wf.name)

    if not wf.is_enabled:
        raise HTTPException(status_code=409, detail=f"Workflow '{wf.name}' is currently disabled")

    # 3. Human-in-the-loop governance gate for ALL sensitive or approval-required workflows
    must_approve = bool(wf.requires_approval or wf.is_sensitive or wf.action_type in SENSITIVE_ACTION_TYPES)
    if must_approve:
        ex = AutomationExecution(
            workflow_id=wf.id,
            canteen_id=canteen_id or wf.canteen_id,
            dedup_key=dedup_key,
            status="pending_approval",
            trigger_evidence_json={"trigger_type": wf.trigger_type, "requested_at": now.isoformat()},
            proposed_action_json=proposed_payload or {"action_type": wf.action_type, "requires_human_approval": True},
            requested_by_user_id=actor_user_id,
        )
        db.add(ex)
        db.flush()
        notification_service.create_role_notifications(
            db,
            roles=["college_admin", "canteen_manager"],
            canteen_id=canteen_id or wf.canteen_id,
            event_type="automation_approval_requested",
            category="system",
            priority="high",
            title=f"Approval Required • {wf.name}",
            message=f"Sensitive workflow '{wf.name}' requires explicit authorized sign-off before execution.",
            event_id_base=f"auto_req:{ex.id}",
        )
        record_audit_log(
            db,
            action="automation.approval_queued",
            entity_type="automation_execution",
            entity_id=str(ex.id),
            actor_user_id=actor_user_id,
            details={"workflow_key": wf.workflow_key, "action_type": wf.action_type},
        )
        db.commit()
        db.refresh(ex)
        return _serialize_execution(ex, wf.name)

    # 4. Execute non-sensitive workflow safely with error capture & alerting
    ex = AutomationExecution(
        workflow_id=wf.id,
        canteen_id=canteen_id or wf.canteen_id,
        dedup_key=dedup_key,
        status="executed",
        trigger_evidence_json={"trigger_type": wf.trigger_type, "triggered_at": now.isoformat()},
        proposed_action_json=proposed_payload or {"action_type": wf.action_type},
        requested_by_user_id=actor_user_id,
    )
    try:
        res = _run_safe_action(db, wf, canteen_id=canteen_id or wf.canteen_id, actor_user_id=actor_user_id)
        ex.execution_result_json = res
        ex.executed_at = now
        wf.last_run_at = now
    except Exception as exc:
        ex.status = "failed"
        ex.error_message = f"{type(exc).__name__}: {str(exc)[:300]}"
        ex.retry_count += 1
        notification_service.create_role_notifications(
            db,
            roles=["college_admin", "canteen_manager"],
            canteen_id=canteen_id or wf.canteen_id,
            event_type="automation_execution_failed",
            category="system",
            priority="critical",
            title=f"Automation Failed • {wf.name}",
            message=f"Workflow '{wf.name}' failed: {ex.error_message}",
            event_id_base=f"auto_fail:{wf.workflow_key}:{now.strftime('%Y%m%d%H%M')}",
        )
    db.add(ex)
    record_audit_log(
        db,
        action="automation.workflow_executed",
        entity_type="automation_workflow",
        entity_id=wf.workflow_key,
        actor_user_id=actor_user_id,
        details={"status": ex.status, "error": ex.error_message},
    )
    db.commit()
    db.refresh(ex)
    return _serialize_execution(ex, wf.name)


def decide_execution_approval(
    db: Session,
    execution_id: UUID,
    *,
    approve: bool,
    notes: str,
    actor_user_id: UUID,
    actor_roles: set[str],
) -> dict[str, Any]:
    if not (actor_roles & {ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER}):
        raise HTTPException(status_code=403, detail="Insufficient privileges to approve or reject automation executions")
    ex = db.scalar(select(AutomationExecution).where(AutomationExecution.id == execution_id).with_for_update())
    if not ex:
        raise HTTPException(status_code=404, detail="Automation execution not found")
    if ex.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Execution is already in state '{ex.status}'")
    wf = db.get(AutomationWorkflow, ex.workflow_id)
    now = datetime.now(timezone.utc)
    ex.approved_by_user_id = actor_user_id
    ex.approved_at = now
    ex.approval_notes = (notes or "").strip()[:500] or None

    if not approve:
        ex.status = "rejected"
    else:
        gov = get_or_create_governance_state(db)
        if not gov.global_automation_enabled:
            raise HTTPException(status_code=409, detail="Global emergency automation override is active; re-enable before approving execution")
        ex.status = "approved"
        ex.executed_at = now
        ex.execution_result_json = {
            "human_approved": True,
            "approved_at": now.isoformat(),
            "note": "Authorized human approval recorded. Sensitive financial/inventory changes remain audited.",
        }
        if wf:
            wf.last_run_at = now

    record_audit_log(
        db,
        action="automation.execution_approved" if approve else "automation.execution_rejected",
        entity_type="automation_execution",
        entity_id=str(ex.id),
        actor_user_id=actor_user_id,
        details={"approve": approve, "notes": ex.approval_notes},
    )
    db.commit()
    db.refresh(ex)
    return _serialize_execution(ex, wf.name if wf else None)


def list_executions(
    db: Session, *, status_filter: Optional[str] = None, limit: int = 80, offset: int = 0
) -> list[dict[str, Any]]:
    stmt = (
        select(AutomationExecution, AutomationWorkflow.name)
        .join(AutomationWorkflow, AutomationWorkflow.id == AutomationExecution.workflow_id)
        .order_by(AutomationExecution.created_at.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 200)))
    )
    if status_filter:
        stmt = stmt.where(AutomationExecution.status == status_filter)
    return [_serialize_execution(ex, wname) for ex, wname in db.execute(stmt).all()]

