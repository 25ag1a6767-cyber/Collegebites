# CollegeBites

**Smart College Canteen Management, Food Ordering, Payment, QR Token & Operations Platform**

Built for **one college** supporting multiple operational locations (Main Canteen, Snacks & Bakery Counter, Juice Bar, Food Court, multiple Kitchens, Pickup Counters, Tables, and optional Self-Service Kiosks).

## Core End-to-End Workflow
`Customer / Guest / Table QR Scan` → `Backend Price & Capacity Validation` → `Razorpay / Stripe / Counter Payment` → `Backend Payment Verification` → `Unique Pickup Token (A001)` → `HMAC-Signed QR Code` → `Complete Printable Receipt (58mm / 80mm / A4 PDF / ESC-POS)` → `Kitchen Display System (KDS)` → `Live Digital Token Board` → `QR Pickup Verification` → `Atomic Handover (No Duplicate Collection)` → `COMPLETED`

> **Strict No-Refund Policy**: CollegeBites never exposes refund APIs, buttons, or balances. Cancelled/rejected paid orders retain immutable payment transaction records; exceptional adjustments are handled outside the app by the college finance office.

## Repository Layout
- `backend/` — FastAPI, Pydantic v2, SQLAlchemy 2 (PostgreSQL), Alembic migrations, Redis, Celery, WebSockets, ReportLab PDF, ESC/POS builder, Pytest suite (`test_phase1`..`test_phase12`).
- `frontend/` — React, TypeScript, Vite, Tailwind CSS, TanStack Query, Zustand, Recharts, installable PWA (`manifest.webmanifest`, `sw.js`, mobile bottom navigation bar), WebUSB/WebSerial/Browser thermal printing, Camera QR scanner (`/scan`).
- `mobile/` — React Native, Expo SDK 52, TypeScript, Expo Router (`collegebites://` deep linking + `/scan/[code]`), SecureStore, Expo Camera QR scanner, Expo Notifications, EAS Android APK & iOS builds.
- `docs/` — [Architecture](docs/ARCHITECTURE.md), [Database Schema](docs/DATABASE.md), [API Reference](docs/API.md), [Deployment Guide](docs/DEPLOYMENT.md), [Security](docs/SECURITY.md), [Hardware & Credentials](docs/HARDWARE_AND_CREDENTIALS.md).

## Quick Verification Commands
```bash
# Backend migrations + all 12 phase test suites (requires PostgreSQL; set TEST_DATABASE_URL)
cd backend && alembic upgrade head && pytest -v

# Frontend typecheck, unit tests & production PWA bundle
cd frontend && npm run typecheck && npm run test && npm run build

# Mobile typecheck & Android/iOS/Web Metro export
cd mobile && npm run typecheck && npx expo export --platform all
```
