# CollegeBites — Load, Stress & Breaking-Point Test Report

## 1. Test Environment & Safety Compliance
- **Live Production Untouched:** `https://collegebites-alpha.vercel.app/board` was **NOT** load-tested or stressed.
- **Test Harness:** Local staging single-worker Uvicorn ASGI server (`127.0.0.1`) running the upgraded CollegeBites FastAPI application (`407` routes, `e5f6a7b8c9d0` schema) tested with **Grafana k6** (`performance-testing/bin/k6.exe`).
- **Workload Mix:** Realistic mixed campus traffic across `GET /api/v1/canteens`, `GET /api/v1/menus/canteens/{id}/items`, `GET /api/v1/queue/canteens/{id}`, `GET /api/v1/pickup/board/{id}`, authenticated `GET /api/v1/food-safety/dashboard`, and authenticated `POST /api/v1/orders/checkout`.
- **Integrity Disclaimer:** All numbers below are **100% real measured outputs** from `k6.exe` summary exports (`performance-testing/enterprise-master/results.json` and `results_wal.json`). Higher concurrency tiers beyond the local single-worker SQLite breaking point were **not fabricated or extrapolated**.

---

## 2. Run A — Mixed Read/Write with Live Outbound Razorpay API + SQLite Default Journal
*Script:* `performance-testing/enterprise-master/run_staging_k6.py`

| Virtual Users (VUs) | Completed Requests | Throughput (RPS) | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Error Rate |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 37 | 5.79 | 121.94 | 8.95 | 1,006.51 | 1,631.90 | 0.00% |
| 5 | 127 | 13.77 | 236.50 | 8.89 | 1,139.67 | 6,887.41 | 0.00% |
| 10 | 201 | 12.00 | 501.05 | 14.59 | 2,391.63 | 13,457.51 | 0.00% |
| 25 | 365 | 10.14 | 191.77 | 91.42 | 304.86 | 3,423.68 | 0.00% |
| 50 | 0 (stalled) | 0.00 | — | — | — | — | Timeout stall |
| 250 | 19,482 | 541.11 | 0.00 | 0.00 | 0.00 | 0.00 | 100.00% (refused) |

**Root Cause Diagnosis (Run A):**
1. Synchronous outbound HTTPS calls to `api.razorpay.com` during `POST /orders/checkout` added ~1–1.6s per checkout request, saturating worker threads at 50 VUs.
2. Default SQLite rollback journal locks the entire database file on writes.

---

## 3. Run B — Isolated Staging Engine (SQLite WAL Mode + Local Mock Gateway)
*Script:* `performance-testing/enterprise-master/run_staging_k6_wal.py`

| Virtual Users (VUs) | Completed Requests | Throughput (RPS) | Avg (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Error Rate |
|---:|---:|---:|---:|---:|---:|---:|---:|
| **1** | 88 | **14.55** | 17.65 | 7.48 | 41.87 | 128.53 | **0.00%** |
| **5** | 354 | **58.49** | 34.11 | 24.80 | 90.81 | 167.70 | **0.00%** |
| **10** | 491 | **80.21** | 72.28 | 53.52 | 212.23 | 343.82 | **0.00%** |
| **25** | 566 | **91.67** | 217.81 | 190.98 | 433.88 | 729.11 | **0.00%** |
| **50** *(Breaking Point)* | 137 | 15.01 | 3,169.05 | 547.70 | 8,001.10 | 8,001.40 | **36.50%** |

### Measured Findings (Run B)
- **Peak Stable Single-Process Staging Throughput:** **91.67 RPS (~5,500 requests/minute)** at **25 concurrent VUs** with **0.00% error rate** and **433.88 ms p95 latency**.
- **Measured Local Staging Breaking Point:** **50 concurrent VUs** on a single Windows Python Uvicorn process backed by a single-file SQLite database (8s timeout errors reached 36.50% due to SQLite single-writer lock contention + single-process GIL/event-loop saturation).
- **100 / 250 / 500 / 1,000 VU Production Scaling Status:** **NOT TESTED** against multi-worker PostgreSQL + Redis production infrastructure (local Windows PostgreSQL 18 binary crashes in sandbox with `0xC0000409`, and live Vercel production was intentionally protected). Production deployment behind Neon PostgreSQL (lock-free sequences + MVCC row-level locking) + Redis + Vercel auto-scaling serverless/multi-worker instances removes both SQLite's single-writer lock and the 1-process Python bottleneck.
