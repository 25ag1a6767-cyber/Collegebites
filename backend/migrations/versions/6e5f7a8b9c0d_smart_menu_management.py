"""Smart menu management: date/time windows, special events, and restock restore approvals

Revision ID: 6e5f7a8b9c0d
Revises: 5d4e6f7a8b9c
Create Date: 2026-11-23 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "6e5f7a8b9c0d"
down_revision = "5d4e6f7a8b9c"
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
        "food_items",
        sa.Column("pending_restore_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing("food_items", sa.Column("available_from_time", sa.Time(), nullable=True))
    _add_column_if_missing("food_items", sa.Column("available_until_time", sa.Time(), nullable=True))
    _add_column_if_missing("food_items", sa.Column("valid_from", sa.Date(), nullable=True))
    _add_column_if_missing("food_items", sa.Column("valid_until", sa.Date(), nullable=True))

    _add_column_if_missing("menu_schedules", sa.Column("valid_from", sa.Date(), nullable=True))
    _add_column_if_missing("menu_schedules", sa.Column("valid_until", sa.Date(), nullable=True))
    _add_column_if_missing(
        "menu_schedules",
        sa.Column("special_dates", sa.JSON(), nullable=False, server_default="[]"),
    )
    _add_column_if_missing(
        "menu_schedules",
        sa.Column("is_special_event", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing("menu_schedules", sa.Column("event_name", sa.String(length=160), nullable=True))

    if not _table_exists("menu_restore_approvals"):
        op.create_table(
            "menu_restore_approvals",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("canteen_id", sa.UUID(), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("food_item_id", sa.UUID(), sa.ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
            sa.Column("reason", sa.String(length=255), nullable=True),
            sa.Column("reviewed_by_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_notes", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id", name="pk_menu_restore_approvals"),
        )
        op.create_index("ix_menu_restore_approvals_canteen_id", "menu_restore_approvals", ["canteen_id"], if_not_exists=True)
        op.create_index("ix_menu_restore_approvals_food_item_id", "menu_restore_approvals", ["food_item_id"], if_not_exists=True)
        op.create_index("ix_menu_restore_approvals_status", "menu_restore_approvals", ["status"], if_not_exists=True)


def downgrade() -> None:
    if _table_exists("menu_restore_approvals"):
        op.drop_index("ix_menu_restore_approvals_status", table_name="menu_restore_approvals", if_exists=True)
        op.drop_index("ix_menu_restore_approvals_food_item_id", table_name="menu_restore_approvals", if_exists=True)
        op.drop_index("ix_menu_restore_approvals_canteen_id", table_name="menu_restore_approvals", if_exists=True)
        op.drop_table("menu_restore_approvals")

    op.drop_column("menu_schedules", "event_name")
    op.drop_column("menu_schedules", "is_special_event")
    op.drop_column("menu_schedules", "special_dates")
    op.drop_column("menu_schedules", "valid_until")
    op.drop_column("menu_schedules", "valid_from")

    op.drop_column("food_items", "valid_until")
    op.drop_column("food_items", "valid_from")
    op.drop_column("food_items", "available_until_time")
    op.drop_column("food_items", "available_from_time")
    op.drop_column("food_items", "pending_restore_approval")
