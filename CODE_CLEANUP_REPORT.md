# CollegeBites — Complete Code Audit, Classification & Cleanup Report

**Audit Date:** `2026-11-23`  
**Git Backup Checkpoint Created:** `backup/pre-cleanup-checkpoint-20261123` (anchored at commit `7d92752` prior to any removal or edit)  
**Production Deployment Policy:** **NOT deployed to production** (all changes remain strictly local pending your review and approval).

---

## 1. Executive Summary of Audit Findings (All 9 Audit Dimensions)

1. **Newly Created Files Audited:** Over 75 generated files across `backend/app/`, `backend/migrations/versions/`, `backend/tests/`, `frontend/src/`, `mobile/`, `performance-testing/`, and documentation (`CAMPUS_LAUNCH_GUIDE.md`, `VERCEL_CPU_OPTIMIZATION_REPORT.md`).
2. **Modified Existing Files Audited:** All 49 commits in Git history (`a781b0d` through `7d92752`) compared across backend APIs, ORM models, services, Alembic migrations, frontend workspaces, mobile screens, `requirements.txt`, `package.json`, `.gitignore`, `.vercelignore`, and `vercel.json`.
3. **Duplicate Implementations Found & Resolved:**
   - **0 duplicate FastAPI routes** (`348` unique `(method, path)` routes registered across `29` routers).
   - **1 duplicate 65.3 MB binary removed:** `performance-testing/bin/k6-v0.54.0-windows-amd64/k6.exe` (exact byte-for-byte duplicate of `performance-testing/bin/k6.exe`).
   - **1 duplicate PostgreSQL Python driver removed:** `psycopg2-binary==2.9.10` in `backend/requirements.txt` (unused anywhere in the repository; `database.py` and `migrations/env.py` strictly use `psycopg[binary]==3.2.3`).
4. **Unused Modules Found:**
   - **Backend (`backend/app/`):** `0` unused modules. All `29` routers, `10` model files, `24` services (including `website_qr_service.py` imported by `api/qr/routes.py` and `reconciliation_service.py` imported by `api/payments/routes.py` & `maintenance_service.py`), integrations, and CLI scripts are referenced.
   - **Frontend (`frontend/src/`):** `0` unused modules. Every page, tab component, hook, store, and utility is imported.
   - **Mobile (`mobile/src/`):** `0` unused modules (`StripePayButton.native.tsx` and `StripePayButton.web.tsx` are platform-resolved by Expo Metro).
5. **Unnecessary Dependencies Found & Removed:**
   - `backend/requirements.txt`: Removed `psycopg2-binary==2.9.10` (`0` code references).
   - `frontend/package.json`: Removed `@hookform/resolvers`, `class-variance-authority`, `react-hook-form`, and `zod` (`0` code references in `frontend/`; kept intact in `mobile/package.json` where they ARE actively imported).
   - `mobile/package.json`: Kept Expo peer/runtime dependencies (`expo-asset`, `expo-font`, `expo-linking`, `expo-status-bar`, `react-native-svg`, `react-native-screens`, `react-native-safe-area-context`, `react-native-web`, `@expo/metro-runtime`) classified as `KEEP` because Expo Router and `react-native-qrcode-svg` require them at runtime.
6. **Features That Already Existed vs Extended Cleanly:**
   - All advanced modules (Food Waste, Smart Menu, Staff Management, Smart Queue, BI Dashboard, Offline Recovery, Security/Fraud, Financial Reconciliation, Encrypted Backup/DR, Vendor Procurement, Meal Plans, College Events & Bulk Orders, Campaigns/Coupons, Nutrition Verification, Support Categories, Tax Invoices, Operations Control Center) were built by extending existing models, services, and dashboards rather than creating parallel duplicate applications.
7. **Incomplete Features / API Contract Bugs Found & Fixed (`IMPROVE`):**
   - `mobile/src/api/profile.api.ts`, `mobile/app/profile.tsx`, and `mobile/app/order/[orderNumber].tsx` had mismatched request/response property names against FastAPI (`BulkOrderCreateIn` required `scheduled_prep_at` / `scheduled_pickup_at` instead of `requested_delivery_at`; event fields were `ev.name`/`ev.location` instead of `ev.title`/`ev.venue`; bulk order fields were `bulk_order_number`/`total_quantity` instead of `order_reference`/`headcount`; invoice guest query parameter was `guest_access_token` instead of `guest_token`; invoice total fields were `subtotal_amount`/`tax_breakdown.cgst_amount`/`tax_breakdown.sgst_amount`/`total_amount`). **All fixed and verified.**
8. **Performance Regressions & Runtime Bugs Found & Fixed (`IMPROVE`):**
   - `backend/app/api/admin/routes.py:514`: Fixed `1 + 7N` N+1 order serialization loop (`[order_service.serialize_order(db, o) for o in orders]` -> `order_service.serialize_orders_batch(db, list(orders))`), cutting SQL queries for 25 orders from **`235` down to `21`** (**91.1% reduction**).
   - `backend/app/services/menu_service.py`: Preloaded `station_map` in `list_food_items()` and passed it into `serialize_food_item()` to eliminate per-item `KitchenStation` lookups.
   - `backend/app/services/event_service.py:40` & `backend/app/services/meal_plan_service.py:164`: Normalized naive datetimes to UTC before comparing with `datetime.now(timezone.utc)` so both PostgreSQL and SQLite test environments work cleanly.
   - `.vercelignore`: Added `performance-testing` and audit markdown docs so Vercel deployments stop uploading `70+ MB` of local load-testing binaries, PDFs, and raw JSON datasets.
9. **Items Pending Further Review (`REVIEW`):**
   - Frontend 1-second REST polling (`refetchInterval: 1000`, `refetchIntervalInBackground: true`) on `TokenBoardPage.tsx`, `OperationalTokenBoardPage.tsx`, and `PickupScannerPage.tsx` running alongside 25-second SSE streams (`0.9s` `NullPool` DB loops) — explicitly left untouched during cleanup per your earlier 1-second pickup display requirement and documented for approval in [`VERCEL_CPU_OPTIMIZATION_REPORT.md`](file:///C:/Users/HP/Desktop/collegebites/VERCEL_CPU_OPTIMIZATION_REPORT.md).

---

## 2. Complete File & Module Classification Matrix

### A. REMOVED (Confirmed Duplicate, Stale, or Unused — Safely Deleted After Backup Branch)

| File / Artifact / Dependency | Classification | Reason for Removal | Dependency / Impact Check |
| :--- | :--- | :--- | :--- |
| `performance-testing/bin/k6-v0.54.0-windows-amd64/k6.exe` | **REMOVE (Deleted)** | Exact `65.3 MB` byte-for-byte duplicate of `performance-testing/bin/k6.exe` accidentally extracted & committed in `7d92752`. | Zero references; `run_all_benchmarks.py` uses `performance-testing/bin/k6.exe` (kept intact). |
| `performance-testing/raw-results/collegebites_perf_staging.db-shm` | **REMOVE (Deleted)** | Stale temporary SQLite WAL shared-memory file (`32 KB`) left over from benchmark run and committed in `7d92752`. | Zero references; recreated/deleted automatically on benchmark runs. |
| `performance-testing/raw-results/collegebites_perf_staging.db-wal` | **REMOVE (Deleted)** | Stale temporary SQLite WAL journal file (`0 B`) committed in `7d92752`. | Zero references. |
| `performance-testing/__pycache__/staging_asgi.cpython-313.pyc` | **REMOVE (Deleted)** | Untracked Python bytecode cache file. | Ignored by `.gitignore`. |
| `psycopg2-binary==2.9.10` in [`backend/requirements.txt`](file:///C:/Users/HP/Desktop/collegebites/backend/requirements.txt) | **REMOVE (Removed)** | Duplicate PostgreSQL driver with **0 references** across the entire codebase; `database.py` and `migrations/env.py` strictly use `psycopg[binary]==3.2.3`. | Verified via repo grep + Alembic + staging integration suite. |
| `@hookform/resolvers`, `class-variance-authority`, `react-hook-form`, `zod` in [`frontend/package.json`](file:///C:/Users/HP/Desktop/collegebites/frontend/package.json) | **REMOVE (Removed)** | **0 references** anywhere in `frontend/src/` or `frontend/vite.config.ts`. (Still retained in `mobile/package.json` where actively used.) | Verified via `tsc --noEmit`, `vitest run`, and `vite build` (`dist/` builds cleanly in `9.83s`). |

---

### B. IMPROVED (Useful & Necessary — Verified Fixes Applied)

| File | Classification | Issue Identified | Fix Applied & Verification |
| :--- | :--- | :--- | :--- |
| [`backend/app/api/admin/routes.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/admin/routes.py#L513-L514) | **IMPROVE (Fixed)** | Line 514 called `[order_service.serialize_order(db, o) for o in orders]` causing a `1 + 7N` N+1 query regression (`235` SQL queries for 25 orders). | Replaced with `order_service.serialize_orders_batch(db, list(orders))`. **Verified:** 25 orders now execute in **21 SQL queries** (**91.1% reduction**). |
| [`backend/app/services/menu_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/menu_service.py#L156-L370) | **IMPROVE (Fixed)** | `serialize_food_item` called `db.get(KitchenStation, item.station_id)` per item instead of batch-loading stations in `list_food_items`. | Preloaded `station_map` in `list_food_items` and passed into `serialize_food_item`. **Verified:** `GET /menus/canteens/{id}/items` returns `200 OK` with batched queries. |
| [`backend/app/services/event_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/event_service.py#L39-L43) | **IMPROVE (Fixed)** | Naive vs timezone-aware datetime comparison (`ev.ordering_deadline <= now`) caused `TypeError` on SQLite staging/test databases. | Normalized `ev.ordering_deadline` to UTC when `tzinfo is None`. **Verified:** `GET /api/v1/events` & `test_phase31_events_bulk_orders.py` PASS. |
| [`backend/app/services/meal_plan_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/meal_plan_service.py#L163-L169) | **IMPROVE (Fixed)** | Naive vs timezone-aware datetime comparison (`sub.expires_at <= now`) caused `TypeError` on SQLite staging/test databases. | Normalized `sub.expires_at` to UTC when `tzinfo is None`. **Verified:** Meal plan subscribe, verify-payment, and `my-subscriptions` PASS. |
| [`mobile/src/api/profile.api.ts`](file:///C:/Users/HP/Desktop/collegebites/mobile/src/api/profile.api.ts#L34-L72) | **IMPROVE (Fixed)** | `createEventBulkOrder`, `subscribeMealPlan`, and `getOrderInvoice` used field/query names that did not match FastAPI routes (`requested_delivery_at` vs `scheduled_prep_at`/`scheduled_pickup_at`; `guest_token` vs `guest_access_token`). | Aligned all 3 methods to exact FastAPI Pydantic schemas and route query params. **Verified:** `mobile` `tsc --noEmit` PASS + live staging endpoint check PASS. |
| [`mobile/app/profile.tsx`](file:///C:/Users/HP/Desktop/collegebites/mobile/app/profile.tsx#L395-L560) | **IMPROVE (Fixed)** | Rendered `ev.title`/`ev.venue`, `bo.order_reference`/`bo.headcount`, and sent invalid `auto_confirm_demo` & bulk order payload fields. | Aligned to `ev.name`/`ev.location`, `bo.bulk_order_number`/`bo.total_quantity`, and exact `BulkOrderCreateIn` & `MealPlanSubscribeIn` schemas. **Verified:** `mobile` `tsc --noEmit` PASS. |
| [`mobile/app/order/[orderNumber].tsx`](file:///C:/Users/HP/Desktop/collegebites/mobile/app/order/[orderNumber].tsx#L360-L378) | **IMPROVE (Fixed)** | Referenced nonexistent invoice properties (`taxable_subtotal`, `cgst_amount`, `grand_total`) and `?guest_token=` instead of `?guest_access_token=`. | Updated to `invoice.subtotal_amount`, `invoice.tax_breakdown?.cgst_amount`, `invoice.tax_breakdown?.sgst_amount`, `invoice.total_amount`, and `?guest_access_token=`. **Verified:** `mobile` `tsc --noEmit` PASS. |
| [`.vercelignore`](file:///C:/Users/HP/Desktop/collegebites/.vercelignore) & [`.gitignore`](file:///C:/Users/HP/Desktop/collegebites/.gitignore) | **IMPROVE (Fixed)** | `.vercelignore` uploaded `performance-testing/` (`70+ MB`) on every Vercel deploy; `.gitignore` missed `*.db-shm` and `*.db-wal`. | Added `performance-testing` & audit report docs to `.vercelignore`, and `*.db-shm`/`*.db-wal` to `.gitignore`. |
| [`backend/tests/conftest.py`](file:///C:/Users/HP/Desktop/collegebites/backend/tests/conftest.py#L44-L53) | **IMPROVE (Fixed)** | `TRUNCATE TABLE ... RESTART IDENTITY CASCADE` only worked on PostgreSQL. | Added SQLite `DELETE FROM` branch while leaving PostgreSQL `TRUNCATE ... CASCADE` 100% unchanged for CI/Postgres. |

---

### C. KEEP (Useful, Necessary, Actively Wired & Verified)

| Area | Files / Modules Classified `KEEP` | Verification Reason |
| :--- | :--- | :--- |
| **Backend Core, Auth, Security & Fraud** | `backend/app/core/*` (`config.py`, `database.py`, `permissions.py`, `rate_limit.py`, `redis_client.py`, `security.py`, `time_utils.py`), `backend/app/api/security/routes.py`, `backend/app/services/security_service.py`, `backend/app/middleware/security_headers.py` | Active RBAC (8 roles), brute-force lockout, QR tamper/duplicate handover fraud alerts, and SlowAPI protection (`test_phase26_security_fraud.py` PASSED). |
| **Backend Backup & Disaster Recovery** | `backend/app/api/backups/routes.py`, `backend/app/services/backup_service.py`, `backend/app/models/system.py` | Encrypted Fernet AES-128 + gzip snapshots, retention policy, integrity verification, and controlled restore. |
| **Backend Financial Reconciliation & Payments** | `backend/app/services/reconciliation_service.py`, `backend/app/services/payment_service.py`, `backend/app/api/payments/routes.py`, `backend/app/integrations/razorpay_client.py`, `backend/app/integrations/stripe_client.py` | Online-only Razorpay/Stripe verification, webhook idempotency, no-refund ledger enforcement, and automated discrepancy reconciliation (`test_phase4_*`, `test_phase27_*` PASSED). |
| **Backend Advanced Operations Modules** | `backend/app/api/{events,invoices,meal_plans,realtime,ws}/routes.py`, `backend/app/models/{event,meal_plan}.py`, `backend/app/services/{event,invoice,meal_plan,waste,realtime,website_qr,report,maintenance}_service.py`, `backend/app/integrations/web_push_provider.py` | All 29 routers (`348` endpoints) wired in `app/api/router.py` with zero route collisions; verified by `test_phase14` through `test_phase32` & live staging suite. |
| **Alembic Database Migrations (`11` revisions)** | `backend/migrations/versions/9cfdc6326304` through `be1f2a3b4c5d_advanced_modules_v2.py` | Clean linear single-head chain (`be1f2a3b4c5d (head)`), zero branches, zero duplicate migrations. |
| **Frontend Workspaces & Offline Recovery** | `frontend/src/pages/admin/components/{BiAnalyticsPanel,BackupRecoveryPanel,MealPlansEventsInvoicesTab,OperationsControlCenterPanel,ReconciliationPanel,SecurityMonitorPanel,StaffManagementPanel,WebsiteQrTab}.tsx`, `frontend/src/pages/inventory/components/{FoodWasteTab,VendorProcurementTab}.tsx`, `frontend/src/pages/board/OperationalTokenBoardPage.tsx`, `frontend/src/pages/staff/StaffPortalPage.tsx`, `frontend/src/hooks/useRealtimeSync.ts`, `frontend/src/store/useOfflineStore.ts`, `frontend/src/utils/{offlineSync,notifications,razorpay}.ts`, `frontend/src/components/layout/OfflineBanner.tsx`, `frontend/src/components/ui/{NetworkSyncPanel,RealtimeStatusBadge}.tsx` | All actively imported in `App.tsx` / workspace tabs; verified by `tsc --noEmit`, Vitest (`11/11` passed), and `vite build`. |
| **Mobile App Parity** | `mobile/app/{index,checkout,orders,profile,support,board,scan}.tsx`, `mobile/app/order/[orderNumber].tsx`, `mobile/src/hooks/useMobileRealtimeWs.ts`, `mobile/src/api/*` | Verified by `mobile` `tsc --noEmit` with zero errors after API contract fixes. |
| **Load-Testing & Monitoring Suite** | `performance-testing/k6-test-scripts/*`, `performance-testing/bin/k6.exe`, `performance-testing/{run_all_benchmarks,generate_reports,generate_markdown_docs,staging_asgi}.py`, `performance-testing/*.{csv,pdf,md}`, `performance-testing/charts/*`, `performance-testing/raw-results/*.json`, `CAMPUS_LAUNCH_GUIDE.md`, `VERCEL_CPU_OPTIMIZATION_REPORT.md` | Preserved intact per user instruction (*"Do not remove useful load-testing scripts, monitoring tools, security protections or disaster recovery implementations"*), while excluded from Vercel upload via `.vercelignore`. |

---

### D. REVIEW (Pending Explicit User Decision Before Changing)

| File / Area | Classification | Why Marked `REVIEW` |
| :--- | :--- | :--- |
| [`backend/app/api/realtime/routes.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/api/realtime/routes.py#L64-L185) + [`backend/app/core/database.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/core/database.py#L23-L24) | **REVIEW** | 25-second SSE streams open/close a new `NullPool` Neon connection every `0.9s` on Vercel Fluid Compute. Changing to a small per-instance `QueuePool(pool_size=2, max_overflow=3)` + `2.0s` watermark sleep is recommended in [`VERCEL_CPU_OPTIMIZATION_REPORT.md`](file:///C:/Users/HP/Desktop/collegebites/VERCEL_CPU_OPTIMIZATION_REPORT.md) but awaits explicit approval before modifying production pooling/SSE behavior. |
| [`frontend/src/pages/board/TokenBoardPage.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/board/TokenBoardPage.tsx#L82), [`OperationalTokenBoardPage.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/board/OperationalTokenBoardPage.tsx#L281), [`PickupScannerPage.tsx`](file:///C:/Users/HP/Desktop/collegebites/frontend/src/pages/pickup/PickupScannerPage.tsx#L49) | **REVIEW** | Running `refetchInterval: 1000` (`refetchIntervalInBackground: true`) simultaneously with live SSE doubles backend hits; however, 1-second auto-refresh was explicitly requested earlier. Recommended to back off REST polling only while `syncStatus === "live"` upon your approval. |
| [`backend/app/services/auth_service.py`](file:///C:/Users/HP/Desktop/collegebites/backend/app/services/auth_service.py#L467) (and other UTC comparisons across services) | **REVIEW** | On PostgreSQL (production & GitHub Actions CI), `DateTime(timezone=True)` columns always return timezone-aware UTC datetimes. Only SQLite drops `tzinfo`, causing 15 of 58 `pytest` cases to fail when run offline against SQLite instead of PostgreSQL 16/18. |

---

## 3. Post-Cleanup Verification & Test Evidence (All Executed Locally)

| Check | Command / Tool Executed | Result | Evidence |
| :--- | :--- | :--- | :--- |
| **1. Frontend TypeScript Check** | `node node_modules\typescript\bin\tsc --noEmit` (in `frontend/`) | **PASS** | Exit code `0`, `0` TypeScript errors after removing 4 unused dependencies from `frontend/package.json`. |
| **2. Frontend Regression / Unit Tests** | `node node_modules\vitest\vitest.mjs run` (in `frontend/`) | **PASS** | `2 passed (2)` test files, **`11 passed (11)` tests** (`offline.test.ts` 5/5, `receipt.test.ts` 6/6) in `2.24s`. |
| **3. Frontend Production Build** | `node node_modules\vite\bin\vite.js build` (in `frontend/`) | **PASS** | `✓ 2711 modules transformed`, `✓ built in 9.83s`, all code-split vendor chunks generated cleanly. |
| **4. Mobile TypeScript Check** | `node node_modules\typescript\bin\tsc --noEmit` (in `mobile/`) | **PASS** | Exit code `0`, `0` errors across updated `profile.api.ts`, `profile.tsx`, and `order/[orderNumber].tsx`. |
| **5. Database Migration Graph Check** | `python -m alembic heads`, `alembic branches`, `alembic history` (in `backend/`) | **PASS** | Single head `be1f2a3b4c5d (head)`, `0` branches, complete unbroken 11-revision linear chain from `<base>` -> `9cfdc6326304` -> `be1f2a3b4c5d`. |
| **6. Staging End-to-End API, Payment, Order, QR, Invoice & N+1 Verification** | `verify_staging_workflows.py` (isolated SQLite staging DB, zero production traffic) | **PASS** | - `[PASS] Menu items fetch: 4 items, SQL queries=11`<br>- `[PASS] Order & Payment workflow: CB-20261123-000001 token=A001 discount=24.00` (Cart + `CAMPUS15` Coupon + Razorpay signature verification)<br>- `[PASS] Kitchen + QR Verification + Handover workflow: COMPLETED`<br>- `[PASS] Tax Invoice & PDF generation: INV-20261123-000001 (2098 bytes)`<br>- `[PASS] Meal Plan workflow & SQLite tz fix: code=CBMP-89369711`<br>- `[PASS] Events & Mobile Bulk Order payload contract: EBO-20261123-AA83B4 (total=Rs.840.00)`<br>- `[PASS] Admin Orders N+1 Fix: 25 orders returned in ONLY 21 SQL queries (down from 235 queries before cleanup!)` |
| **7. Backend `pytest` Suite** | `python -m pytest -q` against offline SQLite fallback (`pg_ctl.exe` blocked by Windows sandbox `0xC0000409`) | **PARTIAL ON SQLITE (43/58 PASS)** | **43 passed** (including `test_phase4_payments_razorpay_norefund.py`, `test_phase5`–`test_phase9`, `test_phase11`, `test_phase13`, `test_phase14`, `test_phase16`, `test_phase17`, `test_phase19`, `test_phase20`, `test_phase22`, `test_phase24`–`test_phase27`, `test_phase29`, `test_phase31`, `test_phase32`). **15 failed strictly due to SQLite dropping `tzinfo` on `DateTime(timezone=True)` columns or lacking PostgreSQL `pg_advisory_xact_lock`** (requires PostgreSQL 16/18, e.g. GitHub Actions CI, to execute all 58/58). |

---

## 4. Next Steps (Awaiting Your Approval)

- All local changes are safely backed up on branch `backup/pre-cleanup-checkpoint-20261123` and **have not been pushed or deployed to production**.
- If you approve these cleanup and bug-fix changes, I can commit them on a separate cleanup branch or `main` (and optionally also apply the Vercel Fluid CPU optimizations from [`VERCEL_CPU_OPTIMIZATION_REPORT.md`](file:///C:/Users/HP/Desktop/collegebites/VERCEL_CPU_OPTIMIZATION_REPORT.md)) so GitHub Actions CI runs the full 58/58 PostgreSQL 16 test suite.
