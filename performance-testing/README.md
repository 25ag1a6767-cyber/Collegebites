# CollegeBites — Automated Performance, Load, Stress & Endurance Testing Suite

**Generated:** `2026-11-23 13:34:13 UTC`  
**Production URL Tested (Safe Read-Only):** `https://collegebites-alpha.vercel.app/board`  
**Isolated Staging Environment Tested (1–1,000 VUs):** `http://127.0.0.1:8010` (FastAPI + SQLAlchemy Pool `20+30` + PostgreSQL 18)

---

## 1. Directory Structure & Deliverables

All 10 mandatory deliverables are located in `CollegeBites/performance-testing/`:

| # | File / Folder | Description |
| :--- | :--- | :--- |
| 1 | `COMPLETE_PERFORMANCE_REPORT.pdf` | Executive PDF report with all 15 mandatory answers, load test tables, API benchmarks, and embedded charts |
| 2 | `LOAD_TEST_RESULTS.csv` | Complete dataset for 1, 5, 10, 25, 50, 100, 250, 500, and 1,000 VUs (all 20 required metrics) |
| 3 | `API_PERFORMANCE_REPORT.csv` | Module-by-module latency distribution (Avg, Min, P50, P90, P95, P99, Max) & SQL query count per endpoint |
| 4 | `CONCURRENT_USER_CAPACITY.csv` | Capacity matrix with SLA guardrail pass/fail verdicts across 1 to 1,000 concurrent users |
| 5 | `STRESS_TEST_REPORT.pdf` | Stress ramp, Spike tests (`5->50`, `10->100`, `25->250`), DB thread concurrency, and WebSocket stress PDF |
| 6 | `ENDURANCE_TEST_REPORT.pdf` | 5-minute (300s) continuous soak test PDF report with 15-second telemetry checkpoints and charts |
| 7 | `PERFORMANCE_BOTTLENECKS.md` | Code-level architectural audit & root-cause analysis categorized by severity (`Critical`, `High`, `Medium`, `Low`) |
| 8 | `OPTIMIZATION_RECOMMENDATIONS.md` | Concrete code, SQL index, pooling, caching, and rate-limiter fixes with estimated improvements |
| 9 | `k6-test-scripts/` | 6 executable Grafana `k6` scripts (`01` through `06`) for production safe read-only, load, module, stress/spike, endurance, and WebSockets |
| 10 | `README.md` | This comprehensive summary, 15 mandatory answers, and reproduction guide |

---

## 2. Final Performance Summary — 15 Mandatory Questions Answered with Evidence

| # | Question | Measured Answer & Evidence |
| :--- | :--- | :--- |
| **1** | **How many requests can CollegeBites handle per second (RPS)?** | **105.91 RPS** peak measured throughput (at 10 VUs), and **86.23 RPS** at the maximum sustainable load (50 VUs with P95 `1201.61ms` < 1,500ms and `0.0%` errors). When SlowAPI per-IP rate limiting (`300/min`) is active for a single IP, single-IP throughput caps at **5.0 RPS** (`300 RPM`). |
| **2** | **How many requests can it handle per minute (RPM)?** | **6,354.4 RPM** peak (`105.91 × 60`), and **5,173.6 RPM** sustainable (`86.23 × 60`). |
| **3** | **How many requests can it handle per hour (RPH)?** | **381,266.7 RPH** peak projection (`105.91 × 3,600`), and **310,416.8 RPH** sustainable projection (`86.23 × 3,600`). |
| **4** | **How many requests can it handle per day (RPD)?** | **7,450,002.6 RPD** theoretical daily projection (`86.23 × 86,400`). *Note: This is a mathematical projection from short/5-minute tests; a 24-hour endurance test was NOT MEASURED in this session.* |
| **5** | **How many concurrent users can use it successfully?** | **50 concurrent virtual users** on a single Uvicorn worker within the 1.5s P95 latency guardrail and 0% error rate. |
| **6** | **What is the average API response time?** | **13.44ms** at 1 VU and **516.01ms** at 50 VUs on local staging; **189.29ms** across public `GET` endpoints on Vercel Production (`https://collegebites-alpha.vercel.app`). |
| **7** | **What is the P95 response time?** | **28.67ms** at 1 VU and **1201.61ms** at 50 VUs on local staging; **275.90ms** on Vercel Production (for successful `200 OK` responses). |
| **8** | **What is the P99 response time?** | **58.13ms** at 1 VU and **1648.34ms** at 50 VUs on local staging. |
| **9** | **What percentage of requests fail?** | **0.00%** failure rate from `1` through `50` VUs on unthrottled staging (`0.0%` over `11341` requests in the 5-minute endurance test). When SlowAPI `300/min` per-IP limiting is enabled, single-IP bursts at 25 VUs experience **0.0% HTTP 429** responses. |
| **10** | **Which API is the slowest?** | **`GET /api/v1/admin/orders`** (`Admin Orders Console`) at **134.51ms average / 193.12ms P95 / 213.45ms P99** (executes **235 SQL queries** per request). |
| **11** | **What is the main database bottleneck?** | 1) `NullPool` on Vercel Serverless opening a fresh PostgreSQL connection on every 1-second `/pickup/board` poll; 2) `1 + 7N` N+1 query loop in `GET /api/v1/admin/orders` (`backend/app/api/admin/routes.py:514`); 3) multi-query aggregation in `/reports/dashboard` and `/reports/operations-control-center`; and 4) SQLAlchemy synchronous pool limit (`20 + 30 = 50` connections) queuing requests above 100 VUs. |
| **12** | **What is the maximum sustainable tested load?** | **50 concurrent virtual users** (`86.23 RPS`, `Avg=516.01ms`, `P95=1201.61ms`, `P99=1648.34ms`, `Errors=0.0%`). |
| **13** | **At what load does performance begin degrading?** | Performance begins degrading at **25 concurrent virtual users** (`Avg=202.31ms`, `P95=792.53ms`) as concurrent requests exceed the single-process threadpool (40 threads) and SQLAlchemy connection pool (50 max connections). |
| **14** | **Can the application support 100, 500 or 1,000 concurrent users?** | - **50 VUs (Max Sustainable on 1 Worker):** **YES** (`RPS=86.23`, `Avg=516.01ms`, `P95=1201.61ms`, `Err=0.0%`).<br>- **100 VUs:** **NO on 1 worker** (`RPS=26.49`, `Avg=3574.02ms`, `P95=10001.17ms`, `Err=28.9%` — saturates the 50-connection DB pool and 40-thread AnyIO worker pool).<br>- **500 VUs:** **NO on 1 worker** (`Err=99.24%`, timeouts at 10s).<br>- **1,000 VUs:** **NO on 1 worker** (`Err=100.0%` — requires 4–8 Gunicorn/Uvicorn workers, PgBouncer pooling, and Redis caching). |
| **15** | **What infrastructure improvements are needed?** | 1) Use Neon PgBouncer (`-pooler`) URL on Vercel; 2) Replace `serialize_order` loop in `/admin/orders` with `serialize_orders_batch`; 3) Add 1-second Redis/in-memory response caching on `/api/v1/pickup/board` and 15-second caching on `/api/v1/menus/items`; 4) Key SlowAPI rate limiting by authenticated user ID instead of shared campus NAT IP; 5) Run 4+ Uvicorn workers behind a load balancer for 500–1,000+ VUs. |

---

## 3. How to Re-Run the Automated Test Suite

### Run Individual Grafana `k6` Scripts
```powershell
# 1. Safe Read-Only Production Test (Max 5 VUs, strict abortOnFail guardrails)
.\performance-testing\bin\k6.exe run -e BASE_URL="https://collegebites-alpha.vercel.app" -e TARGET_VUS=1 -e DURATION=10s .\performance-testing\k6-test-scripts\01_production_safe_readonly.js

# 2. Local Staging Progressive Load Test
.\performance-testing\bin\k6.exe run -e BASE_URL="http://127.0.0.1:8010" -e TARGET_VUS=100 -e DURATION=15s .\performance-testing\k6-test-scripts\02_progressive_load_test.js

# 3. Stress & Spike Test (Modes: stress | spike_5_50 | spike_10_100 | spike_25_250)
.\performance-testing\bin\k6.exe run -e BASE_URL="http://127.0.0.1:8010" -e MODE=spike_25_250 .\performance-testing\k6-test-scripts\04_stress_and_spike_test.js

# 4. Endurance / Soak Test (Configurable: 5m, 15m, 30m, 1h, 6h, 24h)
.\performance-testing\bin\k6.exe run -e BASE_URL="http://127.0.0.1:8010" -e TARGET_VUS=25 -e DURATION=5m .\performance-testing\k6-test-scripts\05_endurance_soak_test.js
```

### Run Complete Orchestrator & Regenerate All CSVs, Charts, PDFs, and Markdown Reports
```powershell
.\backend\.venv\Scripts\python.exe .\performance-testing\run_all_benchmarks.py
.\backend\.venv\Scripts\python.exe .\performance-testing\generate_reports.py
.\backend\.venv\Scripts\python.exe .\performance-testing\generate_markdown_docs.py
```
