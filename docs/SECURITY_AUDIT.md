# CollegeBites — Security Audit Report

## 1. Authentication, Session & RBAC Controls
- **Password Hashing:** Strong salted password hashing (`passlib` / `bcrypt`).
- **JWT + Refresh Token Rotation:** Short-lived access tokens paired with DB-backed refresh sessions (`UserSession`), replay revocation, and explicit session logout/revocation endpoints.
- **Role-Based Access Control (9 Roles):** `super_admin`, `college_admin`, `canteen_manager`, `cashier`, `kitchen_staff`, `inventory_manager`, `pickup_staff`, `food_safety_inspector`, `customer`.
- **Canteen Scope Isolation:** `enforce_canteen_scope` and `scoped_canteen_for_principal` lock counter-assigned staff to their assigned canteen while permitting college-wide oversight for `super_admin`, `college_admin`, and campus-wide `food_safety_inspector`.
- **Verified Negative Access Tests (Phases 35–37):**
  - Customers receive HTTP `403 Forbidden` on `/api/v1/ai-assistant/ask`, `/api/v1/notifications/system-maintenance`, `/api/v1/food-safety/*`, `/api/v1/reordering/*`, and `/api/v1/forecasting/*`.
  - Unauthenticated and customer calls to `GET /api/v1/queue/canteens/{canteen_id}` receive aggregate queue metrics only (`active_orders_queue: []`, `delayed_orders: []`), eliminating customer-name PII exposure.
  - Inventory managers cannot approve selling price changes, cannot create pre-approved/ordered POs (`403`), cannot transition unapproved POs directly to `"ordered"` (`403`), and cannot self-verify recipes (`403`).
  - Canteen managers cannot create or edit global (`canteen_id=None`) food safety checklist templates (`403`).
  - Live OTP security enforced: 6-digit CSPRNG codes stored only as HMAC-SHA256 digests (`OTP_TEST_ECHO`/`dev_otp` removed), 60s resend cooldown, 5-attempt lockout, 5-minute TTL, single-use replay protection, and destination/IP/account rate limits.

## 2. Payment, Financial & No-Refund Security
- **Server-Side Pricing Authority:** Cart/order totals are computed strictly from database `FoodItem.base_price`, `FoodVariant.price_delta`, and `FoodAddon.price` with zero client price trust, zero discounts, and zero extra checkout taxes.
- **Cryptographic Webhook & Callback Verification (Razorpay Only):**
  - Razorpay: Server-side HMAC-SHA256 verification of `razorpay_order_id|razorpay_payment_id`, gateway payment status/amount/currency validation when live credentials are active, and `X-Razorpay-Signature` webhook verification (`payment.captured`, `order.paid`, `payment.failed`).
  - Amount & currency mismatch detection creates `PaymentReconciliation` discrepancy records and high-severity `SecurityAlert` rows.
  - Duplicate payment references and late captures on terminal orders are blocked (`409`), logged as `late_capture_conflict`, and trigger critical `duplicate_payment_investigation` alerts.
- **No Refunds Policy:** Zero refund APIs exist; confirmed payments are preserved in immutable payment/ledger tables.

## 3. AI Assistant & Procurement Governance Guardrails
- **Zero SQL Generation / Injection Protection:** AI Canteen Assistant invokes ONLY parameterized, role-checked Python service functions (`report_service`, `queue_service`, `inventory_service`, `food_safety_service`, `forecast_service`, `traceability_service`, `production_service`).
- **Read-Only Write Blocker & Role-Filtered Outputs:** Prompts attempting PO creation/approval, money transfer, refunds, order/batch cancellation, menu/user deactivation, recipe/price/inventory modification, recall approvals, payment confirmation, broadcasts, or SQL commands are intercepted before tool execution (`policy_restricted`, `blocked_action_attempted=true`). Non-finance roles (`kitchen_staff`, `food_safety_inspector`) never receive `₹` revenue or financial loss totals from `top_items` or `wastage_report`, and `food_safety_inspector` cannot query demand forecasts.
- **Automated Reordering Guard:** Draft Purchase Orders (`status="draft"`) are created atomically in a single DB transaction and require explicit human manager/admin approval and verified GRN before inventory updates.

## 4. Transport, Headers, PII Masking & Rate Limiting
- **Security Headers:** `SecurityHeadersMiddleware` sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Permissions-Policy`.
- **Unified Correlation & Safe Logging:** `RequestObservabilityMiddleware` establishes a single canonical `X-Request-ID` propagated through ASGI scope state, response headers, `contextvars.ContextVar`, and all JSON/text log records (eliminating duplicate IDs and duplicate timing headers) without logging JWTs, passwords, OTPs, webhook secrets, or raw PII.
- **PII Masking in Notification Delivery Logs:** Email addresses (`a***@collegebites.edu`) and mobile numbers (`+91******3210`) are masked in `NotificationDelivery` records.
- **Rate Limiting:** Pure ASGI `PureASGIRateLimitMiddleware` + SlowAPI protects authentication, OTP, checkout, and public endpoints against brute force and flood bursts.
