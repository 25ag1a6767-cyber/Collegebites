from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.database import SessionLocal
from app.models.order import Order
from tests.conftest import login_as


def test_smart_queue_positions_routing_reassignment_and_autoremoval(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]
    canteen_detail = client.get(f"/api/v1/canteens/{cid}").json()
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    slow_dish = max(items, key=lambda x: int(x.get("prep_time_minutes") or 10))
    fast_dish = min(items, key=lambda x: int(x.get("prep_time_minutes") or 10))

    # Create a balanced secondary pickup counter + express lane counter
    c_bal = client.post(
        f"/api/v1/admin/canteens/{cid}/counters",
        headers=admin["headers"],
        json={"name": "Counter Beta", "code": "CBETA", "counter_type": "pickup", "max_queue_capacity": 10},
    )
    assert c_bal.status_code == 201, c_bal.text
    counter_beta = c_bal.json()

    c_exp = client.post(
        f"/api/v1/admin/canteens/{cid}/counters",
        headers=admin["headers"],
        json={"name": "Express Lane Counter", "code": "CEXP", "counter_type": "express", "max_queue_capacity": 15},
    )
    assert c_exp.status_code == 201, c_exp.text
    counter_exp = c_exp.json()

    # Check existing seeded primary counter matching slow_dish preference (or first active pickup)
    default_cnt = next(
        (c for c in canteen_detail["counters"] if c["id"] == slow_dish.get("counter_id")),
        next(c for c in canteen_detail["counters"] if c["counter_type"] in ("pickup", "both")),
    )

    # 1. Place two POS orders on default counter -> verify real queue positions & dynamic wait
    p1 = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={
            "canteen_id": cid,
            "counter_id": default_cnt["id"],
            "customer_name": "Queue Guest One",
            "payment_method": "upi_pos",
            "items": [{"food_item_id": slow_dish["id"], "quantity": 1}],
        },
    )
    assert p1.status_code == 201, p1.text
    o1 = p1.json()

    p2 = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={
            "canteen_id": cid,
            "counter_id": default_cnt["id"],
            "customer_name": "Queue Guest Two",
            "payment_method": "upi_pos",
            "items": [{"food_item_id": slow_dish["id"], "quantity": 1}],
        },
    )
    assert p2.status_code == 201, p2.text
    o2 = p2.json()

    # Tokens must be distinct
    assert o1["pickup_token_code"] and o2["pickup_token_code"]
    assert o1["pickup_token_code"] != o2["pickup_token_code"]

    q1 = client.get(f"/api/v1/queue/orders/{o1['order_number']}", headers=manager["headers"]).json()
    q2 = client.get(f"/api/v1/queue/orders/{o2['order_number']}", headers=manager["headers"]).json()
    assert q1["queue_position"] == 1
    assert q1["orders_ahead_count"] == 0
    assert q2["queue_position"] == 2
    assert q2["orders_ahead_count"] == 1
    assert q2["dynamic_wait_minutes"] > q1["dynamic_wait_minutes"]

    # 2. Mark Order 2 Priority -> verify queue position swaps immediately on queue, pickup board & live stream
    prio = client.post(
        f"/api/v1/kitchen/orders/{o2['id']}/priority",
        headers=manager["headers"],
        json={"is_priority": True},
    )
    assert prio.status_code == 200, prio.text
    q1_after_prio = client.get(f"/api/v1/queue/orders/{o1['order_number']}", headers=manager["headers"]).json()
    q2_after_prio = client.get(f"/api/v1/queue/orders/{o2['order_number']}", headers=manager["headers"]).json()
    assert q2_after_prio["queue_position"] == 1
    assert q1_after_prio["queue_position"] == 2

    # 3. Reassign Order 2 to Counter Beta -> both Order & PickupToken reflect new counter
    reassigned = client.post(
        f"/api/v1/queue/orders/{o2['id']}/assign-counter",
        headers=manager["headers"],
        json={"counter_id": counter_beta["id"]},
    )
    assert reassigned.status_code == 200, reassigned.text
    q_entries = reassigned.json()["active_orders_queue"]
    o2_row = next(e for e in q_entries if e["order_id"] == o2["id"])
    assert o2_row["counter_id"] == counter_beta["id"]

    # 4. Express Routing Rule: fast item <=6m with small qty routes automatically to Express counter when counter_id omitted
    if int(fast_dish["prep_time_minutes"]) <= 6:
        exp_ord = client.post(
            "/api/v1/pos/orders",
            headers=cashier["headers"],
            json={
                "canteen_id": cid,
                "customer_name": "Express Lane Student",
                "payment_method": "upi_pos",
                "items": [{"food_item_id": fast_dish["id"], "quantity": 1}],
            },
        )
        assert exp_ord.status_code == 201, exp_ord.text
        assert exp_ord.json()["counter_id"] == counter_exp["id"]

    # 5. Load balancing across standard counters when counter_id is omitted for slow items (>= 7 min)
    slow_ord = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={
            "canteen_id": cid,
            "customer_name": "Balanced Counter Student",
            "payment_method": "upi_pos",
            "items": [{"food_item_id": slow_dish["id"], "quantity": 4}],
        },
    )
    assert slow_ord.status_code == 201, slow_ord.text
    # Should avoid express counter and avoid overloaded default counter (or balance evenly across active pickup counters)
    assert slow_ord.json()["counter_id"] != counter_exp["id"]

    # 6. Complete Order 2 -> auto-removes from active_orders_queue & decrements orders_ahead_count / dynamic wait
    assert client.post(f"/api/v1/kitchen/orders/{o2['id']}/accept", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{o2['id']}/start-preparing", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{o2['id']}/mark-ready", headers=kitchen["headers"]).status_code == 200
    assert (
        client.post(
            "/api/v1/pickup/handover",
            headers=pickup["headers"],
            json={"order_id": o2["id"], "counter_id": counter_beta["id"], "verification_method": "manual_token"},
        ).status_code
        == 200
    )

    live_dash = client.get(f"/api/v1/queue/canteens/{cid}", headers=manager["headers"]).json()
    assert all(e["order_id"] != o2["id"] for e in live_dash["active_orders_queue"])

    q1_final = client.get(f"/api/v1/queue/orders/{o1['order_number']}", headers=manager["headers"]).json()
    assert q1_final["queue_position"] == 1
    assert q1_final["orders_ahead_count"] == 0
    assert q1_final["dynamic_wait_minutes"] < q2["dynamic_wait_minutes"]

    # 7. Overdue auto-escalation marks old active order as priority
    with SessionLocal() as db:
        db.execute(
            update(Order)
            .where(Order.id == o1["id"])
            .values(confirmed_at=datetime.now(timezone.utc) - timedelta(minutes=90), is_priority=False)
        )
        db.commit()

    esc = client.post(f"/api/v1/queue/canteens/{cid}/escalate-overdue", headers=manager["headers"])
    assert esc.status_code == 200, esc.text
    assert o1["order_number"] in esc.json()["escalated_order_numbers"]
    o1_entry = next(e for e in esc.json()["dashboard"]["active_orders_queue"] if e["order_id"] == o1["id"])
    assert o1_entry["is_priority"] is True
    assert o1_entry["is_overdue"] is True

    # 8. Real-time Queue & Order SSE streams emit live snapshot frames
    q_sse = client.get(f"/api/v1/realtime/queue/{cid}/stream?once=true", headers=manager["headers"])
    assert q_sse.status_code == 200
    assert "event: queue.snapshot" in q_sse.text
    assert o1["order_number"] in q_sse.text

    o_sse = client.get(f"/api/v1/realtime/orders/{o1['id']}/stream?once=true", headers=manager["headers"])
    assert o_sse.status_code == 200
    assert "event: order.snapshot" in o_sse.text
    assert '"queue_position": 1' in o_sse.text
