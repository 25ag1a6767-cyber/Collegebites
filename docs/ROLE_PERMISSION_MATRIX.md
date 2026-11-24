# CollegeBites — Role & Permission Matrix

Source of truth: [`backend/app/core/permissions.py`](../backend/app/core/permissions.py) and enforced via `require_roles(...)`, `require_permission(...)`, and `enforce_canteen_scope(...)`.

## 1. Roles Overview

| Role Constant | Display Role | Canteen Scope | Primary Workspace |
|---|---|---|---|
| `super_admin` | Super Administrator | All canteens (`*`) | Admin Console (`/admin`), System & Audit |
| `college_admin` | College Administrator | All canteens (`*`) | Admin Console (`/admin`), Website QR Generator, College Settings |
| `canteen_manager` | Canteen Manager | Assigned canteen | Admin Console (Canteen-scoped), Selling Price Approvals |
| `cashier` | Cashier (POS) | Assigned canteen | Cashier POS (`/cashier`), Digital Walk-in POS (`upi_pos` / `card_pos`), Handover |
| `kitchen_staff` | Kitchen Staff | Assigned canteen | Kitchen Display (`/kitchen`) |
| `inventory_manager` | Inventory Manager | Assigned canteen | Inventory Portal (`/inventory`), Customer Menu Mgmt (price-restricted) |
| `pickup_staff` | Pickup Staff | Assigned canteen | Pickup Verification (`/pickup`) |
| `customer` | Universal Customer / Visitor | Self-owned orders | Customer Web / Mobile App (`/`) |

## 2. Backend Permission Assignment Matrix

| Role | Granted Permission Codes |
|---|---|
| `super_admin` | `*` (Wildcard full administrative & operational access) |
| `college_admin` | `college:manage`, `canteen:manage`, `menu:manage`, `staff:manage`, `customer:manage`, `order:view_all`, `order:manage`, `payment:view`, `payment:reconcile`, `inventory:manage`, `qr:manage`, `qr:website_manage`, `queue:manage`, `notification:manage`, `announcement:manage`, `promotion:manage`, `report:view`, `support:manage`, `kiosk:manage`, `audit:view` |
| `canteen_manager` | `canteen:manage_assigned`, `menu:manage`, `order:view_canteen`, `order:manage`, `kitchen:manage`, `staff:manage_canteen`, `inventory:manage`, `queue:manage`, `report:view_canteen`, `support:view`, `qr:manage` |
| `cashier` | `pos:use`, `order:create_walkin`, `order:view_canteen`, `payment:accept_counter`, `receipt:print`, `receipt:reprint`, `pickup:verify`, `pickup:handover`, `shift:manage_own` |
| `kitchen_staff` | `kitchen:view`, `kitchen:update_order`, `kitchen:report_delay`, `kitchen:report_unavailable` |
| `inventory_manager` | `inventory:manage`, `supplier:manage`, `purchase_order:manage`, `wastage:record`, `menu:manage_inventory` |
| `pickup_staff` | `pickup:verify`, `pickup:handover`, `order:view_canteen` |
| `customer` | `order:create`, `order:view_own`, `receipt:view_own`, `review:create`, `support:create_own`, `profile:manage_own` |

## 3. Critical Access Boundaries & Separation of Duties

1. **Selling Price Approval Gate (`inventory_manager` vs `canteen_manager` / `college_admin` / `super_admin`)**:
   - `inventory_manager` CAN update raw-material purchase/cost price directly (`POST /api/v1/inventory/items/{id}/purchase-price`).
   - `inventory_manager` CAN manage customer menu categories, add new menu items, edit non-price fields (`name`, `description`, `prep_time_minutes`, `is_veg`, `is_available`, `is_active`), and upload validated dish images (`POST /api/v1/menus/items/{id}/upload-image`).
   - `inventory_manager` CANNOT directly modify existing food item selling prices (`PATCH /api/v1/menus/items/{id}` with altered `base_price` returns HTTP `403`) and CANNOT self-approve `POST /api/v1/inventory/price-changes/{id}/review` (returns HTTP `403`). Only `canteen_manager`, `college_admin`, or `super_admin` may approve or reject selling price requests.
2. **Admin / Finance / Sales Report Isolation**:
   - `inventory_manager` receives HTTP `403` on `/api/v1/admin/users`, `/api/v1/admin/health`, `/api/v1/reports/dashboard`, and `/api/v1/payments`.
3. **Website QR Code Generator**:
   - Restricted strictly to `college_admin` and `super_admin` (`qr:website_manage` / `require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)`).
4. **Kiosk Self-Service Activation & Staff Control**:
   - Disabled by default; management limited to `super_admin`, `college_admin`, and scoped `canteen_manager`.
5. **Pickup Verification vs Handover**:
   - `POST /api/v1/pickup/verify` validates signed QR/token and returns current state without changing order state.
   - `POST /api/v1/pickup/handover` performs atomic `WITH FOR UPDATE` transition from `READY` to `COMPLETED` and blocks duplicate handovers (`ALREADY_COLLECTED`).
6. **Strict No-Cash / No-Refunds Policy**:
   - No role has refund permissions or refund endpoints (all refund attempts return `404`/`405`).
   - Online-only payments via Razorpay (`razorpay`) for customer/kiosk orders; POS walk-in supports digital counter methods (`upi_pos`, `card_pos`) only.
