"""Remove Stripe config column, add print job type, and add live OTP security columns

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-24 15:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, column: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _has_index(insp, table: str, index_name: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(ix["name"] == index_name for ix in insp.get_indexes(table))


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # 1. Remove deprecated singleton configuration flag `college_settings.stripe_enabled`.
    # Historical payment, transaction, webhook, reconciliation, and order tables are untouched.
    if _has_column(insp, "college_settings", "stripe_enabled"):
        with op.batch_alter_table("college_settings") as batch_op:
            batch_op.drop_column("stripe_enabled")

    # 2. Distinguish customer receipt print jobs vs after-acceptance KOT print jobs.
    if insp.has_table("receipt_print_jobs") and not _has_column(insp, "receipt_print_jobs", "job_type"):
        op.add_column(
            "receipt_print_jobs",
            sa.Column("job_type", sa.String(length=32), nullable=False, server_default="customer_receipt"),
        )

    # 3. Live OTP security, delivery metadata, cooldown, replay & rate-limit tracking columns.
    if insp.has_table("otp_verifications"):
        otp_cols = [
            sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
            sa.Column("channel", sa.String(length=24), nullable=True),
            sa.Column("provider", sa.String(length=48), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("resend_available_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        ]
        for col in otp_cols:
            if not _has_column(insp, "otp_verifications", col.name):
                op.add_column("otp_verifications", col)

        insp = sa.inspect(conn)
        if not _has_index(insp, "otp_verifications", "ix_otp_ip_created"):
            op.create_index("ix_otp_ip_created", "otp_verifications", ["ip_address", "created_at"], unique=False)
        if not _has_index(insp, "otp_verifications", "ix_otp_user_created"):
            op.create_index("ix_otp_user_created", "otp_verifications", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if insp.has_table("otp_verifications"):
        if _has_index(insp, "otp_verifications", "ix_otp_user_created"):
            op.drop_index("ix_otp_user_created", table_name="otp_verifications")
        if _has_index(insp, "otp_verifications", "ix_otp_ip_created"):
            op.drop_index("ix_otp_ip_created", table_name="otp_verifications")
        with op.batch_alter_table("otp_verifications") as batch_op:
            for cname in (
                "invalidated_at",
                "consumed_at",
                "resend_available_at",
                "ip_address",
                "provider",
                "channel",
                "user_id",
            ):
                if _has_column(insp, "otp_verifications", cname):
                    batch_op.drop_column(cname)

    if _has_column(insp, "receipt_print_jobs", "job_type"):
        with op.batch_alter_table("receipt_print_jobs") as batch_op:
            batch_op.drop_column("job_type")

    if insp.has_table("college_settings") and not _has_column(insp, "college_settings", "stripe_enabled"):
        op.add_column(
            "college_settings",
            sa.Column("stripe_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
