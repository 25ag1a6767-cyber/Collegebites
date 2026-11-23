# CollegeBites — Actionable Performance Optimization Recommendations

> **Note:** In accordance with Section 3 & Section 11 rules (*"Do not change production code without approval"*), no production application files were modified during this assessment. Every optimization below includes the exact file, code change, evidence, and **clearly labeled estimated performance improvement**.

---

## 1. Critical Severity Optimizations

### OPT-01: Replace N+1 Loop in `GET /api/v1/admin/orders` with Existing `serialize_orders_batch`
- **Target File:** `backend/app/api/admin/routes.py` (Line 514)
- **Bottleneck Addressed:** **BN-02** (`235` SQL queries per call; up to `701` SQL queries at `limit=100`).
- **Recommended Code Change:**
  ```python
  # BEFORE (backend/app/api/admin/routes.py:514)
  orders = db.scalars(stmt).all()
  return [order_service.serialize_order(db, o) for o in orders]

  # AFTER
  orders = list(db.scalars(stmt).all())
  return order_service.serialize_orders_batch(db, orders)
  ```
- **Expected Performance Improvement (Estimate):**
  - **Estimated SQL Query Reduction:** From `1 + 7N` (`235`–`701` queries) down to a constant **7 queries total** (an **85% to 99% reduction in SQL queries**).
  - **Estimated Latency Reduction:** From `134.51ms` average (`193.12ms` P95) down to an estimated **6–10ms** locally and **40–65ms** on Vercel + Neon (**~70%–85% faster**).

### OPT-02: Route Vercel Serverless Connections Through Neon PgBouncer (`-pooler`) & Add Short-TTL Board Cache
- **Target Files:**
  - Vercel Environment Variable `DATABASE_URL` (use Neon pooled connection string `ep-...-pooler.ap-southeast-1.aws.neon.tech`)
  - `backend/app/services/pickup_service.py` (`get_digital_token_board`)
- **Bottleneck Addressed:** **BN-01** (`NullPool` TCP/TLS handshake per 1-second `/pickup/board` poll).
- **Recommended Solution:**
  1. Ensure `DATABASE_URL` on Vercel uses the `-pooler` endpoint with `?sslmode=require`.
  2. Cache `DigitalBoardResponse` in Redis / in-process memory for `800ms` keyed by `cb:board:{canteen_id or 'all'}` and invalidate immediately inside `emit_order_event_sync()`.
- **Expected Performance Improvement (Estimate):**
  - **Estimated Database Load Reduction:** Coalesces 50 concurrent 1-second TV/customer board polls into **1 database query per second** (**~98% reduction in `/pickup/board` SQL traffic**).
  - **Estimated Latency Reduction:** Reduces production `/api/v1/pickup/board` P95 latency from `~266ms` to an estimated **35–60ms**.

---

## 2. High Severity Optimizations

### OPT-03: Make SlowAPI Rate Limiting Campus-NAT Aware (Key by Authenticated User ID / Token + Tiered Limits)
- **Target Files:** `backend/app/core/rate_limit.py`, `backend/app/core/config.py`
- **Bottleneck Addressed:** **BN-03** (`300/minute` per IP causes `HTTP 429` when multiple students or TV boards share a college Wi-Fi NAT public IP).
- **Recommended Solution:**
  1. Extract the JWT `sub` (or `X-Guest-Session-Id`) in the SlowAPI `key_func` before falling back to `X-Forwarded-For` / client IP, so each authenticated student gets their own rate-limit bucket instead of sharing one campus NAT bucket.
  2. Exempt or assign a higher limit (`1200/minute`) to read-only polling endpoints (`GET /api/v1/pickup/board`, `GET /api/v1/canteens`, `GET /api/v1/menus/items`) while keeping strict limits (`20/minute`) on `/api/v1/auth/login` and `/api/v1/auth/otp/request`.
- **Expected Performance Improvement (Estimate):**
  - **Estimated Error Reduction:** Eliminates **100% of false-positive HTTP 429 errors** for concurrent campus Wi-Fi users while preserving brute-force protection on authentication endpoints.

### OPT-04: Push Time-Series Bucketing in `get_analytics_report` & Supplier Totals in `list_suppliers` to SQL `GROUP BY`
- **Target Files:**
  - `backend/app/services/report_service.py` (Lines 114–172)
  - `backend/app/services/inventory_service.py` (`list_suppliers`)
- **Bottleneck Addressed:** **BN-04 & BN-05** (`42` SQL queries in `/reports/dashboard` and `21` SQL queries in `/reports/operations-control-center`).
- **Recommended Solution:**
  1. Replace the Python `for o in paid_orders:` bucketing loop with a single PostgreSQL `SELECT DATE_TRUNC('day', created_at AT TIME ZONE 'Asia/Kolkata'), COUNT(*), SUM(total_amount) FROM orders WHERE ... GROUP BY 1`.
  2. Replace per-supplier PO and payment sum queries in `list_suppliers` with two batch `GROUP BY supplier_id` queries across `PurchaseOrder` and `VendorPayment`.
  3. Cache `/reports/dashboard` in Redis for `30 seconds` per `(canteen_id, preset)`.
- **Expected Performance Improvement (Estimate):**
  - **Estimated SQL Query Reduction:** Reduces `/reports/dashboard` queries from `42` to **8 queries** and `/reports/operations-control-center` queries from `21` to **11 queries** (**~55%–65% fewer queries**).
  - **Estimated Latency Reduction:** Reduces `/reports/dashboard` P95 latency by an estimated **50%–70%** as order history grows beyond 10,000 rows.

---

## 3. Medium & Low Severity Optimizations

### OPT-05: Batch-Load `KitchenStation` & Cache `MenuSchedule` in `list_food_items`
- **Target File:** `backend/app/services/menu_service.py` (Lines 193, 351–369)
- **Bottleneck Addressed:** **BN-06** (`11` SQL queries per `GET /api/v1/menus/items`).
- **Recommended Solution:**
  Preload `station_map = {s.id: s for s in db.scalars(select(KitchenStation).where(KitchenStation.id.in_(station_ids))).all()}` in `list_food_items` and pass `station_map` into `serialize_food_item`. Cache active canteen menu responses in Redis for `15 seconds` (invalidated on menu/stock mutation).
- **Expected Performance Improvement (Estimate):**
  - **Estimated Latency Reduction:** Cuts uncached SQL queries from `11` to **6 queries** and reduces cached menu response times to **<3ms** (**~80% faster**).

### OPT-06: Add Composite PostgreSQL Indexes for Hot Analytics & Token Board Joins
- **Target Files:** `backend/app/models/order.py`, `backend/app/models/payment.py` (via Alembic migration)
- **Bottleneck Addressed:** **BN-08**
- **Recommended SQL / Alembic Indexes:**
  ```sql
  CREATE INDEX CONCURRENTLY ix_order_items_food_item_id ON order_items (food_item_id);
  CREATE INDEX CONCURRENTLY ix_pickup_tokens_service_date_canteen ON pickup_tokens (service_date, canteen_id, sequence_number);
  CREATE INDEX CONCURRENTLY ix_orders_paid_created_at ON orders (canteen_id, payment_status, created_at DESC);
  ```
- **Expected Performance Improvement (Estimate):**
  - **Estimated Query Speedup:** Converts sequential scans on `order_items` and `pickup_tokens` into Index-Only / Bitmap Index Scans, improving join throughput by an estimated **40%–75%** at 50,000+ historical order rows.

### OPT-07: Coalesce WebSocket 1-Second DB Watermark Polls into a Single Shared Topic Broadcaster
- **Target File:** `backend/app/api/ws/routes.py` (Lines 110–159)
- **Bottleneck Addressed:** **BN-07** (`N` connected WebSocket clients running `N` independent 1-second DB queries).
- **Recommended Solution:**
  Maintain a single background watermark poller task per unique `(watch_kind, target_id)` room inside `ws_manager` instead of spawning `_watch_room_db_changes` per individual `WebSocket` connection.
- **Expected Performance Improvement (Estimate):**
  - **Estimated Database Load Reduction:** Reduces WebSocket idle DB query load at 100 connected clients from **100 queries/sec** down to **1 query/sec per active canteen room** (**~97% reduction**).
