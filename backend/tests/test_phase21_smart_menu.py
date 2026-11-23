from datetime import date, datetime, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_smart_menu_schedules_events_windows_and_bypass_blocks(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    coffee = next(i for i in items if "Coffee" in i["name"])
    biryani = next(i for i in items if "Biryani" in i["name"])

    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    # 1. Special Event schedule for a specific future date -> inactive today, hidden with available_only=true
    ev = client.post(
        "/api/v1/menus/schedules",
        headers=manager["headers"],
        json={
            "canteen_id": cid,
            "name": "Annual TechFest Dinner",
            "schedule_type": "event",
            "start_time": "00:00:00",
            "end_time": "23:59:59",
            "days_of_week": [0, 1, 2, 3, 4, 5, 6],
            "special_dates": [tomorrow.isoformat()],
            "is_special_event": True,
            "event_name": "TechFest 2026",
        },
    )
    assert ev.status_code == 201, ev.text
    ev_id = ev.json()["id"]
    assert ev.json()["is_special_event"] is True

    assert client.put(
        f"/api/v1/menus/schedules/{ev_id}/items",
        headers=manager["headers"],
        json={"food_item_ids": [coffee["id"]]},
    ).status_code == 200

    avail_items = client.get(f"/api/v1/menus/canteens/{cid}/items?available_only=true").json()
    assert all(i["id"] != coffee["id"] for i in avail_items)

    # Customer cannot add off-event item
    assert client.post(
        "/api/v1/carts/items",
        headers=student["headers"],
        json={"canteen_id": cid, "food_item_id": coffee["id"], "quantity": 1},
    ).status_code == 400

    # Pickup slot on tomorrow IS active for tomorrow's special event, whereas a slot today must reject it
    slot_today = client.post(
        f"/api/v1/queue/canteens/{cid}/slots",
        headers=manager["headers"],
        json={"slot_date": today.isoformat(), "start_time": "18:00:00", "end_time": "19:00:00", "capacity": 20},
    )
    assert slot_today.status_code in (200, 201), slot_today.text
    slot_tom = client.post(
        f"/api/v1/queue/canteens/{cid}/slots",
        headers=manager["headers"],
        json={"slot_date": tomorrow.isoformat(), "start_time": "18:00:00", "end_time": "19:00:00", "capacity": 20},
    )
    assert slot_tom.status_code in (200, 201), slot_tom.text

    assert client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "pickup_slot_id": slot_today.json()["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    ).status_code == 400

    ok_ev_order = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "pickup_slot_id": slot_tom.json()["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert ok_ev_order.status_code == 201, ok_ev_order.text
    assert client.delete(f"/api/v1/menus/schedules/{ev_id}", headers=admin["headers"]).status_code == 200

    # 2. Item validity expiration + Cart Update (PATCH /carts/items/{id}) bypass block
    add_res = client.post(
        "/api/v1/carts/items",
        headers=student["headers"],
        json={"canteen_id": cid, "food_item_id": biryani["id"], "quantity": 1},
    )
    assert add_res.status_code == 200
    cart_item_id = add_res.json()["items"][0]["id"]

    # Expire item validity yesterday
    assert client.patch(
        f"/api/v1/menus/items/{biryani['id']}",
        headers=manager["headers"],
        json={"valid_until": yesterday.isoformat()},
    ).status_code == 200

    # PATCH quantity > 0 must be blocked (400); PATCH quantity = 0 removal succeeds cleanly
    assert client.patch(
        f"/api/v1/carts/items/{cart_item_id}",
        headers=student["headers"],
        json={"quantity": 2},
    ).status_code == 400
    cart_sum = client.get(f"/api/v1/carts?canteen_id={cid}", headers=student["headers"]).json()
    assert len(cart_sum["validation_errors"]) >= 1
    assert client.patch(
        f"/api/v1/carts/items/{cart_item_id}",
        headers=student["headers"],
        json={"quantity": 0},
    ).status_code == 200

    # Restore valid_until = tomorrow
    assert client.patch(
        f"/api/v1/menus/items/{biryani['id']}",
        headers=manager["headers"],
        json={"valid_until": tomorrow.isoformat()},
    ).status_code == 200

    # 3. Inactive FoodCategory enforcement across browsing, cart, checkout, and payment retry
    cat_id = coffee["category_id"]
    assert client.patch(f"/api/v1/menus/categories/{cat_id}", headers=manager["headers"], json={"is_active": False}).status_code == 200
    assert all(i["id"] != coffee["id"] for i in client.get(f"/api/v1/menus/canteens/{cid}/items").json())
    assert client.post(
        "/api/v1/carts/items",
        headers=student["headers"],
        json={"canteen_id": cid, "food_item_id": coffee["id"], "quantity": 1},
    ).status_code == 400
    assert client.patch(f"/api/v1/menus/categories/{cat_id}", headers=manager["headers"], json={"is_active": True}).status_code == 200

    # 4. Retry payment cannot bypass disabled/unavailable item
    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert co.status_code == 201
    oid = co.json()["id"]
    fail = client.post(
        "/api/v1/payments/razorpay/fail",
        headers=student["headers"],
        json={"order_id": oid, "reason": "Simulated card decline"},
    )
    assert fail.status_code == 200

    assert client.patch(f"/api/v1/menus/items/{coffee['id']}", headers=manager["headers"], json={"is_available": False}).status_code == 200
    retry_blocked = client.post(
        f"/api/v1/payments/retry/{oid}",
        headers=student["headers"],
        json={"payment_method": "razorpay"},
    )
    assert retry_blocked.status_code == 400

    assert client.patch(f"/api/v1/menus/items/{coffee['id']}", headers=manager["headers"], json={"is_available": True}).status_code == 200
    retry_ok = client.post(
        f"/api/v1/payments/retry/{oid}",
        headers=student["headers"],
        json={"payment_method": "razorpay"},
    )
    assert retry_ok.status_code == 200
    assert retry_ok.json()["status"] == "PAYMENT_PENDING"


def test_stock_depletion_auto_disable_and_manager_restore_approval(client: TestClient):
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]
    biryani = next(i for i in client.get(f"/api/v1/menus/canteens/{cid}/items").json() if "Biryani" in i["name"])
    invs = client.get(f"/api/v1/inventory/canteens/{cid}/items", headers=inv_mgr["headers"]).json()
    rice = next(i for i in invs if i["sku"] == "RICE-BAS")

    # Deplete Rice below 180g recipe requirement
    waste = client.post(
        "/api/v1/inventory/wastage",
        headers=inv_mgr["headers"],
        json={"inventory_item_id": rice["inventory_item_id"], "quantity": "24900.000", "reason": "Spillage depletion"},
    )
    assert waste.status_code == 200

    biryani_after_loss = client.get(f"/api/v1/menus/items/{biryani['id']}").json()
    assert biryani_after_loss["insufficient_ingredients"] is True
    assert biryani_after_loss["is_available"] is False

    # Restock Rice -> insufficient_ingredients clears, BUT item stays disabled pending manager approval!
    restock = client.post(
        f"/api/v1/inventory/items/{rice['inventory_item_id']}/restock",
        headers=inv_mgr["headers"],
        json={"quantity": "5000.000", "notes": "Fresh Basmati delivery"},
    )
    assert restock.status_code == 200

    biryani_after_restock = client.get(f"/api/v1/menus/items/{biryani['id']}").json()
    assert biryani_after_restock["insufficient_ingredients"] is False
    assert biryani_after_restock["is_available"] is False
    assert biryani_after_restock["pending_restore_approval"] is True

    # Customer still sees item unavailable and cannot order
    assert all(i["id"] != biryani["id"] for i in client.get(f"/api/v1/menus/canteens/{cid}/items?available_only=true").json())
    assert client.post(
        "/api/v1/carts/items",
        headers=student["headers"],
        json={"canteen_id": cid, "food_item_id": biryani["id"], "quantity": 1},
    ).status_code == 400

    # Inventory Manager CANNOT bypass manager approval to re-enable item
    assert client.patch(
        f"/api/v1/menus/items/{biryani['id']}",
        headers=inv_mgr["headers"],
        json={"is_available": True},
    ).status_code == 403

    # Manager reviews & approves restore request -> item becomes orderable again
    reqs = client.get(
        f"/api/v1/menus/canteens/{cid}/restore-approvals?status=pending_approval",
        headers=manager["headers"],
    ).json()
    req = next(r for r in reqs if r["food_item_id"] == biryani["id"])
    rev = client.post(
        f"/api/v1/menus/restore-approvals/{req['id']}/review",
        headers=manager["headers"],
        json={"decision": "approve", "review_notes": "Verified batch quality"},
    )
    assert rev.status_code == 200
    assert rev.json()["is_available"] is True
    assert rev.json()["pending_restore_approval"] is False

    assert client.post(
        "/api/v1/carts/items",
        headers=student["headers"],
        json={"canteen_id": cid, "food_item_id": biryani["id"], "quantity": 1},
    ).status_code == 200
