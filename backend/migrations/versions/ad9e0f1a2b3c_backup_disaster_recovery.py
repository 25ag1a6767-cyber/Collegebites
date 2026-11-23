"""Automated backup and disaster recovery tracking

Revision ID: ad9e0f1a2b3c
Revises: 9c8d0e1f2a3b
Create Date: 2026-11-23 12:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ad9e0f1a2b3c"
down_revision = "9c8d0e1f2a3b"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if not _table_exists("backup_records"):
        op.create_table(
            "backup_records",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("backup_code", sa.String(length=64), nullable=False, unique=True),
            sa.Column("trigger_type", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("storage_backend", sa.String(length=32), nullable=False, server_default="database_encrypted"),
            sa.Column("file_path", sa.String(length=255), nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("checksum_sha256", sa.String(length=128), nullable=False),
            sa.Column("encryption_algo", sa.String(length=64), nullable=False, server_default="fernet-aes128-hmac-sha256"),
            sa.Column("is_encrypted", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
            sa.Column("integrity_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("row_counts_json", sa.JSON(), nullable=True),
            sa.Column("payload_encrypted", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_backup_records_status", "backup_records", ["status"])
        op.create_index("ix_backup_records_created_at", "backup_records", ["created_at"])

    if not _table_exists("backup_settings"):
        op.create_table(
            "backup_settings",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("singleton_key", sa.String(length=32), nullable=False, unique=True, server_default="default"),
            sa.Column("auto_backup_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("frequency_hours", sa.Integer(), nullable=False, server_default="24"),
            sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("max_backups", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("storage_backend", sa.String(length=32), nullable=False, server_default="database_encrypted"),
            sa.Column("last_backup_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_scheduled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )

    if not _table_exists("recovery_logs"):
        op.create_table(
            "recovery_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("backup_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backup_records.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_env", sa.String(length=64), nullable=False, server_default="dry_run_sandbox"),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
            sa.Column("restored_tables_json", sa.JSON(), nullable=True),
            sa.Column("verification_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("authorized_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_recovery_logs_backup", "recovery_logs", ["backup_id"])


def downgrade() -> None:
    for tbl in ("recovery_logs", "backup_settings", "backup_records"):
        if _table_exists(tbl):
            op.drop_table(tbl)
