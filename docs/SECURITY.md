# CollegeBites Security Posture

- **Password Hashing**: Argon2id via Passlib.
- **Session & Token Rotation**: Short-lived JWT access tokens + rotating SHA-256 hashed refresh tokens with reuse detection that revokes compromised token families.
- **RBAC**: Server-side role & permission verification on every protected route (`super_admin`, `college_admin`, `canteen_manager`, `cashier`, `kitchen_staff`, `inventory_manager`, `pickup_staff`, `customer`), including canteen-scoped enforcement.
- **Server-Side Pricing & Checkout**: Frontend prices/totals/discounts are never trusted; all pricing, coupon rules, stock/availability, and capacity are recalculated inside PostgreSQL transactions.
- **Payment & Webhook Integrity**: Razorpay HMAC-SHA256 signature verification, webhook event deduplication (`uq_webhook_provider_event_id`), and strictly NO refund endpoints/tables.
- **QR & Pickup Token Security**: High-entropy random tokens HMAC-signed with `QR_SIGNING_SECRET`, hashed with SHA-256 at rest, containing zero passwords, payment credentials, or DB PK authorization. Separate verification vs row-locked atomic handover prevents duplicate collection.
- **Guest Privacy**: Masked mobile numbers on printed slips, zero PII on public TV token boards, and hashed `guest_access_token` authorization on guest order endpoints.
- **HTTP Security Headers & Rate Limiting**: `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy`, `slowapi` rate limiting, and parameterized SQLAlchemy 2 queries preventing SQL injection.
