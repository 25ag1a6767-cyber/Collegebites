from __future__ import annotations

from uuid import uuid4
from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_health_no_store_and_checkout_header_idempotency_deduplication(client: TestClient):
    # 1. Health check must forbid caching and include live UTC server_time for offline/online recovery probes
    health_resp = client.get("/health")
    assert health_resp.status_code == 200, health_resp.text
    assert health_resp.headers.get("cache-control") == "no-store"
    health_data = health_resp.json()
    assert health_data["status"] == "ok"
    assert health_data["server_time"]

    # 2. Student checkout with X-Idempotency-Key header deduplicates repeated retried submissions
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    items = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/items").json()
    food = items[0]

    idem_key = f"offline-retry-{uuid4().hex[:16]}"
    payload = {
        "canteen_id": main_canteen["id"],
        "order_type": "pickup",
        "order_channel": "web",
        "payment_method": "razorpay",
        "accepted_policy": True,
        "use_cart": False,
        "direct_items": [{"food_item_id": food["id"], "quantity": 2}],
    }
    headers_with_idem = {**student["headers"], "X-Idempotency-Key": idem_key}

    first = client.post("/api/v1/orders/checkout", headers=headers_with_idem, json=payload)
    assert first.status_code == 201, first.text
    first_order = first.json()
    # Unverified online checkout must NOT generate pickup token offline/pre-verification
    assert not first_order.get("pickup_token_code")

    second = client.post("/api/v1/orders/checkout", headers=headers_with_idem, json=payload)
    assert second.status_code == 201, second.text
    second_order = second.json()

    assert second_order["id"] == first_order["id"]
    assert second_order["order_number"] == first_order["order_number"]
    assert second_order["razorpay_order_id"] == first_order["razorpay_order_id"]

    # Customer order list must only contain one order for this retry sequence
    my_orders = client.get("/api/v1/orders/my", headers=student["headers"]).json()
    matching = [o for o in my_orders if o["id"] == first_order["id"]]
    assert len(matching) == 1
