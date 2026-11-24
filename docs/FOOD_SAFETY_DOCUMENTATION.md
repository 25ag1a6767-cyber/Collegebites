# CollegeBites — Food Safety, Traceability & Recall Documentation

## 1. Food Safety & Hygiene Compliance (`/api/v1/food-safety`)
- **Daily Hygiene Checklists:**
  - Configurable templates (`FoodSafetyChecklistTemplate`) seeded with 10 standard hygiene inspection domains (kitchen surfaces, equipment sanitization, temperature checks, storage separation, staff hygiene, water safety, waste disposal, pest control, expiry/FEFO check, serving counter hygiene).
  - Inspections (`FoodSafetyInspection`, `FoodSafetyInspectionItem`) record `pass | fail | not_applicable` per item, inspector identity, timestamps, notes, optional photo URLs, and export printable PDF reports (`GET /inspections/{id}/pdf`).
  - Failed items automatically dispatch high/critical Notification Center alerts to `food_safety_inspector`, `canteen_manager`, `college_admin`, and `kitchen_staff`.
- **Equipment Temperature Monitoring:**
  - Admin/manager configures explicit per-equipment safe operating ranges (`min_temp_c < max_temp_c`, optional policy/OEM reference) — the system never invents universal thresholds.
  - Every logged temperature (`EquipmentTemperatureLog`) is evaluated against configured bounds; violations immediately raise critical alerts.
- **Expiry Monitoring & Safe Disposal:**
  - Reuses existing `StockBatch` + `InventoryItem` tables to surface `expired_batches` and `approaching_expiry_batches` (default ≤ 7 days).
  - `POST /batches/{batch_id}/dispose` zeroes remaining stock, marks batch `blocked`, updates `InventoryItem.current_quantity`, records `WastageRecord(loss_type="expired")` and `StockMovement`, and refreshes menu item sufficiency.
- **Cleaning Schedules & Food Safety Incidents:**
  - Supports `daily | weekly | monthly` schedules, overdue detection, overdue reminder notifications, and full incident lifecycle (`open → under_investigation → resolved → closed`) with corrective action audit trails.
- **Zero-Fabrication Compliance Dashboard:**
  - Returns strictly actual database counts; when 0 inspections exist, `inspection_pass_rate_percent` is `null` with an explicit empty-state notice.

## 2. Food Traceability & Batch Tracking (`/api/v1/traceability`)
- **Batch Metadata:** Tracks vendor (`supplier_id`), `purchase_order_id`, `goods_receipt_id`, `manufacturing_date` (optional, never fabricated), `expiry_date` (optional), `storage_location`, `quality_status` (`pending | approved | rejected | blocked | recalled`), `allocated_quantity`, `consumed_quantity`, `rejected_quantity`, `wasted_quantity`, and `remaining_quantity`.
- **FIFO / FEFO Enforcement:**
  - `allocate_stock_batches(..., strategy="FEFO"|"FIFO")` executes under `SELECT ... FOR UPDATE`.
  - Automatically excludes `expired`, `rejected`, `blocked`, and `recalled` batches.
  - Authorized override (`allow_override=True`) is restricted to `super_admin`, `college_admin`, and `canteen_manager`, requires a documented `override_reason` (≥ 5 chars), and writes an immutable audit log entry.
- **End-to-End Traceability Chains (`GET /batches/{id}/chain`, `GET /orders/{id}/chain`):**
  - Traces `Vendor → PO → GRN → StockBatch → Recipe → ProductionBatch → FoodItem → Order`.
  - Explicitly classifies chains as `complete` or `partial` and lists exact `missing_links` whenever upstream or downstream links do not exist.
- **Recall Management Workflow:**
  - `POST /recalls` immediately quarantines targeted stock batches (`blocked`), computes all impacted `ProductionBatch` and confirmed `Order` IDs, and enters `under_review`.
  - `POST /recalls/{id}/approve` (Manager/Admin/Inspector) activates `active_recall` and permanently marks impacted stock batches as `recalled` (completely un-allocatable).
  - `GET /recalls/{id}/report.pdf` generates a formal PDF traceability & recall dossier.
