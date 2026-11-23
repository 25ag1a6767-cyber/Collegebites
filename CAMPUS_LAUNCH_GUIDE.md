# CollegeBites — Campus Launch & Real-World Operations Guide

**Live Production Platform:** https://collegebites-alpha.vercel.app  
**API Base URL:** https://collegebites-alpha.vercel.app/api/v1  
**Database Engine:** Neon Serverless PostgreSQL (Alembic Revision `be1f2a3b4c5d`)  
**Payment Policy:** Strictly Online Digital Payments Only (Razorpay UPI / Cards / NetBanking & Stripe). No cash, no pay-at-pickup, and no in-app refunds.

---

## 1. Live Production Workspaces & URLs

| Workspace | Live URL | Target Device / Display |
| :--- | :--- | :--- |
| **Customer Ordering Portal** | `https://collegebites-alpha.vercel.app/` | Student & Faculty smartphones / laptops |
| **Student Profile, Meal Plans & Event Bulk Orders** | `https://collegebites-alpha.vercel.app/profile` | Student & Event Organizer accounts |
| **Live Public Token Display Board** | `https://collegebites-alpha.vercel.app/board` | Large TV screen mounted above canteen pickup area (1-second auto-refresh) |
| **QR Location & Counter Scanner** | `https://collegebites-alpha.vercel.app/scan` | Customer camera scanner for table/counter/poster QR codes |
| **Customer Support Center** | `https://collegebites-alpha.vercel.app/support` | Ticket submission (`food_quality`, `missing_item`, `incorrect_order`, `payment_issue`, `order_issue`) |
| **Admin & Operations Control Center** | `https://collegebites-alpha.vercel.app/admin` | Super Admin, College Admin, Canteen Manager |
| **Inventory & Vendor Procurement** | `https://collegebites-alpha.vercel.app/inventory` | Inventory Manager, Canteen Manager, College Admin |
| **Kitchen Display System (KDS)** | `https://collegebites-alpha.vercel.app/kitchen` | Kitchen tablets / monitors (shows `EVENT BULK` badge for event catering) |
| **Cashier & Payment Verification Desk** | `https://collegebites-alpha.vercel.app/cashier` | Cashier desk terminal (online payment reconciliation & receipt lookup) |
| **Pickup Counter Scanner & Meal Plan Redeemer** | `https://collegebites-alpha.vercel.app/pickup` | Pickup counter tablet/scanner (verifies both Order Pickup QR Tokens and Student Meal Plan QR Passes) |

---

## 2. Role-Based Access Control (RBAC) Accounts

All 8 campus roles are pre-configured in PostgreSQL with strict route, API, and canteen-scope enforcement:

| Role | Email | Default Password | Scope & Responsibilities |
| :--- | :--- | :--- | :--- |
| **Super Admin** | `superadmin@collegebites.edu` | `Admin@12345` | Wildcard (`*`) access across all canteens, settings, security, backups, and staff |
| **College Admin** | `admin@collegebites.edu` | `Admin@12345` | College-wide operations, Operations Control Center, Website QR Poster generator, payment reconciliation, PO approvals, meal plans, events, invoices |
| **Canteen Manager** | `manager@collegebites.edu` | `Staff@12345` | Scoped to assigned canteen (`Main Canteen`): menu & nutrition verification, PO approvals, event bulk order approval & kitchen dispatch, waste & staff shifts |
| **Inventory Manager** | `inventory@collegebites.edu` | `Staff@12345` | Raw stock SKUs, Vendor & Procurement PO creation, Goods Receiving (GRN), wastage recording, selling-price requests |
| **Kitchen Staff** | `kitchen@collegebites.edu` | `Staff@12345` | Live KDS queue (`PLACED` → `ACCEPTED` → `PREPARING` → `READY`), prep timers, station availability |
| **Cashier** | `cashier@collegebites.edu` | `Staff@12345` | Online payment ledger verification, digital receipt & tax invoice lookup |
| **Pickup Counter Staff** | `pickup@collegebites.edu` | `Staff@12345` | Single-use Order QR/Token collection (`READY` → `COMPLETED`) and Student Meal Plan QR Pass redemption |
| **Student / Customer** | `student@collegebites.edu` | `Student@123` | Ordering, coupon vouchers (`CAMPUS15`), meal plan subscription & QR pass, event bulk ordering, tax invoice PDF download |

> **Security Note:** Before public campus launch, rotate the default staff passwords from `/profile` or `/admin` → **Staff & Shifts**.

---

## 3. End-to-End Operational Workflows

### A. Vendor & Procurement Lifecycle (`/inventory` & `/admin` → `Vendors & POs`)
1. **Vendor Onboarding:** Add or update supplier details, GST/tax ID, payment terms, and supplied categories.
2. **Purchase Order Creation:** Select vendor, add line items (ingredient SKU or supply description, quantity, unit cost, tax %), and submit for approval (`draft` → `pending_approval`).
3. **Manager Approval & Ordering:** Canteen Manager or College Admin approves (`approved`) and marks as dispatched to vendor (`ordered`). Download printable A4 Purchase Order PDF anytime.
4. **Goods Receiving (GRN):** When supplies arrive, record received, accepted, damaged, and rejected quantities. **Inventory stock automatically increments only for verified accepted quantities** with full `StockMovement` audit logs.
5. **Vendor Payments & Statements:** Record bank/UPI settlements (`NEFT`, `UPI`, `RTGS`) against POs and inspect real-time vendor balance statements.

### B. Student Meal Plans & Pickup Counter Redemption (`/profile`, `/admin`, `/pickup`)
1. **Publish Plans:** Admins configure semester/monthly/weekly meal plans in `/admin` → **Meal Plans, Events & Invoices** (e.g., *Monthly Campus Lunch Pass — 25 Meals*, *Weekly Light Bite Combo Pass — 12 Meals*).
2. **Student Subscription:** Students subscribe via `/profile` (Web or Mobile) using online checkout. Once payment is verified, a unique `CBMP-...` pass code and signed QR code are generated.
3. **Counter Redemption:** At the canteen counter, Pickup Staff scan the student's Meal Plan QR Pass (or type `CBMP-...`) in `/pickup` → **Student Meal Plan Pass Verification & Redemption**. The system enforces active status, expiry date, daily meal limit, and remaining balance in an atomic PostgreSQL transaction.

### C. College Events & Bulk Ordering (`/profile`, `/admin`, `/kitchen`)
1. **Publish Event:** Admins create campus events (e.g., *Annual Tech Symposium & Hackathon*) in `/admin` → **Meal Plans, Events & Invoices**.
2. **Organizer Submission:** Faculty or student organizers submit bulk catering requests with headcount, delivery venue, requested time, and menu items.
3. **Approval & Kitchen Dispatch:** Managers approve the bulk order and click **Confirm Payment** (or verify online checkout), which automatically dispatches a priority canteen `Order` tagged `[EVENT BULK ...]` directly to the **Kitchen Display System (`/kitchen`)** and generates an official **Tax Invoice**.

### D. Offers, Nutrition & Tax Invoices
- **Promotional Coupons:** Active coupon vouchers (such as `CAMPUS15` — 15% off up to ₹60 on orders ≥ ₹149) appear on the customer Home screen for 1-tap application and are re-validated at checkout.
- **Nutrition & Allergen Verification:** Managers update calories, macros (`protein_g`, `carbs_g`, `fat_g`, `fiber_g`), allergen tags, and toggle `nutrition_verified` in `/admin` → **Menu & QR**. Unverified dishes automatically display a clear estimation disclaimer.
- **Automated Tax Invoices:** Every payment-confirmed order automatically generates an immutable `Invoice` record (`INV-YYYYMMDD-XXXXXX`) with CGST/SGST breakdown and downloadable A4 PDF (`/api/v1/invoices/{order_id}/pdf`).

---

## 4. Automated Scheduled Maintenance & Backups

Configured in `vercel.json` under `schedules` (`collegebites-hourly-maintenance`, running hourly `0 * * * *` in `Asia/Kolkata` against `/api/v1/admin/maintenance/run`):
- Purges expired OTP codes, expired refresh tokens, and expired session records.
- Releases stale unpaid pickup slot reservations.
- Automatically transitions past-due `StudentMealSubscription` rows (`expires_at <= now`) to `expired`.
- Scans all active canteens for low-stock and expiring ingredient batches and dispatches in-app notifications to Inventory Managers.
- Executes automated financial reconciliation across payments and orders, logging any discrepancies.
- Triggers scheduled encrypted PostgreSQL snapshots when due.
