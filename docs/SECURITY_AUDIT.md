# CollegeBites — Security Audit Report

## 1. Authentication, Session & RBAC Controls
- **Password Hashing:** Strong salted password hashing (`passlib` / `bcrypt`).
- **JWT + Refresh Token Rotation:** Short-lived access tokens paired with DB-backed refresh sessions (`UserSession`), replay revocation, and explicit session logout/revocation endpoints.
- **Role-Based Access Control (9 Roles):** `super_admin`, `college_admin`, `canteen_manager`, `cashier`, `kitchen_staff`, `inventory_manager`, `pickup_staff`, `food_safety_inspector`, `customer`.
- **Canteen Scope Isolation:** `enforce_canteen_scope` and `scoped_canteen_for_principal` lock counter-assigned staff to their assigned canteen while permitting college-wide oversight for `super_admin`, `college_admin`, and campus-wide `food_safety_inspector`.
- **Verified Negative Access Tests:**
  - Customers receive HTTP `403 Forbidden` on `/api/v1/ai-assistant/ask`, `/api/v1/notifications/system-maintenance`, `/api/v1/food-safety/*`, `/api/v1/reordering/*`, and `/api/v1/forecasting/*`.
  - Inventory managers cannot approve selling price changes or auto-approve purchase orders.

## 2. Payment, Financial & No-Refund Security
- **Server-Side Pricing Authority:** Cart/order totals are computed strictly from database `FoodItem.base_price`, `FoodVariant.price_delta`, and `FoodAddon.price` with zero client price trust, zero discounts, and zero extra checkout taxes.
- **Cryptographic Webhook & Callback Verification:**
  - Razorpay: HMAC-SHA256 verification of `razorpay_order_id|razorpay_payment_id` and `X-Razorpay-Signature` webhook verification.
  - Stripe: Official SDK `PaymentIntent`/`CheckoutSession` verification and `Stripe-Signature` HMAC verification.
  - Amount & currency mismatch detection creates `PaymentReconciliation` discrepancy records and high-severity `SecurityAlert` rows.
  - Duplicate payment references and late captures on terminal orders are blocked (`409`), logged as `late_capture_conflict`, and trigger critical `duplicate_payment_investigation` alerts.
- **No Refunds Policy:** Zero refund APIs exist; confirmed payments are preserved in immutable payment/ledger tables.

## 3. AI Assistant & Procurement Governance Guardrails
- **Zero SQL Generation / Injection Protection:** AI Canteen Assistant invokes ONLY parameterized, role-checked Python service functions (`report_service`, `queue_service`, `inventory_service`, `food_safety_service`, `forecast_service`, `traceability_service`, `production_service`).
- **Read-Only Write Blocker:** Prompts attempting PO approval, money transfer, refunds, price/menu/inventory modification, payment confirmation, or system broadcasts are intercepted before tool execution, marked `policy_restricted`, refused cleanly, and recorded in `AIAssistantAuditLog` (`blocked_action_attempted=true`).
- **Automated Reordering Guard:** Draft Purchase Orders (`status="draft"`) require explicit human manager/admin approval and verified GRN before inventory updates.

## 4. Transport, Headers, PII Masking & Rate Limiting
- **Security Headers:** `SecurityHeadersMiddleware` sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and `Strict-Transport-Security` (in production).
- **Correlation & Safe Logging:** `X-Request-ID` propagated cleanly on every HTTP request/response without logging JWTs, passwords, webhook secrets, or raw PII.
- **PII Masking in Notification Delivery Logs:** Email addresses (`a***@collegebites.edu`) and mobile numbers (`+91******3210`) are masked in `NotificationDelivery` records.
- **Rate Limiting:** Pure ASGI `PureASGIRateLimitMiddleware` + SlowAPI protects authentication, OTP, checkout, and public endpoints against brute force and flood bursts.
