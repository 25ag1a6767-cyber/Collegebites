# CollegeBites — Database Performance & Schema Optimization Report

## 1. Schema & Indexing Audit (`f6a7b8c9d0e1`)
- **Database Engine:** PostgreSQL 16+ in production (Neon serverless / PgBouncer pooled), SQLAlchemy 2.0 ORM, **132 tables**, Alembic single migration head `f6a7b8c9d0e1` (chaining off `e5f6a7b8c9d0`).
- **Zero-Duplication Extensions:** Extended existing `notifications`, `suppliers`, `stock_batches`, and `recipes` tables rather than duplicating operational records.
- **Composite Indexes Added for Hot Operational Queries:**
  - `ix_fs_insp_canteen_date` (`food_safety_inspections(canteen_id, inspected_at)`)
  - `ix_temp_logs_canteen_time` (`equipment_temperature_logs(canteen_id, recorded_at)`)
  - `ix_cleaning_tasks_canteen_due` (`cleaning_task_logs(canteen_id, due_at, status)`)
  - `ix_fs_incidents_canteen_status` (`food_safety_incidents(canteen_id, status, occurred_at)`)
  - `ix_prod_plan_canteen_date` (`production_plans(canteen_id, plan_date)`)
  - `ix_prod_batch_canteen_status` (`production_batches(canteen_id, status, created_at)`)
  - `ix_trace_stock_batch`, `ix_trace_prod_batch`, `ix_trace_order` (`traceability_records`)
  - `ix_reorder_rec_canteen_status` (`reorder_recommendations(canteen_id, status, created_at)`)
  - `ix_queue_est_canteen_created` (`queue_estimate_history(canteen_id, estimated_at)`) + `uq_queue_est_order`
  - `ix_forecast_models_canteen_active` (`forecast_models(canteen_id, is_active, trained_at)`)
  - `ix_demand_fc_canteen_date` & `ix_demand_fc_model_item` (`demand_forecasts`)
  - `ix_ai_audit_user_created` (`ai_assistant_audit_logs(user_id, created_at)`)
  - `ix_notif_deliveries_notif_status` (`notification_deliveries(notification_id, status)`)

## 2. Critical Contention Bottlenecks Eliminated
1. **Lock-Free Order & Invoice Number Generation:**
   - **Before:** `_generate_order_number` (`pg_advisory_xact_lock(918273645)`) and `_generate_invoice_number` (`pg_advisory_xact_lock(918273701)`) serialized ALL checkouts and payment confirmations behind a single global transaction-scoped lock.
   - **After:** Replaced with lock-free PostgreSQL `SEQUENCE` (`order_number_seq`, `invoice_number_seq`) via `nextval(...)` wrapped in `with db.begin_nested():` savepoints (preventing `InFailedSqlTransaction` if sequence auto-creation triggers on a fresh database) + thread-safe monotonic counter fallback on SQLite. Restore operations also resync both PostgreSQL sequences via `setval(...)` to prevent post-restore collisions.
2. **Canonical Row-Lock Ordering:**
   - Order verification & webhook handlers lock `Order` before `Payment`; stock transfers lock `InventoryItem` rows in canonical sorted `(canteen_id, ingredient_id)` order; `allocate_stock_batches` locks `StockBatch` under `SELECT ... FOR UPDATE` in deterministic FEFO/FIFO order.
3. **Post-Commit External Side Effects:**
   - External notification dispatch and `QueueEstimateHistory` recording execute **after** `db.commit()` in `_finalize_confirmed_payment`, eliminating long-held DB locks during SMTP/SMS/Push I/O.
4. **Batched Aggregations (Eliminating N+1 Queries):**
   - `report_service.py` collapses sales/operations KPIs into single-pass conditional SQL `GROUP BY` queries and column projections (`select(Order.created_at, ...)` instead of full ORM hydration).
   - `inventory_service.py` batches `Recipe`, `RecipeIngredient`, and expired batch sums in O(1) SQL queries during `refresh_food_item_ingredient_sufficiency`.

## 3. Connection Pooling & Production Tuning Notes
- `backend/app/core/database.py` configures SQLAlchemy pooling (`pool_pre_ping=True`, `pool_recycle`, configurable `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`) and exposes live pool stats via `GET /health/ready`.
- For sustained >50 concurrent write sessions in production, pair Neon/PostgreSQL with transaction-mode PgBouncer and external Redis (`REDIS_URL` / Upstash) so multi-worker/serverless instances share L2 cache and rate-limit counters.
