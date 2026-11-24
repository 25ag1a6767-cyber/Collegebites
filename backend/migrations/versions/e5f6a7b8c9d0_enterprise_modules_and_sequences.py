"""Enterprise modules (Notifications, Food Safety, Traceability, Production, Reordering, Queue History, ML Forecasting, AI Assistant) and lock-free sequences

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-24 13:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, column: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _add_col_if_missing(insp, table: str, column: sa.Column) -> None:
    if insp.has_table(table) and not _has_column(insp, table, column.name):
        op.add_column(table, column)


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # 1. Lock-free PostgreSQL sequences for order & invoice numbering (Section 17)
    if conn.dialect.name == "postgresql":
        conn.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS order_number_seq START WITH 1 INCREMENT BY 1"))
        conn.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS invoice_number_seq START WITH 1 INCREMENT BY 1"))

    # 2. Extend existing notifications table
    _add_col_if_missing(insp, "notifications", sa.Column("event_id", sa.String(160), nullable=True))
    _add_col_if_missing(insp, "notifications", sa.Column("category", sa.String(40), nullable=False, server_default="order"))
    _add_col_if_missing(insp, "notifications", sa.Column("priority", sa.String(24), nullable=False, server_default="normal"))
    _add_col_if_missing(insp, "notifications", sa.Column("last_error", sa.Text(), nullable=True))
    _add_col_if_missing(insp, "notifications", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))

    # 3. Extend existing suppliers, stock_batches, and recipes tables
    _add_col_if_missing(insp, "suppliers", sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default="2"))

    _add_col_if_missing(insp, "stock_batches", sa.Column("purchase_order_id", sa.Uuid(), nullable=True))
    _add_col_if_missing(insp, "stock_batches", sa.Column("goods_receipt_id", sa.Uuid(), nullable=True))
    _add_col_if_missing(insp, "stock_batches", sa.Column("allocated_quantity", sa.Numeric(14, 3), nullable=False, server_default="0.000"))
    _add_col_if_missing(insp, "stock_batches", sa.Column("consumed_quantity", sa.Numeric(14, 3), nullable=False, server_default="0.000"))
    _add_col_if_missing(insp, "stock_batches", sa.Column("rejected_quantity", sa.Numeric(14, 3), nullable=False, server_default="0.000"))
    _add_col_if_missing(insp, "stock_batches", sa.Column("wasted_quantity", sa.Numeric(14, 3), nullable=False, server_default="0.000"))
    _add_col_if_missing(insp, "stock_batches", sa.Column("manufacturing_date", sa.Date(), nullable=True))
    _add_col_if_missing(insp, "stock_batches", sa.Column("storage_location", sa.String(120), nullable=True))
    _add_col_if_missing(insp, "stock_batches", sa.Column("quality_status", sa.String(32), nullable=False, server_default="approved"))
    _add_col_if_missing(insp, "stock_batches", sa.Column("block_reason", sa.String(255), nullable=True))
    _add_col_if_missing(insp, "stock_batches", sa.Column("supporting_documents", sa.JSON(), nullable=True))

    _add_col_if_missing(insp, "recipes", sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_col_if_missing(insp, "recipes", sa.Column("verified_by_user_id", sa.Uuid(), nullable=True))
    _add_col_if_missing(insp, "recipes", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))

    # 4. Create all new enterprise tables via SQLAlchemy metadata (checkfirst=True for idempotency)
    from app.models.base import Base
    import app.models  # noqa: F401

    new_tables = [
        "notification_deliveries",
        "food_safety_checklist_templates",
        "food_safety_inspections",
        "food_safety_inspection_items",
        "equipment_temperature_configs",
        "equipment_temperature_logs",
        "cleaning_schedules",
        "cleaning_task_logs",
        "food_safety_incidents",
        "production_plans",
        "production_batches",
        "production_batch_ingredients",
        "production_quality_checks",
        "traceability_records",
        "recall_incidents",
        "reorder_rules",
        "reorder_recommendations",
        "queue_estimate_history",
        "forecast_models",
        "demand_forecasts",
        "forecast_evaluations",
        "ai_assistant_conversations",
        "ai_assistant_messages",
        "ai_assistant_audit_logs",
    ]
    tables_to_create = [Base.metadata.tables[t] for t in new_tables if t in Base.metadata.tables]
    Base.metadata.create_all(bind=conn, tables=tables_to_create, checkfirst=True)


def downgrade() -> None:
    # Non-destructive downgrade to protect historical compliance, traceability, and audit records.
    pass
