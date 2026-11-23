"""Financial reconciliation system: gateway cross-checking, batches, and discrepancy tracking

Revision ID: 9c8d0e1f2a3b
Revises: 8b7c9d0e1f2a
Create Date: 2026-11-23 12:20:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "9c8d0e1f2a3b"
down_revision = "8b7c9d0e1f2a"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(table_name)}
    if column.name not in cols:
        op.add_column(table_name, column)


def upgrade() -> None:
    if not _table_exists("reconciliation_runs"):
        op.create_table(
            "reconciliation_runs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("trigger", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("canteen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("total_checked", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("discrepancy_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_verified_amount", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
            sa.Column("run_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("summary_json", sa.JSON(), nullable=True),
        )
        op.create_index("ix_reconciliation_runs_canteen", "reconciliation_runs", ["canteen_id"])
        op.create_index("ix_reconciliation_runs_created", "reconciliation_runs", ["created_at"])

    _add_column_if_missing(
        "payment_reconciliation",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reconciliation_runs.id", ondelete="SET NULL"), nullable=True),
    )
    _add_column_if_missing(
        "payment_reconciliation",
        sa.Column("gateway_provider", sa.String(length=48), nullable=False, server_default="razorpay"),
    )
    _add_column_if_missing(
        "payment_reconciliation",
        sa.Column("gateway_settlement_id", sa.String(length=120), nullable=True),
    )
    _add_column_if_missing(
        "payment_reconciliation",
        sa.Column("gateway_reference", sa.String(length=120), nullable=True),
    )
    _add_column_if_missing(
        "payment_reconciliation",
        sa.Column("gateway_fee", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
    )
    _add_column_if_missing(
        "payment_reconciliation",
        sa.Column("tax_on_fee", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
    )
    _add_column_if_missing(
        "payment_reconciliation",
        sa.Column("reconciliation_source", sa.String(length=32), nullable=False, server_default="manual"),
    )
    _add_column_if_missing(
        "payment_reconciliation",
        sa.Column("discrepancy_type", sa.String(length=48), nullable=False, server_default="none"),
    )

    # Deduplicate pre-existing payment_id entries before enforcing unique index
    op.execute(
        """
        DELETE FROM payment_reconciliation a
        USING payment_reconciliation b
        WHERE a.payment_id = b.payment_id AND a.ctid < b.ctid;
        """
    )
    uqs = {u["name"] for u in sa.inspect(op.get_bind()).get_unique_constraints("payment_reconciliation")}
    if "uq_reconcil_payment_id" not in uqs:
        op.create_unique_constraint("uq_reconcil_payment_id", "payment_reconciliation", ["payment_id"])


def downgrade() -> None:
    bind = op.get_bind()
    uqs = {u["name"] for u in sa.inspect(bind).get_unique_constraints("payment_reconciliation")}
    if "uq_reconcil_payment_id" in uqs:
        op.drop_constraint("uq_reconcil_payment_id", "payment_reconciliation", type_="unique")
    cols = {c["name"] for c in sa.inspect(bind).get_columns("payment_reconciliation")}
    for col_name in (
        "discrepancy_type",
        "reconciliation_source",
        "tax_on_fee",
        "gateway_fee",
        "gateway_reference",
        "gateway_settlement_id",
        "gateway_provider",
        "batch_id",
    ):
        if col_name in cols:
            op.drop_column("payment_reconciliation", col_name)
    if _table_exists("reconciliation_runs"):
        op.drop_table("reconciliation_runs")
