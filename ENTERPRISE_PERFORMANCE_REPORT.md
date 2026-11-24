# CollegeBites — Enterprise Performance Optimization, Scalability & Load Testing Report

**Generated:** `2026-11-24 06:40:18 UTC`  
**Staging Environment:** `Isolated Local Staging (Windows 11, 12 Logical CPUs, 34 GB RAM)`  
**Runtime Topology:** `FastAPI (Pure ASGI Middlewares) + 4 Uvicorn Workers (ports 8011..8014) + SQLite WAL (busy_timeout=30000ms) + Local TCP Redis (fakeredis.TcpFakeServer on 127.0.0.1:6389)`  
**Baseline Preserved:** `performance-testing/COMPLETE_PERFORMANCE_REPORT.pdf` (untouched)  
**Enterprise PDF Report:** `performance-testing/ENTERPRISE_SCALABILITY_PERFORMANCE_REPORT.pdf`

> **Measurement Integrity Disclosure:** Local PostgreSQL 18 binary (postgres.exe) exits with Windows sandbox code 0xC0000409 and Docker daemon is stopped in this environment; all staging measurements were genuinely executed on isolated SQLite WAL + 4-worker Uvicorn + TCP Redis and are clearly separated from production PostgreSQL projections. Production (`https://collegebites-alpha.vercel.app`) was never load-tested or mutated.

---

## Executive Capacity Summary (Verified Measurements Only)

| Metric | Baseline (`COMPLETE_PERFORMANCE_REPORT.pdf`) | Enterprise Optimized (Measured Staging) | Target / SLA | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Max Sustainable Unique User Arrival Rate** | Not measured (failed at 100 VUs / 26 RPS) | **1,500 unique sessions/min** | 500 min / 1,000 primary | **PASS** |
| **Max Sustainable Concurrent Virtual Users** | 50 VUs (`P95=1,201.6ms`, `0%` err) | **50 VUs** (`<500ms` Read P95, `<1%` err on local SQLite WAL) | Separate Concurrency Metric | Verified |
| **Admin Orders SQL Queries (`/admin/orders`)** | 235 SQL/req | **15 cold / 11 warm** (`-95.3%`) | Eliminate N+1 | **PASS** |
| **Analytics BI Dashboard (`/reports/dashboard`)** | 42 SQL/req | **27 cold / 1 warm** (`-97.6%`) | Eliminate N+1 + Cache | **PASS** |
| **Queue Metrics (`/queue/canteens/{id}`)** | 25 SQL/req | **14 cold / 0 warm** (`-100.0%`) | Eliminate N+1 + Cache | **PASS** |
| **Menu Catalog (`/menus/canteens/{id}/items`)** | 11 SQL/req | **10 cold / 0 warm** (`-100.0%`) | Eliminate N+1 + Cache | **PASS** |
| **Admin Users RBAC (`/admin/users`)** | ~240 SQL/req (78 users) | **6 SQL/req** (`-97.5%`) | Batched RBAC | **PASS** |
| **Ordering / Payment / Token Integrity** | Not stress-verified | **0 duplicate orders, 0 duplicate payments, 0 duplicate tokens, 0 lost confirmed txns** (139 confirmed) | Zero Integrity Violations | **PASS** |

---

## 1. Before-vs-After SQL Query & Latency Comparison

| Module / Endpoint | Baseline SQL | Optimized Cold SQL | Optimized Warm Redis SQL | Warm SQL Reduction | Cold ms | Warm Avg ms |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Admin Orders Console (`GET /api/v1/admin/orders?limit=50`) | 235 | 15 | 11 | -95.3% | 44.4 | 19.99 |
| Analytics BI Dashboard (`GET /api/v1/reports/dashboard?preset=last_30_days`) | 42 | 27 | 1 | -97.6% | 51.8 | 8.55 |
| Live Queue Metrics (`GET /api/v1/queue/canteens/5c9dcaa4-1f57-4921-9bee-25d1e5c9cd89`) | 25 | 14 | 0 | -100.0% | 26.6 | 5.42 |
| Operations Control Center (`GET /api/v1/reports/operations-control-center`) | 21 | 17 | 1 | -95.2% | 38.7 | 7.69 |
| Customer Orders History (`GET /api/v1/orders/my?limit=50`) | 21 | 15 | 11 | -47.6% | 29.9 | 20.19 |
| Menu Items Catalog (`GET /api/v1/menus/canteens/5c9dcaa4-1f57-4921-9bee-25d1e5c9cd89/items`) | 11 | 10 | 0 | -100.0% | 35.3 | 5.59 |
| List Canteens (`GET /api/v1/canteens`) | 11 | 5 | 0 | -100.0% | 16.4 | 4.53 |
| Operational Token Board (`GET /api/v1/pickup/token-board`) | 11 | 6 | 1 | -90.9% | 21.5 | 10.72 |
| Auth Current Session (`GET /api/v1/auth/me`) | 10 | 1 | 1 | -90.0% | 7.2 | 6.86 |
| Vendor & Suppliers List (`GET /api/v1/inventory/suppliers`) | 9 | 5 | 5 | -44.4% | 11.2 | 10.53 |
| Public Token Board (`GET /api/v1/pickup/board`) | 3 | 3 | 0 | -100.0% | 11.6 | 4.30 |
| Admin Users List (78 users) (`GET /api/v1/admin/users`) | 240 | 6 | 6 | -97.5% | 23.8 | 38.07 |
| Inventory Items List (`GET /api/v1/inventory/canteens/5c9dcaa4-1f57-4921-9bee-25d1e5c9cd89/items`) | N/A | 4 | 4 | N/A | 14.6 | 9.14 |
| Purchase Orders List (`GET /api/v1/inventory/canteens/5c9dcaa4-1f57-4921-9bee-25d1e5c9cd89/purchase-orders`) | N/A | 2 | 2 | N/A | 7.5 | 6.37 |
| Kitchen Orders Queue (`GET /api/v1/kitchen/canteens/5c9dcaa4-1f57-4921-9bee-25d1e5c9cd89/orders`) | N/A | 15 | 1 | N/A | 29.3 | 7.53 |
| Readiness Health Probe (`GET /health/ready`) | N/A | 1 | 1 | N/A | 3.8 | 4.12 |

---

## 2. Progressive Unique User Arrival-Rate Ladder (50 to 1,500 sessions/min)

All four roles active concurrently (65% Student, 15% Canteen Manager, 10% Inventory Manager, 10% Admin) with JWT auth, RBAC, HMAC-SHA256 payment verification, and Redis-backed campus-NAT rate limiting (`600/minute`) **enabled**.

| Target Sessions/Min | Achieved Sessions/Min | Peak Active VUs | RPS | RPM | Read P50 (ms) | Read P95 (ms) | Read P99 (ms) | Write P95 (ms) | Error % | HTTP 429 | Orders / Verified | Verdict |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| 50 | 51.9 | 0 | 4.0 | 239 | 8.5 | 34.5 | 61.0 | 35.5 | 0.00% | 0 | 1/1 | **PASS** |
| 100 | 100.0 | 0 | 7.9 | 472 | 7.0 | 32.1 | 56.3 | 64.4 | 0.00% | 0 | 6/6 | **PASS** |
| 250 | 250.0 | 1 | 18.9 | 1134 | 6.3 | 29.3 | 53.7 | 48.3 | 0.00% | 0 | 13/13 | **PASS** |
| 500 | 500.0 | 1 | 38.0 | 2283 | 6.5 | 31.7 | 46.8 | 53.0 | 0.00% | 0 | 28/28 | **PASS** |
| 750 | 751.2 | 3 | 57.2 | 3434 | 7.5 | 35.7 | 59.6 | 92.3 | 0.00% | 0 | 43/43 | **PASS** |
| 1000 | 995.6 | 4 | 77.5 | 4648 | 8.7 | 53.3 | 109.6 | 105.6 | 0.00% | 0 | 77/77 | **PASS** |
| 1500 | 1496.3 | 13 | 115.2 | 6913 | 10.6 | 87.8 | 303.3 | 237.4 | 0.04% | 0 | 110/110 | **PASS** |

---

## 3. Separate Simultaneous Concurrency Ladder (50 to 1,000 Concurrent VUs)

Measured independently with k6 `constant-vus` (`1.5s` think time between multi-endpoint role flows).

| Concurrent VUs | Baseline Error % | Optimized Error % | Measured RPS | Measured RPM | Read P50 (ms) | Read P95 (ms) | Write P95 (ms) | Host CPU % | 4-Worker RSS (MB) | Verdict (`<500ms` & `<1%`) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 50 | 0.0% | 0.13% | 110.6 | 6635 | 19.4 | 318.0 | 940.4 | 24.4% | N/A | **PASS** |
| 100 | 28.9% | 0.22% | 92.3 | 5540 | 44.0 | 2889.8 | 9925.6 | 36.8% | N/A | **FAIL** |
| 250 | 100.0% | 2.82% | 105.3 | 6316 | 273.4 | 5328.4 | 11456.7 | 38.9% | N/A | **FAIL** |
| 500 | 99.2% | 15.70% | 95.4 | 5726 | 609.6 | 7868.7 | 17127.7 | 23.3% | N/A | **FAIL** |
| 1000 | 100.0% | 85.13% | 72.0 | 4320 | 452.8 | 3557.9 | 0.0 | 10.7% | N/A | **FAIL** |

---

## 4. Stress/Spike, Endurance Soak, Redis Failover & Transaction Integrity

- **Lunch-Rush Spike (`100 -> 500 -> 1,000 -> 1,500 -> 250` sessions/min):** `4,751` requests, `63.30` RPS, Read P95 `74.5 ms`, Write P95 `180.1 ms`, Error Rate `0.000%`, Host CPU `10.7%`.
- **Endurance Soak (`1,000` sessions/min for 120s):** Achieved `998.7` sessions/min, `9,145` requests, Read P95 `110.2 ms`, Error Rate `0.011%`, CPU `14.4%`, RSS `1351.8 -> 1336.4 MB` (`-15.3 MB`), zero crashes.
- **Redis Outage & Automatic Recovery (`500` sessions/min):** During outage `/health/ready` reported `redis=fallback` (`database=connected`), Read P95 `406.5 ms`, Error Rate `0.000%`. After Redis restart, `/health/ready` self-healed to `redis=connected`, Read P95 recovered to `36.2 ms`, Error Rate `0.000%`.
- **Live Concurrency Race Audit:** `20/20` simultaneous duplicate-idempotency checkouts -> `1` unique order (`0` 5xx); `15/15` simultaneous payment verifies -> `1` unique pickup token (`0` 5xx); `15/15` simultaneous duplicate webhooks (`0` 5xx).
- **Post-Test Database Financial Integrity Audit:** `139` orders, `139` confirmed orders, `139` confirmed payments, `139` pickup tokens, **`0` duplicate order numbers, `0` duplicate idempotency keys, `0` duplicate payments, `0` duplicate tokens, `0` confirmed orders missing tokens**.

---

## 5. Implemented Optimizations & Modified Files

### Database, Pooling & Migrations
- `backend/migrations/versions/cf2a3b4c5d6e_enterprise_performance_indexes.py` — Idempotent migration adding 30 composite B-tree indexes across `orders`, `order_items`, `payments`, `pickup_tokens`, `food_items`, `sessions`, `inventory_items`, `stock_batches`, `purchase_orders`, `notifications`, and `audit_logs`.
- `backend/app/core/database.py` — Auto-detects Neon PgBouncer `-pooler` (`prepare_threshold=None`), bounded `QueuePool` for both dedicated servers (`12+18`, `pool_use_lifo=True`) and warm serverless instances (`2+3`, `pool_recycle=300`), SQLite WAL pragmas, guaranteed rollback on exception in `get_db()`, `run_with_db_retry()`, `get_pool_stats()`, and `dispose_engine()`.
- `backend/app/models/{auth,engagement,inventory,menu,order,payment,promotion,staff,system}.py` — Matching SQLAlchemy composite `Index(...)` declarations.

### Redis Two-Tier Caching & N+1 Elimination
- `backend/app/core/cache.py` — Thread-safe bounded L1 LRU+TTL + L2 Redis JSON cache with O(1) atomic namespace version invalidation (`INCR cb:ver:{ns}` starting from v0 -> v1), 8-second self-healing Redis circuit breaker, and hit/miss telemetry.
- `backend/app/core/redis_client.py` — Bounded connection pool (`max_connections=64`), fast fail timeouts (`0.4s`/`0.5s`), test reset hook.
- `backend/app/api/admin/routes.py`, `backend/app/api/orders/routes.py`, `backend/app/api/kitchen/routes.py`, `backend/app/api/menus/routes.py`, `backend/app/api/reports/routes.py`, `backend/app/api/realtime/routes.py` — Batched serialization, bounded pagination, cached responses, and 1.5s SSE watermark backoff on serverless.
- `backend/app/services/{order_service,payment_service,token_service,report_service,menu_service,queue_service,pickup_service,kitchen_service,inventory_service,college_service,auth_service,realtime_service}.py` & `backend/app/core/permissions.py` — Eliminated N+1 queries, batched checkout & RBAC lookups, moved post-payment notifications after `db.commit()`, added savepoint webhook/token deduplication and aligned lock ordering.

### Pure ASGI Runtime, Rate Limiting & Deployment
- `backend/app/main.py`, `backend/app/middleware/security_headers.py`, `backend/app/core/rate_limit.py` — Replaced all three `BaseHTTPMiddleware` layers with pure zero-buffering ASGI middlewares (`RequestObservabilityMiddleware`, `SecurityHeadersMiddleware`, `PureASGIRateLimitMiddleware`), tuned AnyIO threadpool tokens (`100`), added `GZipMiddleware`, `/health/ready`, and campus-NAT-aware Redis rate limiting (`600/minute` per user/guest/IP with `<1ms` circuit-breaker in-memory fallback).
- `backend/run_prod.py`, `backend/Dockerfile`, `docker-compose.yml`, `vercel.json`, `.env.example` — Production multi-worker ASGI launcher bounded by CPU and PostgreSQL connection budget, container healthcheck, tuned PostgreSQL 16 + Redis 7 compose stack, and `/health/(.*)` Vercel rewrite.

### Frontend Performance Optimizations
- `frontend/src/App.tsx`, `frontend/vite.config.ts`, `frontend/src/hooks/useDebouncedValue.ts`, `frontend/src/hooks/useRealtimeSync.ts` — Lazy-loaded 16 routes via `React.lazy()` + `<Suspense>`, split `vendor-charts` (`recharts`), disabled React Query retry amplification (`retry: false`), preserved live SSE streams across tab switches.
- `frontend/src/components/layout/Navbar.tsx`, `TokenBoardPage.tsx`, `OperationalTokenBoardPage.tsx`, `PickupScannerPage.tsx`, `HomePage.tsx`, `OrderTrackingPage.tsx`, `OrdersUsersTab.tsx`, `OperationsControlCenterPanel.tsx`, `CheckoutPage.tsx`, `InventoryPage.tsx` — Skipped notification mount on `/board`, backed off polling when SSE is live (`5s`–`60s`), stopped polling on terminal orders, debounced search filters, and added lazy image loading.

---

## 6. How to Execute the Automated Load-Testing Suite

```powershell
# 1. Run backend enterprise performance & idempotency regression tests
cd C:\Users\HP\Desktop\collegebites\backend
$env:TEST_DATABASE_URL = 'sqlite:///C:/Users/HP/Desktop/collegebites/backend/test_p33.db'
.\.venv\Scripts\python.exe -m pytest tests/test_phase33_enterprise_performance.py -v

# 2. Run the complete isolated 4-worker + TCP Redis enterprise benchmark suite
cd C:\Users\HP\Desktop\collegebites\performance-testing\enterprise-scale
..\..\backend\.venv\Scripts\python.exe -u run_enterprise_benchmarks.py

# 3. Regenerate charts, Markdown report, and enterprise PDF report
..\..\backend\.venv\Scripts\python.exe -u generate_enterprise_report.py
```

To target a dedicated PostgreSQL + Redis staging server directly with k6:
```bash
k6 run -e BASE_URL=https://staging-api.example.com -e SEED_FILE=./raw-results/seed_context.json -e RATE_PER_MIN=1000 -e DURATION=2m k6/01_multi_role_arrival_rate.js
```

---

## 7. Remaining Bottlenecks & Production Infrastructure Recommendations

1. **Database Engine & Connection Pooling (Top Production Priority):** Local staging validated `1,500` sessions/min on SQLite WAL, while extreme simultaneous write concurrency (`250–1,000` continuous VUs) hits SQLite's single-writer lock. In production, deploy managed **PostgreSQL 16 (2–4 vCPU, 4 GB RAM, `max_connections=200`)** behind **PgBouncer transaction pooling** (e.g., Neon `-pooler` endpoint or RDS Proxy) and run `alembic upgrade head` to apply `cf2a3b4c5d6e`.
2. **Dedicated Multi-Worker Backend Containers vs Serverless:** Keep the React/Vite static SPA on **Vercel Edge CDN**, and deploy the FastAPI backend on **dedicated container hosting (Railway, Render Standard/Pro, or AWS ECS Fargate: 2–4 vCPU, 2–4 GB RAM running `python run_prod.py` with 4 Uvicorn workers)** behind an L7 load balancer for true WebSockets, zero cold starts, predictable CPU, and warm L1+L2 caching.
3. **Managed Shared Redis:** Provision **Upstash Redis** or regional **Redis 7 (256–512 MB, `allkeys-lru`)** in the same cloud region as the API (`<2ms` RTT) so all Uvicorn workers and horizontal replicas share L2 cache, O(1) namespace invalidation, and distributed SlowAPI rate limits.
4. **Operational Capacity Configuration:** Default `Canteen.max_concurrent_orders = 60` legitimately throttles orders with HTTP 429 once 60 uncompleted orders queue up. Configure per-canteen thresholds matching real kitchen throughput (e.g., `150–300` across multi-counter canteens) and ensure kitchen staff advance orders to `READY`/`COMPLETED` continuously during lunch rush.
5. **Argon2id Login CPU Isolation:** Argon2id password hashing consumes ~100–130ms CPU per fresh login. At 1,000 sessions/min with 10% fresh logins (~1.7 logins/sec), 4 workers handle it easily (`<25%` CPU); for campus-wide simultaneous login storms (e.g., 500 students logging in within the exact same 5 seconds), scale horizontally to 2 container replicas (8 workers total) behind a load balancer.
