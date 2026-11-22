# CollegeBites — Production Deployment & Operations Guide

## 1. Architecture Summary
CollegeBites runs as one shared system across:
- **Customer Web & Staff Portals (`frontend/`)**: React 18 + Vite + TypeScript + Tailwind CSS (PWA with `manifest.webmanifest` and `sw.js`).
- **Customer Mobile App (`mobile/`)**: Expo Router + React Native + TypeScript (Android, iOS, and Web export).
- **Backend API & WebSockets (`backend/`)**: FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL + Redis + Celery (deployed via Vercel Python Serverless Runtime in `vercel.json`).

## 2. Environment Variables Required in Production

### Required Core Secrets
- `ENVIRONMENT=production`
- `DATABASE_URL` / `DATABASE_URL_UNPOOLED` (PostgreSQL SSL connection string, e.g., Neon Postgres)
- `SECRET_KEY` (64+ random character JWT signing key)
- `QR_SIGNING_SECRET` (64+ random character HMAC-SHA256 key for pickup QRs & guest access tokens)
- `PUBLIC_BASE_URL=https://collegebites-alpha.vercel.app`
- `PUBLIC_FRONTEND_URL=https://collegebites-alpha.vercel.app`
- `CORS_ORIGINS=["https://collegebites-alpha.vercel.app"]`

### Payment Gateways (Strict Online-Only Policy)
Live online checkout requires configured gateway credentials (`503 Service Unavailable` returned cleanly if unconfigured in production):
- **Razorpay**: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `RAZORPAY_TEST_MODE=false` (or test keys `rzp_test_*` when testing in Razorpay Sandbox — note real REST API calls still run whenever credentials are set).
- **Stripe**: `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` (served to Web Elements & Mobile PaymentSheet via `/api/v1/payments/stripe/config`), `STRIPE_WEBHOOK_SECRET`, `STRIPE_TEST_MODE=false`.
- **Redis**: Set `REDIS_URL` (or Vercel `KV_URL`/`UPSTASH_REDIS_URL`) for multi-instance cache/Celery coordination; non-authoritative slot/queue cache writes degrade cleanly to PostgreSQL `FOR UPDATE` if Redis is unavailable, and development falls back to `memory://` FakeRedis when local Redis is offline.
- Webhook URLs to register in merchant dashboards:
  - `POST https://<domain>/api/v1/payments/razorpay/webhook`
  - `POST https://<domain>/api/v1/payments/stripe/webhook`

### OTP & Notifications (SMTP Email + SMS)
- **Email OTP (SMTP)**: Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME` (or `SMTP_USER`), `SMTP_PASSWORD`, `SMTP_SECURE` (`true` for port `465` SSL / `false` for STARTTLS), `SMTP_FROM`.
- **SMS / WhatsApp OTP**: Set `SMS_PROVIDER=twilio` (with `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`) or `SMS_PROVIDER=webhook` (`SMS_WEBHOOK_URL`). If no SMS provider is configured in production, SMS OTP requests return HTTP `503` instead of silently faking delivery.

### Mobile Build Configuration (`mobile/`)
- Set `EXPO_PUBLIC_API_URL=https://collegebites-alpha.vercel.app/api/v1` (or `mobile/app.json` `expo.extra.apiUrl`) before building EAS / native binaries (`npx eas build --platform all`). Note that `@stripe/stripe-react-native` native PaymentSheet requires a custom Expo development client or EAS build (Android APK/AAB or iOS IPA) rather than stock Expo Go.

## 3. Deployment Steps (Vercel + Neon Postgres)

1. **Pre-Deploy Database Migration**:
   ```bash
   cd backend
   alembic upgrade head
   ```
   Migration head `3b2c4d5e7f8a` creates `inventory_audit_logs` and `price_change_requests`, widens `food_images.image_url` to `TEXT`, deletes legacy coupon records, disables legacy cash/pay-at-pickup database flags, and seeds `qr:website_manage` + `menu:manage_inventory` permissions.
2. **Production Initial Admin Bootstrap** (only when creating a clean production database; `seed_demo` blocks execution in `ENVIRONMENT=production`):
   ```bash
   python -m app.cli.create_admin --email admin@yourcollege.edu --name "College Super Admin"
   ```
3. **Frontend & Backend Verification**:
   - Build and check zero dev-account leaks: `cd frontend && npx tsc --noEmit && npm test -- --run && npm run build`
   - Run full backend pytest suite against PostgreSQL (`TEST_DATABASE_URL`).
4. **Deploy to Vercel Production**:
   ```bash
   vercel deploy --prod --yes
   ```
5. **Post-Deploy Verification**:
   - Verify `GET /health` returns `200 OK`
   - Verify `GET /api/v1/canteens` returns seeded canteens with `allow_cash_at_counter=false` and `allow_pay_at_pickup=false`
   - Verify `GET /api/v1/qr/website/download?target_type=website&format=svg` (as `college_admin`) embeds the configured HTTPS URL (never `localhost`)
   - Confirm coupon endpoints return `404`/`405`.

## 4. Backup & Rollback Procedure
- Create a Neon branch snapshot or `pg_dump --format=custom --no-owner "$DATABASE_URL_UNPOOLED"` prior to running Alembic migrations.
- Roll back deployments via `vercel rollback <deployment-url>` and schema if necessary via `alembic downgrade -1`.
