"""Food waste management: daily prepared vs sold logs and enriched wastage tracking

Revision ID: 5d4e6f7a8b9c
Revises: 4c3d5e6f7a9b
Create Date: 2026-11-23 10:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "5d4e6f7a8b9c"
down_revision = "4c3d5e6f7a9b"
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
    op.alter_column("wastage_records", "inventory_item_id", existing_type=sa.UUID(), nullable=True)

    _add_column_if_missing(
        "wastage_records",
        sa.Column("canteen_id", sa.UUID(), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=True),
    )
    _add_column_if_missing(
        "wastage_records",
        sa.Column("food_item_id", sa.UUID(), sa.ForeignKey("food_items.id", ondelete="SET NULL"), nullable=True),
    )
    _add_column_if_missing(
        "wastage_records",
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="ingredient"),
    )
    _add_column_if_missing(
        "wastage_records",
        sa.Column("waste_date", sa.Date(), nullable=True),
    )
    _add_column_if_missing(
        "wastage_records",
        sa.Column("responsible_staff_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )

    op.execute(
        """
        UPDATE wastage_records wr
        SET canteen_id = inv.canteen_id
        FROM inventory_items inv
        WHERE wr.inventory_item_id = inv.id AND wr.canteen_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE wastage_records
        SET waste_date = DATE(created_at)
        WHERE waste_date IS NULL
        """
    )

    op.create_index("ix_wastage_records_canteen_id", "wastage_records", ["canteen_id"], if_not_exists=True)
    op.create_index("ix_wastage_records_food_item_id", "wastage_records", ["food_item_id"], if_not_exists=True)
    op.create_index("ix_wastage_records_waste_date", "wastage_records", ["waste_date"], if_not_exists=True)
    op.create_index(
        "ix_wastage_records_responsible_staff_id",
        "wastage_records",
        ["responsible_staff_id"],
        if_not_exists=True,
    )

    if not _table_exists("daily_food_prep_logs"):
        op.create_table(
            "daily_food_prep_logs",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("canteen_id", sa.UUID(), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("food_item_id", sa.UUID(), sa.ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False),
            sa.Column("prep_date", sa.Date(), nullable=False),
            sa.Column("meal_session", sa.String(length=32), nullable=False, server_default="all_day"),
            sa.Column("prepared_quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unsold_wasted_quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("waste_reason", sa.String(length=255), nullable=True),
            sa.Column("responsible_staff_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("recorded_by_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("notes", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id", name="pk_daily_food_prep_logs"),
            sa.UniqueConstraint(
                "canteen_id",
                "food_item_id",
                "prep_date",
                "meal_session",
                name="uq_daily_food_prep_item_session",
            ),
        )
        op.create_index("ix_daily_food_prep_logs_canteen_id", "daily_food_prep_logs", ["canteen_id"], if_not_exists=True)
        op.create_index("ix_daily_food_prep_logs_food_item_id", "daily_food_prep_logs", ["food_item_id"], if_not_exists=True)
        op.create_index("ix_daily_food_prep_logs_prep_date", "daily_food_prep_logs", ["prep_date"], if_not_exists=True)


def downgrade() -> None:
    if _table_exists("daily_food_prep_logs"):
        op.drop_index("ix_daily_food_prep_logs_prep_date", table_name="daily_food_prep_logs", if_exists=True)
        op.drop_index("ix_daily_food_prep_logs_food_item_id", table_name="daily_food_prep_logs", if_exists=True)
        op.drop_index("ix_daily_food_prep_logs_canteen_id", table_name="daily_food_prep_logs", if_exists=True)
        op.drop_table("daily_food_prep_logs")

    op.drop_index("ix_wastage_records_responsible_staff_id", table_name="wastage_records", if_exists=True)
    op.drop_index("ix_wastage_records_waste_date", table_name="wastage_records", if_exists=True)
    op.drop_index("ix_wastage_records_food_item_id", table_name="wastage_records", if_exists=True)
    op.drop_index("ix_wastage_records_canteen_id", table_name="wastage_records", if_exists=True)
    op.drop_column("wastage_records", "responsible_staff_id")
    op.drop_column("wastage_records", "waste_date")
    op.drop_column("wastage_records", "source_type")
    op.drop_column("wastage_records", "food_item_id")
    op.drop_column("wastage_records", "canteen_id")
    op.execute("DELETE FROM wastage_records WHERE inventory_item_id IS NULL")
    op.alter_column("wastage_records", "inventory_item_id", existing_type=sa.UUID(), nullable=False)
