# CollegeBites — Enterprise System Architecture

## 1. Deployment Scope & Core Principles
- **Single-College Operational Scope:** Deployed exclusively for one college campus (**ACE Engineering College**) with a fixed two-counter cafeteria layout (`Main Canteen` and `Snacks & Bakery Counter`, both located at `College Cafeteria`).
- **Zero Fake Data Policy:** Every dashboard metric, analytics figure, compliance statistic, queue wait estimate, forecast, and AI assistant response is backed strictly by real database records, explicitly classified as `actual`, `calculated`, `estimated`, `ai_predicted`, `unavailable`, or `policy_restricted`.
- **Financial & Pricing Invariants:**
  - Exact listed item pricing (`subtotal == total`, zero discounts, zero coupons, zero additional checkout tax; statutory tax-inclusive notice on receipts & invoices).
  - Online-only payments via Razorpay (`razorpay`) and digital counter terminals (`upi_pos`, `card_pos`); cash and pay-at-pickup are disabled.
  - Strict no-refund policy; confirmed orders preserve immutable payment & ledger records.
  - Automated reordering generates **Draft** Purchase Orders only and never auto-approves or transfers money.

## 2. Layered Architecture
```
[Customer Web / Staff Portals (React + Vite + TypeScript + Tailwind + React Query)]
[Customer Mobile App (Expo + React Native + TypeScript)]
                          │ HTTPS + WSS + SSE (X-Request-ID)
                          ▼
[Vercel / ASGI Edge → Pure ASGI Middleware Stack (CORS → RequestObservability → SecurityHeaders → RateLimit → GZip)]
                          │
                          ▼
[FastAPI Application (35 Routers, 412 Mounted ASGI Routes: 402 /api/v1 HTTP + 6 Health/Docs + 4 WebSockets, 132 Tables)]
 ├── Core Ordering, Exact Pricing & Online Payments (Razorpay HMAC, Status Sync & Webhooks)
 ├── QR/Token Engine, Digital Token Board & Thermal ESC/POS Printing
 ├── Smart Queue Prediction & Accuracy History Engine
 ├── Notification & Communication Center (In-App, Email SMTP, SMS/WhatsApp, Web Push, Delivery Audit)
 ├── Food Safety & Hygiene Compliance (Checklists, Equipment Temps, Expiry, Cleaning, Incidents)
 ├── Food Traceability & Batch Tracking (FIFO/FEFO Allocation, End-to-End Chains, Recalls)
 ├── Kitchen & Food Production Management (Verified Recipes, Planning, 8-State Batches, QC, KDS)
 ├── Automated Reordering System (Rules, Consumption/Forecast Analysis, Draft POs)
 ├── Business Intelligence & Financial Analytics (Revenue vs Verified Ingredient Cost & Margin)
 ├── AI Demand Forecasting Pipeline (Chronological ML: Baseline vs Ridge vs RF vs GradientBoosting)
 └── Controlled Role-Aware AI Canteen Assistant (Read-Only Tool Dispatcher + Policy Guardrails)
                          │
         ┌────────────────┴────────────────┐
         ▼                                 ▼
[PostgreSQL 16+ (SQLAlchemy 2 + Alembic)] [Redis / Upstash Cache + PubSub + Rate Limit]
   Lock-free Sequences (order_number_seq,    L1 In-Process + L2 Redis Versioned Cache
   invoice_number_seq), FOR UPDATE Locks
```

## 3. Data Model Consolidation (Zero Duplication)
All enterprise modules extend existing authoritative entities rather than duplicating tables:
- **Inventory & Traceability:** Extends `StockBatch` (`purchase_order_id`, `goods_receipt_id`, `allocated_quantity`, `consumed_quantity`, `rejected_quantity`, `wasted_quantity`, `manufacturing_date`, `storage_location`, `quality_status`, `block_reason`, `supporting_documents`) and `Supplier` (`lead_time_days`), adding `TraceabilityRecord` and `RecallIncident`.
- **Production:** Extends `Recipe` (`is_verified`, `verified_by_user_id`, `verified_at`) and connects `ProductionPlan`, `ProductionBatch`, `ProductionBatchIngredient`, and `ProductionQualityCheck` directly to existing `FoodItem`, `StockBatch`, and `WastageRecord`.
- **Notifications:** Extends `Notification` (`event_id`, `category`, `priority`, `last_error`, `delivered_at`) and adds `NotificationDelivery` for per-channel masked-PII tracking and retries.
- **Queue Accuracy, ML & Assistant:** Adds `QueueEstimateHistory`, `ForecastModel`, `DemandForecast`, `ForecastEvaluation`, `AIAssistantConversation`, `AIAssistantMessage`, and `AIAssistantAuditLog`.
- **Alembic Migration Head:** `f6a7b8c9d0e1` (`f6a7b8c9d0e1_razorpay_only_and_live_otp.py`), chaining cleanly off `e5f6a7b8c9d0`.

## 4. Connected 15-Step End-to-End Operational Workflow
1. Vendor registered (`Supplier`) → 2. Purchase Order created (`draft`) → 3. Manager approves & orders PO → 4. Verified Goods Receipt (`GRN`) creates traceable `StockBatch` + `TraceabilityRecord` → 5. Batch expiry & quality tracked under Food Safety → 6. Verified `Recipe` linked to `FoodItem` → 7. Production Planning compares confirmed orders, event bulk orders, and AI forecast separately (no double-counting) → 8. `ProductionBatch` atomically allocates ingredients via FIFO/FEFO (blocking expired/recalled batches) → 9. Mandatory Quality Control check recorded before completion → 10. Customer checks out at exact listed price via Razorpay → 11. Lock-free order/invoice sequence + QR token + customer receipt & print job + `QueueEstimateHistory` snapshot + notifications → 12. Kitchen accepts order (generating KOT print job), prepares via Order/Item-Grouped KDS, and marks `READY` (finalizing queue accuracy) → 13. Pickup staff verifies QR & confirmed payment and hands over → 14. Reordering & ML Demand Forecasting detect upcoming deficits and generate Draft POs → 15. BI Analytics & Role-Aware AI Assistant report verified revenue, direct costs, safety compliance, and forecasts.
