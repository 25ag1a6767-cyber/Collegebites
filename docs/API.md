# CollegeBites API Documentation

Base URL: `/api/v1` (interactive OpenAPI docs served at `/docs` and `/redoc`).

## Authentication & RBAC (`/auth`)
- `POST /auth/register` — Universal customer registration (students, faculty, visitors).
- `POST /auth/login` — Email/phone + password login returning JWT access token + rotating refresh token.
- `POST /auth/refresh` — Refresh token rotation with reuse detection.
- `POST /auth/logout` — Revoke current session and refresh tokens.
- `POST /auth/otp/request` & `POST /auth/otp/verify` — 6-digit OTP request & verification for guest checkout or phone verification.
- `GET /auth/me` — Current authenticated user profile, roles, and permissions.

## Canteens & Administration (`/canteens`, `/admin`)
- `GET /canteens/college` — College branding, tax defaults, kiosk toggle, cancellation/payment policy text.
- `GET /canteens`, `GET /canteens/{id_or_slug}` — Live canteen status, crowd level (`LOW..TEMPORARILY_UNAVAILABLE`), ETA, counters, kitchens, tables, hours, holidays.
- `PUT /admin/college`, `POST /admin/canteens`, `PATCH /admin/canteens/{id}`, `POST /admin/canteens/{id}/counters|kitchens|tables`, `PUT /admin/canteens/{id}/hours`, `POST /admin/holidays`
- `GET /admin/users`, `POST /admin/users/staff`, `PATCH /admin/users/{id}/roles`, `GET /admin/audit-logs`, `GET /admin/health`

## Menus & Customers (`/menus`, `/customers`)
- `GET /menus/canteens/{id}/categories`, `POST/PATCH /menus/categories`
- `GET /menus/canteens/{id}/items` — Search, category, veg/non-veg, price range, featured/popular/special/recommended, sort (`popularity`, `price_asc`, `price_desc`, `rating`).
- `POST/PATCH /menus/items`, `GET /menus/canteens/{id}/export-csv`, `POST /menus/canteens/{id}/import-csv`
- `GET/PATCH /customers/profile`, `POST/DELETE /customers/favourites/{food_item_id}`

## QR Location Ordering, Cart & Checkout (`/qr`, `/carts`, `/orders`)
- `GET /qr/locations/resolve/{code}` — Identify canteen/counter/table from permanent QR; `POST /qr/locations`, `POST /qr/locations/{id}/revoke|replace`, `GET /qr/locations/{id}/image`
- `GET /carts`, `POST /carts/items`, `PATCH /carts/items/{id}`, `POST /carts/coupon`
- `GET /orders/slots/{canteen_id}`, `POST /orders/checkout`, `GET /orders/my`, `GET /orders/{id_or_number}`, `POST /orders/{id}/cancel`

## Payments — NO REFUNDS (`/payments`)
- `POST /payments/razorpay/verify` — Verifies HMAC payment signature on backend, confirms order, atomically generates token + QR + receipt.
- `POST /payments/razorpay/webhook` — Verifies `X-Razorpay-Signature`, handles idempotent capture/failure.
- `POST /payments/razorpay/fail` — Marks failed payment and releases reserved slot.
- `POST /payments/counter/collect` — Authorized cashier confirms cash/POS payment.
- `POST /payments/reconcile`, `GET /payments/reconciliations`
- **No refund endpoints exist.**

## Tokens, QR, Receipts & Printing (`/tokens`, `/printing`)
- `GET /tokens/receipts/{order_id_or_number}` — Complete receipt JSON snapshot + base64 QR.
- `GET /tokens/receipts/{order_id_or_number}/pdf?format=a4|80mm&reprint=false` — Downloadable ReportLab PDF.
- `GET /tokens/receipts/{order_id_or_number}/qr.png` — Scannable QR PNG.
- `GET /printing/receipts/{order_id_or_number}/escpos?width=58mm|80mm` — Base64 ESC/POS thermal command bytes.
- `POST /printing/receipts/{order_id_or_number}/print`, `POST /printing/jobs/{id}/retry`, `GET /printing/history/{order_id_or_number}`

## Operations: Kitchen, Pickup, Digital Board, POS (`/kitchen`, `/pickup`, `/pos`)
- `GET /kitchen/canteens/{id}/orders`, `POST /kitchen/orders/{id}/accept|start-preparing|mark-ready|report-delay`, `POST /kitchen/items/{id}/unavailable`
- `POST /pickup/verify` — Validates QR/manual token/order number (separate from handover).
- `POST /pickup/handover` — Row-locked atomic handover (`COMPLETED`); rejects duplicate collection with `409`.
- `GET /pickup/board/{canteen_id}` — Public TV display board data without PII.
- `POST /pos/orders`, `GET /pos/orders/search`, `POST /pos/shifts/open|close`, `GET /pos/shifts/current`

## Queue, Inventory, Staff, Promotions, Notifications, Support, Reports, Kiosk
- `/queue/canteens/{id}`, `/queue/canteens/{id}/estimate`, `/queue/canteens/{id}/controls`, `/queue/canteens/{id}/slots`
- `/inventory/suppliers`, `/inventory/canteens/{id}/items`, `/inventory/ingredients`, `/inventory/recipes/{food_item_id}`, `/inventory/purchase-orders`, `/inventory/adjustments`, `/inventory/wastage`, `/inventory/transfers`, `/inventory/canteens/{id}/alerts`
- `/staff`, `/staff/shifts`, `/staff/attendance/check-in|check-out|leave`, `/staff/tasks`, `/staff/activity`
- `/promotions`, `/promotions/coupons`, `/promotions/loyalty/me`, `/promotions/loyalty/apply-referral`
- `/notifications/my`, `/notifications/{id}/read`, `/notifications/preferences`, `/notifications/announcements`
- `/support/reviews`, `/support/tickets`, `/support/tickets/{id}/assign|messages|resolve`
- `/reports/dashboard`, `/reports/export/csv`, `/reports/export/pdf`
- `/kiosk/status`, `/kiosk/devices`, `/kiosk/orders`, `/kiosk/recommendations/{canteen_id}`
- WebSockets: `/api/v1/ws/orders/{order_id}`, `/api/v1/ws/kitchen/{canteen_id}`, `/api/v1/ws/board/{canteen_id}`
