"""Production enhancements: priority orders, item-wise prep & stations, notification dedup & web push

Revision ID: 4c3d5e6f7a9b
Revises: 3b2c4d5e7f8a
Create Date: 2026-11-22 22:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "4c3d5e6f7a9b"
down_revision = "3b2c4d5e7f8a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("guest_email", sa.String(length=160), nullable=True))
    op.add_column("orders", sa.Column("is_priority", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_orders_canteen_created_at", "orders", ["canteen_id", "created_at"], if_not_exists=True)

    op.add_column("order_items", sa.Column("prep_status", sa.String(length=24), nullable=False, server_default="PENDING"))
    op.add_column(
        "order_items",
        sa.Column("station_id", sa.UUID(), sa.ForeignKey("kitchen_stations.id", ondelete="SET NULL"), nullable=True),
    )

    op.add_column(
        "food_items",
        sa.Column("station_id", sa.UUID(), sa.ForeignKey("kitchen_stations.id", ondelete="SET NULL"), nullable=True),
    )

    op.add_column("notifications", sa.Column("dedup_key", sa.String(length=160), nullable=True))
    op.create_index("ix_notifications_dedup_key", "notifications", ["dedup_key"], if_not_exists=True)

    op.add_column(
        "notification_preferences",
        sa.Column("web_push_subscriptions", sa.JSON(), nullable=False, server_default="[]"),
    )

    # Sync single-column indexes declared on models in 3b2c4d5e7f8a
    op.create_index("ix_inventory_audit_logs_canteen_id", "inventory_audit_logs", ["canteen_id"], if_not_exists=True)
    op.create_index("ix_inventory_audit_logs_inventory_item_id", "inventory_audit_logs", ["inventory_item_id"], if_not_exists=True)
    op.create_index("ix_price_change_requests_canteen_id", "price_change_requests", ["canteen_id"], if_not_exists=True)
    op.create_index("ix_price_change_requests_inventory_item_id", "price_change_requests", ["inventory_item_id"], if_not_exists=True)
    op.create_index("ix_price_change_requests_food_item_id", "price_change_requests", ["food_item_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_price_change_requests_food_item_id", table_name="price_change_requests", if_exists=True)
    op.drop_index("ix_price_change_requests_inventory_item_id", table_name="price_change_requests", if_exists=True)
    op.drop_index("ix_price_change_requests_canteen_id", table_name="price_change_requests", if_exists=True)
    op.drop_index("ix_inventory_audit_logs_inventory_item_id", table_name="inventory_audit_logs", if_exists=True)
    op.drop_index("ix_inventory_audit_logs_canteen_id", table_name="inventory_audit_logs", if_exists=True)

    op.drop_column("notification_preferences", "web_push_subscriptions")
    op.drop_index("ix_notifications_dedup_key", table_name="notifications", if_exists=True)
    op.drop_column("notifications", "dedup_key")
    op.drop_column("food_items", "station_id")
    op.drop_column("order_items", "station_id")
    op.drop_column("order_items", "prep_status")
    op.drop_index("ix_orders_canteen_created_at", table_name="orders", if_exists=True)
    op.drop_column("orders", "is_priority")
    op.drop_column("orders", "guest_email")
