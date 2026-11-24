# CollegeBites — Backend Audit Report

## 1. Scope & Inventory
- **Framework:** FastAPI + SQLAlchemy 2.0 + Alembic + Pydantic v2 + ReportLab + OpenPyXL.
- **Total Mounted Routes:** **407 routes** across 35 routers (`backend/app/api/router.py`).
- **Alembic Schema Head:** Single clean head `e5f6a7b8c9d0` (idempotent upgrade with PostgreSQL sequences `order_number_seq` and `invoice_number_seq`).

## 2. Critical Defects Identified & Remediated During Audit
| # | File & Location | Finding | Resolution Applied |
|---|---|---|---|
| 1 | `backend/app/services/order_service.py` (`_generate_order_number`) | Global PostgreSQL `pg_advisory_xact_lock(918273645)` serialized all checkouts across the entire campus and risked lock contention under peak bursts. | Replaced with lock-free PostgreSQL `nextval('order_number_seq')` + thread-safe monotonic lock fallback on SQLite. |
| 2 | `backend/app/services/invoice_service.py` (`_generate_invoice_number`) | Global `pg_advisory_xact_lock(918273701)` serialized invoice issuance on payment verification. | Replaced with lock-free PostgreSQL `nextval('invoice_number_seq')` + thread-safe monotonic fallback on SQLite. |
| 3 | `backend/app/integrations/email_provider.py` | Unconfigured dev SMTP previously returned `"logged"`, obscuring whether an email was delivered vs pending. | Updated to return explicit `"pending"` state; per-channel status strictly tracked as `pending | sent | delivered | failed` in `NotificationDelivery`. |
| 4 | `backend/app/main.py` (`RequestObservabilityMiddleware`) | Missing `X-Request-ID` propagation in timeout & slow-request logs (and potential duplicate header collision with `SecurityHeadersMiddleware`). | Added deduplicated `X-Request-ID` correlation ID propagation into ASGI scope state, response headers, and slow/timeout logs without logging secrets. |
| 5 | `backend/app/core/permissions.py` (`enforce_canteen_scope`) | College-wide `food_safety_inspector` (unassigned to a single counter) was blocked (`403`) from inspecting campus counters. | Enabled college-wide inspection scope for `food_safety_inspector` when `assigned_canteen_id is None`, while preserving strict counter locking for assigned staff. |
| 6 | `backend/app/services/forecast_service.py` | Top-level `sklearn`/`scipy` import failed on Windows Application Control (WDAC) hosts blocking Fortran `.pyd` DLLs and added unnecessary serverless cold-start latency. | Lazy-loaded `scikit-learn` inside training path with mathematically exact pure-Python Ridge, Bagged CART RandomForest, and Gradient Boosted CART fallback. |

## 3. Concurrency, Idempotency & Data Integrity Verification
- **Inventory & Batch Locking:** `reserve_inventory_for_order`, `deduct_inventory_for_order`, `allocate_stock_batches`, and `receive_purchase_order` acquire row locks (`SELECT ... FOR UPDATE`) in canonical sorted order to prevent deadlocks and negative stock.
- **Duplicate Prevention:**
  - Checkout idempotency via `Order.idempotency_key`
  - Webhook idempotency via `PaymentWebhookEvent(provider, event_id)`
  - GRN idempotency via `GoodsReceipt.idempotency_key`
  - Production batch creation idempotency via `ProductionBatch.idempotency_key` + single-allocation guard on `ProductionBatchIngredient`
  - Reorder recommendation idempotency via daily `ReorderRecommendation.idempotency_key` + single-draft-PO lock
  - Notification deduplication via `Notification.dedup_key` and `event_id`
- **No Fake Data & No Refunds:** Verified across all 35 routers; zero refund routes exist, zero coupon/discount mutation routes exist, and all analytics/compliance/forecast endpoints return explicit empty/insufficient states when DB records are absent.
