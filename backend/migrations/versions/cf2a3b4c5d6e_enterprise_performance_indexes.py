"""Enterprise performance composite indexes for high-concurrency ordering, queues, boards & analytics

Revision ID: cf2a3b4c5d6e
Revises: be1f2a3b4c5d
Create Date: 2026-11-24 10:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "cf2a3b4c5d6e"
down_revision = "be1f2a3b4c5d"
branch_labels = None
depends_on = None


INDEX_SPECS: list[tuple[str, str, list[str]]] = [
    # Carts & Orders hot paths (checkout, /orders/my, /admin/orders, /reports/dashboard, /queue, /pickup/board)
    ("ix_carts_user_canteen_status", "carts", ["user_id", "canteen_id", "status"]),
    ("ix_carts_guest_canteen_status", "carts", ["guest_session_id", "canteen_id", "status"]),
    ("ix_orders_canteen_payment_created", "orders", ["canteen_id", "payment_status", "created_at"]),
    ("ix_orders_payment_created", "orders", ["payment_status", "created_at"]),
    ("ix_orders_canteen_status_ready", "orders", ["canteen_id", "status", "ready_at"]),
    ("ix_orders_canteen_status_completed", "orders", ["canteen_id", "status", "completed_at"]),
    ("ix_orders_created_at", "orders", ["created_at"]),
    ("ix_order_items_food_item_id", "order_items", ["food_item_id"]),
    ("ix_order_items_prep_status", "order_items", ["prep_status"]),
    ("ix_order_status_history_created_actor", "order_status_history", ["created_at", "changed_by_user_id"]),
    ("ix_slot_reservations_status_expires", "slot_reservations", ["status", "expires_at"]),
    # Payments & Pickup Tokens
    ("ix_payments_order_created", "payments", ["order_id", "created_at"]),
    ("ix_payments_status_created", "payments", ["status", "created_at"]),
    ("ix_pickup_tokens_date_canteen_seq", "pickup_tokens", ["service_date", "canteen_id", "sequence_number"]),
    # Menu catalog hot browse & sufficiency checks
    ("ix_food_items_canteen_popularity", "food_items", ["canteen_id", "is_active", "popularity_score"]),
    ("ix_food_items_canteen_insuff", "food_items", ["canteen_id", "insufficient_ingredients"]),
    # Auth, Sessions & Security
    ("ix_sessions_user_revoked", "sessions", ["user_id", "revoked_at"]),
    ("ix_sessions_expires_at", "sessions", ["expires_at"]),
    ("ix_audit_logs_created_at", "audit_logs", ["created_at"]),
    ("ix_login_attempts_ip_success_time", "login_attempts", ["ip_address", "success", "created_at"]),
    # Notifications
    ("ix_notifications_user_read_created", "notifications", ["user_id", "is_read", "created_at"]),
    ("ix_notifications_role_created", "notifications", ["role_target", "created_at"]),
    # Inventory, Procurement & Staff Queue
    ("ix_inventory_canteen_arch_qty", "inventory_items", ["canteen_id", "is_archived", "current_quantity"]),
    ("ix_po_supplier_status", "purchase_orders", ["supplier_id", "status"]),
    ("ix_po_canteen_status_created", "purchase_orders", ["canteen_id", "status", "created_at"]),
    ("ix_vendor_payments_po_status", "vendor_payments", ["purchase_order_id", "status"]),
    ("ix_vendor_payments_supplier_status", "vendor_payments", ["supplier_id", "status"]),
    ("ix_staff_attendance_canteen_date_status", "staff_attendance", ["canteen_id", "attendance_date", "status"]),
    # Promotions & Loyalty
    ("ix_coupon_redemptions_coupon_user", "coupon_redemptions", ["coupon_id", "user_id"]),
    ("ix_loyalty_txn_order_type", "loyalty_transactions", ["order_id", "transaction_type"]),
]


def _table_exists(table_name: str) -> bool:
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(idx.get("name") == index_name for idx in sa.inspect(op.get_bind()).get_indexes(table_name))


def upgrade() -> None:
    for idx_name, table_name, cols in INDEX_SPECS:
        if _table_exists(table_name) and not _index_exists(table_name, idx_name):
            op.create_index(idx_name, table_name, cols)


def downgrade() -> None:
    for idx_name, table_name, _cols in reversed(INDEX_SPECS):
        if _index_exists(table_name, idx_name):
            op.drop_index(idx_name, table_name=table_name)
