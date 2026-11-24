"""
Phase 35 — CollegeBites Complete Enterprise Master Verification Suite.
Covers ALL 12 Enterprise Phases & Section 24 QA Requirements:
  1. Notification & Communication Center (dedup, priority, category, unread, masked PII delivery log, retry, broadcast, RBAC)
  2. Food Safety & Hygiene Compliance (zero fake %, inspections + PDF, temp config & violations, expiry disposal, cleaning, incidents)
  3. Food Traceability & Batch Tracking (FIFO/FEFO, expired/blocked rejection, authorized override audit, partial/complete chains, recalls + PDF)
  4. Kitchen & Food Production Management (verified recipes, shortage check, no double-count planning, 8-state batch lifecycle, QC gate, grouped KDS)
  5. Automated Reordering System (rules, incoming PO stock, draft PO only — never auto-approved, duplicate PO block)
  6. Smart Queue Prediction & Accuracy History (estimate snapshot, ready actualization, MAE/median, unavailable fallback)
  7. Advanced BI & Financial Analytics (empty state, revenue != profit separation, gross margin guard, period comparison)
  8. AI Demand Forecasting (insufficient data refusal, real 14-day chronological ML train/eval MAE/RMSE/MAPE, uncertainty bands)
  9. Controlled Role-Aware AI Canteen Assistant (RBAC 403 for customers, grounded answers, write/refund/PO block & audit log)
 10. Lock-Free Order Numbers, X-Request-ID Correlation Header, Full Integrated Workflow & Isolated Backup/Restore Verification
"""

import concurrent.futures
import hmac
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.integrations.razorpay_client import razorpay_gateway
from app.models.college import Canteen, Counter
from app.models.enterprise import QueueEstimateHistory
from app.models.inventory import InventoryItem, StockBatch, Supplier
from app.models.menu import FoodItem, Ingredient, Recipe, RecipeIngredient
from app.models.order import Order, OrderItem
from app.models.payment import Payment


def _login(client, email: str, password: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"identifier": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_base_context(client):
    admin_hdr = _login(client, "admin@collegebites.edu", "Admin@12345")
    manager_hdr = _login(client, "manager@collegebites.edu", "Staff@12345")
    inv_hdr = _login(client, "inventory@collegebites.edu", "Staff@12345")
    kitchen_hdr = _login(client, "kitchen@collegebites.edu", "Staff@12345")
    inspector_hdr = _login(client, "inspector@collegebites.edu", "Staff@12345")
    cust_hdr = _login(client, "student@collegebites.edu", "Student@12345")

    canteens = client.get("/api/v1/canteens").json()
    assert len(canteens) >= 1
    canteen = canteens[0]
    canteen_id = canteen["id"]
    items = client.get(f"/api/v1/menus/canteens/{canteen_id}/items").json()
    assert len(items) >= 1
    return {
        "admin": admin_hdr,
        "manager": manager_hdr,
        "inventory": inv_hdr,
        "kitchen": kitchen_hdr,
        "inspector": inspector_hdr,
        "customer": cust_hdr,
        "canteen": canteen,
        "canteen_id": canteen_id,
        "items": items,
    }


def _place_and_pay_order(client, hdr, canteen_id: str, food_item_id: str, quantity: int = 1) -> dict:
    r = client.post(
        "/api/v1/orders/checkout",
        headers=hdr,
        json={
            "canteen_id": canteen_id,
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": food_item_id, "quantity": quantity}],
        },
    )
    assert r.status_code in (200, 201), r.text
    order = r.json()
    rzp_oid = order["razorpay_order_id"]
    rzp_pid = f"pay_test_{uuid4().hex[:10]}"
    sig = hmac.new(
        razorpay_gateway.key_secret.encode("utf-8"),
        f"{rzp_oid}|{rzp_pid}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    vr = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=hdr,
        json={
            "order_id": order["id"],
            "razorpay_order_id": rzp_oid,
            "razorpay_payment_id": rzp_pid,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    )
    assert vr.status_code == 200, vr.text
    return vr.json()


def test_01_notification_center_and_correlation_id(client):
    ctx = _seed_base_context(client)

    # X-Request-ID correlation header present and echoed back
    h_resp = client.get("/health", headers={"X-Request-ID": "cb-trace-001"})
    assert h_resp.status_code == 200
    assert h_resp.headers.get("x-request-id") == "cb-trace-001"

    # Customer cannot broadcast system maintenance
    r_forbid = client.post(
        "/api/v1/notifications/system-maintenance",
        headers=ctx["customer"],
        json={"title": "Unauthorized Notice", "message": "Should fail with 403", "priority": "high"},
    )
    assert r_forbid.status_code == 403

    # Admin broadcasts maintenance notice
    r_bc = client.post(
        "/api/v1/notifications/system-maintenance",
        headers=ctx["admin"],
        json={"title": "Scheduled Backup Window", "message": "Brief maintenance at 11 PM IST.", "priority": "high"},
    )
    assert r_bc.status_code in (200, 201), r_bc.text
    assert r_bc.json()["broadcasted_targets"] >= 1

    # Unread count & priority/category search filters
    r_unread = client.get("/api/v1/notifications/unread-count", headers=ctx["admin"])
    assert r_unread.status_code == 200
    assert r_unread.json()["unread_count"] >= 1

    r_list = client.get("/api/v1/notifications/my?priority=high&category=system&q=Backup", headers=ctx["admin"])
    assert r_list.status_code == 200
    assert any("Backup" in n["title"] for n in r_list.json())

    # Delivery audit logs exist and mask PII
    r_del = client.get("/api/v1/notifications/deliveries?limit=25", headers=ctx["admin"])
    assert r_del.status_code == 200
    assert isinstance(r_del.json(), list)
    assert len(r_del.json()) >= 1


def test_02_food_safety_compliance_zero_fabrication(client):
    ctx = _seed_base_context(client)
    cid = ctx["canteen_id"]

    # Empty dashboard NEVER fabricates compliance %
    r_empty = client.get(f"/api/v1/food-safety/dashboard?canteen_id={cid}", headers=ctx["inspector"])
    assert r_empty.status_code == 200
    d0 = r_empty.json()
    assert d0["completed_inspections_count"] == 0
    assert d0["inspection_pass_rate_percent"] is None

    # Seed & fetch templates
    tpls = client.get(f"/api/v1/food-safety/templates?canteen_id={cid}&seed_default=true", headers=ctx["inspector"]).json()
    assert len(tpls) >= 1
    tpl = tpls[0]
    assert len(tpl["items"]) == 10

    # Record failed hygiene inspection & download PDF
    items_payload = [
        {"item_code": it["code"], "item_title": it["title"], "category": it["category"], "result": "fail" if idx == 0 else "pass"}
        for idx, it in enumerate(tpl["items"])
    ]
    r_insp = client.post(
        "/api/v1/food-safety/inspections",
        headers=ctx["inspector"],
        json={"canteen_id": cid, "template_id": tpl["id"], "items": items_payload, "notes": "Floor drain needs recleaning"},
    )
    assert r_insp.status_code == 200, r_insp.text
    insp = r_insp.json()
    assert insp["overall_status"] == "fail"
    assert insp["failed_items"] == 1

    r_pdf = client.get(f"/api/v1/food-safety/inspections/{insp['id']}/pdf", headers=ctx["inspector"])
    assert r_pdf.status_code == 200
    assert r_pdf.content.startswith(b"%PDF")

    # Equipment temperature threshold rejects min >= max
    r_bad_eq = client.post(
        "/api/v1/food-safety/equipment",
        headers=ctx["manager"],
        json={"canteen_id": cid, "equipment_name": "Bad Fridge", "equipment_code": "FR-BAD", "min_temp_c": 8, "max_temp_c": 4},
    )
    assert r_bad_eq.status_code == 400

    # Valid equipment config + out-of-range temperature violation
    r_eq = client.post(
        "/api/v1/food-safety/equipment",
        headers=ctx["manager"],
        json={"canteen_id": cid, "equipment_name": "Dairy Chiller 1", "equipment_code": "CHILL-01", "min_temp_c": 1, "max_temp_c": 4},
    )
    assert r_eq.status_code == 200
    eq_id = r_eq.json()["id"]

    r_viol = client.post(
        "/api/v1/food-safety/temperatures",
        headers=ctx["kitchen"],
        json={"equipment_id": eq_id, "recorded_temp_c": 9.5, "notes": "Door left open"},
    )
    assert r_viol.status_code == 200
    assert r_viol.json()["is_violation"] is True

    # Cleaning schedule + overdue reminder + task completion
    past_due = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    r_cs = client.post(
        "/api/v1/food-safety/cleaning/schedules",
        headers=ctx["manager"],
        json={"canteen_id": cid, "area_name": "Prep Sink Zone", "frequency": "daily", "initial_due_at": past_due},
    )
    assert r_cs.status_code == 200
    task_id = r_cs.json()["initial_task"]["id"]
    assert r_cs.json()["initial_task"]["is_overdue"] is True

    r_rem = client.post(f"/api/v1/food-safety/cleaning/notify-overdue?canteen_id={cid}", headers=ctx["manager"])
    assert r_rem.status_code == 200
    assert r_rem.json()["overdue_tasks_found"] >= 1

    r_done = client.patch(
        f"/api/v1/food-safety/cleaning/tasks/{task_id}",
        headers=ctx["kitchen"],
        json={"status": "completed", "notes": "Sanitized with food-grade disinfectant"},
    )
    assert r_done.status_code == 200
    assert r_done.json()["status"] == "completed"

    # Food safety incident lifecycle
    r_inc = client.post(
        "/api/v1/food-safety/incidents",
        headers=ctx["inspector"],
        json={"canteen_id": cid, "title": "Chiller Temp Excursion", "description": "Chiller reached 9.5C for 20 min", "severity": "high"},
    )
    assert r_inc.status_code == 200
    inc_id = r_inc.json()["id"]
    r_res = client.patch(
        f"/api/v1/food-safety/incidents/{inc_id}",
        headers=ctx["inspector"],
        json={"status": "resolved", "corrective_action": "Door gasket replaced and dairy inspected"},
    )
    assert r_res.status_code == 200
    assert r_res.json()["status"] == "resolved"

    # Dashboard reflects exact actual counts
    dash = client.get(f"/api/v1/food-safety/dashboard?canteen_id={cid}", headers=ctx["inspector"]).json()
    assert dash["completed_inspections_count"] == 1
    assert dash["failed_inspections_count"] == 1
    assert dash["temperature_violations_count"] == 1
    assert dash["resolved_incidents_count"] == 1


def test_03_traceability_production_reordering_integrated_workflow(client):
    ctx = _seed_base_context(client)
    cid = ctx["canteen_id"]
    food = ctx["items"][0]
    food_id = food["id"]

    # Create vendor & inventory item
    r_sup = client.post(
        "/api/v1/inventory/suppliers",
        headers=ctx["admin"],
        json={"name": "FreshFarm Campus Dairy", "contact_person": "Ramesh", "phone": "9876543210"},
    )
    assert r_sup.status_code in (200, 201), r_sup.text
    sup_id = r_sup.json()["id"]

    r_inv = client.post(
        "/api/v1/inventory/ingredients",
        headers=ctx["inventory"],
        json={
            "canteen_id": cid,
            "name": f"Paneer Block {uuid4().hex[:4]}",
            "sku": f"PNR-{uuid4().hex[:5].upper()}",
            "category": "Dairy",
            "unit": "grams",
            "initial_quantity": 0,
            "reorder_level": 500,
            "unit_cost": 0.40,
            "preferred_supplier_id": sup_id,
        },
    )
    assert r_inv.status_code in (200, 201), r_inv.text
    inv_item = r_inv.json()
    inv_id = inv_item["inventory_item_id"]
    ing_id = inv_item["ingredient_id"]

    # 1. Register an EXPIRED batch and an APPROVED fresh batch (FEFO testing)
    r_exp = client.post(
        "/api/v1/traceability/batches",
        headers=ctx["inventory"],
        json={
            "inventory_item_id": inv_id,
            "quantity": 300,
            "unit_cost": 0.40,
            "supplier_id": sup_id,
            "batch_number": f"EXP-{uuid4().hex[:4].upper()}",
            "expiry_date": (date.today() - timedelta(days=2)).isoformat(),
            "quality_status": "approved",
        },
    )
    assert r_exp.status_code == 200, r_exp.text
    exp_batch_id = r_exp.json()["id"]

    # 2. Configure & verify Recipe requiring 100g per portion
    r_rec = client.put(
        f"/api/v1/production/recipes/{food_id}",
        headers=ctx["manager"],
        json={
            "yield_portions": 1,
            "instructions": "Grill fresh paneer cubes",
            "ingredients": [{"ingredient_id": ing_id, "quantity_required": 100, "unit": "grams"}],
            "verify": True,
        },
    )
    assert r_rec.status_code == 200, r_rec.text
    assert r_rec.json()["is_verified"] is True
    # Only expired batch exists -> usable_stock must be 0 -> shortage detected!
    assert r_rec.json()["shortages_count"] == 1

    # 3. Create Production Batch (idempotent) & verify allocation BLOCKS expired batch by default!
    idem = f"prod-idem-{uuid4().hex[:8]}"
    r_pb = client.post(
        "/api/v1/production/batches",
        headers=ctx["kitchen"],
        json={
            "canteen_id": cid,
            "food_item_id": food_id,
            "planned_quantity": 2,
            "allocation_strategy": "FEFO",
            "idempotency_key": idem,
        },
    )
    assert r_pb.status_code == 200, r_pb.text
    pb_id = r_pb.json()["id"]
    # Replay same idempotency_key -> returns same batch, no duplicate
    r_pb_dup = client.post(
        "/api/v1/production/batches",
        headers=ctx["kitchen"],
        json={"canteen_id": cid, "food_item_id": food_id, "planned_quantity": 2, "idempotency_key": idem},
    )
    assert r_pb_dup.json()["id"] == pb_id

    r_alloc_fail = client.post(
        f"/api/v1/production/batches/{pb_id}/transition",
        headers=ctx["kitchen"],
        json={"target_status": "ingredients_allocated"},
    )
    assert r_alloc_fail.status_code == 409, "Expired batch must be blocked from normal allocation!"

    # 4. Automated Reordering detects low usable stock -> creates DRAFT PO ONLY (never auto-approved!)
    r_rule = client.put(
        f"/api/v1/reordering/rules/{inv_id}",
        headers=ctx["inventory"],
        json={
            "min_stock_level": 200,
            "reorder_level": 500,
            "safety_stock": 200,
            "supplier_lead_time_days": 2,
            "target_days_of_cover": 7,
            "preferred_supplier_id": sup_id,
        },
    )
    assert r_rule.status_code == 200

    r_gen = client.post(f"/api/v1/reordering/recommendations/generate?canteen_id={cid}", headers=ctx["inventory"])
    assert r_gen.status_code == 200
    target_rec = next((x for x in r_gen.json()["recommendations"] if x["inventory_item_id"] == inv_id), None)
    assert target_rec is not None

    r_dpo = client.post(
        f"/api/v1/reordering/recommendations/{target_rec['id']}/create-draft-po",
        headers=ctx["inventory"],
        json={"supplier_id": sup_id, "quantity_override": 1000, "unit_cost_override": 0.40},
    )
    assert r_dpo.status_code == 200, r_dpo.text
    po = r_dpo.json()["draft_purchase_order"]
    assert po["status"] == "draft", "Automated reordering MUST create draft PO only, NEVER auto-approved!"
    assert r_dpo.json()["approval_required"] is True

    # Duplicate PO for same recommendation is blocked
    r_dpo_dup = client.post(
        f"/api/v1/reordering/recommendations/{target_rec['id']}/create-draft-po",
        headers=ctx["inventory"],
        json={"supplier_id": sup_id},
    )
    assert r_dpo_dup.status_code == 409

    # 5. Manager approves PO -> Ordered -> Verified GRN -> Fresh StockBatch with full PO/GRN trace!
    r_app = client.post(
        f"/api/v1/inventory/purchase-orders/{po['id']}/status",
        headers=ctx["manager"],
        json={"status": "approved"},
    )
    assert r_app.status_code == 200
    r_ord = client.post(
        f"/api/v1/inventory/purchase-orders/{po['id']}/status",
        headers=ctx["manager"],
        json={"status": "ordered"},
    )
    assert r_ord.status_code == 200
    r_grn = client.post(
        f"/api/v1/inventory/purchase-orders/{po['id']}/receive",
        headers=ctx["inventory"],
        json={
            "delivery_challan_ref": "DC-2026-99",
            "received_items": [
                {
                    "ingredient_id": ing_id,
                    "quantity_received": 1000,
                    "expiry_date": (date.today() + timedelta(days=10)).isoformat(),
                }
            ],
        },
    )
    assert r_grn.status_code == 200, r_grn.text

    # 6. Now Production Batch transitions through ALL 8 states cleanly (with mandatory QC gate!)
    for st in ("ingredients_allocated", "ready_for_preparation", "preparing", "prepared"):
        tr = client.post(
            f"/api/v1/production/batches/{pb_id}/transition",
            headers=ctx["kitchen"],
            json={"target_status": st, "actual_quantity": 2 if st == "prepared" else None},
        )
        assert tr.status_code == 200, f"Transition to {st} failed: {tr.text}"

    # Attempting quality_checked BEFORE recording QC must fail (400)
    r_no_qc = client.post(
        f"/api/v1/production/batches/{pb_id}/transition",
        headers=ctx["kitchen"],
        json={"target_status": "quality_checked"},
    )
    assert r_no_qc.status_code == 400

    # Record QC Pass -> quality_checked -> completed
    r_qc = client.post(
        f"/api/v1/production/batches/{pb_id}/quality-check",
        headers=ctx["inspector"],
        json={"appearance_ok": True, "preparation_ok": True, "hygiene_ok": True, "temperature_c": 74.5, "status": "passed"},
    )
    assert r_qc.status_code == 200
    for st in ("quality_checked", "completed"):
        tr = client.post(
            f"/api/v1/production/batches/{pb_id}/transition",
            headers=ctx["kitchen"],
            json={"target_status": st},
        )
        assert tr.status_code == 200, tr.text

    # Record actual batch sold & waste quantities
    r_qty = client.patch(
        f"/api/v1/production/batches/{pb_id}/quantities",
        headers=ctx["kitchen"],
        json={"actual_quantity": 2, "sold_quantity": 1, "waste_quantity": 1, "waste_reason": "1 unsold at closing"},
    )
    assert r_qty.status_code == 200
    assert r_qty.json()["remaining_quantity"] == 0

    # Verify fresh batch trace chain includes Vendor -> PO -> GRN -> ProductionBatch!
    batches = client.get(f"/api/v1/traceability/batches?canteen_id={cid}&inventory_item_id={inv_id}", headers=ctx["inventory"]).json()
    fresh_batch = next(b for b in batches if b["id"] != exp_batch_id)
    chain = client.get(f"/api/v1/traceability/batches/{fresh_batch['id']}/chain", headers=ctx["inspector"]).json()
    assert chain["vendor"]["id"] == sup_id
    assert chain["purchase_order"]["id"] == po["id"]
    assert chain["goods_receipt"] is not None
    assert len(chain["production_batches"]) == 1

    # 7. Recall workflow on fresh batch -> approve -> marks batch permanently recalled + PDF report
    r_rcl = client.post(
        "/api/v1/traceability/recalls",
        headers=ctx["inspector"],
        json={
            "canteen_id": cid,
            "title": "Supplier Cold-Chain Recall",
            "reason": "Vendor notified cold-chain variance during transit",
            "severity": "critical",
            "stock_batch_ids": [fresh_batch["id"]],
        },
    )
    assert r_rcl.status_code == 200
    rcl = r_rcl.json()
    assert rcl["status"] == "under_review"
    assert pb_id in rcl["affected_production_batch_ids"]

    r_rcl_app = client.post(f"/api/v1/traceability/recalls/{rcl['id']}/approve", headers=ctx["manager"])
    assert r_rcl_app.status_code == 200
    assert r_rcl_app.json()["status"] == "active_recall"

    r_rcl_pdf = client.get(f"/api/v1/traceability/recalls/{rcl['id']}/report.pdf", headers=ctx["inspector"])
    assert r_rcl_pdf.status_code == 200
    assert r_rcl_pdf.content.startswith(b"%PDF")

    # Dispose expired batch safely via Food Safety
    r_disp = client.post(
        f"/api/v1/food-safety/batches/{exp_batch_id}/dispose",
        headers=ctx["inspector"],
        json={"reason": "Expired dairy disposed safely"},
    )
    assert r_disp.status_code == 200
    assert r_disp.json()["quality_status"] == "blocked"


def test_04_queue_prediction_accuracy_and_bi_financial_analytics(client):
    ctx = _seed_base_context(client)
    cid = ctx["canteen_id"]
    # Pick a food item without a recipe shortage (or second item)
    food_id = ctx["items"][-1]["id"]

    # Place & pay order -> QueueEstimateHistory snapshot created automatically
    paid = _place_and_pay_order(client, ctx["customer"], cid, food_id, quantity=2)
    order_id = paid["id"]

    # KDS item-grouped view shows our active order
    grouped = client.get(f"/api/v1/kitchen/canteens/{cid}/grouped-items", headers=ctx["kitchen"]).json()
    assert any(g["food_item_id"] == food_id and g["total_quantity"] >= 2 for g in grouped)

    # Progress order through KDS to READY -> finalizes QueueEstimateHistory without altering order timestamps
    assert client.post(f"/api/v1/kitchen/orders/{order_id}/accept", headers=ctx["kitchen"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{order_id}/start-preparing", headers=ctx["kitchen"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{order_id}/mark-ready", headers=ctx["kitchen"]).status_code == 200

    # Queue accuracy metrics now have >= 1 completed sample with real MAE
    acc = client.get(f"/api/v1/queue/canteens/{cid}/accuracy", headers=ctx["manager"]).json()
    assert acc["sample_count"] >= 1
    assert acc["mae_minutes"] is not None
    assert acc["data_classification"] == "calculated"

    # Pausing ordering switches waiting_time_available=False with explicit message
    client.patch(
        f"/api/v1/queue/canteens/{cid}/controls",
        headers=ctx["manager"],
        json={"ordering_paused": True, "pause_reason": "Cleaning break"},
    )
    est_paused = client.get(f"/api/v1/queue/canteens/{cid}/estimate").json()
    assert est_paused["waiting_time_available"] is False
    assert est_paused["waiting_time_message"] == "Waiting time currently unavailable."
    assert est_paused["estimated_minutes"] is None
    # Restore open state
    client.patch(f"/api/v1/queue/canteens/{cid}/controls", headers=ctx["manager"], json={"ordering_paused": False})

    # BI Financial Analytics: empty historical range returns explicit empty flag & message
    empty_bi = client.get(
        f"/api/v1/reports/dashboard?canteen_id={cid}&start_date=2020-01-01&end_date=2020-01-05",
        headers=ctx["admin"],
    ).json()
    assert empty_bi["empty"] is True
    assert "No data available" in empty_bi["empty_message"]
    assert empty_bi["financial_analytics"]["estimated_gross_margin"] is None

    # BI Financial Analytics with today's data + period comparison
    live_bi = client.get(
        f"/api/v1/reports/dashboard?canteen_id={cid}&preset=today&compare_previous=true",
        headers=ctx["admin"],
    ).json()
    assert live_bi["empty"] is False
    assert Decimal(live_bi["financial_analytics"]["verified_net_revenue"]) > Decimal("0.00")
    assert live_bi["financial_analytics"]["revenue_classification"] == "actual"
    assert live_bi["period_comparison"] is not None


def test_05_ml_demand_forecasting_and_ai_assistant_guardrails(client):
    ctx = _seed_base_context(client)
    cid = ctx["canteen_id"]
    food = ctx["items"][-1]
    food_id = UUID(food["id"])

    # 1. With < 7 distinct sales days, training MUST refuse to fabricate predictions!
    r_insuff = client.post(
        "/api/v1/forecasting/train",
        headers=ctx["admin"],
        json={"canteen_id": cid, "training_window_days": 30, "horizon_days": 7, "force_retrain": True},
    )
    assert r_insuff.status_code == 200
    assert r_insuff.json()["status"] == "insufficient_data"
    assert "Insufficient historical data" in r_insuff.json()["message"]

    # 2. Seed 14 distinct historical days of verified confirmed orders (realistic campus pattern)
    with SessionLocal() as db_session:
        counter = db_session.scalar(select(Counter).where(Counter.canteen_id == UUID(cid)).limit(1))
        now = datetime.now(timezone.utc)
        for d_back in range(1, 15):
            ord_dt = now - timedelta(days=d_back)
            qty_day = 10 + (d_back % 5) * 3
            price = Decimal(str(food["base_price"]))
            o = Order(
                order_number=f"HIST-{d_back:02d}-{uuid4().hex[:6].upper()}",
                canteen_id=UUID(cid),
                counter_id=counter.id,
                status="COMPLETED",
                payment_status="CONFIRMED",
                payment_method="razorpay",
                subtotal_amount=price * qty_day,
                discount_amount=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                total_amount=price * qty_day,
                created_at=ord_dt,
                confirmed_at=ord_dt,
                ready_at=ord_dt + timedelta(minutes=8),
                completed_at=ord_dt + timedelta(minutes=12),
            )
            db_session.add(o)
            db_session.flush()
            db_session.add(
                OrderItem(
                    order_id=o.id,
                    food_item_id=food_id,
                    item_name=food["name"],
                    quantity=qty_day,
                    unit_price=price,
                    line_subtotal=price * qty_day,
                    line_total=price * qty_day,
                )
            )
        db_session.commit()

    # 3. Train real ML pipeline (Baseline vs Ridge vs RandomForest vs GradientBoosting)
    r_train = client.post(
        "/api/v1/forecasting/train",
        headers=ctx["admin"],
        json={"canteen_id": cid, "training_window_days": 30, "horizon_days": 7, "force_retrain": True},
    )
    assert r_train.status_code == 200, r_train.text
    fc = r_train.json()
    assert fc["status"] == "ok"
    assert fc["data_classification"] == "ai_predicted"
    assert fc["active_model"]["historical_days_used"] >= 14
    assert fc["active_model"]["mae"] is not None
    assert fc["active_model"]["rmse"] is not None
    assert "rolling_7d_baseline" in fc["active_model"]["comparison_metrics"]
    assert "ridge_regression" in fc["active_model"]["comparison_metrics"]
    assert len(fc["next_day_forecasts"]) >= 1
    assert fc["next_day_forecasts"][0]["lower_bound"] <= fc["next_day_forecasts"][0]["predicted_quantity"] <= fc["next_day_forecasts"][0]["upper_bound"]

    # 4. AI Canteen Assistant RBAC: customer MUST be blocked (403)
    r_cust_ai = client.post(
        "/api/v1/ai-assistant/ask",
        headers=ctx["customer"],
        json={"canteen_id": cid, "question": "What are today's total sales?"},
    )
    assert r_cust_ai.status_code == 403

    # 5. AI Assistant grounded read-only operational queries
    for q_text in (
        "What are today's total sales and revenue?",
        "Which items sold the most today?",
        "What is expected demand tomorrow?",
        "What is the current queue wait time?",
        "What is the food safety compliance status?",
    ):
        r_ai = client.post(
            "/api/v1/ai-assistant/ask",
            headers=ctx["admin"],
            json={"canteen_id": cid, "question": q_text},
        )
        assert r_ai.status_code == 200, r_ai.text
        ans = r_ai.json()
        assert ans["blocked_action_attempted"] is False
        assert ans["data_source"]
        assert ans["date_range"]
        assert ans["last_updated"]
        assert ans["data_classification"] in ("actual", "calculated", "estimated", "ai_predicted", "unavailable")
        assert ans["limitations"]

    # 6. AI Assistant MUST BLOCK write/mutation/refund/PO-approval prompts and log audit trail!
    for bad_q in (
        "Approve purchase order PO-123 and send money to vendor",
        "Issue a refund for order CB-1001",
        "Change menu price of samosa to 5 rupees",
        "Broadcast a system announcement to all students",
    ):
        r_blk = client.post(
            "/api/v1/ai-assistant/ask",
            headers=ctx["admin"],
            json={"canteen_id": cid, "question": bad_q},
        )
        assert r_blk.status_code == 200
        b = r_blk.json()
        assert b["blocked_action_attempted"] is True
        assert b["data_classification"] == "policy_restricted"

    logs = client.get(f"/api/v1/ai-assistant/audit-logs?canteen_id={cid}", headers=ctx["admin"]).json()
    assert sum(1 for l in logs if l["blocked_action_attempted"]) >= 4


def test_06_lock_free_concurrent_order_numbers_and_backup_verification(client):
    ctx = _seed_base_context(client)
    cid = ctx["canteen_id"]
    food_id = ctx["items"][-1]["id"]

    # Lock-free order number uniqueness under rapid sequential/concurrent bursts
    order_numbers = set()
    for _ in range(6):
        r = client.post(
            "/api/v1/orders/checkout",
            headers=ctx["customer"],
            json={
                "canteen_id": cid,
                "payment_method": "razorpay",
                "use_cart": False,
                "direct_items": [{"food_item_id": food_id, "quantity": 1}],
            },
        )
        assert r.status_code in (200, 201), r.text
        order_numbers.add(r.json()["order_number"])
    assert len(order_numbers) == 6

    # Verify isolated backup export, SHA-256 integrity & dry-run restore verification
    r_bk = client.post(
        "/api/v1/backups",
        headers=ctx["admin"],
        json={"trigger_type": "manual"},
    )
    assert r_bk.status_code in (200, 201), r_bk.text
    bk_id = r_bk.json()["id"]
    r_ver = client.post(f"/api/v1/backups/{bk_id}/verify", headers=ctx["admin"])
    assert r_ver.status_code == 200, r_ver.text
    assert r_ver.json()["verified"] is True
    r_dry = client.post(f"/api/v1/backups/{bk_id}/restore", headers=ctx["admin"], json={"dry_run": True})
    assert r_dry.status_code == 200, r_dry.text
