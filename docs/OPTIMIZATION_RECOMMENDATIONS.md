# CollegeBites — Optimization Recommendations

## 1. Optimizations Already Implemented in This Release
1. **Lock-Free Sequences (`order_number_seq`, `invoice_number_seq`):** Eliminated global PostgreSQL advisory locks during checkout and invoice creation.
2. **Lazy ML Library Loading:** Removed eager top-level `scipy`/`sklearn` imports from FastAPI boot path, reducing cold-start time and Vercel Fluid Active CPU overhead while ensuring full portability across Windows/Linux hosts.
3. **Post-Commit Notification & Queue History Dispatch:** Moved external notification delivery and `QueueEstimateHistory` insertion outside payment confirmation DB row-lock windows.
4. **Route-Level Frontend Code Splitting:** Lazy-loaded `NotificationCenterPage` (2.88 kB gzip), `FoodSafetyPage` (4.85 kB gzip), `AIAssistantPage` (0.89 kB gzip), `ForecastingAssistantTab` (2.97 kB gzip), `InventoryPage`, `KitchenDisplayPage`, and `AdminConsolePage`.
5. **Deduplicated Correlation IDs (`X-Request-ID`) & Slow Request Telemetry:** Added end-to-end request tracing with slow-request warnings (>500 ms) and timeout guards.

## 2. Prioritized Next-Stage Production Scaling Recommendations
| Priority | Area | Recommendation | Expected Impact (Estimate) |
|---|---|---|---|
| **P0** | Payment Gateway Latency | Move synchronous `razorpay_gateway.create_order` / `razorpay_gateway.fetch_payment` HTTP calls to async `httpx.AsyncClient` with tight timeouts (≤5s) and circuit-breaker retries so slow external gateway calls never stall ASGI worker threads (directly observed in k6 Run A vs Run B!). | Eliminates threadpool starvation during checkout spikes (observed 4.2x–12.5x latency improvement in staging isolation). |
| **P0** | Production Multi-Worker + PostgreSQL | Run production with Neon PostgreSQL + PgBouncer transaction pooling + Redis (`REDIS_URL` / Upstash) and multiple ASGI workers (or Vercel Fluid Compute concurrency). | Removes SQLite 50-VU single-writer breaking point and enables horizontal scaling past 1,000+ campus users/min. |
| **P1** | Food Safety & BI Short-TTL Caching | Add 15–30s Redis L2 caching (with write invalidation) on `GET /api/v1/food-safety/dashboard` and `GET /api/v1/production/planning` matching `report_service.py` and `queue_service.py`. | Cuts repeated dashboard DB reads by ~70–85% during shift handovers. |
| **P1** | Background Task Offloading | Execute scheduled ML model retraining (`POST /api/v1/forecasting/train`), nightly overdue-cleaning alerts, and bulk notification retries via Celery / Vercel Schedules instead of synchronous admin HTTP requests. | Keeps interactive API latency sub-100ms during heavy ML retraining. |
| **P2** | Real Staging PostgreSQL Load Verification | Execute `performance-testing/enterprise-master/run_staging_k6_wal.py` against a dedicated staging PostgreSQL + Redis instance across 100 / 250 / 500 / 1,000 VUs before campus launch day. | Empirically validates multi-worker MVCC throughput prior to peak lunch traffic. |
