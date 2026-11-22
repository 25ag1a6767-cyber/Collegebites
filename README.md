# CollegeBites

**Smart College Canteen Management, Food Ordering, Payment, QR Token & Operations Platform**

Built for **one college** supporting multiple operational locations (Main Canteen, Snacks & Bakery Counter, Juice Bar, Food Court, multiple Kitchens, Pickup Counters, Tables, and optional Self-Service Kiosks).

## Core End-to-End Workflow
`Customer / Guest / Table QR Scan` → `Backend Price & Capacity Validation` → `Razorpay / Stripe / Counter Payment` → `Backend Payment Verification` → `Unique Pickup Token (A001)` → `HMAC-Signed QR Code` → `Complete Printable Receipt (58mm / 80mm / A4 PDF / ESC-POS)` → `Kitchen Display System (KDS)` → `Live Digital Token Board` → `QR Pickup Verification` → `Atomic Handover (No Duplicate Collection)` → `COMPLETED`

> **Strict No-Refund Policy**: CollegeBites never exposes refund APIs, buttons, or balances. Cancelled/rejected paid orders retain immutable payment transaction records; exceptional adjustments are handled outside the app by the college finance office.

## Repository Layout
- `backend/` — FastAPI, Pydantic v2, SQLAlchemy 2 (PostgreSQL), Alembic migrations, Redis, Celery, WebSockets, ReportLab PDF, ESC/POS builder, Stripe & Razorpay SDKs, Pytest suite (`test_phase1`..`test_phase14`, 33 tests).
- `frontend/` — React, TypeScript, Vite, Tailwind CSS, TanStack Query, Zustand, Recharts, Stripe Elements (`@stripe/stripe-js`), installable PWA (`manifest.webmanifest`, `sw.js`, mobile bottom navigation bar), WebUSB/WebSerial/Browser thermal printing, Camera QR scanner (`/scan`).
- `mobile/` — React Native, Expo SDK 52, TypeScript, Expo Router (`collegebites://` deep linking + `/scan/[code]`), SecureStore, Expo Camera QR scanner, Expo Notifications, `@stripe/stripe-react-native` PaymentSheet, EAS Android APK & iOS builds.
- `e2e/` — Full-stack Chromium Playwright E2E suite (`collegebites.e2e.mjs`).
- `docs/` — [Architecture](docs/ARCHITECTURE.md), [Database Schema](docs/DATABASE_SCHEMA.md), [API Documentation](docs/API_DOCUMENTATION.md), [Deployment Guide](docs/DEPLOYMENT_GUIDE.md), [Implementation Audit](docs/IMPLEMENTATION_AUDIT.md), [Security](docs/SECURITY.md), [Hardware & Credentials](docs/HARDWARE_AND_CREDENTIALS.md).

## Quick Verification Commands
```bash
# Backend migrations + all 14 phase test suites (33 tests; requires PostgreSQL; set TEST_DATABASE_URL)
cd backend && alembic upgrade head && pytest -v

# Frontend typecheck, unit tests & production PWA bundle
cd frontend && npm run typecheck && npm run test && npm run build

# Mobile typecheck & Android/iOS/Web Metro export
cd mobile && npm run typecheck && npx expo export --platform all

# Full-stack browser E2E against local backend + Vite frontend
cd e2e && node collegebites.e2e.mjs
```
