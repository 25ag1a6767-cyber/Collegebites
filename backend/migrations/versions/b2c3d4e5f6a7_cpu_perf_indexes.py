"""Add production CPU performance composite indexes across campus_ops and hot core tables.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-25 18:05:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_SPECS: list[tuple[str, str, list[str]]] = [
    # System A & B (campus_ops) composite & lookup indexes matching SQLAlchemy models
    ("ix_crowd_snap_canteen_captured", "crowd_activity_snapshots", ["canteen_id", "captured_at"]),
    ("ix_tray_verif_canteen_created", "order_tray_verifications", ["canteen_id", "created_at"]),
    ("ix_tray_verif_order", "order_tray_verifications", ["order_id", "created_at"]),
    ("ix_timetable_dow_type", "academic_timetable_slots", ["day_of_week", "slot_type"]),
    ("ix_timetable_canteen_active", "academic_timetable_slots", ["canteen_id", "is_active"]),
    ("ix_menu_avail_canteen_created", "menu_availability_events", ["canteen_id", "created_at"]),
    ("ix_menu_avail_food_created", "menu_availability_events", ["food_item_id", "created_at"]),
    ("ix_seating_zones_canteen_active", "seating_zones", ["canteen_id", "is_active"]),
    ("ix_seating_log_zone_recorded", "seating_occupancy_logs", ["zone_id", "recorded_at"]),
    ("ix_voice_session_created", "voice_assistant_sessions", ["created_at"]),
    ("ix_voice_session_lang_intent", "voice_assistant_sessions", ["language", "detected_intent"]),
    ("ix_ops_inc_status_sev", "operational_incidents", ["status", "severity"]),
    ("ix_ops_inc_canteen_created", "operational_incidents", ["canteen_id", "created_at"]),
    ("ix_rca_canteen_created", "root_cause_investigations", ["canteen_id", "created_at"]),
    ("ix_rca_domain_status", "root_cause_investigations", ["target_domain", "status"]),
    ("ix_auto_wf_trigger_enabled", "automation_workflows", ["trigger_type", "is_enabled"]),
    ("ix_auto_exec_wf_created", "automation_executions", ["workflow_id", "created_at"]),
    ("ix_auto_exec_status_created", "automation_executions", ["status", "created_at"]),
    ("ix_sim_canteen_created", "simulation_scenarios", ["canteen_id", "created_at"]),
    ("ix_ops_rep_period", "operational_reports", ["period_type", "period_start", "period_end"]),
    # Hot transactional & realtime core table composite indexes
    ("ix_orders_canteen_status_created", "orders", ["canteen_id", "status", "created_at"]),
    ("ix_orders_canteen_ready_at", "orders", ["canteen_id", "ready_at"]),
    ("ix_orders_customer_created", "orders", ["customer_id", "created_at"]),
    ("ix_orders_status_completed_at", "orders", ["status", "completed_at"]),
    ("ix_order_items_order_prep", "order_items", ["order_id", "prep_status"]),
    ("ix_order_items_station_prep", "order_items", ["station_id", "prep_status"]),
    ("ix_payments_order_status_created", "payments", ["order_id", "status", "created_at"]),
    ("ix_payments_status_created", "payments", ["status", "created_at"]),
    ("ix_notifications_user_chan_read_created", "notifications", ["user_id", "channel", "is_read", "created_at"]),
    ("ix_notifications_role_chan_canteen_created", "notifications", ["role_target", "channel", "canteen_id", "created_at"]),
    ("ix_announcements_active_canteen_created", "announcements", ["is_active", "canteen_id", "created_at"]),
    ("ix_pickup_tokens_service_date_order", "pickup_tokens", ["service_date", "order_id"]),
    ("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"]),
    ("ix_sessions_expires_at", "sessions", ["expires_at"]),
    ("ix_food_items_canteen_active_avail", "food_items", ["canteen_id", "is_active", "is_available"]),
    ("ix_inventory_items_canteen_arch_qty", "inventory_items", ["canteen_id", "is_archived", "current_quantity"]),
    ("ix_payment_reconciliations_status_created", "payment_reconciliations", ["status", "created_at"]),
    ("ix_receipt_print_jobs_status_created", "receipt_print_jobs", ["status", "created_at"]),
]


def _create_index_if_missing(idx_name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table_name):
        return
    table_cols = {c["name"] for c in insp.get_columns(table_name)}
    if not all(col in table_cols for col in columns):
        return
    existing_names = {idx["name"] for idx in insp.get_indexes(table_name)}
    if idx_name in existing_names:
        return
    op.create_index(idx_name, table_name, columns, unique=False)


def _drop_index_if_present(idx_name: str, table_name: str) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table_name):
        return
    existing_names = {idx["name"] for idx in insp.get_indexes(table_name)}
    if idx_name in existing_names:
        op.drop_index(idx_name, table_name=table_name)


def upgrade() -> None:
    for idx_name, table_name, columns in INDEX_SPECS:
        _create_index_if_missing(idx_name, table_name, columns)


def downgrade() -> None:
    for idx_name, table_name, _columns in reversed(INDEX_SPECS):
        _drop_index_if_present(idx_name, table_name)
