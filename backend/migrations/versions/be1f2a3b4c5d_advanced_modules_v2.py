"""Advanced modules v2: Vendor Procurement, Meal Plans, Events Bulk Orders, Nutrition Verified, Invoices

Revision ID: be1f2a3b4c5d
Revises: ad9e0f1a2b3c
Create Date: 2026-11-23 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "be1f2a3b4c5d"
down_revision = "ad9e0f1a2b3c"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table_name)}
    return column_name in cols


def upgrade() -> None:
    # 1. Supplier extensions
    if not _column_exists("suppliers", "business_details"):
        op.add_column("suppliers", sa.Column("business_details", sa.Text(), nullable=True))
    if not _column_exists("suppliers", "supplied_products"):
        op.add_column("suppliers", sa.Column("supplied_products", sa.JSON(), nullable=True))
    if not _column_exists("suppliers", "payment_terms"):
        op.add_column("suppliers", sa.Column("payment_terms", sa.String(length=80), nullable=True))

    # 2. PurchaseOrder & PurchaseOrderItem extensions
    if not _column_exists("purchase_orders", "subtotal_amount"):
        op.add_column("purchase_orders", sa.Column("subtotal_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"))
    if not _column_exists("purchase_orders", "tax_amount"):
        op.add_column("purchase_orders", sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"))
    if not _column_exists("purchase_orders", "approved_by_user_id"):
        op.add_column(
            "purchase_orders",
            sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
    if not _column_exists("purchase_orders", "approved_at"):
        op.add_column("purchase_orders", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    if not _column_exists("purchase_orders", "expected_delivery_date"):
        op.add_column("purchase_orders", sa.Column("expected_delivery_date", sa.Date(), nullable=True))

    if _table_exists("purchase_order_items"):
        op.alter_column("purchase_order_items", "ingredient_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    if not _column_exists("purchase_order_items", "item_name"):
        op.add_column("purchase_order_items", sa.Column("item_name", sa.String(length=140), nullable=True))
    if not _column_exists("purchase_order_items", "unit"):
        op.add_column("purchase_order_items", sa.Column("unit", sa.String(length=32), nullable=False, server_default="units"))
    if not _column_exists("purchase_order_items", "tax_rate_percent"):
        op.add_column("purchase_order_items", sa.Column("tax_rate_percent", sa.Numeric(5, 2), nullable=False, server_default="0.00"))
    if not _column_exists("purchase_order_items", "tax_amount"):
        op.add_column("purchase_order_items", sa.Column("tax_amount", sa.Numeric(10, 2), nullable=False, server_default="0.00"))
    if not _column_exists("purchase_order_items", "quantity_damaged"):
        op.add_column("purchase_order_items", sa.Column("quantity_damaged", sa.Numeric(12, 3), nullable=False, server_default="0.000"))
    if not _column_exists("purchase_order_items", "quantity_rejected"):
        op.add_column("purchase_order_items", sa.Column("quantity_rejected", sa.Numeric(12, 3), nullable=False, server_default="0.000"))
    if not _column_exists("purchase_order_items", "quantity_missing"):
        op.add_column("purchase_order_items", sa.Column("quantity_missing", sa.Numeric(12, 3), nullable=False, server_default="0.000"))

    # 3. GoodsReceipt, GoodsReceiptItem, VendorPayment
    if not _table_exists("goods_receipts"):
        op.create_table(
            "goods_receipts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("grn_number", sa.String(length=48), nullable=False, unique=True),
            sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("canteen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("idempotency_key", sa.String(length=96), nullable=True, unique=True),
            sa.Column("delivery_challan_ref", sa.String(length=96), nullable=True),
            sa.Column("received_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_goods_receipts_po_id", "goods_receipts", ["purchase_order_id"])
        op.create_index("ix_goods_receipts_canteen_id", "goods_receipts", ["canteen_id"])
        op.create_index("ix_goods_receipts_supplier_id", "goods_receipts", ["supplier_id"])

    if not _table_exists("goods_receipt_items"):
        op.create_table(
            "goods_receipt_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("goods_receipt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("po_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_order_items.id", ondelete="CASCADE"), nullable=False),
            sa.Column("ingredient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True),
            sa.Column("item_name", sa.String(length=140), nullable=False),
            sa.Column("quantity_delivered", sa.Numeric(12, 3), nullable=False),
            sa.Column("quantity_accepted", sa.Numeric(12, 3), nullable=False),
            sa.Column("quantity_damaged", sa.Numeric(12, 3), nullable=False, server_default="0.000"),
            sa.Column("quantity_rejected", sa.Numeric(12, 3), nullable=False, server_default="0.000"),
            sa.Column("quantity_missing", sa.Numeric(12, 3), nullable=False, server_default="0.000"),
            sa.Column("unit_cost", sa.Numeric(10, 2), nullable=False),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_goods_receipt_items_grn_id", "goods_receipt_items", ["goods_receipt_id"])

    if not _table_exists("vendor_payments"):
        op.create_table(
            "vendor_payments",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("payment_number", sa.String(length=48), nullable=False, unique=True),
            sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("canteen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("payment_method", sa.String(length=32), nullable=False, server_default="bank_transfer"),
            sa.Column("payment_reference", sa.String(length=128), nullable=True),
            sa.Column("document_url", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_verification"),
            sa.Column("payment_date", sa.Date(), nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("recorded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("verified_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_vendor_payments_supplier", "vendor_payments", ["supplier_id"])
        op.create_index("ix_vendor_payments_po", "vendor_payments", ["purchase_order_id"])
        op.create_index("ix_vendor_payments_status", "vendor_payments", ["status"])

    # 4. Student Meal Plans
    if not _table_exists("meal_plans"):
        op.create_table(
            "meal_plans",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("canteen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=True),
            sa.Column("code", sa.String(length=48), nullable=False, unique=True),
            sa.Column("name", sa.String(length=140), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("plan_type", sa.String(length=32), nullable=False, server_default="monthly"),
            sa.Column("price", sa.Numeric(10, 2), nullable=False),
            sa.Column("tax_rate_percent", sa.Numeric(5, 2), nullable=False, server_default="5.00"),
            sa.Column("validity_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("total_meals", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("eligible_category_ids", sa.JSON(), nullable=True),
            sa.Column("eligible_food_item_ids", sa.JSON(), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_meal_plans_canteen", "meal_plans", ["canteen_id"])

    if not _table_exists("student_meal_subscriptions"):
        op.create_table(
            "student_meal_subscriptions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("subscription_number", sa.String(length=48), nullable=False, unique=True),
            sa.Column("student_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("meal_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meal_plans.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("canteen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("total_meals", sa.Integer(), nullable=False),
            sa.Column("remaining_meals", sa.Integer(), nullable=False),
            sa.Column("subtotal_amount", sa.Numeric(10, 2), nullable=False),
            sa.Column("tax_amount", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
            sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
            sa.Column("payment_method", sa.String(length=32), nullable=False, server_default="razorpay"),
            sa.Column("payment_status", sa.String(length=32), nullable=False, server_default="PENDING"),
            sa.Column("provider_order_id", sa.String(length=128), nullable=True),
            sa.Column("provider_payment_id", sa.String(length=128), nullable=True, unique=True),
            sa.Column("payment_reference", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_payment"),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("redemption_code", sa.String(length=64), nullable=False, unique=True),
            sa.Column("redemption_qr_payload", sa.String(length=255), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_meal_subs_student", "student_meal_subscriptions", ["student_user_id"])
        op.create_index("ix_meal_subs_status", "student_meal_subscriptions", ["status"])

    if not _table_exists("meal_plan_redemptions"):
        op.create_table(
            "meal_plan_redemptions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("redemption_number", sa.String(length=48), nullable=False, unique=True),
            sa.Column("idempotency_key", sa.String(length=96), nullable=True, unique=True),
            sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("student_meal_subscriptions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("student_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("canteen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("meal_item_name", sa.String(length=140), nullable=False),
            sa.Column("meals_deducted", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("remaining_meals_after", sa.Integer(), nullable=False),
            sa.Column("redeemed_by_staff_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_meal_redemptions_sub", "meal_plan_redemptions", ["subscription_id"])
        op.create_index("ix_meal_redemptions_student", "meal_plan_redemptions", ["student_user_id"])

    # 5. College Events & Bulk Orders
    if not _table_exists("college_events"):
        op.create_table(
            "college_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("event_code", sa.String(length=48), nullable=False, unique=True),
            sa.Column("canteen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("department", sa.String(length=120), nullable=False),
            sa.Column("organizer_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("organizer_name", sa.String(length=120), nullable=False),
            sa.Column("contact_phone", sa.String(length=32), nullable=False),
            sa.Column("contact_email", sa.String(length=160), nullable=True),
            sa.Column("event_date", sa.Date(), nullable=False),
            sa.Column("location", sa.String(length=180), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("ordering_deadline", sa.DateTime(timezone=True), nullable=False),
            sa.Column("eligible_food_item_ids", sa.JSON(), nullable=True),
            sa.Column("min_order_quantity", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("max_order_quantity", sa.Integer(), nullable=False, server_default="500"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_college_events_canteen", "college_events", ["canteen_id"])
        op.create_index("ix_college_events_date", "college_events", ["event_date"])

    if not _table_exists("event_bulk_orders"):
        op.create_table(
            "event_bulk_orders",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("bulk_order_number", sa.String(length=48), nullable=False, unique=True),
            sa.Column("idempotency_key", sa.String(length=96), nullable=True, unique=True),
            sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("college_events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("canteen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organizer_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("linked_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("scheduled_prep_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("scheduled_pickup_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("pickup_arrangement", sa.String(length=32), nullable=False, server_default="grouped_token"),
            sa.Column("group_pickup_token", sa.String(length=48), nullable=True),
            sa.Column("individual_tokens_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
            sa.Column("payment_method", sa.String(length=32), nullable=False, server_default="razorpay"),
            sa.Column("payment_status", sa.String(length=32), nullable=False, server_default="PENDING"),
            sa.Column("provider_order_id", sa.String(length=128), nullable=True),
            sa.Column("provider_payment_id", sa.String(length=128), nullable=True),
            sa.Column("payment_reference", sa.String(length=128), nullable=True),
            sa.Column("total_quantity", sa.Integer(), nullable=False),
            sa.Column("subtotal_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index("ix_event_bulk_orders_event", "event_bulk_orders", ["event_id"])
        op.create_index("ix_event_bulk_orders_canteen", "event_bulk_orders", ["canteen_id"])
        op.create_index("ix_event_bulk_orders_status", "event_bulk_orders", ["status"])

    if not _table_exists("event_bulk_order_items"):
        op.create_table(
            "event_bulk_order_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("bulk_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("event_bulk_orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("item_name", sa.String(length=140), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
            sa.Column("tax_rate_percent", sa.Numeric(5, 2), nullable=False),
            sa.Column("tax_amount", sa.Numeric(10, 2), nullable=False),
            sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        )
        op.create_index("ix_event_bulk_order_items_bulk", "event_bulk_order_items", ["bulk_order_id"])

    # 6. FoodItem nutrition_verified column
    if not _column_exists("food_items", "nutrition_verified"):
        op.add_column("food_items", sa.Column("nutrition_verified", sa.Boolean(), nullable=False, server_default=sa.false()))

    # 7. Formal Tax Invoices
    if not _table_exists("invoices"):
        op.create_table(
            "invoices",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("invoice_number", sa.String(length=48), nullable=False, unique=True),
            sa.Column("invoice_type", sa.String(length=32), nullable=False, server_default="order"),
            sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=True, unique=True),
            sa.Column("bulk_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("event_bulk_orders.id", ondelete="CASCADE"), nullable=True, unique=True),
            sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("student_meal_subscriptions.id", ondelete="CASCADE"), nullable=True, unique=True),
            sa.Column("canteen_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("canteens.id", ondelete="SET NULL"), nullable=True),
            sa.Column("customer_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reference_number", sa.String(length=64), nullable=False),
            sa.Column("customer_name", sa.String(length=140), nullable=False),
            sa.Column("customer_contact", sa.String(length=140), nullable=True),
            sa.Column("subtotal_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("tax_breakdown_json", sa.JSON(), nullable=True),
            sa.Column("items_json", sa.JSON(), nullable=False),
            sa.Column("payment_method", sa.String(length=32), nullable=False),
            sa.Column("payment_reference", sa.String(length=128), nullable=True),
            sa.Column("payment_status", sa.String(length=32), nullable=False, server_default="CONFIRMED"),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_invoices_canteen", "invoices", ["canteen_id"])
        op.create_index("ix_invoices_customer", "invoices", ["customer_user_id"])
        op.create_index("ix_invoices_type", "invoices", ["invoice_type"])


def downgrade() -> None:
    for tbl in (
        "invoices",
        "event_bulk_order_items",
        "event_bulk_orders",
        "college_events",
        "meal_plan_redemptions",
        "student_meal_subscriptions",
        "meal_plans",
        "vendor_payments",
        "goods_receipt_items",
        "goods_receipts",
    ):
        if _table_exists(tbl):
            op.drop_table(tbl)
