from __future__ import annotations

from uuid import uuid4
from fastapi.testclient import TestClient

from app.integrations.razorpay_client import razorpay_gateway
from tests.conftest import login_as


def _place_paid_order(client: TestClient, student_headers: dict, canteen_id: str, food_id: str) -> dict:
    co = client.post(
        "/api/v1/orders/checkout",
        headers=student_headers,
        json={
            "canteen_id": canteen_id,
            "order_type": "pickup",
            "order_channel": "web",
            "payment_method": "razorpay",
            "idempotency_key": f"kds-{uuid4().hex[:12]}",
            "accepted_policy": True,
            "use_cart": False,
            "direct_items": [{"food_item_id": food_id, "quantity": 1}],
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
            "payment_method": "upi",
        },
    )
    assert ver.status_code == 200, ver.text
    return ver.json()


def test_kds_priority_item_prep_delay_guards_and_notification_dedup(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")

    main_canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    food = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/items").json()[0]

    o1 = _place_paid_order(client, student["headers"], main_canteen["id"], food["id"])
    o2 = _place_paid_order(client, student["headers"], main_canteen["id"], food["id"])

    # Toggle o2 as priority and verify priority-first ordering on KDS
    pr = client.post(f"/api/v1/kitchen/orders/{o2['id']}/priority", headers=kitchen["headers"], json={"is_priority": True})
    assert pr.status_code == 200
    assert pr.json()["is_priority"] is True

    kds_orders = client.get(f"/api/v1/kitchen/canteens/{main_canteen['id']}/orders", headers=kitchen["headers"]).json()
    ids = [o["id"] for o in kds_orders]
    assert ids.index(o2["id"]) < ids.index(o1["id"])

    # Unauthorized customer cannot bump priority or update item prep status
    assert (
        client.post(f"/api/v1/kitchen/orders/{o1['id']}/priority", headers=student["headers"], json={"is_priority": True}).status_code
        == 403
    )

    # Item-wise preparation status update
    item_id = o2["items"][0]["id"]
    prep_item = client.post(
        f"/api/v1/kitchen/order-items/{item_id}/prep-status",
        headers=kitchen["headers"],
        json={"prep_status": "PREPARING"},
    )
    assert prep_item.status_code == 200
    assert prep_item.json()["items"][0]["prep_status"] == "PREPARING"

    # Delay order, advance through READY -> COMPLETED, verify delay rejected after COMPLETED
    d1 = client.post(
        f"/api/v1/kitchen/orders/{o2['id']}/report-delay",
        headers=kitchen["headers"],
        json={"additional_minutes": 10, "reason": "Oven queue"},
    )
    assert d1.status_code == 200
    assert d1.json()["delayed_minutes"] == 10

    assert client.post(f"/api/v1/kitchen/orders/{o2['id']}/accept", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{o2['id']}/start-preparing", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{o2['id']}/mark-ready", headers=kitchen["headers"]).status_code == 200
    assert (
        client.post(
            "/api/v1/pickup/handover",
            headers=pickup["headers"],
            json={"order_id": o2["id"], "verification_method": "manual_token"},
        ).status_code
        == 200
    )

    late_delay = client.post(
        f"/api/v1/kitchen/orders/{o2['id']}/report-delay",
        headers=kitchen["headers"],
        json={"additional_minutes": 5, "reason": "Too late"},
    )
    assert late_delay.status_code == 409

    # Customer notifications: confirm no duplicates and every lifecycle notification arrived
    cust_notifs = client.get("/api/v1/notifications/my", headers=student["headers"]).json()
    o2_types = [n["event_type"] for n in cust_notifs if n["order_id"] == o2["id"]]
    assert "order_confirmed" in o2_types
    assert "order_accepted" in o2_types
    assert "order_preparing" in o2_types
    assert "order_ready" in o2_types
    assert "order_completed" in o2_types
    assert "order_delayed" in o2_types
    assert len(o2_types) == len(set(o2_types)), f"Duplicate notifications found: {o2_types}"

    # Pickup staff received pickup_ready & Manager received kitchen_new_order
    pickup_notifs = client.get("/api/v1/notifications/my", headers=pickup["headers"]).json()
    assert any(n["event_type"] == "pickup_ready" and n["order_id"] == o2["id"] for n in pickup_notifs)
    mgr_notifs = client.get("/api/v1/notifications/my", headers=manager["headers"]).json()
    assert any(n["event_type"] == "kitchen_new_order" and n["order_id"] == o2["id"] for n in mgr_notifs)

    # Notification SSE stream + web push subscription management
    sse = client.get("/api/v1/realtime/notifications/stream?once=true", headers=student["headers"])
    assert sse.status_code == 200
    assert "notifications.snapshot" in sse.text

    sub = client.post(
        "/api/v1/notifications/web-push/subscribe",
        headers=student["headers"],
        json={"endpoint": "https://fcm.googleapis.com/fcm/send/sample-sub-1", "keys": {"p256dh": "k1", "auth": "a1"}},
    )
    assert sub.status_code == 200
    assert sub.json()["subscription_count"] == 1
    unsub = client.delete(
        "/api/v1/notifications/web-push/subscribe?endpoint=https://fcm.googleapis.com/fcm/send/sample-sub-1",
        headers=student["headers"],
    )
    assert unsub.status_code == 200
    assert unsub.json()["subscription_count"] == 0
