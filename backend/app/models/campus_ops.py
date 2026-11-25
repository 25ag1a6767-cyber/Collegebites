import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# =============================================================================
# SYSTEM A: SMART CAMPUS INTELLIGENCE MODELS
# =============================================================================


class CrowdActivitySnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "crowd_activity_snapshots"
    __table_args__ = (
        Index("ix_crowd_snap_canteen_captured", "canteen_id", "captured_at"),
    )

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    waiting_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    preparing_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ready_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workload_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activity_level: Mapped[str] = mapped_column(String(24), nullable=False, default="low")  # low | moderate | busy
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="order_based_estimate")


class OrderTrayVerification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "order_tray_verifications"
    __table_args__ = (
        Index("ix_tray_verif_canteen_created", "canteen_id", "created_at"),
        Index("ix_tray_verif_order", "order_id", "created_at"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    verified_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    verification_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="manual_checklist")  # manual_checklist | camera_assisted
    expected_items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    verified_items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    missing_items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    mismatched_items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    cv_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cv_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review")  # pending_review | verified | mismatch_flagged | overridden
    notes: Mapped[Optional[str]] = mapped_column(Text)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AcademicTimetableSlot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "academic_timetable_slots"
    __table_args__ = (
        Index("ix_timetable_dow_type", "day_of_week", "slot_type"),
        Index("ix_timetable_canteen_active", "canteen_id", "is_active"),
    )

    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True, index=True)
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    academic_term: Mapped[Optional[str]] = mapped_column(String(64))
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon .. 6=Sun
    slot_type: Mapped[str] = mapped_column(String(32), nullable=False, default="class")  # class | short_break | lunch_break | exam
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    estimated_cohort_size: Mapped[Optional[int]] = mapped_column(Integer)
    label: Mapped[Optional[str]] = mapped_column(String(160))
    import_batch_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    uploaded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MenuAvailabilityEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "menu_availability_events"
    __table_args__ = (
        Index("ix_menu_avail_canteen_created", "canteen_id", "created_at"),
        Index("ix_menu_avail_food_created", "food_item_id", "created_at"),
    )

    food_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    new_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_type: Mapped[str] = mapped_column(String(32), nullable=False)  # stock_auto | manual_override | schedule | restore_approved
    reason_detail: Mapped[Optional[str]] = mapped_column(String(300))
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class SeatingZone(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "seating_zones"
    __table_args__ = (
        UniqueConstraint("zone_code", name="uq_seating_zone_code"),
    )

    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True, index=True)
    zone_code: Mapped[str] = mapped_column(String(32), nullable=False)
    zone_name: Mapped[str] = mapped_column(String(120), nullable=False)
    total_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    occupied_seats: Mapped[Optional[int]] = mapped_column(Integer)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="unconfigured")  # manual | sensor | estimated | unconfigured
    sensor_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unavailable")  # unavailable | online | offline
    layout_x: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    layout_y: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    layout_w: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    layout_h: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_measured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SeatingOccupancyLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "seating_occupancy_logs"
    __table_args__ = (
        Index("ix_seating_log_zone_recorded", "zone_id", "recorded_at"),
    )

    zone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seating_zones.id", ondelete="CASCADE"), nullable=False, index=True)
    total_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    occupied_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    available_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    occupancy_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(300))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VoiceAssistantSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "voice_assistant_sessions"
    __table_args__ = (
        Index("ix_voice_session_created", "created_at"),
        Index("ix_voice_session_lang_intent", "language", "detected_intent"),
    )

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    guest_session_id: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True, index=True)
    language: Mapped[str] = mapped_column(String(12), nullable=False, default="en")  # en | te
    transcript_text: Mapped[str] = mapped_column(Text, nullable=False)
    detected_intent: Mapped[str] = mapped_column(String(64), nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_language: Mapped[str] = mapped_column(String(12), nullable=False, default="en")
    draft_order_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=Decimal("0.000"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="answered")  # answered | clarification_needed | draft_order_ready | blocked


# =============================================================================
# SYSTEM B: AUTONOMOUS CAFETERIA OPERATIONS COMMAND CENTER MODELS
# =============================================================================


class OperationalIncident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "operational_incidents"
    __table_args__ = (
        Index("ix_ops_inc_status_sev", "status", "severity"),
        Index("ix_ops_inc_canteen_created", "canteen_id", "created_at"),
    )

    incident_code: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="medium")  # low | medium | high | critical
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")  # open | investigating | mitigated | resolved | closed
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    related_entity_type: Mapped[Optional[str]] = mapped_column(String(64))
    related_entity_id: Mapped[Optional[str]] = mapped_column(String(120))
    reported_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_to_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)


class RootCauseInvestigation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "root_cause_investigations"
    __table_args__ = (
        Index("ix_rca_canteen_created", "canteen_id", "created_at"),
        Index("ix_rca_domain_status", "target_domain", "status"),
    )

    incident_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("operational_incidents.id", ondelete="SET NULL"), nullable=True, index=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True, index=True)
    target_domain: Mapped[str] = mapped_column(String(48), nullable=False)
    query_summary: Mapped[str] = mapped_column(String(300), nullable=False)
    confirmed_facts_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    ai_hypotheses_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    recommended_actions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    linked_incident_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")  # open | reviewed | closed
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AutomationWorkflow(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "automation_workflows"
    __table_args__ = (
        Index("ix_auto_wf_trigger_enabled", "trigger_type", "is_enabled"),
    )

    workflow_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(48), nullable=False)
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True, index=True)
    trigger_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    action_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    responsible_role: Mapped[str] = mapped_column(String(48), nullable=False, default="canteen_manager")
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AutomationExecution(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "automation_executions"
    __table_args__ = (
        Index("ix_auto_exec_wf_created", "workflow_id", "created_at"),
        Index("ix_auto_exec_status_created", "status", "created_at"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("automation_workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True, index=True)
    dedup_key: Mapped[Optional[str]] = mapped_column(String(160), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_approval")
    trigger_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    proposed_action_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    execution_result_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approval_notes: Mapped[Optional[str]] = mapped_column(Text)


class AutomationGovernanceState(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "automation_governance_state"

    global_automation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    emergency_disabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    emergency_disabled_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    emergency_reason: Mapped[Optional[str]] = mapped_column(String(300))


class SimulationScenario(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "simulation_scenarios"
    __table_args__ = (
        Index("ix_sim_canteen_created", "canteen_id", "created_at"),
    )

    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    baseline_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    simulated_outcomes_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class OperationalReportRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "operational_reports"
    __table_args__ = (
        Index("ix_ops_rep_period", "period_type", "period_start", "period_end"),
    )

    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True, index=True)
    period_type: Mapped[str] = mapped_column(String(24), nullable=False, default="daily")  # daily | weekly | monthly
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    report_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    generated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    generation_source: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")  # manual | scheduled

