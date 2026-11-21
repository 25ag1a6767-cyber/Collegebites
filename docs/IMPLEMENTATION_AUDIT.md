# CollegeBites — Complete Implementation Audit & Engineering Log

## 1. Architecture Verification
CollegeBites operates with a single FastAPI + SQLAlchemy 2 + PostgreSQL + Redis backend (`backend/`) shared across:
- Customer Website & Staff Portals (`frontend/`, React + Vite + Tailwind + TanStack Query + Zustand PWA)
- Customer Mobile App (`mobile/`, Expo Router + React Native + TypeScript)
- Real-time Kitchen Display, Cashier Digital POS, Pickup Verification Scanner, Digital Token Board, Admin Console, and Inventory Manager Portal.

All operational KPIs, order histories, inventory balances, low-stock alerts, price approvals, reports, notifications, and audits query live database records with zero fabricated/hardcoded fallback numbers.

## 2. Key Audit Findings & Fixes Implemented

### A. Strict Online-Only Policy ("NO CASH ONLY ONLINE")
- **Backend Enforcement**:
  - Blocked `"cash"` and `"pay_at_pickup"` across [`order_service.py`](../backend/app/services/order_service.py), [`pos_service.py`](../backend/app/services/pos_service.py), [`payment_service.py`](../backend/app/services/payment_service.py) (counter collect accepts `upi_pos` / `card_pos` digital settlements only), [`kiosk/routes.py`](../backend/app/api/kiosk/routes.py), and admin toggles in [`college_service.py`](../backend/app/services/college_service.py) (`400 Bad Request`).
  - Updated [`college.py`](../backend/app/models/college.py) and [`seed_service.py`](../backend/app/services/seed_service.py) defaults and added idempotent SQL enforcement in migration `3b2c4d5e7f8a` setting `cash_at_counter_enabled=false`, `pay_at_pickup_enabled=false`, `allow_cash_at_counter=false`, and `allow_pay_at_pickup=false`.
- **Frontend & Mobile Cleanup**:
  - Removed Cash at Counter and Pay at Pickup selection buttons from Web [`CheckoutPage.tsx`](../frontend/src/pages/customer/CheckoutPage.tsx), [`KioskPage.tsx`](../frontend/src/pages/kiosk/KioskPage.tsx), [`PromotionsSystemTab.tsx`](../frontend/src/pages/admin/components/PromotionsSystemTab.tsx), [`CashierPOSPage.tsx`](../frontend/src/pages/cashier/CashierPOSPage.tsx) (digital `upi_pos` / `card_pos` terminals only), and Mobile [`checkout.tsx`](../mobile/app/checkout.tsx) + onboarding copy in [`_layout.tsx`](../mobile/app/_layout.tsx).

### B. Payment Gateway Security & Real Integrations (Razorpay & Stripe)
- **Removed Client-Side Test Signing & Fallback Secrets**:
  - Removed `signHmacHex`, `hmacSha256Hex`, `mobile/src/utils/hmacSha256.ts`, `"test_mode_signature"`, `"rzp_test_secret_collegebites_local"`, and `"sk_test_collegebites_local"` from frontend and mobile bundles.
  - Added shared [`frontend/src/utils/razorpay.ts`](../frontend/src/utils/razorpay.ts) modal launcher for Checkout, Order Tracking retry, and Kiosk checkout using genuine Razorpay Checkout.js when `razorpay_key_id` is configured, and Stripe Checkout redirects via `stripe_checkout_url`.
- **Production Safety**:
  - [`RazorpayGateway`](../backend/app/integrations/razorpay_client.py) and [`StripeGateway`](../backend/app/integrations/stripe_client.py) invoke real gateway REST APIs whenever real credentials are configured, omit dummy public keys when unconfigured, and raise HTTP `503` in `ENVIRONMENT=production` if gateway credentials are missing.
- **Bug Fix**: Added missing `OrderStatusHistory` import in [`payment_service.py`](../backend/app/services/payment_service.py) (`retry_online_payment`).

### C. Production OTP Generation & Delivery Fix
- **Root Cause Found**:
  1. `auth_service.request_otp` never invoked `send_email` or `send_sms_or_whatsapp` to deliver generated OTP codes.
  2. `config.py` read `SMTP_USER`, ignoring Vercel's configured `SMTP_USERNAME` and `SMTP_SECURE`.
  3. Production (`ENVIRONMENT=production`) suppressed `dev_otp` (even with `OTP_TEST_ECHO=true`) without configured SMS credentials (`SMS_PROVIDER=log`), returning `200` with `dev_otp: null` and zero delivery.
- **Fix**:
  - Added `SMTP_USERNAME`, `SMTP_SECURE`, `effective_smtp_user`, and `effective_smtp_from` to [`config.py`](../backend/app/core/config.py) and real SSL/STARTTLS SMTP dispatch in [`email_provider.py`](../backend/app/integrations/email_provider.py).
  - Updated [`sms_provider.py`](../backend/app/integrations/sms_provider.py) so unconfigured/`log`/`none` providers fail honestly in production instead of reporting fake log delivery.
  - Updated [`auth_service.py`](../backend/app/services/auth_service.py) (`request_otp`) to dispatch email OTPs via SMTP, check user's linked email fallback if a login phone target is requested without SMS configured, and raise explicit `503` errors when neither Email SMTP nor SMS gateway can deliver in production.
  - Added Guest Email OTP support in [`CheckoutPage.tsx`](../frontend/src/pages/customer/CheckoutPage.tsx), [`mobile/app/checkout.tsx`](../mobile/app/checkout.tsx), [`orders.api.ts`](../mobile/src/api/orders.api.ts), and backend [`OrderCheckoutIn`](../backend/app/schemas/order.py).

### D. Zero Coupons Policy
- Removed coupon APIs, UI inputs, promo coupon fields, and `CAMPUS10` seed data; backend rejects non-empty `coupon_code` with `400` and migration `3b2c4d5e7f8a` deletes legacy coupon rows while preserving Loyalty Points and non-coupon Announcements/Banners.

### E. Inventory Manager Portal & Customer Menu Operations
- Extended [`InventoryItem`](../backend/app/models/inventory.py), [`WastageRecord`](../backend/app/models/inventory.py), [`InventoryAuditLog`](../backend/app/models/inventory.py), and [`PriceChangeRequest`](../backend/app/models/inventory.py) in [`inventory_service.py`](../backend/app/services/inventory_service.py) and [`InventoryPage.tsx`](../frontend/src/pages/inventory/InventoryPage.tsx):
  - Dashboard KPIs from live database records, full item metadata CRUD with field-level `InventoryAuditLog`, archive/restore guarded by `409` on active orders, negative-stock rejection (`400`), damaged/expired/wastage loss separation, 1-click restock, immediate purchase cost updates, approval-gated selling price requests (`403` for `inventory_manager` on approval or direct `PATCH /menus/items/{id}` `base_price` alteration; historical `OrderItem` prices immutable), and CSV/PDF inventory reports.
  - Enabled `ROLE_INVENTORY_MANAGER` customer menu management (`Customer Menu` tab in `InventoryPage.tsx`, `POST/PATCH/DELETE /menus/categories`, `POST/PATCH /menus/items`, plus Pillow-validated image uploads via `POST /menus/items/{id}/upload-image` stored in widened `TEXT` `food_images.image_url`).

### F. Website QR Code Generator Module
- Added `PUBLIC_FRONTEND_URL` validation in [`config.py`](../backend/app/core/config.py) and [`website_qr_service.py`](../backend/app/services/website_qr_service.py) (strictly blocks `localhost` URLs in production with `503`).
- Implemented `GET /api/v1/qr/website/config`, `POST /api/v1/qr/website/generate`, and `GET /api/v1/qr/website/download` supporting full-website, specific-canteen, and category menu URLs, PNG + crisp vector SVG export, optional college branding/logo overlay, and printable `"Scan to Order Food"` poster UI in [`WebsiteQrTab.tsx`](../frontend/src/pages/admin/components/WebsiteQrTab.tsx) + deep-link hydration in [`HomePage.tsx`](../frontend/src/pages/customer/HomePage.tsx) and [`App.tsx`](../frontend/src/App.tsx).
- Completely separate from order pickup QR tokens (`order_qr_codes`) and table/counter location QR codes (`location_qr_codes`).

### G. Production Hardening
- Gated `DEMO_USERS` quick-login list in [`AuthPage.tsx`](../frontend/src/pages/auth/AuthPage.tsx) behind `import.meta.env.DEV` (verified completely absent from Vite production JS bundle).
- Guarded [`seed_demo.py`](../backend/app/cli/seed_demo.py) CLI against running when `ENVIRONMENT=production`.
