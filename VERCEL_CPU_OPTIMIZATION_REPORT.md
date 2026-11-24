# CollegeBites — Read-Only Vercel Fluid Active CPU & Performance Optimization Report

**Audit Date:** `2026-11-23`  
**Audit Mode:** Strictly Read-Only (No production code, environment variables, database records, or deployment settings were modified; zero load tests or synthetic traffic were generated during this audit).

---

## 1. Deployed Vercel Architecture & Function Inventory

Inspection of [`vercel.json`](file:///C:/Users/HP/Desktop/collegebites/vercel.json#L1-L32) shows that CollegeBites uses **Vercel Services** with two logical services and one platform schedule:

| Component | Configuration in `vercel.json` | Runtime / Execution Model | Consumes Vercel Fluid Active CPU? |
| :--- | :--- | :--- | :--- |
| **1. Frontend Service (`frontend`)** | `root: "frontend"`, `framework: "vite"`, rewrite `/(.*) -> /index.html` | Static SPA bundle served directly from Vercel Edge CDN (`index.html` + Vite code-split chunks) | **No** (Static asset delivery does not execute serverless functions). |
| **2. Backend Service (`backend`)** | `root: "backend"`, `framework: "fastapi"`, `entrypoint: "app/main.py"` | Monolithic Python 3.12 ASGI Serverless Function handling `/api/(.*)`, `/health`, `/docs(.*)`, and `/openapi.json` | **Yes — 100% of Vercel Fluid Active CPU is consumed by this FastAPI Python Serverless Function.** |
| **3. Scheduled Cron (`collegebites-hourly-maintenance`)** | `schedule: "0 * * * *"`, `timezone: "Asia/Kolkata"`, `path: "/api/v1/admin/maintenance/run"`, `requestMethod: "POST"` | Hourly Vercel Schedule invoking the `backend` FastAPI function | **Yes** (Invokes cleanup, inventory alert scan, 1,000-row payment reconciliation, and full-database encrypted backup). |

> **Important Note on Telemetry:** Per Audit Rule #8, no Vercel dashboard CPU usage numbers are fabricated. All findings below are backed by exact source-code line references, deterministic request-frequency math from frontend timers, and measured SQL query counts per endpoint from the SQLAlchemy cursor profiler (`API_PERFORMANCE_REPORT.csv`).

---

## 2. Primary Causes of Excessive Vercel Fluid Active CPU Usage

Although Vercel Fluid Compute pauses CPU billing during pure network I/O wait, **Python user-space CPU is actively billed** during:
- Opening and tearing down `psycopg` v3 TCP + TLS + PostgreSQL authentication handshakes on every unpooled (`NullPool`) database session.
- SQLAlchemy ORM query compilation, row hydration, and relationship loading.
- Pydantic v2 model validation and JSON serialization (`model_validate`, `model_dump`).
- Cryptographic hashing/encryption (`sha256_hex`, `bcrypt`, `gzip.compress`, `Fernet.encrypt`) and PDF/XLSX generation (`reportlab`, `openpyxl`).

Below are the **6 verified root causes** of excessive Fluid Active CPU consumption, ordered by impact.

---

### Finding 1 (CRITICAL): Continuous 25-Second SSE Streams Opening & Closing a Fresh `NullPool` PostgreSQL Connection Every `0.9 Seconds`

- **Files & Functions Responsible:**
  - [`backend/app/api/realtime/routes.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/realtime/routes.py#L64-L185) — `_default_stream_window()` (Lines 64–70) & `_stream_with_watermark()` / `event_generator()` (Lines 112–185)
  - [`backend/app/core/database.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/core/database.py#L20-L44) — `_build_engine_kwargs()` (Lines 23–24) & `get_db()` (Lines 38–44)
  - [`frontend/src/hooks/useRealtimeSync.ts`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/hooks/useRealtimeSync.ts#L200-L306) — `connectSse()` (Lines 207–297)
- **Evidence from Source Code:**
  1. When running on Vercel (`os.environ.get("VERCEL")`), `_default_stream_window()` in [`backend/app/api/realtime/routes.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/realtime/routes.py#L67-L68) holds each SSE HTTP request open for **`25.0` seconds**, and when it emits `stream.reconnect`, [`frontend/src/hooks/useRealtimeSync.ts`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/hooks/useRealtimeSync.ts#L287-L288) reconnects **`150ms` later** (`const delayMs = cycleRequested ? 150 : 1200;`). This keeps a serverless invocation active 24/7 for every open browser tab.
  2. Inside the 25-second `while True:` loop ([`backend/app/api/realtime/routes.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/realtime/routes.py#L148-L169)):
     ```python
     await asyncio.wait_for(queue.get(), timeout=min(0.9, remaining))
     ...
     gen, sess = realtime_service.resolve_db_session(request)
     try:
         watermark = compute_version(sess)
         ...
     finally:
         realtime_service.close_db_session(gen)
     ```
     Every **`0.9 seconds`** (`~27 times` per 25-second request = **`~66.7 times per minute`**), the loop opens a new SQLAlchemy session via `resolve_db_session()` and closes it in `finally:`.
  3. Because [`backend/app/core/database.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/core/database.py#L23-L24) configures `NullPool` on Vercel:
     ```python
     if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
         return {"poolclass": NullPool, "pool_pre_ping": True}
     ```
     `close_db_session(gen)` **physically disconnects from Neon PostgreSQL every 0.9 seconds**, and the next tick 0.9 seconds later performs a **brand-new TCP + TLS handshake + PostgreSQL authentication + `pool_pre_ping` + SQL watermark query + SHA-256 fingerprint computation in Python CPU**.
  4. **Stacked Concurrent SSE Streams per Browser Tab:**
     - [`Navbar.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/components/layout/Navbar.tsx#L72-L83) mounts `useRealtimeSync` (`/realtime/notifications/stream`) globally on almost every route for every signed-in user.
     - When a staff member opens `/admin` ([`AdminConsolePage.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/admin/AdminConsolePage.tsx#L84-L89)) and views the **Orders** tab ([`OrdersUsersTab.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/admin/components/OrdersUsersTab.tsx#L40)) or **Queue** tab ([`QueueStaffTab.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/admin/components/QueueStaffTab.tsx#L26)), **3 concurrent SSE streams** run simultaneously from that single browser tab (`Navbar` + `AdminConsolePage` + child tab = **~200 full PostgreSQL connection/TLS/query cycles per minute from 1 tab**).

---

### Finding 2 (CRITICAL): Duplicate 1-Second REST Polling (`refetchInterval: 1000` with `refetchIntervalInBackground: true`) Running Alongside the 0.9-Second SSE Stream

- **Files & Functions Responsible:**
  - [`frontend/src/pages/board/TokenBoardPage.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/board/TokenBoardPage.tsx#L44-L86) — `useRealtimeSync` (Line 44) + `useQuery(["digital-board"])` (Lines 58–86)
  - [`frontend/src/pages/board/OperationalTokenBoardPage.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/board/OperationalTokenBoardPage.tsx#L242-L285) — `useRealtimeSync` (Line 242) + `useQuery(["operational-token-board"])` (Lines 256–285)
  - [`frontend/src/pages/pickup/PickupScannerPage.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/pickup/PickupScannerPage.tsx#L31-L53) — `useRealtimeSync` (Line 31) + `useQuery(["pickup-scanner-board"])` (Lines 41–53)
  - [`mobile/app/board.tsx`](file:///C:/Users/HP/Desktop/collegebites/mobile/app/board.tsx#L31) — `refetchInterval: 1000`
- **Evidence from Source Code:**
  - All three web pages open a real-time SSE stream (`/realtime/board/stream` or `/realtime/token-board/stream`) **and simultaneously** run a 1-second HTTP REST poll (`GET /api/v1/pickup/board` or `GET /api/v1/pickup/token-board`) with `staleTime: 0` and `refetchIntervalInBackground: true`.
  - Unlike [`KitchenDisplayPage.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/kitchen/KitchenDisplayPage.tsx#L130) (which backs off polling when SSE is live: `refetchInterval: !isOnline ? false : kdsSyncStatus === "live" ? 30000 : 4000`), `TokenBoardPage`, `OperationalTokenBoardPage`, and `PickupScannerPage` poll every `1,000ms` unconditionally—even when the SSE stream is `"live"` and even when the browser tab is minimized or hidden in the background.
  - Furthermore, on `/token-board`, each 1-second call to `GET /api/v1/pickup/token-board` executes **`11 SQL queries`** and serializes **`26.5 KB` of JSON** (`660 SQL queries/minute` from REST polling alone, plus `~66` SSE ticks/minute, plus `Navbar` SSE ticks).

---

### Finding 3 (HIGH): Complete Inventory of Frontend & Mobile Polling Timers Burning Background Serverless CPU

Every active `refetchInterval` in the repository was audited along with the measured SQL queries executed per request:

| File & Line | Endpoint Polled | Poll Interval | SQL Queries / Call | Requests / Min (Per Tab) | SQL Queries / Min (Per Tab) |
| :--- | :--- | :--- | ---: | ---: | ---: |
| [`TokenBoardPage.tsx:82`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/board/TokenBoardPage.tsx#L82) | `GET /api/v1/pickup/board` (+ SSE 0.9s loop) | **`1,000 ms`** *(bg: true)* | 3 | 60.0 (+66.7 SSE) | **380 / min** |
| [`OperationalTokenBoardPage.tsx:281`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/board/OperationalTokenBoardPage.tsx#L281) | `GET /api/v1/pickup/token-board` (+ SSE 0.9s loop) | **`1,000 ms`** *(bg: true)* | 11 | 60.0 (+66.7 SSE) | **860 / min** |
| [`PickupScannerPage.tsx:49`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/pickup/PickupScannerPage.tsx#L49) | `GET /api/v1/pickup/board/{id}` (+ SSE 0.9s loop) | **`1,000 ms`** *(bg: true)* | 4 | 60.0 (+66.7 SSE) | **440 / min** |
| [`OperationsControlCenterPanel.tsx:58`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/admin/components/OperationsControlCenterPanel.tsx#L58) | `GET /api/v1/reports/operations-control-center` | **`8,000 ms`** | 21 (+10 auth) | 7.5 | **232 / min** |
| [`HomePage.tsx:56,71,106,133,258`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/customer/HomePage.tsx#L56-L258) | `/canteens` (15s), `/categories` (8s), `/items` (8s), `/recommendations` (10s), `/orders/my` (20s) | **`8s – 20s`** | 11, 1, 11, 4, 21 | 27.0 | **258 / min** |
| [`Navbar.tsx:72,111`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/components/layout/Navbar.tsx#L72-L111) | `GET /api/v1/notifications/my` (20s) + SSE `/realtime/notifications/stream` (0.9s) | **`20,000 ms`** + **`900 ms` SSE** | 12 | 3.0 (+66.7 SSE) | **760 / min** |
| [`OrdersUsersTab.tsx:67`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/admin/components/OrdersUsersTab.tsx#L67) | `GET /api/v1/admin/orders` | **`5,000 ms`** (or `30s` live) | **235** (at 25 orders) | 2.0 – 12.0 | **470 – 2,820 / min** |
| [`AdminConsolePage.tsx:95`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/admin/AdminConsolePage.tsx#L95) | `GET /api/v1/reports/dashboard` | **`6,000 ms`** (or `30s` live) | **42** (+10 auth) | 2.0 – 10.0 | **104 – 520 / min** |
| [`CashierPOSPage.tsx:50,65,72`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/cashier/CashierPOSPage.tsx#L50-L72) | `/menus/.../items`, `/queue/canteens/{id}`, `/pos/orders/recent` | **`5s–8s`** (or `30s` live) | 11, 25, 18 | 6.0 – 28.5 | **108 – 510 / min** |

---

### Finding 4 (HIGH): `1 + 7N` N+1 Query Explosion in `GET /api/v1/admin/orders` and Unbatched Queries in Reports, Auth & Menus

- **Files & Functions Responsible:**
  - [`backend/app/api/admin/routes.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/admin/routes.py#L514) — `list_all_orders()` (Line 514)
  - [`backend/app/services/order_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/order_service.py#L239-L293) — `serialize_order()` vs `serialize_orders_batch()`
  - [`backend/app/services/report_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/report_service.py#L67-L220) — `get_analytics_report()` (Line 114 full ORM load + 42 queries)
  - [`backend/app/api/reports/routes.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/reports/routes.py#L187-L363) — `get_operations_control_center()` (21 queries + per-supplier PO/payment aggregation)
  - [`backend/app/services/menu_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/menu_service.py#L89-L114) — `compute_schedule_availability_map()` & `serialize_food_item()` (Line 193 per-item `db.get(KitchenStation)`)
  - [`backend/app/core/permissions.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/core/permissions.py) — `load_user_roles_and_permissions()` (`10 SQL queries` on every authenticated request)
- **Evidence from Source Code & SQL Profiler:**
  1. **`GET /api/v1/admin/orders` (`235 SQL queries` measured for 25 orders; up to `701 SQL queries` at `limit=100`):**
     Line 514 of [`backend/app/api/admin/routes.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/admin/routes.py#L514) calls:
     ```python
     return [order_service.serialize_order(db, o) for o in orders]
     ```
     even though `order_service.serialize_orders_batch(db, orders)` already exists at [`backend/app/services/order_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/order_service.py#L239)!
  2. **`GET /api/v1/reports/dashboard` (`42 SQL queries` + Python memory loop):**
     Line 114 of [`backend/app/services/report_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/report_service.py#L114) loads every confirmed `Order` ORM instance in the date range into Python memory (`paid_orders = db.scalars(select(Order).where(*paid_filters)).all()`) and iterates over them in Python to bucket daily, weekly, monthly, and hourly revenue.
  3. **Synchronous Expired-Slot Cleanup Inside Customer Read/Write Endpoints:**
     [`backend/app/services/order_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/order_service.py#L296) calls `release_expired_slot_reservations(db)` inside `list_pickup_slots()` (a public `GET` endpoint polled every `8,000ms` on `CheckoutPage.tsx:46`!) as well as on every `checkout_order()` call (Line 344).

---

### Finding 5 (MEDIUM): CPU-Intensive Hourly Cron Job (`/api/v1/admin/maintenance/run`) Doing Full-Database Gzip + Fernet Encryption & 1,000-Order Reconciliation

- **Files & Functions Responsible:**
  - [`vercel.json`](file:///C:/Users/HP/Desktop/collegebites/vercel.json#L24-L31) — `collegebites-hourly-maintenance` (`0 * * * *`)
  - [`backend/app/services/maintenance_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/maintenance_service.py#L72-L114) — `run_scheduled_maintenance()`
  - [`backend/app/services/reconciliation_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/reconciliation_service.py#L96-L140) — `run_auto_reconciliation()`
  - [`backend/app/services/backup_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/backup_service.py#L226-L317) — `create_backup()`
- **Evidence from Source Code:**
  - Every hour (`24 times/day`), `run_scheduled_maintenance()` runs `reconciliation_service.run_auto_reconciliation(db)`, which fetches up to `1,000` `Payment` + `Order` rows and their transactions/webhooks and performs per-row Python Decimal comparisons and DB upserts.
  - When the daily backup is due, `backup_service.create_backup()` (Lines 245–298) queries `SELECT *` on every application table, recursively scrubs dictionaries in Python (`_scrub_json_value`), serializes the entire database to a JSON string, compresses it at `gzip.compress(..., compresslevel=6)`, hashes it with SHA-256, and encrypts it with `Fernet` AES-128 in Python CPU before inserting the multi-megabyte encrypted string back into PostgreSQL (`BackupRecord.payload_encrypted`).

---

## 3. Recommended Optimizations & Estimated CPU Savings

> **All percentage reductions below are clearly labeled as engineering estimates** based on the measured request rates and SQL query counts per endpoint. Every recommendation preserves 100% of existing features (login, registration, menus, ordering, payments, 1s live token board responsiveness, QR/token verification, and all 8 RBAC roles).

| # | Optimization | Target Files | Preserves All Features? | Estimated Impact *(Estimate)* |
| :--- | :--- | :--- | :--- | :--- |
| **OPT-1** | **Keep One Reusable DB Session per SSE Stream & Increase SSE Watermark Sleep on Vercel from `0.9s` to `2.0s` (or use `QueuePool(pool_size=2, max_overflow=3)` per Lambda)** | [`backend/app/api/realtime/routes.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/realtime/routes.py#L127-L185), [`backend/app/core/database.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/core/database.py#L23-L30) | **Yes** — In-process `ws_manager` queue still wakes immediately (`0ms`) on same-instance events, and reusing 1 pooled connection across the 25s stream eliminates 26 redundant TCP/TLS handshakes per stream. | **Estimated 75%–85% reduction** in SSE Fluid Active CPU and Neon connection handshakes. |
| **OPT-2** | **Disable Duplicate 1s REST Polling When SSE is `"live"` & Set `refetchIntervalInBackground: false`** | [`TokenBoardPage.tsx:82`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/board/TokenBoardPage.tsx#L82), [`OperationalTokenBoardPage.tsx:281`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/board/OperationalTokenBoardPage.tsx#L281), [`PickupScannerPage.tsx:49`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/pickup/PickupScannerPage.tsx#L49) | **Yes** — When SSE is `"live"`, the board already receives instant server-pushed `board.snapshot` payloads; if SSE drops (`syncStatus !== "live"`), it automatically falls back to `1000ms` polling! | **Estimated 50%–65% reduction** in `/pickup/board` and `/pickup/token-board` function invocations. |
| **OPT-3** | **Eliminate Duplicate SSE Streams in the Same Browser Tab & Relax `HomePage` / `OperationsControlCenter` Polling** | [`Navbar.tsx:72,111`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/components/layout/Navbar.tsx#L72-L111), [`HomePage.tsx:56-258`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/customer/HomePage.tsx#L56-L258), [`OperationsControlCenterPanel.tsx:58`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/admin/components/OperationsControlCenterPanel.tsx#L58) | **Yes** — On `HomePage`, increase menu/category background refetch from `8s` to `30s–60s` (with `refetchOnWindowFocus: true`), and only poll `/notifications/my` when the notificationSSE stream is not `"live"`. | **Estimated 60%–75% reduction** in idle customer & admin tab background API calls. |
| **OPT-4** | **Fix `1 + 7N` N+1 Loop in `GET /api/v1/admin/orders` Using Existing `serialize_orders_batch(db, orders)`** | [`backend/app/api/admin/routes.py:514`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/admin/routes.py#L514) | **Yes** — Returns the exact same `list[OrderOut]` schema while using batch `WHERE id IN (...)` lookups. | **Estimated 90%–97% reduction** in SQL queries on `/admin/orders` (from `235–701` queries down to `7` queries). |
| **OPT-5** | **Add Short-TTL In-Memory / Redis Response Cache (`1s–15s`) for Public Read Endpoints & Principal Auth Cache (`15s`)** | [`pickup_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/pickup_service.py#L374), [`menu_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/menu_service.py#L287), [`permissions.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/core/permissions.py) | **Yes** — Cache is invalidated immediately on order/menu mutation or logout, while coalescing concurrent polls and avoiding 10 auth SQL queries on every poll. | **Estimated 65%–80% reduction** in Python ORM/Pydantic CPU across hot `GET` endpoints. |
| **OPT-6** | **Remove `release_expired_slot_reservations(db)` from `GET /orders/slots/{canteen_id}` & Incrementalize Hourly Auto-Reconciliation** | [`order_service.py:296`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/order_service.py#L296), [`reconciliation_service.py:120`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/reconciliation_service.py#L120) | **Yes** — Expired slots are already cleaned up during `checkout_order()` and hourly maintenance; reconciliation only needs to scan payments created/updated in the last 48 hours on hourly cron runs. | **Estimated 50%–70% reduction** in hourly cron CPU and checkout slot-polling DB writes. |

---

## 4. Safe, Staged Implementation Plan (Awaiting Approval)

No production files have been altered. Upon your approval, these optimizations can be rolled out safely in 3 low-risk phases on a dedicated branch:

1. **Phase 1 — Backend Database & SSE CPU Fixes (Zero UI Changes):**
   - Replace `NullPool` on Vercel in [`backend/app/core/database.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/core/database.py#L23-L24) with a small per-instance `QueuePool(pool_size=2, max_overflow=3, pool_pre_ping=True, pool_recycle=300)` (coupled with Neon's `-pooler` URL) so warm serverless instances and 25-second SSE loops reuse their open PostgreSQL connection instead of performing a new TCP/TLS handshake every `0.9s`.
   - Switch [`backend/app/api/admin/routes.py:514`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/admin/routes.py#L514) from `[order_service.serialize_order(db, o) for o in orders]` to `order_service.serialize_orders_batch(db, orders)`.
   - Batch-load `KitchenStation` in `menu_service.list_food_items()` and remove `release_expired_slot_reservations(db)` from the read-only `list_pickup_slots()` query.
2. **Phase 2 — Short-TTL Caching & Incremental Cron Maintenance:**
   - Add a `1.0s` in-process/Redis cache on `get_digital_token_board()` (invalidated on `emit_order_event_sync`) and a `15s` cache on `list_food_items()` / `list_canteens()`.
   - Scope `run_auto_reconciliation(trigger="vercel_schedule")` to payments updated within the last 48 hours instead of re-scanning 1,000 historical rows every hour.
3. **Phase 3 — Smart Frontend Polling Backoff (When SSE is Live / Tab Hidden):**
   - Set `refetchIntervalInBackground: false` across customer/admin tabs (keeping background refresh only for dedicated full-screen TV displays `/board`) and back off REST polling on `/token-board`, `/pickup`, and `Navbar` notifications when `syncStatus === "live"`.
   - Run the existing 58-test backend pytest suite and frontend Vitest/TypeScript build to verify zero regressions before deploying.
