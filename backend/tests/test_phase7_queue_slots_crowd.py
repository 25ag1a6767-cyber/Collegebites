from datetime import date, time
from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_queue_dashboard_slot_capacity_throttling_and_pause(client: TestClient):
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    biryani = items[0]

    # Create a slot with capacity=1
    slot = client.post(
        f"/api/v1/queue/canteens/{cid}/slots",
        headers=manager["headers"],
        json={
            "slot_date": date.today().isoformat(),
            "start_time": "22:00:00",
            "end_time": "22:30:00",
            "capacity": 1,
            "is_active": True,
        },
    ).json()

    # Reserve slot with 1 order -> succeeds
    o1 = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "pickup_slot_id": slot["id"],
            "payment_method": "razorpay",
            "idempotency_key": "idem-slot-1",
            "use_cart": False,
            "accepted_policy": True,
            "direct_items": [{"food_item_id": biryani["id"], "quantity": 1}],
        },
    )
    assert o1.status_code == 201

    # Second order in same capacity=1 slot -> rejected 409!
    o2 = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "pickup_slot_id": slot["id"],
            "payment_method": "razorpay",
            "idempotency_key": "idem-slot-2",
            "use_cart": False,
            "accepted_policy": True,
            "direct_items": [{"food_item_id": biryani["id"], "quantity": 1}],
        },
    )
    assert o2.status_code == 409

    # Place a confirmed walk-in order and check queue dashboard + prep estimate
    client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={"canteen_id": cid, "payment_method": "upi_pos", "items": [{"food_item_id": biryani["id"], "quantity": 2}]},
    )
    q = client.get(f"/api/v1/queue/canteens/{cid}").json()
    assert q["active_order_count"] >= 1
    assert q["placed_count"] >= 1
    assert q["crowd_level"] in ("LOW", "MODERATE", "HIGH", "VERY_HIGH", "TEMPORARILY_UNAVAILABLE")

    est = client.get(f"/api/v1/queue/canteens/{cid}/estimate?item_ids={biryani['id']}").json()
    assert est["estimated_minutes"] >= 3

    # Pause ordering -> checkout rejected
    paused = client.patch(
        f"/api/v1/queue/canteens/{cid}/controls",
        headers=manager["headers"],
        json={"ordering_paused": True, "pause_reason": "Kitchen deep clean"},
    ).json()
    assert paused["ordering_paused"] is True
    assert paused["crowd_level"] == "TEMPORARILY_UNAVAILABLE"

    blocked = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "payment_method": "razorpay",
            "idempotency_key": "idem-paused-1",
            "use_cart": False,
            "accepted_policy": True,
            "direct_items": [{"food_item_id": biryani["id"], "quantity": 1}],
        },
    )
    assert blocked.status_code == 400
