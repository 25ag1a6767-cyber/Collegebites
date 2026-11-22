# CollegeBites — Complete REST & WebSocket API Reference

Base URL: `/api/v1` (except `GET /health` and WebSocket endpoints `/api/v1/ws/...`)
Authentication: Bearer JWT access token (`Authorization: Bearer <access_token>`) with refresh token rotation. Guest flows authenticate via `?guest_token=` or verified `OTPVER.*` tokens.

**Platform-wide invariants:**
- **No Refunds**: All refund endpoints are omitted (`404`/`405`). Orders confirmed by payment enter kitchen preparation and preserve payment records even if cancelled.
- **No Coupons**: All `/promotions/coupons*` and `/carts/coupon` routes are removed (`404`/`405`), and any non-empty `coupon_code` on checkout or POS raises HTTP `400`.
- **Online-Only Payments**: `"cash"` and `"pay_at_pickup"` return HTTP `400` on customer checkout, counter collect, POS orders, and admin configuration toggles. Walk-in Cashier POS uses digital terminals (`upi_pos`, `card_pos`).

---

## 1. Health & Public Catalog
- `GET /health` — Service health probe (`{"status": "ok"}`).
- `GET /api/v1/canteens/college` — College profile, timezone, policy text, and gateway enablement flags.
- `GET /api/v1/canteens` — Active campus canteens with open/closed & crowd status.
- `GET /api/v1/canteens/{canteen_id_or_slug}` — Detailed canteen info including counters, kitchens, and crowd metrics.
- `GET /api/v1/menus/canteens/{canteen_id}/categories` — List active (or all) menu categories.
- `GET /api/v1/menus/canteens/{canteen_id}/items` — Search/filter food items with variants, addons, allergens, and active menu schedules.
- `GET /api/v1/menus/items/{item_id}` — Single dish detail.

## 2. Authentication & OTP (`/api/v1/auth`)
- `POST /api/v1/auth/register` — Universal account signup (`customer` role).
- `POST /api/v1/auth/login` — Password login with email or phone.
- `GET /api/v1/auth/otp/capabilities` — Reports live Email SMTP OTP, SMS OTP, and dev-echo availability booleans.
- `POST /api/v1/auth/otp/request` — Request 6-digit OTP (`login`, `guest_checkout`, `password_reset`, `phone_verify`). Dispatches SMTP email OTP for email targets; phone targets dispatch via SMS gateway if configured or fall back to registered account email (`400`/`503` in production if neither channel is configured).
- `POST /api/v1/auth/otp/verify` — Verify OTP and receive signed `OTPVER.*` verification token.
- `POST /api/v1/auth/otp/login` — Passwordless OTP login returning JWT tokens.
- `POST /api/v1/auth/refresh` — Refresh token rotation with replay revocation.
- `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`, `POST /api/v1/auth/phone/verify`, `POST /api/v1/auth/change-password`, `POST /api/v1/auth/password-reset/confirm`, `GET /api/v1/auth/sessions`, `DELETE /api/v1/auth/sessions/{session_id}`.

## 3. Customer Cart, Profile, Orders & Tracking
- `GET /api/v1/customers/profile`, `PATCH /api/v1/customers/profile`, `DELETE /api/v1/customers/me`
- `GET /api/v1/customers/favourites`, `POST /api/v1/customers/favourites/{food_item_id}`, `DELETE /api/v1/customers/favourites/{food_item_id}`
- `GET /api/v1/carts`, `POST /api/v1/carts/items`, `PATCH /api/v1/carts/items/{cart_item_id}`
- `GET /api/v1/orders/slots/{canteen_id}` — Available pickup slots with remaining capacity.
- `POST /api/v1/orders/checkout` — Idempotent server-calculated order creation (`razorpay` or `stripe`; supports registered users and OTP-verified guests via `guest_phone` / `guest_email`).
- `GET /api/v1/orders/my`, `POST /api/v1/orders/guest/lookup`, `GET /api/v1/orders/{order_id_or_number}`, `POST /api/v1/orders/{order_id}/cancel`.

## 4. Payments & Webhooks (`/api/v1/payments`)
- `GET /api/v1/payments/stripe/config` — Public Stripe publishable key and gateway readiness status for Web Elements & Mobile PaymentSheet.
- `POST /api/v1/payments/razorpay/verify` — HMAC-SHA256 verification of `razorpay_order_id|razorpay_payment_id` + atomic token/QR/receipt generation & stock deduction.
- `POST /api/v1/payments/razorpay/fail` — Record Razorpay payment failure/cancellation.
- `POST /api/v1/payments/razorpay/webhook` — Verify `X-Razorpay-Signature` idempotently.
- `POST /api/v1/payments/stripe/verify` — Verify Stripe PaymentIntent (`stripe_payment_intent_id` / `payment_intent_id`) or Checkout Session (`stripe_session_id`) via official `stripe` Python SDK in live mode or HMAC verification in dev/test.
- `POST /api/v1/payments/stripe/fail` — Record Stripe failure/cancellation.
- `POST /api/v1/payments/stripe/webhook` — Verify `Stripe-Signature` (`t=...,v1=...`) idempotently via official Stripe webhook SDK (with HMAC fallback in dev/test).
- `POST /api/v1/payments/retry/{order_id}` — Re-initiate online checkout for `PAYMENT_PENDING` / `PAYMENT_FAILED` orders (`razorpay` or `stripe`).
- `POST /api/v1/payments/counter/collect` — Staff digital counter collection (`upi_pos` or `card_pos` only).
- `GET /api/v1/payments`, `POST /api/v1/payments/reconcile`, `GET /api/v1/payments/reconciliations`.

## 5. Tokens, Receipts, QR Codes & Printing
- `GET /api/v1/tokens/receipts/{order_id_or_number}`, `GET /api/v1/tokens/receipts/{order_id_or_number}/pdf`, `GET /api/v1/tokens/receipts/{order_id_or_number}/qr.png`, `POST /api/v1/tokens/orders/{order_id}/revoke-qr`.
- `GET /api/v1/printing/receipts/{order_id_or_number}/escpos`, `POST /api/v1/printing/receipts/{order_id_or_number}/print`, `POST /api/v1/printing/jobs/{job_id}/retry`, `GET /api/v1/printing/jobs`, `GET /api/v1/printing/history/{order_id_or_number}`.
- `GET /api/v1/qr/locations`, `POST /api/v1/qr/locations`, `POST /api/v1/qr/locations/{qr_id}/revoke`, `POST /api/v1/qr/locations/{qr_id}/replace`, `GET /api/v1/qr/locations/resolve/{code}`, `GET /api/v1/qr/locations/{qr_id}/image`.
- **Website QR Code Generator (Admin Only)**:
  - `GET /api/v1/qr/website/config` — Public frontend URL config (blocks `localhost` in production with `503`), active canteens/categories, college logo/branding.
  - `POST /api/v1/qr/website/generate` — Generate preview & target URL (`website`, `canteen`, `category`), SVG markup + PNG base64 data URI.
  - `GET /api/v1/qr/website/download` — Download high-resolution PNG or vector SVG (`format=png|svg`).

## 6. Kitchen, Pickup, Digital POS & Queue Controls
- `GET /api/v1/kitchen/canteens/{canteen_id}/orders`, `POST /api/v1/kitchen/orders/{order_id}/{accept,start-preparing,mark-ready,report-delay,reject}`, `POST /api/v1/kitchen/items/{food_item_id}/unavailable`, `GET /api/v1/kitchen/canteens/{canteen_id}/ingredients`, `POST /api/v1/kitchen/ingredients/{inventory_item_id}/unavailable`.
- `POST /api/v1/pickup/verify`, `POST /api/v1/pickup/handover`, `GET /api/v1/pickup/board/{canteen_id}`.
- `POST /api/v1/pos/orders` (`upi_pos` / `card_pos`), `GET /api/v1/pos/orders/active`, `GET /api/v1/pos/orders/pending-counter`, `GET /api/v1/pos/orders/search`, `POST /api/v1/pos/shifts/open`, `GET /api/v1/pos/shifts/current`, `POST /api/v1/pos/shifts/close`.
- `GET /api/v1/queue/canteens/{canteen_id}`, `GET /api/v1/queue/canteens/{canteen_id}/estimate`, `PATCH /api/v1/queue/canteens/{canteen_id}/controls`, `POST /api/v1/queue/canteens/{canteen_id}/slots`.

## 7. Inventory Manager Portal & Menu Operations
- **Menu Endpoints (Manager/Admin + Inventory Manager without direct price mutation)**:
  - `POST/PATCH/DELETE /api/v1/menus/categories`, `POST/PATCH/DELETE /api/v1/menus/items` (`DELETE` hard-deletes un-ordered items after clearing cart items or safely archives `is_active=false, is_available=false` when historical orders exist), `POST /api/v1/menus/items/{item_id}/upload-image` (Pillow-validated PNG/JPEG/WEBP <= 512 KB), `POST/PATCH/DELETE /api/v1/menus/variants*`, `POST/PATCH /api/v1/menus/addons*`, `POST /api/v1/menus/items/{item_id}/addons`, `DELETE /api/v1/menus/items/{item_id}/addons/{addon_id}`, `GET/POST/PATCH/PUT/DELETE /api/v1/menus/schedules*`, `GET/POST /api/v1/menus/canteens/{canteen_id}/{export-csv,import-csv}`.
- **Inventory & Price Governance Endpoints (`/api/v1/inventory`)**:
  - `GET /dashboard`, `GET /canteens/{canteen_id}/items`, `POST /ingredients`, `PATCH /items/{inventory_item_id}`, `POST /items/{inventory_item_id}/{archive,restore,restock,purchase-price}`
  - `POST /adjustments`, `POST /wastage` (`wastage|damaged|expired`), `POST /transfers`, `GET /movements`, `GET /transfers`, `GET /alerts`
  - `GET /canteens/{canteen_id}/price-changes`, `POST /price-changes`, `POST /price-changes/{request_id}/review` (Manager/Admin only; `403` for Inventory Manager)
  - `GET/POST/PATCH /suppliers*`, `GET/POST /purchase-orders*`, `POST /purchase-orders/{po_id}/receive`, `GET/PUT /recipes/{food_item_id}`
  - `GET /canteens/{canteen_id}/audit-logs`, `GET /canteens/{canteen_id}/reports/{summary,csv,pdf}`.

## 8. Staff, Announcements, Loyalty, Reviews, Support, Kiosk, Reports & Admin
- `GET/POST/PATCH/DELETE /api/v1/staff*` (`shifts`, `attendance/{check-in,check-out,leave,leave/request,review}`, `tasks`, `activity`).
- `GET/POST/DELETE /api/v1/promotions`, `GET /api/v1/promotions/loyalty/me`, `POST /api/v1/promotions/loyalty/apply-referral`.
- `GET /api/v1/notifications/my`, `POST /api/v1/notifications/{id}/read`, `POST /api/v1/notifications/mark-all-read`, `GET/PUT /api/v1/notifications/preferences`, `POST /api/v1/notifications/push-tokens`, `GET/POST/DELETE /api/v1/notifications/announcements*`.
- `POST /api/v1/support/reviews`, `PATCH /api/v1/support/reviews/{id}/visibility`, `GET /api/v1/support/items/{id}/reviews`, `POST/GET /api/v1/support/tickets*`.
- `GET /api/v1/reports/{dashboard,export/csv,export/pdf}`.
- `GET /api/v1/kiosk/status`, `POST /api/v1/kiosk/devices`, `PATCH /api/v1/kiosk/devices/{device_id}`, `POST /api/v1/kiosk/devices/{device_id}/heartbeat`, `POST /api/v1/kiosk/orders`, `GET /api/v1/kiosk/recommendations/{canteen_id}`.
- `PUT /api/v1/admin/college`, `POST/PATCH /api/v1/admin/canteens*`, `POST/PATCH /api/v1/admin/{counters,kitchens,tables,holidays,kitchen-stations,pickup-locations}*`, `GET/POST/PATCH /api/v1/admin/users*`, `GET /api/v1/admin/{orders,audit-logs,system-events,health}`, `POST /api/v1/admin/maintenance/run` (authenticated via `CRON_SECRET` Bearer token or `super_admin`/`college_admin` JWT; runs expired OTP/refresh token/slot cleanup & inventory low-stock/expiry scan).

## 9. Real-time WebSockets (`/api/v1/ws`)
All rooms support `"ping"` keepalive messages (server replies `{"event": "pong"}`).
- `WS /api/v1/ws/orders/{order_id}?token=...&guest_token=...` — Live order status stream (customer, guest with valid `guest_token`, or canteen staff).
- `WS /api/v1/ws/kitchen/{canteen_id}?token=...` — Live kitchen queue updates (authenticated canteen staff).
- `WS /api/v1/ws/board/{canteen_id}` — Public digital pickup token board updates.
- `WS /api/v1/ws/notifications/{user_id}?token=...` — Per-user live alerts.
