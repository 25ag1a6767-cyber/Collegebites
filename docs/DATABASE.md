# CollegeBites Database Design

PostgreSQL relational schema using SQLAlchemy 2 and Alembic migrations.
All monetary columns strictly use `NUMERIC(12, 2)` (Decimal), never floating-point types.
**No refund tables exist in this database by policy and design.**

## Table Domains

### 1. College & Operational Locations
- `college_settings`: Singleton configuration for the college (name, logo URL, address, phone, email, cancellation/payment policy text, default tax rate, kiosk enabled flag, printer settings).
- `canteens`: Main Canteen, Food Court, etc. with slug, description, location, status, temporary closure/pause flags, crowd thresholds, preparation settings, and tax/payment settings.
- `counters`: Pickup/Cashier counters per canteen (e.g., Counter 1, Counter 2, Juice Counter).
- `kitchens`: Kitchens assigned to canteens with concurrent capacity and prep settings.
- `kitchen_stations`: Sub-stations inside a kitchen (Grill, Beverages, South Indian, Bakery).
- `tables`: Dining/ordering tables linked to a canteen and optional counter.
- `pickup_locations`: Named pickup bays mapped to counters.
- `kiosk_devices`: Registered self-service touchscreen kiosks (disabled by default).
- `operating_hours`: Per-canteen day-of-week open/close windows.
- `college_holidays`: Holiday and temporary closure windows.
- `location_qr_codes`: Permanent revocable/replaceable/expirable QR identifiers for canteens, counters, tables, and kiosks.

### 2. Users, Roles & Permissions
- `users`: Universal account table (no separate student/faculty/visitor login systems; optional guest accounts or unauthenticated guest orders linked by verified phone).
- `customer_profiles`: Preferences, default canteen, saved favourite item IDs, dietary tags.
- `staff_profiles`: Employee code, assigned canteen, assigned counter/kitchen, designation.
- `roles`: `super_admin`, `college_admin`, `canteen_manager`, `cashier`, `kitchen_staff`, `inventory_manager`, `pickup_staff`, `customer`.
- `permissions`, `user_roles`, `role_permissions`: Fine-grained backend-enforced RBAC.
- `sessions`, `refresh_tokens`, `otp_verifications`: Secure session management, token rotation, and phone/email OTP verification.

### 3. Menu & Recipes
- `food_categories`, `food_items`, `food_images`, `food_variants`, `food_addons`, `food_item_addons`
- `ingredients`, `recipes`, `recipe_ingredients`, `allergens`, `food_item_allergens`
- `menu_schedules` (Breakfast, Lunch, Snacks, Specials), `menu_availability`

### 4. Cart, Orders & Slots
- `carts`, `cart_items`, `cart_item_customizations`
- `orders`, `order_items`, `order_item_customizations` (immutable price/name snapshots)
- `order_status_history`, `order_cancellations`, `order_assignments`
- `pickup_slots`, `slot_reservations`

### 5. Payments, Tokens, QR, Receipts & Printing
- `payments`, `payment_transactions`, `payment_webhook_events`, `payment_reconciliation`
- `order_token_sequences`, `pickup_tokens`, `order_qr_codes`, `qr_verification_events`, `order_handover_records`
- `receipts`, `receipt_print_jobs`, `receipt_print_history`

### 6. Inventory
- `inventory_items`, `stock_batches`, `stock_movements`, `suppliers`, `purchase_orders`, `purchase_order_items`, `stock_adjustments`, `wastage_records`, `stock_transfers`

### 7. Staff Operations
- `staff_shifts`, `staff_attendance`, `staff_tasks`

### 8. Promotions & Loyalty
- `coupons`, `coupon_redemptions`, `promotions`, `loyalty_accounts`, `loyalty_transactions`

### 9. Notifications, Reviews & Support
- `notifications`, `notification_templates`, `notification_preferences`, `announcements`
- `reviews`, `ratings`, `support_tickets`, `support_messages`

### 10. System & Analytics
- `audit_logs`, `activity_logs`, `daily_sales_summaries`, `system_events`
