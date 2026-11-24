# CollegeBites — Food Safety, Traceability & Recall Documentation

## 1. Food Safety & Hygiene Compliance (`/api/v1/food-safety`)
- **Daily Hygiene Checklists:**
  - Configurable templates (`FoodSafetyChecklistTemplate`) seeded with 10 standard hygiene inspection domains (kitchen surfaces, equipment sanitization, temperature checks, storage separation, staff hygiene, water safety, waste disposal, pest control, expiry/FEFO check, serving counter hygiene), with full `GET`/`POST`/`PATCH`/`DELETE` management (global `canteen_id=None` templates restricted to `super_admin`/`college_admin`).
  - Inspections (`FoodSafetyInspection`, `FoodSafetyInspectionItem`) validate canteen-owned templates, record `pass | fail | not_applicable` per item, inspector identity, timestamps, notes, optional photo URLs, and export printable PDF reports (`GET /inspections/{id}/pdf`) with full wrapped notes and photo evidence references.
  - Failed items automatically dispatch high/critical Notification Center alerts to `food_safety_inspector`, `canteen_manager`, `college_admin`, and `kitchen_staff`.
- **Equipment Temperature Monitoring:**
  - Admin/manager configures explicit per-equipment safe operating ranges (`min_temp_c < max_temp_c`, optional policy/OEM reference) — the system never invents universal thresholds.
  - Every logged temperature (`EquipmentTemperatureLog`) is evaluated against configured bounds; violations immediately raise critical alerts.
- **Expiry Monitoring & Safe Disposal:**
  - Reuses existing `StockBatch` + `InventoryItem` tables to surface `expired_batches` and `approaching_expiry_batches` (default ≤ 7 days).
  - `POST /batches/{batch_id}/dispose` zeroes remaining stock, marks batch `blocked`, updates `InventoryItem.current_quantity`, records `WastageRecord` (`loss_type="expired"` for expired batches or `"damaged"` for non-expired early disposal) and `StockMovement`, and refreshes menu item sufficiency.
- **Cleaning Schedules & Food Safety Incidents:**
  - Supports `daily | weekly | monthly` schedules with automatic next-occurrence creation upon completion, overdue detection, scheduled hourly Celery/maintenance overdue reminders, and full incident lifecycle (`open → under_investigation → resolved → closed`) with closed-state immutability, mandatory corrective action/resolution notes, and `GET /incidents/{id}/audit-history`.
- **Zero-Fabrication Compliance Dashboard:**
  - Returns strictly actual database counts; counts ALL currently overdue cleaning tasks and ALL currently open/under-investigation incidents regardless of lookback window; when 0 inspections exist, `inspection_pass_rate_percent` is `null` with an explicit empty-state notice.

## 2. Food Traceability & Batch Tracking (`/api/v1/traceability`)
- **Batch Metadata & Movements:** Tracks vendor (`supplier_id`), `purchase_order_id`, `goods_receipt_id`, `manufacturing_date` (optional, never fabricated), `expiry_date` (optional), `storage_location`, `quality_status` (`pending | approved | rejected | blocked | recalled`), `allocated_quantity`, `consumed_quantity`, `rejected_quantity`, `wasted_quantity`, `remaining_quantity`, and computed `available_quantity` (`0.000` when expired, blocked, rejected, or recalled). Per-batch movement history is exposed via `GET /batches/{id}/movements`.
- **FIFO / FEFO Enforcement:**
  - `allocate_stock_batches(..., strategy="FEFO"|"FIFO")` executes under `SELECT ... FOR UPDATE`.
  - Automatically excludes `expired`, `rejected`, `blocked`, and `recalled` batches, and updates usable inventory & dish sufficiency immediately upon quality/recall changes.
  - Authorized override (`allow_override=True`) is restricted to `super_admin`, `college_admin`, and `canteen_manager`, requires a documented `override_reason` (≥ 5 chars), and writes an immutable audit log entry.
- **End-to-End Traceability Chains (`GET /batches/{id}/chain`, `GET /orders/{id}/chain`):**
  - Traces `Vendor → PO → GRN → StockBatch → Recipe → ProductionBatch → FoodItem → Order` (bounded to a realistic 3-day serving window after production).
  - Explicitly classifies chains as `complete` or `partial` and lists exact `missing_links` whenever upstream or downstream links do not exist.
- **Recall Management Workflow:**
  - `POST /recalls` immediately quarantines targeted stock batches (`blocked`), refreshes menu sufficiency, computes all impacted `ProductionBatch` and confirmed `Order` IDs, and enters `under_review`.
  - `POST /recalls/{id}/approve` (Manager/Admin/Inspector) activates `active_recall` and permanently marks impacted stock batches as `recalled` (completely un-allocatable).
  - `GET /recalls/{id}/report.pdf` generates a multi-page PDF traceability & recall dossier listing vendor/PO/GRN details, affected production batch codes, affected order numbers, investigation notes, and corrective actions.
