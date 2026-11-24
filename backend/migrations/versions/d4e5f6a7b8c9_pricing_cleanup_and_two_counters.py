"""Pricing cleanup (zero additional checkout tax & disable coupons) and two-counter College Cafeteria structure

Revision ID: d4e5f6a7b8c9
Revises: cf2a3b4c5d6e
Create Date: 2026-11-24 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "cf2a3b4c5d6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn: sa.Connection, table_name: str) -> bool:
    return sa.inspect(conn).has_table(table_name)


def _count_refs(conn: sa.Connection, table_name: str, canteen_id) -> int:
    if not _table_exists(conn, table_name):
        return 0
    return int(
        conn.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE canteen_id = :cid"),
            {"cid": canteen_id},
        ).scalar()
        or 0
    )


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Pricing cleanup: remove additional checkout tax rates across active catalog & settings
    #    (Historical orders, invoices, and payments remain completely untouched.)
    if _table_exists(conn, "college_settings"):
        conn.execute(sa.text("UPDATE college_settings SET default_tax_rate_percent = 0.00"))

    if _table_exists(conn, "canteens"):
        conn.execute(sa.text("UPDATE canteens SET tax_rate_percent = 0.00"))

    if _table_exists(conn, "food_items"):
        conn.execute(sa.text("UPDATE food_items SET tax_rate_percent = 0.00 WHERE tax_rate_percent IS NOT NULL"))

    if _table_exists(conn, "meal_plans"):
        conn.execute(sa.text("UPDATE meal_plans SET tax_rate_percent = 0.00"))

    # 2. Disable all active discount coupons & clear active cart/promo coupon codes
    #    (Preserves historical coupons and coupon_redemptions records for audit.)
    if _table_exists(conn, "coupons"):
        conn.execute(sa.text("UPDATE coupons SET is_active = FALSE WHERE is_active = TRUE"))

    if _table_exists(conn, "carts"):
        conn.execute(sa.text("UPDATE carts SET coupon_code = NULL WHERE coupon_code IS NOT NULL"))

    if _table_exists(conn, "promotions"):
        conn.execute(sa.text("UPDATE promotions SET coupon_code = NULL WHERE coupon_code IS NOT NULL"))

    # 3. Standardize the two official College Cafeteria counters
    if not _table_exists(conn, "canteens"):
        return

    conn.execute(
        sa.text(
            "UPDATE canteens SET name = 'Main Canteen', location = 'College Cafeteria', "
            "tax_rate_percent = 0.00, is_active = TRUE "
            "WHERE slug = 'main-canteen'"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE canteens SET name = 'Snacks & Bakery Counter', location = 'College Cafeteria', "
            "tax_rate_percent = 0.00, is_active = TRUE "
            "WHERE slug = 'snacks-bakery'"
        )
    )

    # Normalize any legacy placeholder locations on the two active counters
    conn.execute(
        sa.text(
            "UPDATE canteens SET location = 'College Cafeteria' "
            "WHERE slug IN ('main-canteen', 'snacks-bakery') "
            "OR location IN ('Academic Block Ground Floor', 'Central Courtyard')"
        )
    )

    # 4. Safely remove or retire Fresh Juice & Shake Bar (preserving all historical financial records)
    retired_rows = conn.execute(
        sa.text(
            "SELECT id, slug, name FROM canteens "
            "WHERE slug IN ('juice-bar', 'fresh-juice-shake-bar', 'fresh-juice-and-shake-bar') "
            "OR LOWER(name) LIKE '%fresh juice%' "
            "OR LOWER(name) LIKE '%shake bar%' "
            "OR LOWER(location) LIKE '%sports complex%'"
        )
    ).fetchall()

    for row in retired_rows:
        cid = row[0]
        historical_refs = sum(
            _count_refs(conn, tbl, cid)
            for tbl in (
                "orders",
                "invoices",
                "event_bulk_orders",
                "student_meal_subscriptions",
                "meal_plan_redemptions",
                "purchase_orders",
            )
        )

        # Always clear active shopping carts & unsubmitted promos/QRs for the retired counter
        if _table_exists(conn, "cart_items") and _table_exists(conn, "carts"):
            if _table_exists(conn, "cart_item_customizations"):
                conn.execute(
                    sa.text(
                        "DELETE FROM cart_item_customizations WHERE cart_item_id IN ("
                        "SELECT ci.id FROM cart_items ci JOIN carts c ON c.id = ci.cart_id WHERE c.canteen_id = :cid"
                        ")"
                    ),
                    {"cid": cid},
                )
            conn.execute(
                sa.text("DELETE FROM cart_items WHERE cart_id IN (SELECT id FROM carts WHERE canteen_id = :cid)"),
                {"cid": cid},
            )
            conn.execute(sa.text("DELETE FROM carts WHERE canteen_id = :cid"), {"cid": cid})

        if historical_refs == 0:
            # Safe full removal when zero historical financial/order records reference this counter
            if _table_exists(conn, "staff_profiles"):
                conn.execute(
                    sa.text("UPDATE staff_profiles SET assigned_canteen_id = NULL, assigned_counter_id = NULL, assigned_kitchen_id = NULL WHERE assigned_canteen_id = :cid"),
                    {"cid": cid},
                )
            if _table_exists(conn, "user_roles"):
                conn.execute(sa.text("UPDATE user_roles SET canteen_id = NULL WHERE canteen_id = :cid"), {"cid": cid})
            if _table_exists(conn, "coupons"):
                conn.execute(sa.text("UPDATE coupons SET canteen_id = NULL, is_active = FALSE WHERE canteen_id = :cid"), {"cid": cid})

            # Remove dependent menu, schedule, QR, inventory, and counter records
            for child_sql in (
                "DELETE FROM food_item_addons WHERE food_item_id IN (SELECT id FROM food_items WHERE canteen_id = :cid)",
                "DELETE FROM food_item_allergens WHERE food_item_id IN (SELECT id FROM food_items WHERE canteen_id = :cid)",
                "DELETE FROM food_images WHERE food_item_id IN (SELECT id FROM food_items WHERE canteen_id = :cid)",
                "DELETE FROM food_variants WHERE food_item_id IN (SELECT id FROM food_items WHERE canteen_id = :cid)",
                "DELETE FROM menu_availability WHERE food_item_id IN (SELECT id FROM food_items WHERE canteen_id = :cid)",
                "DELETE FROM food_items WHERE canteen_id = :cid",
                "DELETE FROM food_categories WHERE canteen_id = :cid",
                "DELETE FROM food_addons WHERE canteen_id = :cid",
                "DELETE FROM menu_schedules WHERE canteen_id = :cid",
                "DELETE FROM location_qr_codes WHERE canteen_id = :cid",
                "DELETE FROM pickup_slots WHERE canteen_id = :cid",
                "DELETE FROM pickup_locations WHERE canteen_id = :cid",
                "DELETE FROM tables WHERE canteen_id = :cid",
                "DELETE FROM kiosk_devices WHERE canteen_id = :cid",
                "DELETE FROM kitchen_stations WHERE kitchen_id IN (SELECT id FROM kitchens WHERE canteen_id = :cid)",
                "DELETE FROM kitchens WHERE canteen_id = :cid",
                "DELETE FROM counters WHERE canteen_id = :cid",
                "DELETE FROM operating_hours WHERE canteen_id = :cid",
                "DELETE FROM college_holidays WHERE canteen_id = :cid",
                "DELETE FROM promotions WHERE canteen_id = :cid",
                "DELETE FROM announcements WHERE canteen_id = :cid",
                "DELETE FROM inventory_items WHERE canteen_id = :cid",
                "DELETE FROM ingredients WHERE canteen_id = :cid",
                "DELETE FROM meal_plans WHERE canteen_id = :cid",
                "DELETE FROM college_events WHERE canteen_id = :cid",
                "DELETE FROM canteens WHERE id = :cid",
            ):
                target_tbl = child_sql.split("DELETE FROM ", 1)[1].split(" ", 1)[0]
                if _table_exists(conn, target_tbl):
                    conn.execute(sa.text(child_sql), {"cid": cid})
        else:
            # Historical financial records exist: preserve FK integrity via clean deactivation
            conn.execute(
                sa.text(
                    "UPDATE canteens SET is_active = FALSE, is_temporarily_closed = TRUE, "
                    "ordering_paused = TRUE, closure_reason = 'Retired counter - College Cafeteria operates two counters only' "
                    "WHERE id = :cid"
                ),
                {"cid": cid},
            )
            for deactivate_sql in (
                "UPDATE food_items SET is_active = FALSE, is_available = FALSE WHERE canteen_id = :cid",
                "UPDATE food_categories SET is_active = FALSE WHERE canteen_id = :cid",
                "UPDATE counters SET is_active = FALSE WHERE canteen_id = :cid",
                "UPDATE kitchens SET is_active = FALSE WHERE canteen_id = :cid",
                "UPDATE pickup_locations SET is_active = FALSE WHERE canteen_id = :cid",
                "UPDATE pickup_slots SET is_active = FALSE WHERE canteen_id = :cid",
                "UPDATE location_qr_codes SET is_active = FALSE WHERE canteen_id = :cid",
                "UPDATE promotions SET is_active = FALSE WHERE canteen_id = :cid",
                "UPDATE meal_plans SET is_active = FALSE WHERE canteen_id = :cid",
            ):
                target_tbl = deactivate_sql.split("UPDATE ", 1)[1].split(" ", 1)[0]
                if _table_exists(conn, target_tbl):
                    conn.execute(sa.text(deactivate_sql), {"cid": cid})


def downgrade() -> None:
    # Non-destructive downgrade: intentionally preserves historical order & financial data.
    pass
