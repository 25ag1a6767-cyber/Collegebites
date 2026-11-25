"""Smart Campus Intelligence, Autonomous Operations Command Center, and OTP Removal.

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-11-25 16:15:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table_name: str, column_name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table_name):
        return False
    return any(col["name"] == column_name for col in insp.get_columns(table_name))


def upgrade() -> None:
    # 1. Safely remove ephemeral OTP table and legacy guest_otp_required config column.
    #    User accounts, password hashes, sessions, orders, and payment history are 100% preserved.
    if _has_table("otp_verifications"):
        op.drop_table("otp_verifications")

    if _has_column("college_settings", "guest_otp_required"):
        with op.batch_alter_table("college_settings") as batch_op:
            batch_op.drop_column("guest_otp_required")

    # 2. Create non-OTP cryptographic password reset token table
    if not _has_table("password_reset_tokens"):
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False, unique=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_pwd_reset_user_created", "password_reset_tokens", ["user_id", "created_at"])
        op.create_index("ix_pwd_reset_expires", "password_reset_tokens", ["expires_at"])
        op.create_index("ix_password_reset_tokens_token_hash", "password_reset_tokens", ["token_hash"], unique=True)

    # 3. System A: Smart Campus Intelligence tables
    if not _has_table("crowd_activity_snapshots"):
        op.create_table(
            "crowd_activity_snapshots",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("active_orders", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("waiting_orders", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("preparing_orders", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ready_orders", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("workload_percent", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("activity_level", sa.String(length=24), nullable=False, server_default="low"),
            sa.Column("source_type", sa.String(length=32), nullable=False, server_default="order_based_estimate"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_crowd_snap_canteen_captured", "crowd_activity_snapshots", ["canteen_id", "captured_at"])

    if not _has_table("order_tray_verifications"):
        op.create_table(
            "order_tray_verifications",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("verified_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("verification_mode", sa.String(length=32), nullable=False, server_default="manual_checklist"),
            sa.Column("expected_items_json", sa.JSON(), nullable=False),
            sa.Column("verified_items_json", sa.JSON(), nullable=False),
            sa.Column("missing_items_json", sa.JSON(), nullable=False),
            sa.Column("mismatched_items_json", sa.JSON(), nullable=False),
            sa.Column("cv_available", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("cv_confidence", sa.Numeric(5, 4), nullable=True),
            sa.Column("requires_human_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_review"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_tray_verif_canteen_created", "order_tray_verifications", ["canteen_id", "created_at"])
        op.create_index("ix_tray_verif_order", "order_tray_verifications", ["order_id", "created_at"])

    if not _has_table("academic_timetable_slots"):
        op.create_table(
            "academic_timetable_slots",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("department", sa.String(length=120), nullable=False),
            sa.Column("academic_term", sa.String(length=64), nullable=True),
            sa.Column("day_of_week", sa.Integer(), nullable=False),
            sa.Column("slot_type", sa.String(length=32), nullable=False, server_default="class"),
            sa.Column("start_time", sa.Time(), nullable=False),
            sa.Column("end_time", sa.Time(), nullable=False),
            sa.Column("estimated_cohort_size", sa.Integer(), nullable=True),
            sa.Column("label", sa.String(length=160), nullable=True),
            sa.Column("import_batch_id", sa.String(length=64), nullable=True),
            sa.Column("uploaded_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_timetable_dow_type", "academic_timetable_slots", ["day_of_week", "slot_type"])
        op.create_index("ix_timetable_canteen_active", "academic_timetable_slots", ["canteen_id", "is_active"])

    if not _has_table("menu_availability_events"):
        op.create_table(
            "menu_availability_events",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("food_item_id", sa.Uuid(), sa.ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("previous_available", sa.Boolean(), nullable=False),
            sa.Column("new_available", sa.Boolean(), nullable=False),
            sa.Column("reason_type", sa.String(length=32), nullable=False),
            sa.Column("reason_detail", sa.String(length=300), nullable=True),
            sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_menu_avail_canteen_created", "menu_availability_events", ["canteen_id", "created_at"])
        op.create_index("ix_menu_avail_food_created", "menu_availability_events", ["food_item_id", "created_at"])

    if not _has_table("seating_zones"):
        op.create_table(
            "seating_zones",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("zone_code", sa.String(length=32), nullable=False, unique=True),
            sa.Column("zone_name", sa.String(length=120), nullable=False),
            sa.Column("total_seats", sa.Integer(), nullable=False),
            sa.Column("occupied_seats", sa.Integer(), nullable=True),
            sa.Column("data_source", sa.String(length=32), nullable=False, server_default="unconfigured"),
            sa.Column("sensor_status", sa.String(length=24), nullable=False, server_default="unavailable"),
            sa.Column("layout_x", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("layout_y", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("layout_w", sa.Integer(), nullable=False, server_default="200"),
            sa.Column("layout_h", sa.Integer(), nullable=False, server_default="120"),
            sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("last_measured_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if not _has_table("seating_occupancy_logs"):
        op.create_table(
            "seating_occupancy_logs",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("zone_id", sa.Uuid(), sa.ForeignKey("seating_zones.id", ondelete="CASCADE"), nullable=False),
            sa.Column("total_seats", sa.Integer(), nullable=False),
            sa.Column("occupied_seats", sa.Integer(), nullable=False),
            sa.Column("available_seats", sa.Integer(), nullable=False),
            sa.Column("occupancy_percent", sa.Numeric(5, 2), nullable=False),
            sa.Column("data_source", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("recorded_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("notes", sa.String(length=300), nullable=True),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_seating_log_zone_recorded", "seating_occupancy_logs", ["zone_id", "recorded_at"])

    if not _has_table("voice_assistant_sessions"):
        op.create_table(
            "voice_assistant_sessions",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("guest_session_id", sa.String(length=120), nullable=True),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("language", sa.String(length=12), nullable=False, server_default="en"),
            sa.Column("transcript_text", sa.Text(), nullable=False),
            sa.Column("detected_intent", sa.String(length=64), nullable=False),
            sa.Column("response_text", sa.Text(), nullable=False),
            sa.Column("response_language", sa.String(length=12), nullable=False, server_default="en"),
            sa.Column("draft_order_json", sa.JSON(), nullable=True),
            sa.Column("confidence_score", sa.Numeric(4, 3), nullable=False, server_default="0.000"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="answered"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_voice_session_created", "voice_assistant_sessions", ["created_at"])
        op.create_index("ix_voice_session_lang_intent", "voice_assistant_sessions", ["language", "detected_intent"])

    # 4. System B: Autonomous Cafeteria Operations Command Center tables
    if not _has_table("operational_incidents"):
        op.create_table(
            "operational_incidents",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("incident_code", sa.String(length=48), nullable=False, unique=True),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("category", sa.String(length=48), nullable=False),
            sa.Column("severity", sa.String(length=24), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("evidence_json", sa.JSON(), nullable=False),
            sa.Column("related_entity_type", sa.String(length=64), nullable=True),
            sa.Column("related_entity_id", sa.String(length=120), nullable=True),
            sa.Column("reported_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("assigned_to_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolution_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_ops_inc_status_sev", "operational_incidents", ["status", "severity"])
        op.create_index("ix_ops_inc_canteen_created", "operational_incidents", ["canteen_id", "created_at"])

    if not _has_table("root_cause_investigations"):
        op.create_table(
            "root_cause_investigations",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("operational_incidents.id", ondelete="SET NULL"), nullable=True),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("target_domain", sa.String(length=48), nullable=False),
            sa.Column("query_summary", sa.String(length=300), nullable=False),
            sa.Column("confirmed_facts_json", sa.JSON(), nullable=False),
            sa.Column("ai_hypotheses_json", sa.JSON(), nullable=False),
            sa.Column("recommended_actions_json", sa.JSON(), nullable=False),
            sa.Column("linked_incident_ids_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
            sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reviewed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_rca_canteen_created", "root_cause_investigations", ["canteen_id", "created_at"])
        op.create_index("ix_rca_domain_status", "root_cause_investigations", ["target_domain", "status"])

    if not _has_table("automation_workflows"):
        op.create_table(
            "automation_workflows",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("workflow_key", sa.String(length=80), nullable=False, unique=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("trigger_type", sa.String(length=48), nullable=False),
            sa.Column("action_type", sa.String(length=48), nullable=False),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("trigger_config_json", sa.JSON(), nullable=False),
            sa.Column("action_config_json", sa.JSON(), nullable=False),
            sa.Column("responsible_role", sa.String(length=48), nullable=False, server_default="canteen_manager"),
            sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="15"),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_auto_wf_trigger_enabled", "automation_workflows", ["trigger_type", "is_enabled"])

    if not _has_table("automation_executions"):
        op.create_table(
            "automation_executions",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("workflow_id", sa.Uuid(), sa.ForeignKey("automation_workflows.id", ondelete="CASCADE"), nullable=False),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("dedup_key", sa.String(length=160), nullable=True, unique=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
            sa.Column("trigger_evidence_json", sa.JSON(), nullable=False),
            sa.Column("proposed_action_json", sa.JSON(), nullable=False),
            sa.Column("execution_result_json", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requested_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approval_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_auto_exec_wf_created", "automation_executions", ["workflow_id", "created_at"])
        op.create_index("ix_auto_exec_status_created", "automation_executions", ["status", "created_at"])

    if not _has_table("automation_governance_state"):
        op.create_table(
            "automation_governance_state",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("global_automation_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("emergency_disabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("emergency_disabled_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("emergency_reason", sa.String(length=300), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if not _has_table("simulation_scenarios"):
        op.create_table(
            "simulation_scenarios",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("parameters_json", sa.JSON(), nullable=False),
            sa.Column("baseline_snapshot_json", sa.JSON(), nullable=False),
            sa.Column("simulated_outcomes_json", sa.JSON(), nullable=False),
            sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_sim_canteen_created", "simulation_scenarios", ["canteen_id", "created_at"])

    if not _has_table("operational_reports"):
        op.create_table(
            "operational_reports",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("period_type", sa.String(length=24), nullable=False, server_default="daily"),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("report_payload_json", sa.JSON(), nullable=False),
            sa.Column("generated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("generation_source", sa.String(length=24), nullable=False, server_default="manual"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_ops_rep_period", "operational_reports", ["period_type", "period_start", "period_end"])


def downgrade() -> None:
    for tbl in (
        "operational_reports",
        "simulation_scenarios",
        "automation_governance_state",
        "automation_executions",
        "automation_workflows",
        "root_cause_investigations",
        "operational_incidents",
        "voice_assistant_sessions",
        "seating_occupancy_logs",
        "seating_zones",
        "menu_availability_events",
        "academic_timetable_slots",
        "order_tray_verifications",
        "crowd_activity_snapshots",
        "password_reset_tokens",
    ):
        if _has_table(tbl):
            op.drop_table(tbl)

    if not _has_column("college_settings", "guest_otp_required"):
        with op.batch_alter_table("college_settings") as batch_op:
            batch_op.add_column(sa.Column("guest_otp_required", sa.Boolean(), nullable=False, server_default=sa.text("false")))

