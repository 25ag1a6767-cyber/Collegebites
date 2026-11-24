# CollegeBites — PostgreSQL Database Schema

Generated from SQLAlchemy metadata (PostgreSQL + Alembic revision `f6a7b8c9d0e1`, head).

All monetary values use exact `NUMERIC(12, 2)` / `NUMERIC(10, 2)` decimal types (`Money`), quantities use `NUMERIC(12, 3)` (`QuantityNumeric`), and no refund tables or endpoints exist anywhere in the schema.

## 1. College & Operational Locations (11 Tables)
- `college_settings`: Singleton institution configuration (`college_name`, `college_short_code`, `logo_url`, `address`, `contact_phone`, `contact_email`, `default_tax_rate_percent`, `currency_code`, `currency_symbol`, `cancellation_policy_text`, `kiosk_enabled`, `guest_otp_required`, `razorpay_enabled`, `cash_at_counter_enabled` [=false], `pay_at_pickup_enabled` [=false], `college_timezone`, `extra_config`).
- `canteens`: Multi-canteen records (`name`, `slug`, `code`, `token_prefix`, `description`, `location`, `contact_phone`, `contact_email`, `canteen_type`, `is_active`, `is_temporarily_closed`, `closure_reason`, `ordering_paused`, `pause_reason`, `tax_rate_percent`, `allow_online_payment`, `allow_cash_at_counter` [=false], `allow_pay_at_pickup` [=false], `max_concurrent_orders`, `orders_per_slot_capacity`, `default_prep_time_minutes`, `peak_hour_buffer_minutes`, `crowd_moderate_threshold`, `crowd_high_threshold`, `crowd_very_high_threshold`, `auto_throttle_enabled`, `prep_settings`, `payment_settings`).
- `counters`, `kitchens`, `kitchen_stations`, `tables`, `pickup_locations`, `kiosk_devices`, `operating_hours`, `college_holidays`, `location_qr_codes`.

## 2. Authentication, RBAC & Users (10 Tables)
- `users`: Universal account table (`email`, `phone`, `full_name`, `password_hash`, `user_kind`, `is_active`, `is_verified`, `last_login_at`).
- `customer_profiles`, `staff_profiles`: Role-specific attributes and canteen/counter assignments.
- `roles`, `permissions`, `role_permissions`, `user_roles`: Database-backed RBAC mapping.
- `sessions`, `refresh_tokens`: Refresh token rotation and revocation tracking.
- `otp_verifications`: HMAC-SHA256 hashed OTP codes (`otp_hash`; zero plaintext storage), attempt limits (`max_attempts=5`), expiry timestamps (`expires_at`), cooldown windows (`resend_available_at`), single-use consumption (`consumed_at`), invalidation (`invalidated_at`), `user_id`, `channel`, `provider`, `ip_address`, and hashed verification tokens (`verification_token`) for `register`, `login`, `guest_checkout`, `password_reset`, `phone_verify`, and `email_verify`.

## 3. Menu Catalog & Recipes (13 Tables)
- `food_categories`: Per-canteen category organization (`canteen_id`, `name`, `slug`, `description`, `display_order`, `is_active`).
- `food_items`: Menu dishes (`canteen_id`, `category_id`, `kitchen_id`, `counter_id`, `name`, `slug`, `description`, `base_price`, `tax_rate_percent`, `is_veg`, `is_featured`, `is_popular`, `is_todays_special`, `is_recommended`, `prep_time_minutes`, `portion_size`, `calories`, `nutrition_info`, `spice_levels`, `sugar_levels`, `removable_ingredients`, `ingredients_text`, `average_rating`, `rating_count`, `popularity_score`, `is_available`, `is_active`, `insufficient_ingredients`).
- `food_images`: Stores dish image URLs or validated base64 data URIs (`image_url` altered to `TEXT` in revision `3b2c4d5e7f8a`).
- `food_variants`, `food_addons`, `food_item_addons`, `allergens`, `food_item_allergens`, `menu_schedules`, `menu_availability`.
- `ingredients`, `recipes`, `recipe_ingredients`: Automatic FEFO stock deduction mappings.

## 4. Cart, Orders & Pickup Slots (11 Tables)
- `carts`, `cart_items`, `cart_item_customizations`: Persistent cart storage (authenticated or guest session ID).
- `orders`: Authoritative order records (`order_number`, `idempotency_key`, `canteen_id`, `counter_id`, `kitchen_id`, `table_id`, `kiosk_device_id`, `customer_id`, `cashier_id`, `pickup_slot_id`, `location_qr_id`, `is_guest`, `guest_name`, `guest_phone`, `guest_access_token_hash`, `order_type`, `order_channel`, `status`, `payment_status`, `payment_method`, `subtotal_amount`, `discount_amount`, `tax_amount`, `total_amount`, `coupon_code` [rejected/null], `estimated_prep_minutes`, `estimated_pickup_at`, `confirmed_at`, `accepted_at`, `preparing_at`, `ready_at`, `completed_at`, `delayed_minutes`, `delay_reason`, `notes`, `inventory_deducted`).
- `order_items`, `order_item_customizations`: Immutable price/name snapshots preserved across subsequent menu price changes.
- `order_status_history`, `order_cancellations`, `order_assignments`, `pickup_slots`, `slot_reservations`.

## 5. Payments, Tokens, QR & Printing (12 Tables)
- `payments`, `payment_transactions`, `payment_webhook_events`, `payment_reconciliation`: Payment gateway state (`razorpay` online checkout + `upi_pos` / `card_pos` counter POS; all historical payment & transaction audit rows preserved immutably), cryptographic verification, webhook idempotency, and settlement reconciliation.
- `order_token_sequences`, `pickup_tokens`, `order_qr_codes`, `qr_verification_events`, `order_handover_records`: Daily per-canteen sequence tokens, HMAC-signed QR verification hashes, scan audit trail, and atomic handover completion.
- `receipts`, `receipt_print_jobs` (with `job_type`: `customer_receipt` on payment confirmation vs `kot` after kitchen acceptance), `receipt_print_history`: Immutable digital receipts, print queues, and reprint logs.

## 6. Inventory Management, Price Governance & Suppliers (11 Tables)
- `inventory_items`: Per-canteen ingredient stock & metadata (`current_quantity`, `reserved_quantity`, `reorder_level`, `unit`, `unit_cost`, `category`, `description`, `image_url`, `storage_location`, `preferred_supplier_id`, `is_available`, `is_archived`, `archived_at`, `archived_by_user_id`).
- `stock_batches`, `stock_movements`, `suppliers`, `purchase_orders`, `purchase_order_items`, `stock_adjustments`, `wastage_records` (with `loss_type`: `wastage`, `damaged`, `expired`), `stock_transfers`.
- `inventory_audit_logs`: Field-level immutable edit audit trail.
- `price_change_requests`: Tracks immediate purchase cost updates (`status=applied`) vs approval-gated selling price requests (`pending_approval` -> `approved` / `rejected`).

## 7. Staff Operations, Promotions, Notifications & Support (15 Tables)
- `staff_shifts`, `staff_attendance`, `staff_tasks`.
- `promotions` (banners/announcements only; `coupon_code` nullified), `loyalty_accounts`, `loyalty_transactions`.
- Legacy tables retained for schema history: `coupons`, `coupon_redemptions` (all rows deleted in migration `3b2c4d5e7f8a`; all coupon APIs and UI removed).
- `notifications`, `notification_templates`, `notification_preferences`, `announcements`.
- `reviews`, `ratings`, `support_tickets`, `support_messages`.

## 8. System Observability & Reporting (4 Tables)
- `audit_logs`, `activity_logs`, `daily_sales_summaries`, `system_events`.
