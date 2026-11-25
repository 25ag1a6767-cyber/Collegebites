from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_FOOD_SAFETY_INSPECTOR,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
    scoped_canteen_for_principal,
)
from app.services import automation_service, command_center_service, simulation_service

router = APIRouter(prefix="/command-center", tags=["Autonomous Cafeteria Operations Command Center (System B)"])

ADMIN_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)
MANAGER_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
OPS_STAFF_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
    ROLE_CASHIER,
    ROLE_PICKUP_STAFF,
    ROLE_FOOD_SAFETY_INSPECTOR,
)


class IncidentCreateIn(BaseModel):
    canteen_id: Optional[UUID] = None
    category: str = Field(min_length=2, max_length=48)
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=2000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[str] = None


class IncidentUpdateIn(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(open|investigating|mitigated|resolved|closed)$")
    resolution_notes: Optional[str] = Field(default=None, max_length=2000)


class RcaRunIn(BaseModel):
    target_domain: str = Field(min_length=3, max_length=48)
    canteen_id: Optional[UUID] = None
    incident_id: Optional[UUID] = None
    lookback_hours: int = Field(default=24, ge=1, le=168)


class RcaReviewIn(BaseModel):
    status: str = Field(pattern="^(reviewed|closed)$")


class WorkflowUpdateIn(BaseModel):
    is_enabled: Optional[bool] = None
    requires_approval: Optional[bool] = None
    cooldown_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    trigger_config: Optional[dict[str, Any]] = None
    action_config: Optional[dict[str, Any]] = None


class WorkflowExecuteIn(BaseModel):
    canteen_id: Optional[UUID] = None
    dedup_key: Optional[str] = Field(default=None, max_length=160)
    proposed_payload: Optional[dict[str, Any]] = None


class ExecutionDecisionIn(BaseModel):
    approve: bool
    notes: str = Field(default="", max_length=500)


class EmergencyToggleIn(BaseModel):
    enabled: bool
    reason: str = Field(min_length=3, max_length=300)


class NlCommandIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    canteen_id: Optional[UUID] = None


class SimulationRunIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: Optional[str] = Field(default=None, max_length=1000)
    canteen_id: Optional[UUID] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ReportGenerateIn(BaseModel):
    period_type: str = Field(default="daily", pattern="^(daily|weekly|monthly)$")
    canteen_id: Optional[UUID] = None


# --- Feature 10: Unified Operational Intelligence & Incidents ---
@router.get("/unified-status")
def get_unified_status(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*OPS_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, canteen_id) if not principal.has_role(*ADMIN_ROLES) else canteen_id
    return command_center_service.get_unified_operational_intelligence(db, canteen_id=eff_cid)


@router.get("/incidents")
def list_incidents(
    canteen_id: Optional[UUID] = Query(default=None),
    status: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(*OPS_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, canteen_id) if not principal.has_role(*ADMIN_ROLES) else canteen_id
    return command_center_service.list_operational_incidents(
        db, canteen_id=eff_cid, status_filter=status, category=category, limit=limit, offset=offset
    )


@router.post("/incidents")
def create_incident(
    payload: IncidentCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*OPS_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = payload.canteen_id
    if eff_cid and not principal.has_role(*ADMIN_ROLES):
        enforce_canteen_scope(principal, eff_cid)
    return command_center_service.create_operational_incident(
        db,
        canteen_id=eff_cid,
        category=payload.category,
        severity=payload.severity,
        title=payload.title,
        description=payload.description,
        evidence=payload.evidence,
        related_entity_type=payload.related_entity_type,
        related_entity_id=payload.related_entity_id,
        actor_user_id=principal.user.id,
    )


@router.patch("/incidents/{incident_id}")
def update_incident(
    incident_id: UUID,
    payload: IncidentUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return command_center_service.update_operational_incident(
        db,
        incident_id,
        status=payload.status,
        resolution_notes=payload.resolution_notes,
        actor_user_id=principal.user.id,
    )


# --- Feature 11: AI Root-Cause Investigation ---
@router.post("/investigations/run")
def run_investigation(
    payload: RcaRunIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, payload.canteen_id) if not principal.has_role(*ADMIN_ROLES) else payload.canteen_id
    return command_center_service.run_root_cause_investigation(
        db,
        target_domain=payload.target_domain,
        canteen_id=eff_cid,
        incident_id=payload.incident_id,
        lookback_hours=payload.lookback_hours,
        actor_user_id=principal.user.id,
    )


@router.get("/investigations")
def list_investigations(
    canteen_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, canteen_id) if not principal.has_role(*ADMIN_ROLES) else canteen_id
    return command_center_service.list_investigations(db, canteen_id=eff_cid, limit=limit, offset=offset)


@router.patch("/investigations/{investigation_id}/review")
def review_investigation(
    investigation_id: UUID,
    payload: RcaReviewIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return command_center_service.review_investigation(
        db, investigation_id, status=payload.status, actor_user_id=principal.user.id
    )


# --- Feature 12 & 19: Autonomous Workflow Automation & Human Governance ---
@router.get("/governance")
def get_governance(
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return automation_service.get_governance_overview(db)


@router.post("/governance/emergency-toggle")
def toggle_emergency(
    payload: EmergencyToggleIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    return automation_service.toggle_emergency_automation(
        db, enabled=payload.enabled, reason=payload.reason, actor_user_id=principal.user.id
    )


@router.get("/workflows")
def list_workflows(
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return automation_service.list_workflows(db)


@router.patch("/workflows/{workflow_id}")
def update_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return automation_service.update_workflow(
        db,
        workflow_id,
        is_enabled=payload.is_enabled,
        requires_approval=payload.requires_approval,
        cooldown_minutes=payload.cooldown_minutes,
        trigger_config=payload.trigger_config,
        action_config=payload.action_config,
        actor_user_id=principal.user.id,
    )


@router.post("/workflows/{workflow_id}/execute")
def execute_workflow(
    workflow_id: UUID,
    payload: WorkflowExecuteIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, payload.canteen_id) if not principal.has_role(*ADMIN_ROLES) else payload.canteen_id
    return automation_service.execute_workflow(
        db,
        workflow_id,
        canteen_id=eff_cid,
        dedup_key=payload.dedup_key,
        proposed_payload=payload.proposed_payload,
        actor_user_id=principal.user.id,
    )


@router.get("/executions")
def list_executions(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=80, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return automation_service.list_executions(db, status_filter=status, limit=limit, offset=offset)


@router.post("/executions/{execution_id}/decision")
def decide_execution(
    execution_id: UUID,
    payload: ExecutionDecisionIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return automation_service.decide_execution_approval(
        db,
        execution_id,
        approve=payload.approve,
        notes=payload.notes,
        actor_user_id=principal.user.id,
        actor_roles=principal.roles,
    )


# --- Feature 13: Predictive Incident Prevention ---
@router.get("/incident-prevention")
def get_incident_prevention(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, canteen_id) if not principal.has_role(*ADMIN_ROLES) else canteen_id
    return command_center_service.get_predictive_incident_prevention(db, canteen_id=eff_cid)


# --- Feature 14: Intelligent Resource Allocation ---
@router.get("/resource-allocation")
def get_resource_allocation(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, canteen_id) if not principal.has_role(*ADMIN_ROLES) else canteen_id
    return command_center_service.get_intelligent_resource_allocation(db, canteen_id=eff_cid)


# --- Feature 15: Natural Language Administrative Command Center ---
@router.post("/nl-command")
def run_nl_command(
    payload: NlCommandIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*OPS_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, payload.canteen_id) if not principal.has_role(*ADMIN_ROLES) else payload.canteen_id
    return command_center_service.process_nl_admin_command(
        db,
        question=payload.question,
        canteen_id=eff_cid,
        actor_user_id=principal.user.id,
        actor_roles=principal.roles,
    )


# --- Feature 16: Live Digital Cafeteria Map ---
@router.get("/cafeteria-map")
def get_cafeteria_map(
    hours: int = Query(default=24, ge=1, le=168),
    principal: AuthenticatedPrincipal = Depends(require_roles(*OPS_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    return command_center_service.get_live_cafeteria_map(db, hours=hours)


# --- Feature 17: Isolated What-If Simulation Engine ---
@router.post("/simulations/run")
def run_simulation(
    payload: SimulationRunIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, payload.canteen_id) if not principal.has_role(*ADMIN_ROLES) else payload.canteen_id
    return simulation_service.run_what_if_simulation(
        db,
        name=payload.name,
        description=payload.description,
        canteen_id=eff_cid,
        parameters=payload.parameters,
        actor_user_id=principal.user.id,
    )


@router.get("/simulations")
def list_simulations(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return simulation_service.list_simulations(db, limit=limit, offset=offset)


@router.get("/simulations/{scenario_id}/export/csv")
def export_simulation_csv(
    scenario_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    data, fname = simulation_service.export_simulation_csv(db, scenario_id)
    return Response(content=data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/simulations/{scenario_id}/export/pdf")
def export_simulation_pdf(
    scenario_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    data, fname = simulation_service.export_simulation_pdf(db, scenario_id)
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# --- Feature 18: Automated Daily / Weekly / Monthly Operations Reports ---
@router.post("/reports/generate")
def generate_report(
    payload: ReportGenerateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, payload.canteen_id) if not principal.has_role(*ADMIN_ROLES) else payload.canteen_id
    return command_center_service.generate_operational_report(
        db,
        period_type=payload.period_type,
        canteen_id=eff_cid,
        actor_user_id=principal.user.id,
        generation_source="manual",
    )


@router.get("/reports")
def list_reports(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return command_center_service.list_operational_reports(db, limit=limit, offset=offset)


@router.get("/reports/{report_id}/export/csv")
def export_report_csv(
    report_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    data, fname = command_center_service.export_operational_report_csv(db, report_id)
    return Response(content=data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/reports/{report_id}/export/xlsx")
def export_report_xlsx(
    report_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    data, fname = command_center_service.export_operational_report_xlsx(db, report_id)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/reports/{report_id}/export/pdf")
def export_report_pdf(
    report_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    data, fname = command_center_service.export_operational_report_pdf(db, report_id)
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})

