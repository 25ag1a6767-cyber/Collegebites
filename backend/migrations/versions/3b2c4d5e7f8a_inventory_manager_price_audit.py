"""Add inventory manager metadata, audit log, price change approvals, and purge coupons

Revision ID: 3b2c4d5e7f8a
Revises: 2a1b3c4d5e6f
Create Date: 2026-11-21 20:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "3b2c4d5e7f8a"
down_revision = "2a1b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inventory_items", sa.Column("category", sa.String(length=80), nullable=False, server_default="General"))
    op.add_column("inventory_items", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("inventory_items", sa.Column("image_url", sa.String(length=500), nullable=True))
    op.add_column("inventory_items", sa.Column("storage_location", sa.String(length=120), nullable=True))
    op.add_column(
        "inventory_items",
        sa.Column("preferred_supplier_id", sa.UUID(), sa.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("inventory_items", sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("inventory_items", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("inventory_items", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "inventory_items",
        sa.Column("archived_by_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_inventory_items_is_archived", "inventory_items", ["is_archived"])

    op.add_column("wastage_records", sa.Column("loss_type", sa.String(length=32), nullable=False, server_default="wastage"))

    op.create_table(
        "inventory_audit_logs",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("canteen_id", sa.UUID(), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_item_id", sa.UUID(), sa.ForeignKey("inventory_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("changed_by_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_inv_audit_canteen_item", "inventory_audit_logs", ["canteen_id", "inventory_item_id", "created_at"])

    op.create_table(
        "price_change_requests",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("canteen_id", sa.UUID(), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_item_id", sa.UUID(), sa.ForeignKey("inventory_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("food_item_id", sa.UUID(), sa.ForeignKey("food_items.id", ondelete="CASCADE"), nullable=True),
        sa.Column("price_kind", sa.String(length=32), nullable=False),
        sa.Column("old_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("new_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
        sa.Column("requested_by_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_by_user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("review_notes", sa.String(length=300), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_price_change_canteen_status", "price_change_requests", ["canteen_id", "status", "created_at"])

    # Remove all coupon records and references cleanly per no-coupons policy
    op.execute("DELETE FROM coupon_redemptions")
    op.execute("UPDATE carts SET coupon_code = NULL WHERE coupon_code IS NOT NULL")
    op.execute("UPDATE orders SET coupon_code = NULL WHERE coupon_code IS NOT NULL")
    op.execute("UPDATE promotions SET coupon_code = NULL WHERE coupon_code IS NOT NULL")
    op.execute("DELETE FROM coupons")

    # Allow uploaded data URI images to persist without 500-char truncation
    op.alter_column(
        "food_images",
        "image_url",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=False,
    )

    # Enforce online-only payments across existing college settings and canteens
    op.execute("UPDATE college_settings SET cash_at_counter_enabled = false, pay_at_pickup_enabled = false")
    op.execute("UPDATE canteens SET allow_cash_at_counter = false, allow_pay_at_pickup = false")

    # Seed website QR management permission for college_admin and menu:manage_inventory for inventory_manager
    op.execute(
        """
        INSERT INTO permissions (id, created_at, updated_at, code, resource, action, description)
        VALUES ('9f1e2d3c-4b5a-6789-8abc-def012345678', NOW(), NOW(), 'qr:website_manage', 'qr', 'website_manage', 'qr:website_manage')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO permissions (id, created_at, updated_at, code, resource, action, description)
        VALUES ('8e2d1c3b-5a49-6789-8abc-def012345679', NOW(), NOW(), 'menu:manage_inventory', 'menu', 'manage_inventory', 'menu:manage_inventory')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE r.name = 'college_admin' AND p.code = 'qr:website_manage'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE r.name = 'inventory_manager' AND p.code = 'menu:manage_inventory'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.alter_column(
        "food_images",
        "image_url",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=False,
        postgresql_using="LEFT(image_url, 500)",
    )
    op.drop_index("ix_price_change_canteen_status", table_name="price_change_requests")
    op.drop_table("price_change_requests")
    op.drop_index("ix_inv_audit_canteen_item", table_name="inventory_audit_logs")
    op.drop_table("inventory_audit_logs")
    op.drop_column("wastage_records", "loss_type")
    op.drop_index("ix_inventory_items_is_archived", table_name="inventory_items")
    op.drop_column("inventory_items", "archived_by_user_id")
    op.drop_column("inventory_items", "archived_at")
    op.drop_column("inventory_items", "is_archived")
    op.drop_column("inventory_items", "is_available")
    op.drop_column("inventory_items", "preferred_supplier_id")
    op.drop_column("inventory_items", "storage_location")
    op.drop_column("inventory_items", "image_url")
    op.drop_column("inventory_items", "description")
    op.drop_column("inventory_items", "category")
