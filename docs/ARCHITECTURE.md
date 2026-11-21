# CollegeBites Architecture

## 1. System Overview
CollegeBites is a modular monolith platform built for **one college** with multiple operational locations (Main Canteen, Snacks Counter, Juice Counter, Bakery Counter, Food Court, multiple Kitchens, Pickup Counters, Tables, and optional Self-Service Kiosks).

## 2. Core Principles
1. **Backend Source of Truth**: Every price, variant surcharge, add-on price, loyalty redemption, tax, slot capacity, payment status, pickup token, QR verification, and handover state transition is computed and validated strictly on the backend.
2. **Strict No-Refund Model**: CollegeBites never exposes refund endpoints, refund workflows, or refund balances. Cancelled or rejected paid orders retain their immutable payment transaction record; any exceptional financial adjustment occurs outside the software via the college finance office.
3. **Payment-Before-Token**: Pickup tokens, QR verification codes, and paid receipts are created ONLY inside an atomic database transaction AFTER backend payment confirmation (Razorpay signature/API verification, Razorpay HMAC webhook, or Cashier counter payment authorization).
4. **Atomic Concurrency Safety**:
   - Pickup token generation locks `order_token_sequences` with `SELECT ... FOR UPDATE`.
   - Pickup slot reservations lock `pickup_slots` + Redis capacity counters.
   - Handover locks `orders` with `SELECT ... FOR UPDATE` + unique constraint on `order_handover_records(order_id)` so duplicate collection is impossible.
   - Inventory deduction records idempotent `stock_movements`.
5. **Immutable Historical Receipts**: Receipts snapshot college metadata, canteen/counter details, masked customer info, every ordered item, variant, customizations, add-ons, unit price, line total, tax, discount, and total paid at order creation.

## 3. Application Topology
- **Backend (`backend/`)**: FastAPI + Pydantic v2 + SQLAlchemy 2 + PostgreSQL + Alembic + Redis + Celery + WebSockets.
- **Web App (`frontend/`)**: React + TypeScript + Vite + Tailwind CSS + shadcn/ui components + React Router + TanStack Query + Zustand + Axios + React Hook Form + Zod + Recharts + Framer Motion.
- **Mobile App (`mobile/`)**: React Native + Expo + TypeScript + Expo Router + TanStack Query + Zustand + SecureStore + Expo Camera + Expo Notifications.

## 4. End-to-End Core Flow
```
Customer / Guest / QR Scan / Walk-in POS
  -> Cart & Server-Side Pricing Calculation
  -> Slot & Stock & Opening Hours Validation
  -> Pending Order + Payment Request (Razorpay or Cash at Counter)
  -> Backend Payment Verification / Webhook Signature Verification
  -> Atomic Order Confirmation + Unique Pickup Token + Secure Signed QR + Complete Receipt Snapshot
  -> Real-time WebSocket Push -> Kitchen Display System (KDS)
  -> Kitchen: ACCEPTED -> PREPARING -> READY -> Live Token Display Board
  -> Pickup Counter: Scan QR or Manual Token -> Verify Payment/Canteen/Counter/READY/Uncollected
  -> Separate Handover Confirmation -> COMPLETED + Audit Log
```
