"""Security & fraud detection: login tracking, brute-force lockout, and security alerts

Revision ID: 8b7c9d0e1f2a
Revises: 7f6a8b9c0d1e
Create Date: 2026-11-23 12:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "8b7c9d0e1f2a"
down_revision = "7f6a8b9c0d1e"
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
    _add_column_if_missing(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("users", sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True))

    if not _table_exists("login_attempts"):
        op.create_table(
            "login_attempts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("identifier", sa.String(length=160), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=255), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("failure_reason", sa.String(length=255), nullable=True),
        )
        op.create_index("ix_login_attempts_identifier", "login_attempts", ["identifier"])
        op.create_index("ix_login_attempts_user_id", "login_attempts", ["user_id"])
        op.create_index("ix_login_attempts_ip_address", "login_attempts", ["ip_address"])
        op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])

    if not _table_exists("security_alerts"):
        op.create_table(
            "security_alerts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("alert_type", sa.String(length=64), nullable=False),
            sa.Column("severity", sa.String(length=24), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
            sa.Column("canteen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column(
                "resolved_by_user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolution_notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_security_alerts_type_status", "security_alerts", ["alert_type", "status"])
        op.create_index("ix_security_alerts_canteen_id", "security_alerts", ["canteen_id"])
        op.create_index("ix_security_alerts_created_at", "security_alerts", ["created_at"])


def downgrade() -> None:
    if _table_exists("security_alerts"):
        op.drop_table("security_alerts")
    if _table_exists("login_attempts"):
        op.drop_table("login_attempts")
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    for col_name in ("last_failed_login_at", "locked_until", "failed_login_attempts"):
        if col_name in cols:
            op.drop_column("users", col_name)
