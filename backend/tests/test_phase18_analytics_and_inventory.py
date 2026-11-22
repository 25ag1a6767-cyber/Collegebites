from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.time_utils import today_college
from app.integrations.razorpay_client import razorpay_gateway
from app.models.menu import FoodItem
from app.schemas.order import CheckoutItemDirectIn, CheckoutRequest
from app.services import order_service
from tests.conftest import TestingSessionLocal, login_as


def _create_paid_order(client: TestClient, student_headers: dict, canteen_id: str, food_id: str, qty: int = 1) -> dict:
    co = client.post(
        "/api/v1/orders/checkout",
        headers=student_headers,
        json={
            "canteen_id": canteen_id,
            "order_type": "pickup",
            "order_channel": "web",
            "payment_method": "razorpay",
            "idempotency_key": f"p18-{uuid4().hex[:12]}",
            "accepted_policy": True,
            "use_cart": False,
            "direct_items": [{"food_item_id": food_id, "quantity": qty}],
        },
    )
    assert co.status_code == 201, co.text
    order = co.json()
    pay_id = f"pay_{uuid4().hex[:14]}"
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=order["razorpay_order_id"],
        razorpay_payment_id=pay_id,
    )
    ver = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student_headers,
        json={
            "order_id": order["id"],
            "razorpay_order_id": order["razorpay_order_id"],
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig,
        },
    )
    assert ver.status_code == 200, ver.text
    return ver.json()


def test_reports_scope_real_metrics_and_exports(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    other_canteen = next(c for c in canteens if c["slug"] != "main-canteen")

    main_food = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/items").json()[0]
    other_food = client.get(f"/api/v1/menus/canteens/{other_canteen['id']}/items").json()[0]

    # Create 1 completed order in main canteen + 1 paid order in other canteen
    o_main = _create_paid_order(client, student["headers"], main_canteen["id"], main_food["id"], qty=1)
    assert client.post(f"/api/v1/kitchen/orders/{o_main['id']}/accept", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{o_main['id']}/start-preparing", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{o_main['id']}/mark-ready", headers=kitchen["headers"]).status_code == 200
    assert client.post("/api/v1/pickup/handover", headers=pickup["headers"], json={"order_id": o_main["id"], "verification_method": "qr_scan"}).status_code == 200

    _create_paid_order(client, student["headers"], other_canteen["id"], other_food["id"], qty=1)

    # Canteen manager requesting other canteen must receive 403
    assert client.get(f"/api/v1/reports/dashboard?canteen_id={other_canteen['id']}", headers=manager["headers"]).status_code == 403
    assert client.get(f"/api/v1/reports/export/csv?canteen_id={other_canteen['id']}", headers=manager["headers"]).status_code == 403

    # Canteen manager omitting canteen_id is strictly scoped to main_canteen (1 order, NOT 2)
    mgr_rep = client.get("/api/v1/reports/dashboard", headers=manager["headers"]).json()
    assert mgr_rep["today_summary"]["total_orders_today"] == 1
    assert mgr_rep["today_summary"]["completed_orders_today"] == 1
    assert mgr_rep["sales"]["total_orders"] == 1

    # Admin omitting canteen_id sees college-wide totals (both canteens = 2)
    adm_rep = client.get("/api/v1/reports/dashboard", headers=admin["headers"]).json()
    assert adm_rep["today_summary"]["total_orders_today"] == 2
    assert adm_rep["sales"]["total_orders"] == 2
    assert len(adm_rep["sales"]["weekly_series"]) >= 1
    assert len(adm_rep["sales"]["monthly_series"]) >= 1
    assert len(adm_rep["operations"]["peak_hours"]) >= 1
    assert "revenue" in adm_rep["operations"]["peak_hours"][0]
    assert adm_rep["payment_stats"]["confirmed_count"] >= 2
    assert adm_rep["payment_stats"]["success_rate_percent"] > 0
    assert isinstance(adm_rep["staff_performance"]["staff_breakdown"], list)
    assert len(adm_rep["staff_performance"]["staff_breakdown"]) >= 1

    # CSV and PDF exports return valid payloads with updated sections
    csv_res = client.get("/api/v1/reports/export/csv", headers=manager["headers"])
    assert csv_res.status_code == 200
    assert "TODAY SUMMARY" in csv_res.text
    assert "WEEKLY SERIES" in csv_res.text
    assert "PAYMENT STATISTICS" in csv_res.text
    assert "STAFF ACTIVITY BREAKDOWN" in csv_res.text

    pdf_res = client.get("/api/v1/reports/export/pdf", headers=manager["headers"])
    assert pdf_res.status_code == 200
    assert pdf_res.content.startswith(b"%PDF")


def test_inventory_concurrent_reservation_expiry_alerts_transfer_and_po_cancel(
    client: TestClient, clean_db_and_seed
):
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    other_canteen = next(c for c in canteens if c["slug"] != "main-canteen")
    food = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/items").json()[0]

    # 1. Create ingredient with stock=10 (enough for exactly 1 dish when recipe requires 10)
    ing_res = client.post(
        "/api/v1/inventory/ingredients",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": main_canteen["id"],
            "name": "Special Saffron Paneer",
            "unit": "grams",
            "initial_quantity": 10,
            "reorder_level": 5,
            "unit_cost": 5.0,
        },
    )
    assert ing_res.status_code == 201, ing_res.text
    ing_data = ing_res.json()

    rec_res = client.put(
        f"/api/v1/inventory/recipes/{food['id']}",
        headers=inv_mgr["headers"],
        json={
            "yield_portions": 1,
            "ingredients": [{"ingredient_id": ing_data["ingredient_id"], "quantity_required": 10}],
        },
    )
    assert rec_res.status_code == 200, rec_res.text

    # 2. Concurrent checkout for last 1 portion -> only ONE may succeed!
    student_id = UUID(student["user"]["id"])
    canteen_uuid = UUID(main_canteen["id"])
    food_uuid = UUID(food["id"])

    def _attempt_checkout(idx: int) -> str:
        s = TestingSessionLocal()
        try:
            payload = CheckoutRequest(
                canteen_id=canteen_uuid,
                order_type="pickup",
                order_channel="web",
                payment_method="razorpay",
                idempotency_key=f"race-{idx}-{uuid4().hex[:8]}",
                accepted_policy=True,
                use_cart=False,
                direct_items=[CheckoutItemDirectIn(food_item_id=food_uuid, quantity=1)],
            )
            order_service.checkout_order(s, payload, user_id=student_id)
            return "ok"
        except HTTPException as exc:
            return f"http-{exc.status_code}"
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(_attempt_checkout, [1, 2]))

    assert outcomes.count("ok") == 1, f"Expected single winner under race, got {outcomes}"
    assert outcomes.count("http-400") == 1, f"Expected second racer blocked, got {outcomes}"

    # Cancel the unpaid pending order -> reserved_quantity releases & dish becomes available again
    my_orders = client.get("/api/v1/orders/my", headers=student["headers"]).json()
    pending = my_orders[0]
    can = client.post(
        f"/api/v1/orders/{pending['id']}/cancel",
        headers=student["headers"],
        json={"reason": "Testing reservation release"},
    )
    assert can.status_code == 200, can.text

    inv_items = client.get(f"/api/v1/inventory/canteens/{main_canteen['id']}/items", headers=inv_mgr["headers"]).json()
    target_item = next(x for x in inv_items if x["inventory_item_id"] == ing_data["inventory_item_id"])
    assert float(target_item["reserved_quantity"]) == 0.0
    clean_db_and_seed.expire_all()
    food_row = clean_db_and_seed.get(FoodItem, food_uuid)
    assert food_row.insufficient_ingredients is False

    # 3. Expired batch enforcement: ingredient whose only batch is expired cannot keep dish orderable
    exp_ing = client.post(
        "/api/v1/inventory/ingredients",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": main_canteen["id"],
            "name": "Expired Cream",
            "unit": "ml",
            "initial_quantity": 500,
            "reorder_level": 50,
            "unit_cost": 1.5,
            "expiry_date": (today_college() - timedelta(days=1)).isoformat(),
        },
    ).json()
    rec_exp = client.put(
        f"/api/v1/inventory/recipes/{food['id']}",
        headers=inv_mgr["headers"],
        json={
            "yield_portions": 1,
            "ingredients": [{"ingredient_id": exp_ing["ingredient_id"], "quantity_required": 50}],
        },
    )
    assert rec_exp.status_code == 200
    assert food["name"] in rec_exp.json()["blocked_items"]

    # Checkout fails while blocked by expired batch
    co_exp = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main_canteen["id"],
            "order_type": "pickup",
            "order_channel": "web",
            "payment_method": "razorpay",
            "idempotency_key": f"exp-{uuid4().hex[:10]}",
            "accepted_policy": True,
            "use_cart": False,
            "direct_items": [{"food_item_id": food["id"], "quantity": 1}],
        },
    )
    assert co_exp.status_code == 400

    # 4. Archived item must be excluded from alerts; wastage/adjustments/transfer/PO cancel work
    arch = client.post(
        f"/api/v1/inventory/items/{exp_ing['inventory_item_id']}/archive",
        headers=inv_mgr["headers"],
        json={"reason": "Expired discard"},
    )
    assert arch.status_code == 200
    alerts = client.get(f"/api/v1/inventory/canteens/{main_canteen['id']}/alerts", headers=inv_mgr["headers"]).json()
    assert all(x["inventory_item_id"] != exp_ing["inventory_item_id"] for x in alerts["low_stock"])

    # Transfer stock & check wastage/adjustments endpoints
    waste = client.post(
        "/api/v1/inventory/wastage",
        headers=inv_mgr["headers"],
        json={
            "inventory_item_id": ing_data["inventory_item_id"],
            "quantity": 2,
            "reason": "Damaged packet during prep",
            "operation_type": "damaged",
        },
    )
    assert waste.status_code == 200
    wastage_list = client.get(f"/api/v1/inventory/canteens/{main_canteen['id']}/wastage", headers=inv_mgr["headers"]).json()
    assert len(wastage_list) >= 1 and wastage_list[0]["loss_type"] == "damaged"

    trf = client.post(
        "/api/v1/inventory/transfers",
        headers=inv_mgr["headers"],
        json={
            "from_canteen_id": main_canteen["id"],
            "to_canteen_id": other_canteen["id"],
            "ingredient_id": ing_data["ingredient_id"],
            "quantity": 3,
            "notes": "Rebalance to other canteen",
        },
    )
    assert trf.status_code == 200

    # Create & Cancel Purchase Order; receiving cancelled PO must return 409
    sup = client.post("/api/v1/inventory/suppliers", headers=inv_mgr["headers"], json={"name": "Fresh Dairy Corp"}).json()
    po = client.post(
        "/api/v1/inventory/purchase-orders",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": main_canteen["id"],
            "supplier_id": sup["id"],
            "items": [{"ingredient_id": ing_data["ingredient_id"], "quantity_ordered": 20, "unit_cost": 4.0}],
        },
    ).json()
    can_po = client.post(f"/api/v1/inventory/purchase-orders/{po['id']}/cancel", headers=inv_mgr["headers"])
    assert can_po.status_code == 200 and can_po.json()["status"] == "cancelled"
    assert client.post(f"/api/v1/inventory/purchase-orders/{po['id']}/receive", headers=inv_mgr["headers"]).status_code == 409
