from __future__ import annotations

import base64
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.time_utils import today_college
from app.integrations.razorpay_client import razorpay_gateway
from tests.conftest import login_as


def test_multi_station_routing_kot_escpos_and_queue_controls(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    other_canteen = next(c for c in canteens if c["slug"] != "main-canteen")

    main_detail = client.get(f"/api/v1/canteens/{main_canteen['id']}").json()
    other_detail = client.get(f"/api/v1/canteens/{other_canteen['id']}").json()
    main_kitchen_id = main_detail["kitchens"][0]["id"]
    other_kitchen_id = other_detail["kitchens"][0]["id"]

    # Create kitchen stations in main and other canteen
    st_main = client.post(
        f"/api/v1/admin/kitchens/{main_kitchen_id}/stations",
        headers=manager["headers"],
        json={"name": "South Dosa Counter", "station_type": "tawa"},
    )
    assert st_main.status_code == 201, st_main.text
    st_main_id = st_main.json()["id"]

    st_other = client.post(
        f"/api/v1/admin/kitchens/{other_kitchen_id}/stations",
        headers=admin["headers"],
        json={"name": "Chai Kettle Station", "station_type": "beverage"},
    )
    assert st_other.status_code == 201, st_other.text
    st_other_id = st_other.json()["id"]

    cats = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/categories").json()
    # Assigning station from another canteen must fail with 400
    bad_food = client.post(
        "/api/v1/menus/items",
        headers=manager["headers"],
        json={
            "canteen_id": main_canteen["id"],
            "category_id": cats[0]["id"],
            "station_id": st_other_id,
            "name": "Wrong Station Item",
            "slug": f"wrong-st-{uuid4().hex[:6]}",
            "base_price": "40.00",
        },
    )
    assert bad_food.status_code == 400

    # Valid station assignment
    good_food = client.post(
        "/api/v1/menus/items",
        headers=manager["headers"],
        json={
            "canteen_id": main_canteen["id"],
            "category_id": cats[0]["id"],
            "station_id": st_main_id,
            "name": "Ghee Roast Dosa",
            "slug": f"ghee-roast-{uuid4().hex[:6]}",
            "base_price": "75.00",
        },
    )
    assert good_food.status_code == 201, good_food.text
    assert good_food.json()["station_id"] == st_main_id
    assert good_food.json()["station_name"] == "South Dosa Counter"

    # Place & pay order -> station workload updates & station filter returns it
    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main_canteen["id"],
            "order_type": "pickup",
            "order_channel": "web",
            "payment_method": "razorpay",
            "idempotency_key": f"p19-{uuid4().hex[:10]}",
            "accepted_policy": True,
            "use_cart": False,
            "direct_items": [{"food_item_id": good_food.json()["id"], "quantity": 2}],
        },
    ).json()
    pay_id = f"pay_{uuid4().hex[:14]}"
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=co["razorpay_order_id"],
        razorpay_payment_id=pay_id,
    )
    order = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": co["id"],
            "razorpay_order_id": co["razorpay_order_id"],
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig,
        },
    ).json()
    assert order["items"][0]["station_id"] == st_main_id

    st_wl = client.get(f"/api/v1/kitchen/canteens/{main_canteen['id']}/stations", headers=kitchen["headers"]).json()
    dosa_wl = next(s for s in st_wl if s["id"] == st_main_id)
    assert dosa_wl["pending_units"] >= 2

    filtered_orders = client.get(
        f"/api/v1/kitchen/canteens/{main_canteen['id']}/orders?station_id={st_main_id}",
        headers=kitchen["headers"],
    ).json()
    assert any(o["id"] == order["id"] for o in filtered_orders)

    # OrderAssignment endpoint
    assign = client.post(
        f"/api/v1/kitchen/orders/{order['id']}/assign",
        headers=kitchen["headers"],
        json={"station_id": st_main_id, "staff_user_id": kitchen["user"]["id"], "role_scope": "kitchen"},
    )
    assert assign.status_code == 200 and assign.json()["station_id"] == st_main_id

    # KOT thermal ESC/POS ticket is blocked BEFORE kitchen accepts the order, then generated after acceptance
    kot_before = client.get(
        f"/api/v1/printing/kitchen-ticket/{order['order_number']}/escpos?width=80mm&station_id={st_main_id}",
        headers=kitchen["headers"],
    )
    assert kot_before.status_code == 409

    acc = client.post(
        f"/api/v1/kitchen/orders/{order['id']}/accept",
        headers=kitchen["headers"],
    )
    assert acc.status_code == 200

    kot = client.get(
        f"/api/v1/printing/kitchen-ticket/{order['order_number']}/escpos?width=80mm&station_id={st_main_id}",
        headers=kitchen["headers"],
    )
    assert kot.status_code == 200
    kot_bytes = base64.b64decode(kot.json()["escpos_base64"])
    assert b"KITCHEN ORDER TICKET" in kot_bytes
    assert b"Ghee Roast Dosa" in kot_bytes

    # Cross-canteen order ESC/POS receipt isolation: create other canteen cashier or verify main manager blocked on other order
    other_food = client.get(f"/api/v1/menus/canteens/{other_canteen['id']}/items").json()[0]
    co_other = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": other_canteen["id"],
            "order_type": "pickup",
            "order_channel": "web",
            "payment_method": "razorpay",
            "idempotency_key": f"p19o-{uuid4().hex[:10]}",
            "accepted_policy": True,
            "use_cart": False,
            "direct_items": [{"food_item_id": other_food["id"], "quantity": 1}],
        },
    ).json()
    pay_id2 = f"pay_{uuid4().hex[:14]}"
    sig2 = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=co_other["razorpay_order_id"],
        razorpay_payment_id=pay_id2,
    )
    other_paid = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": co_other["id"],
            "razorpay_order_id": co_other["razorpay_order_id"],
            "razorpay_payment_id": pay_id2,
            "razorpay_signature": sig2,
        },
    ).json()
    assert client.get(f"/api/v1/printing/receipts/{other_paid['order_number']}/escpos", headers=cashier["headers"]).status_code == 403
    assert client.get(f"/api/v1/printing/kitchen-ticket/{other_paid['order_number']}/escpos", headers=kitchen["headers"]).status_code == 403

    # Queue RBAC: kitchen_staff cannot change canteen queue controls
    assert (
        client.patch(
            f"/api/v1/queue/canteens/{main_canteen['id']}/controls",
            headers=kitchen["headers"],
            json={"ordering_paused": True},
        ).status_code
        == 403
    )

    # Pickup slot validation: end_time <= start_time and past slot_date must be rejected with 400
    assert (
        client.post(
            f"/api/v1/queue/canteens/{main_canteen['id']}/slots",
            headers=manager["headers"],
            json={
                "slot_date": today_college().isoformat(),
                "start_time": "14:00:00",
                "end_time": "13:00:00",
                "capacity": 10,
                "is_active": True,
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/v1/queue/canteens/{main_canteen['id']}/slots",
            headers=manager["headers"],
            json={
                "slot_date": (today_college() - timedelta(days=2)).isoformat(),
                "start_time": "12:00:00",
                "end_time": "13:00:00",
                "capacity": 10,
                "is_active": True,
            },
        ).status_code
        == 400
    )

    # KDS staff directory & inventory_manager access to canteen kitchen stations
    k_staff = client.get(f"/api/v1/kitchen/canteens/{main_canteen['id']}/staff", headers=kitchen["headers"])
    assert k_staff.status_code == 200 and len(k_staff.json()) >= 1
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")
    inv_stations = client.get(f"/api/v1/kitchen/canteens/{main_canteen['id']}/stations", headers=inv_mgr["headers"])
    assert inv_stations.status_code == 200 and len(inv_stations.json()) >= 1
