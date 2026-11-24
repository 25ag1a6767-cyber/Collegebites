# CollegeBites — Production Deployment & Operations Guide

## 1. Architecture Summary
CollegeBites runs as one shared system across:
- **Customer Web & Staff Portals (`frontend/`)**: React 18 + Vite + TypeScript + Tailwind CSS (PWA with `manifest.webmanifest` and `sw.js`).
- **Customer Mobile App (`mobile/`)**: Expo Router + React Native + TypeScript (Android, iOS, and Web export).
- **Backend API & WebSockets (`backend/`)**: FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL + Redis + Celery (deployed via Vercel Python Serverless Runtime in `vercel.json`).

## 2. Production Hosting Checklist (Razorpay Only + Live OTP)

### Required Core Secrets
- `ENVIRONMENT=production`
- `DATABASE_URL` / `DATABASE_URL_UNPOOLED` (PostgreSQL SSL connection string, e.g., Neon Postgres `-pooler` host)
- `SECRET_KEY` (64+ random character JWT & OTP HMAC signing key)
- `QR_SIGNING_SECRET` (64+ random character HMAC-SHA256 key for pickup QRs & guest access tokens)
- `PUBLIC_BASE_URL=https://collegebites-alpha.vercel.app`
- `PUBLIC_FRONTEND_URL=https://collegebites-alpha.vercel.app`
- `CORS_ORIGINS=https://collegebites-alpha.vercel.app`
- `CRON_SECRET` (random 16+ char secret for scheduled maintenance `POST /api/v1/admin/maintenance/run`)

### Razorpay Payment Gateway (Sole Online Gateway)
Razorpay is the **only** supported online payment gateway (`503 Service Unavailable` returned cleanly if unconfigured in production):
- **Server-Side Environment Variables (Backend / Vercel Serverless ONLY — NEVER expose secrets to frontend):**
  - `RAZORPAY_KEY_ID` (`rzp_live_...` in production, or `rzp_test_...` in staging)
  - `RAZORPAY_KEY_SECRET` (**strictly server-side secret**)
  - `RAZORPAY_WEBHOOK_SECRET` (**strictly server-side webhook HMAC secret**)
  - `RAZORPAY_TEST_MODE=false` in live production (`true` in sandbox)
- **Optional Public Frontend Variable:**
  - `VITE_RAZORPAY_KEY_ID` (public Key ID only; backend also returns `razorpay_key_id` on Razorpay order payloads and `GET /api/v1/payments/razorpay/config`)
- **Razorpay Dashboard Webhook Registration:**
  - Endpoint: `POST https://collegebites-alpha.vercel.app/api/v1/payments/razorpay/webhook`
  - Subscribed Events: `payment.captured`, `order.paid`, `payment.failed`
  - Secret: Must match `RAZORPAY_WEBHOOK_SECRET`

### Live OTP Authentication & Transactional Delivery
CollegeBites enforces **real OTP delivery only** (zero hardcoded/static OTPs, zero `dev_otp` browser responses, zero plaintext OTP logging):
- `OTP_EXPIRY_SECONDS=300` (5-minute validity)
- `OTP_RESEND_COOLDOWN_SECONDS=60` (60-second resend cooldown)
- `OTP_MAX_ATTEMPTS=5` (invalidates code after 5 failed attempts)
- `OTP_PROVIDER=smtp` (or `resend` / `sendgrid`; auto-detected when left blank)
- `OTP_EMAIL_FROM=noreply@yourdomain.edu` (verified sender address)
- `OTP_SMS_ENABLED=false` (keep `false` until SMS provider + Indian DLT template/entity registration are configured)
- **Transactional Email Credentials (configure one):**
  - **SMTP**: `SMTP_HOST`, `SMTP_PORT` (`587` STARTTLS or `465` SSL), `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SECURE`
  - **Resend API**: `RESEND_API_KEY` + `OTP_EMAIL_FROM`
  - **SendGrid API**: `SENDGRID_API_KEY` + `OTP_EMAIL_FROM`
- **SMS OTP Credentials (only when `OTP_SMS_ENABLED=true`):**
  - `SMS_PROVIDER=twilio` with `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, or `SMS_PROVIDER=webhook` with `SMS_WEBHOOK_URL`

### Redis & Mobile Build Configuration
- **Redis**: Set `REDIS_URL` (or Vercel `KV_URL`/`UPSTASH_REDIS_URL`) for multi-instance cache/Celery coordination.
- **Mobile (`mobile/`)**: Set `EXPO_PUBLIC_API_URL=https://collegebites-alpha.vercel.app/api/v1` before running `npx eas build --platform all`.

## 3. Safe Deployment Steps (Vercel + Neon Postgres)

1. **Pre-Deploy Database Backup & Migration**:
   ```bash
   pg_dump --format=custom --no-owner "$DATABASE_URL_UNPOOLED" -f backup_pre_rzp_otp.dump
   cd backend
   alembic upgrade head
   ```
   Migration head `f6a7b8c9d0e1` (`f6a7b8c9d0e1_razorpay_only_and_live_otp.py`, chaining off `e5f6a7b8c9d0`) drops deprecated `college_settings.stripe_enabled` (preserving 100% of historical payment/transaction/reconciliation rows), adds `receipt_print_jobs.job_type` (`customer_receipt` vs `kot`), and adds live OTP security columns (`user_id`, `channel`, `provider`, `ip_address`, `resend_available_at`, `consumed_at`, `invalidated_at`).
2. **Frontend & Backend Verification**:
   - `cd frontend && npm run typecheck && npm run test && npm run build`
   - `cd mobile && npm run typecheck`
   - `cd backend && pytest`
3. **Deploy & Post-Deploy Smoke Checks**:
   - Verify `GET /health` returns `200 OK`
   - Verify `GET /api/v1/payments/razorpay/config` returns `configured: true` without exposing secrets
   - Verify `GET /api/v1/auth/otp/capabilities` reports `email_otp_enabled: true` once SMTP/Resend/SendGrid is configured.
