"""add_stripe_tz_addon_and_print_host

Revision ID: 2a1b3c4d5e6f
Revises: 9cfdc6326304
Create Date: 2026-11-21 14:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2a1b3c4d5e6f"
down_revision: Union[str, None] = "9cfdc6326304"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "college_settings",
        sa.Column("stripe_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "college_settings",
        sa.Column("college_timezone", sa.String(length=64), nullable=False, server_default="Asia/Kolkata"),
    )
    op.add_column(
        "order_item_customizations",
        sa.Column("addon_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_order_item_customizations_addon_id",
        "order_item_customizations",
        "food_addons",
        ["addon_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("receipt_print_jobs", sa.Column("network_host", sa.String(length=120), nullable=True))
    op.add_column("receipt_print_jobs", sa.Column("network_port", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("receipt_print_jobs", "network_port")
    op.drop_column("receipt_print_jobs", "network_host")
    op.drop_constraint("fk_order_item_customizations_addon_id", "order_item_customizations", type_="foreignkey")
    op.drop_column("order_item_customizations", "addon_id")
    op.drop_column("college_settings", "college_timezone")
    op.drop_column("college_settings", "stripe_enabled")
