# CollegeBites — Payment Reliability & Ledger Integrity Report

## 1. Supported Payment Flows
- **Online Customer Checkout:** Razorpay (`razorpay`) ONLY. Historical ledger/payment audit rows are preserved immutably in PostgreSQL.
- **Walk-in Cashier Digital POS:** `upi_pos` and `card_pos` only.
- **Disabled Methods:** `cash`, `pay_at_pickup`, and non-Razorpay online gateways are strictly rejected (`HTTP 400`/`422`) across checkout, counter collection, POS, and admin settings.
- **Pricing Model:** Exact listed prices (`discount_amount = 0.00`, `tax_amount = 0.00`, statutory tax-inclusive notice on all receipts and invoices).

## 2. Atomic Finalization & Idempotency Guarantees
1. **Checkout Creation (`order_service.py`):**
   - Uses `Order.idempotency_key` to prevent duplicate orders on double-taps or network retries.
   - Generates order numbers via lock-free PostgreSQL sequence `order_number_seq` (eliminating global `pg_advisory_xact_lock` bottleneck).
   - Atomically reserves pickup slot capacity and non-expired ingredient stock (`SELECT ... FOR UPDATE`).
2. **Payment Verification & Webhooks (`payment_service.py`):**
   - Locks `Order` before `Payment` consistently across both callback verification and webhook handlers to eliminate deadlocks.
   - Deduplicates webhook deliveries via `PaymentWebhookEvent(provider, event_id)` nested transaction guard.
   - Validates gateway settled amount and currency against `Payment.amount` and `Payment.currency`; flags discrepancies in `PaymentReconciliation` + `SecurityAlert`.
   - Blocks duplicate `provider_payment_id` reuse (`409`) and flags late captures on `CANCELLED`/`REJECTED`/`PAYMENT_FAILED` orders (`409` + `late_capture_conflict` + critical `duplicate_payment_investigation` notification).
   - Issues pickup token, signed QR code, receipt, lock-free invoice (`invoice_number_seq`), and idempotent inventory deduction (`Order.inventory_deducted` + `StockMovement` guard) inside one atomic transaction.
3. **Post-Commit Side Effects:**
   - Notifications (`notify_order_confirmed`, `notify_payment_failed`) and `QueueEstimateHistory` snapshotting execute **after** `db.commit()` so external SMTP/SMS/Push latency never holds database row locks.
4. **Failure & Timeout Recovery:**
   - Payment failures (`mark_payment_failed`) and expired checkout windows (`release_expired_slot_reservations`) cleanly release pickup slots, release ingredient reservations, restore unpaid loyalty points, record `PaymentTransaction(status="FAILED")`, and dispatch customer failure alerts with safe retry support (`POST /api/v1/payments/retry/{order_id}`).

## 3. Verification Status
- Pricing & exact-total checkout verification: **PASSED** (`test_phase34_pricing_and_two_counters.py` — 17/17 tests passed).
- Payment signature verification, duplicate/late callback alerts, queue estimate snapshotting, and lock-free order sequence uniqueness: **VERIFIED** in Phase 35 test suite.
- Live Razorpay settlement testing against real bank rails: **NOT TESTED** in local sandbox (HMAC + mocked gateway status verification used to avoid real financial charges).
