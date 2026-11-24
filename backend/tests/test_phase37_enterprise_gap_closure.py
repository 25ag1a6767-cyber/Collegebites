from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.time_utils import today_college
from app.models.college import Counter
from app.models.inventory import InventoryItem, StockMovement
from app.models.engagement import Notification, NotificationDelivery
from app.models.order import Order
from app.services import notification_service
from sqlalchemy import select
from tests.conftest import login_as


def _main_canteen_id(client: TestClient) -> str:
    return next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")["id"]


def test_phase37_notifications_per_user_read_and_external_dispatch(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    mgr = login_as(client, "manager@collegebites.edu", "Staff@12345")
    inspector = login_as(client, "inspector@collegebites.edu", "Staff@12345")
    cid = _main_canteen_id(client)

    # 1. Shared broadcast notification (role_target="all"): manager marking it read MUST NOT mark it read for admin!
    with SessionLocal() as db:
        shared_n, created_flag = notification_service._create_notification(
            db,
            role_target="all",
            canteen_id=UUID(cid),
            event_type="phase37_shared_broadcast",
            category="system",
            priority="high",
            title="P37 Shared Broadcast Test",
            message="Verify per-user read state isolation on shared notifications.",
            dedup_key="p37:shared:all:read",
        )
        db.commit()
        assert created_flag is True
        notif_id = str(shared_n.id)

    mgr_list = client.get("/api/v1/notifications/my", headers=mgr["headers"]).json()
    admin_list = client.get("/api/v1/notifications/my", headers=admin["headers"]).json()
    assert any(n["id"] == notif_id and n["is_read"] is False for n in mgr_list)
    assert any(n["id"] == notif_id and n["is_read"] is False for n in admin_list)

    # Manager marks shared notification read
    mk = client.post(f"/api/v1/notifications/{notif_id}/read", headers=mgr["headers"])
    assert mk.status_code == 200

    mgr_after = client.get("/api/v1/notifications/my", headers=mgr["headers"]).json()
    admin_after = client.get("/api/v1/notifications/my", headers=admin["headers"]).json()
    assert any(n["id"] == notif_id and n["is_read"] is True for n in mgr_after)
    assert any(n["id"] == notif_id and n["is_read"] is False for n in admin_after)

    # 2. Disabling in_app_enabled MUST still dispatch external email/SMS notification record
    pref = client.put(
        "/api/v1/notifications/preferences",
        headers=mgr["headers"],
        json={"in_app_enabled": False, "email_enabled": True, "sms_enabled": False, "push_enabled": False},
    )
    assert pref.status_code == 200
    with SessionLocal() as db:
        cnt = db.scalar(select(Counter).where(Counter.canteen_id == UUID(cid)))
        dummy_order = Order(
            order_number="CB-P37-EXT-0001",
            canteen_id=UUID(cid),
            counter_id=cnt.id,
            customer_id=UUID(mgr["user"]["id"]),
            is_guest=False,
            order_type="pickup",
            order_channel="web",
            status="PLACED",
            payment_status="CONFIRMED",
            payment_method="razorpay",
            subtotal_amount=Decimal("50.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("50.00"),
        )
        db.add(dummy_order)
        db.flush()
        notification_service._dispatch_user_notifications(
            db,
            order=dummy_order,
            event_type="phase37_external_only",
            title="External Channel Only Test",
            msg="Must still attempt email dispatch when in-app is muted.",
            send_external=True,
        )
        db.commit()
        ext_n = db.scalar(select(Notification).where(Notification.event_type == "phase37_external_only"))
        assert ext_n is not None
        assert ext_n.channel == "external"
        email_deliv = db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == ext_n.id,
                NotificationDelivery.channel == "email",
            )
        )
        assert email_deliv is not None
        ext_n_id = str(ext_n.id)

    # Muted in-app channel must not appear in in-app feed
    mgr_feed_muted = client.get("/api/v1/notifications/my", headers=mgr["headers"]).json()
    assert not any(n["id"] == ext_n_id for n in mgr_feed_muted)

    # Re-enable in-app for manager
    client.put(
        "/api/v1/notifications/preferences",
        headers=mgr["headers"],
        json={"in_app_enabled": True, "email_enabled": True, "sms_enabled": False, "push_enabled": True},
    )

    # 3. Food safety inspector allowed on SSE notifications stream + offset pagination on deliveries
    sse = client.get("/api/v1/realtime/notifications/stream?once=true", headers=inspector["headers"])
    assert sse.status_code == 200
    deliv = client.get("/api/v1/notifications/deliveries?limit=5&offset=0", headers=admin["headers"])
    assert deliv.status_code == 200 and isinstance(deliv.json(), list)


def test_phase37_food_safety_templates_recurring_and_incident_guards(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    mgr = login_as(client, "manager@collegebites.edu", "Staff@12345")
    inspector = login_as(client, "inspector@collegebites.edu", "Staff@12345")
    cid = _main_canteen_id(client)

    # 1. Canteen manager cannot create global (canteen_id=None) template
    bad_global = client.post(
        "/api/v1/food-safety/templates",
        headers=mgr["headers"],
        json={
            "canteen_id": None,
            "name": "Unauthorized Global Template",
            "category": "daily_hygiene",
            "items": [{"code": "X1", "title": "Check 1"}],
        },
    )
    assert bad_global.status_code == 403

    # Create & PATCH canteen-scoped template
    t_res = client.post(
        "/api/v1/food-safety/templates",
        headers=admin["headers"],
        json={
            "canteen_id": cid,
            "name": "P37 Line Check",
            "category": "daily_hygiene",
            "items": [{"code": "A1", "title": "Gloves worn"}],
        },
    )
    assert t_res.status_code == 200, t_res.text
    tid = t_res.json()["id"]
    upd = client.patch(
        f"/api/v1/food-safety/templates/{tid}",
        headers=admin["headers"],
        json={"name": "P37 Line Check Updated"},
    )
    assert upd.status_code == 200 and upd.json()["name"] == "P37 Line Check Updated"

    # 2. Completing a daily cleaning task auto-schedules the next day's occurrence
    due_now = datetime.now(timezone.utc) + timedelta(hours=2)
    ct = client.post(
        "/api/v1/food-safety/cleaning/schedules",
        headers=inspector["headers"],
        json={
            "canteen_id": cid,
            "area_name": "P37 Prep Sink",
            "frequency": "daily",
            "instructions": "Sanitize sink & faucet",
            "initial_due_at": due_now.isoformat(),
        },
    )
    assert ct.status_code == 200, ct.text
    ct_id = ct.json()["initial_task"]["id"]

    done_ct = client.patch(
        f"/api/v1/food-safety/cleaning/tasks/{ct_id}",
        headers=inspector["headers"],
        json={"status": "completed", "notes": "Sanitized with food-grade solution"},
    )
    assert done_ct.status_code == 200, done_ct.text
    cl_list = client.get(f"/api/v1/food-safety/cleaning?canteen_id={cid}", headers=inspector["headers"]).json()
    sink_tasks = [t for t in cl_list["tasks"] if t["area_name"] == "P37 Prep Sink"]
    assert any(t["status"] == "completed" for t in sink_tasks)
    assert any(t["status"] == "pending" and t["id"] != ct_id for t in sink_tasks)

    # 3. Incident state guards + audit history
    inc = client.post(
        "/api/v1/food-safety/incidents",
        headers=inspector["headers"],
        json={
            "canteen_id": cid,
            "severity": "high",
            "title": "P37 Cold-Store Door Seal Loose",
            "description": "Gasket leaking cold air during morning inspection.",
        },
    )
    assert inc.status_code == 200, inc.text
    inc_id = inc.json()["id"]

    # Resolving without corrective_action or resolution_notes must fail 400
    bad_close = client.patch(
        f"/api/v1/food-safety/incidents/{inc_id}",
        headers=inspector["headers"],
        json={"status": "resolved"},
    )
    assert bad_close.status_code == 400

    ok_close = client.patch(
        f"/api/v1/food-safety/incidents/{inc_id}",
        headers=inspector["headers"],
        json={"status": "closed", "corrective_action": "Replaced gasket and verified 3C"},
    )
    assert ok_close.status_code == 200

    # Closed incident cannot reopen
    reopen = client.patch(
        f"/api/v1/food-safety/incidents/{inc_id}",
        headers=inspector["headers"],
        json={"status": "open"},
    )
    assert reopen.status_code == 409

    hist = client.get(f"/api/v1/food-safety/incidents/{inc_id}/audit-history", headers=inspector["headers"])
    assert hist.status_code == 200 and len(hist.json()) >= 2


def test_phase37_po_rbac_recalled_stock_and_spike_reorder(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")
    cid = _main_canteen_id(client)

    sup = client.post(
        "/api/v1/inventory/suppliers",
        headers=inv_mgr["headers"],
        json={"name": "P37 Spike Agro Vendor", "lead_time_days": 3},
    ).json()
    assert sup["lead_time_days"] == 3

    ing = client.post(
        "/api/v1/inventory/ingredients",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": cid,
            "name": "P37 Organic Paneer",
            "sku": "P37-PNR-01",
            "unit": "kg",
            "initial_quantity": "20.000",
            "reorder_level": "10.000",
            "unit_cost": "320.00",
            "preferred_supplier_id": sup["id"],
        },
    ).json()

    # 1. PO Approval RBAC: inventory_manager CANNOT create initial_status="ordered" or "approved"
    bypass1 = client.post(
        "/api/v1/inventory/purchase-orders",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": cid,
            "supplier_id": sup["id"],
            "initial_status": "ordered",
            "items": [{"ingredient_id": ing["ingredient_id"], "quantity_ordered": "10.000", "unit_cost": "320.00"}],
        },
    )
    assert bypass1.status_code == 403

    # Creating draft PO then trying to jump directly to "ordered" without manager approval -> 403
    draft_po = client.post(
        "/api/v1/inventory/purchase-orders",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": cid,
            "supplier_id": sup["id"],
            "initial_status": "draft",
            "items": [{"ingredient_id": ing["ingredient_id"], "quantity_ordered": "10.000", "unit_cost": "320.00"}],
        },
    )
    assert draft_po.status_code == 201
    po_id = draft_po.json()["id"]
    bypass2 = client.post(
        f"/api/v1/inventory/purchase-orders/{po_id}/status",
        headers=inv_mgr["headers"],
        json={"status": "ordered"},
    )
    assert bypass2.status_code == 403

    # 2. Register stock batch -> block it -> available_quantity becomes 0 & movements endpoint works
    reg_b = client.post(
        "/api/v1/traceability/batches",
        headers=inv_mgr["headers"],
        json={
            "inventory_item_id": ing["inventory_item_id"],
            "quantity": "15.000",
            "expiry_date": (today_college() + timedelta(days=10)).isoformat(),
        },
    )
    assert reg_b.status_code == 200, reg_b.text
    bid = reg_b.json()["id"]
    assert Decimal(reg_b.json()["available_quantity"]) == Decimal("15.000")

    blk = client.patch(
        f"/api/v1/traceability/batches/{bid}/quality",
        headers=inv_mgr["headers"],
        json={"quality_status": "blocked", "block_reason": "P37 quarantine check"},
    )
    assert blk.status_code == 200
    assert Decimal(blk.json()["available_quantity"]) == Decimal("0.000")

    mvs = client.get(f"/api/v1/traceability/batches/{bid}/movements", headers=inv_mgr["headers"])
    assert mvs.status_code == 200 and len(mvs.json()) >= 1

    # 3. Existing draft PO prevents duplicate recommendation; cancelling it exposes the consumption-spike trigger + atomic draft PO
    with SessionLocal() as db:
        inv_obj = db.get(InventoryItem, UUID(ing["inventory_item_id"]))
        # Inject heavy recent 2-day consumption (30 kg in last 2 days => 3d avg = 10/d, 14d avg = 2.14/d => spike!)
        db.add(
            StockMovement(
                inventory_item_id=inv_obj.id,
                movement_type="production_use",
                quantity_delta=Decimal("-30.000"),
                balance_after=inv_obj.current_quantity,
                reference_type="p37_spike",
                reference_id="spike-1",
                created_at=datetime.now(timezone.utc) - timedelta(hours=6),
            )
        )
        db.commit()

    # Existing 10kg draft PO already covers 20+10 >= 30 lead-time need -> duplicate recommendation suppressed!
    scan_dup = client.post(f"/api/v1/reordering/recommendations/generate?canteen_id={cid}", headers=inv_mgr["headers"])
    assert scan_dup.status_code == 200
    assert not any(r["inventory_item_id"] == ing["inventory_item_id"] for r in scan_dup.json()["recommendations"])

    # Cancel earlier draft PO -> consumption-spike recommendation now triggers cleanly!
    assert client.post(f"/api/v1/inventory/purchase-orders/{po_id}/cancel", headers=inv_mgr["headers"]).status_code == 200
    scan = client.post(f"/api/v1/reordering/recommendations/generate?canteen_id={cid}", headers=inv_mgr["headers"])
    assert scan.status_code == 200, scan.text
    my_rec = next((r for r in scan.json()["recommendations"] if r["inventory_item_id"] == ing["inventory_item_id"]), None)
    assert my_rec is not None
    assert any("consumption spike" in r.lower() for r in my_rec["trigger_reasons"])

    dpo = client.post(
        f"/api/v1/reordering/recommendations/{my_rec['id']}/create-draft-po",
        headers=inv_mgr["headers"],
        json={"supplier_id": sup["id"]},
    )
    assert dpo.status_code == 200, dpo.text
    assert dpo.json()["draft_purchase_order"]["status"] == "draft"
    # Duplicate draft PO blocked
    dup_dpo = client.post(
        f"/api/v1/reordering/recommendations/{my_rec['id']}/create-draft-po",
        headers=inv_mgr["headers"],
        json={"supplier_id": sup["id"]},
    )
    assert dup_dpo.status_code == 409


def test_phase37_production_recipe_fix_qc_latest_gate_and_cancel_return(client: TestClient):
    mgr = login_as(client, "manager@collegebites.edu", "Staff@12345")
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    cid = _main_canteen_id(client)

    # 1. GET /production/recipes MUST NOT crash with AttributeError
    rec_list = client.get(f"/api/v1/production/recipes?canteen_id={cid}", headers=mgr["headers"])
    assert rec_list.status_code == 200, rec_list.text
    assert len(rec_list.json()) >= 1
    food_id = rec_list.json()[0]["food_item_id"]

    # Create fresh ingredient & stock batch for deterministic allocation + cancellation return test
    ing = client.post(
        "/api/v1/inventory/ingredients",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": cid,
            "name": "P37 Semolina Mix",
            "sku": "P37-SEM-01",
            "unit": "grams",
            "initial_quantity": "1000.000",
            "reorder_level": "100.000",
            "unit_cost": "0.10",
        },
    ).json()

    # Inventory manager CANNOT self-verify recipe via PUT /production/recipes/{id}
    deny_ver = client.put(
        f"/api/v1/production/recipes/{food_id}",
        headers=inv_mgr["headers"],
        json={
            "yield_portions": 1,
            "instructions": "Steam 12 mins",
            "ingredients": [{"ingredient_id": ing["ingredient_id"], "quantity_required": "50.000"}],
            "verify": True,
        },
    )
    assert deny_ver.status_code == 403

    # Manager upserts & verifies recipe (MUST NOT crash on instructions -> notes!)
    ok_rec = client.put(
        f"/api/v1/production/recipes/{food_id}",
        headers=mgr["headers"],
        json={
            "yield_portions": 1,
            "instructions": "Steam 12 mins carefully",
            "ingredients": [{"ingredient_id": ing["ingredient_id"], "quantity_required": "50.000"}],
            "verify": True,
        },
    )
    assert ok_rec.status_code == 200, ok_rec.text

    # 2. Allocate & cancel batch -> raw stock returned back to 1000.000
    b1 = client.post(
        "/api/v1/production/batches",
        headers=kitchen["headers"],
        json={"canteen_id": cid, "food_item_id": food_id, "planned_quantity": 4},
    ).json()
    assert (
        client.post(
            f"/api/v1/production/batches/{b1['id']}/transition",
            headers=kitchen["headers"],
            json={"target_status": "ingredients_allocated"},
        ).status_code
        == 200
    )
    # 4 * 50 = 200g deducted -> 800g left; cancelling restores to 1000g
    assert (
        client.post(
            f"/api/v1/production/batches/{b1['id']}/transition",
            headers=kitchen["headers"],
            json={"target_status": "cancelled", "notes": "Session rescheduled"},
        ).status_code
        == 200
    )
    inv_after = next(
        i
        for i in client.get(f"/api/v1/inventory/canteens/{cid}/items", headers=inv_mgr["headers"]).json()
        if i["inventory_item_id"] == ing["inventory_item_id"]
    )
    assert Decimal(inv_after["current_quantity"]) == Decimal("1000.000")

    # 3. Latest QC check gate: PASS then FAIL MUST block quality_checked
    b2 = client.post(
        "/api/v1/production/batches",
        headers=kitchen["headers"],
        json={"canteen_id": cid, "food_item_id": food_id, "planned_quantity": 2},
    ).json()
    for st in ("ingredients_allocated", "ready_for_preparation", "preparing", "prepared"):
        assert (
            client.post(
                f"/api/v1/production/batches/{b2['id']}/transition",
                headers=kitchen["headers"],
                json={"target_status": st},
            ).status_code
            == 200
        )
    assert (
        client.post(
            f"/api/v1/production/batches/{b2['id']}/quality-check",
            headers=mgr["headers"],
            json={"appearance_ok": True, "preparation_ok": True, "hygiene_ok": True, "status": "passed"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/production/batches/{b2['id']}/quality-check",
            headers=mgr["headers"],
            json={"appearance_ok": False, "preparation_ok": True, "hygiene_ok": True, "status": "failed", "notes": "Under-cooked sample"},
        ).status_code
        == 200
    )
    blocked_qc = client.post(
        f"/api/v1/production/batches/{b2['id']}/transition",
        headers=mgr["headers"],
        json={"target_status": "quality_checked"},
    )
    assert blocked_qc.status_code == 400

    # Production delay alert endpoint works
    dly = client.post(
        f"/api/v1/production/batches/{b2['id']}/report-delay",
        headers=kitchen["headers"],
        json={"delay_minutes": 15, "reason": "Re-steaming batch after QC hold"},
    )
    assert dly.status_code == 200


def test_phase37_queue_pii_isolation_bi_exports_assistant_rbac_and_correlation_id(client: TestClient):
    mgr = login_as(client, "manager@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    inspector = login_as(client, "inspector@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cid = _main_canteen_id(client)

    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    dish = items[0]

    # Place a confirmed walk-in order with a distinct customer name
    pos = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={
            "canteen_id": cid,
            "customer_name": "P37 Secret Customer Name",
            "payment_method": "upi_pos",
            "items": [{"food_item_id": dish["id"], "quantity": 2}],
        },
    )
    assert pos.status_code == 201, pos.text
    ord_data = pos.json()

    # 1. Public & customer queue calls MUST NOT leak customer PII
    pub_q = client.get(f"/api/v1/queue/canteens/{cid}").json()
    cust_q = client.get(f"/api/v1/queue/canteens/{cid}", headers=student["headers"]).json()
    staff_q = client.get(f"/api/v1/queue/canteens/{cid}", headers=mgr["headers"]).json()
    assert pub_q["active_orders_queue"] == [] and pub_q["delayed_orders"] == []
    assert cust_q["active_orders_queue"] == [] and cust_q["delayed_orders"] == []
    assert "P37 Secret Customer Name" not in str(pub_q)
    assert any(o["order_id"] == ord_data["id"] for o in staff_q["active_orders_queue"])
    assert isinstance(staff_q.get("congestion_warnings"), list)

    # Order queue status includes estimated_pickup_at, last_updated_at, waiting_time_available
    oq = client.get(f"/api/v1/queue/orders/{ord_data['order_number']}", headers=mgr["headers"]).json()
    assert "estimated_pickup_at" in oq
    assert "last_updated_at" in oq and oq["last_updated_at"] is not None
    assert "waiting_time_available" in oq
    assert oq["data_classification"] == "estimated"

    # 2. BI filtered report & exports include financial analytics + period comparison
    bi_f = client.get(
        f"/api/v1/reports/dashboard?canteen_id={cid}&food_item_id={dish['id']}&compare_previous=true",
        headers=mgr["headers"],
    ).json()
    assert bi_f["financial_analytics"]["margin_status"] == "whole_canteen_scope_required"
    assert bi_f["financial_analytics"]["estimated_gross_margin"] is None
    assert bi_f["period_comparison"] is not None

    csv_exp = client.get(
        f"/api/v1/reports/export/csv?canteen_id={cid}&food_item_id={dish['id']}&compare_previous=true",
        headers=mgr["headers"],
    )
    assert csv_exp.status_code == 200
    assert "FINANCIAL ANALYTICS" in csv_exp.text
    assert "PERIOD COMPARISON" in csv_exp.text

    pdf_exp = client.get(
        f"/api/v1/reports/export/pdf?canteen_id={cid}&compare_previous=true",
        headers=mgr["headers"],
    )
    assert pdf_exp.status_code == 200 and pdf_exp.content.startswith(b"%PDF")

    xlsx_exp = client.get(
        f"/api/v1/reports/export/xlsx?canteen_id={cid}&compare_previous=true",
        headers=mgr["headers"],
    )
    assert xlsx_exp.status_code == 200 and len(xlsx_exp.content) > 1000

    # 3. Forecasting evaluations endpoint works
    ev = client.get(f"/api/v1/forecasting/canteens/{cid}/evaluations", headers=mgr["headers"])
    assert ev.status_code == 200 and "realized_vs_predicted" in ev.json()

    # 4. AI Assistant RBAC (kitchen gets no ₹ revenue; inspector blocked from demand_forecast) + expanded action blocker
    kit_top = client.post(
        "/api/v1/ai-assistant/ask",
        headers=kitchen["headers"],
        json={"canteen_id": cid, "question": "Which items sold the most today?"},
    ).json()
    assert "₹" not in kit_top["answer"]

    kit_w = client.post(
        "/api/v1/ai-assistant/ask",
        headers=kitchen["headers"],
        json={"canteen_id": cid, "question": "How much food was wasted today?"},
    ).json()
    assert "₹" not in kit_w["answer"]

    insp_fc = client.post(
        "/api/v1/ai-assistant/ask",
        headers=inspector["headers"],
        json={"canteen_id": cid, "question": "What is expected demand tomorrow?"},
    ).json()
    assert "require" in insp_fc["limitations"].lower()

    blk_cancel = client.post(
        "/api/v1/ai-assistant/ask",
        headers=mgr["headers"],
        json={"canteen_id": cid, "question": "Please cancel order CB-20261124-000001 right now"},
    ).json()
    assert blk_cancel["blocked_action_attempted"] is True

    blk_po = client.post(
        "/api/v1/ai-assistant/ask",
        headers=mgr["headers"],
        json={"canteen_id": cid, "question": "Create a purchase order for 50 kg rice"},
    ).json()
    assert blk_po["blocked_action_attempted"] is True

    calc_q = client.post(
        "/api/v1/ai-assistant/ask",
        headers=mgr["headers"],
        json={"canteen_id": cid, "question": "What is today's average order value and gross margin?"},
    ).json()
    assert calc_q["data_classification"] == "calculated"

    # 5. Unified X-Request-ID header + single timing header (no duplicate X-Process-Time-Ms)
    h_res = client.get("/health", headers={"X-Request-ID": "cb-p37-corr-001"})
    assert h_res.status_code == 200
    assert h_res.headers.get("x-request-id") == "cb-p37-corr-001"
    assert "x-response-time-ms" in h_res.headers
    assert "x-process-time-ms" not in h_res.headers
