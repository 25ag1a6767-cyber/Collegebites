from __future__ import annotations

import json
from uuid import uuid4
from fastapi.testclient import TestClient

from app.integrations.razorpay_client import razorpay_gateway
from tests.conftest import login_as


def _parse_sse(raw: str) -> list[dict]:
    out = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        eid = None
        ename = "message"
        data = []
        for line in block.split("\n"):
            if line.startswith("id:"):
                eid = line[3:].strip()
            elif line.startswith("event:"):
                ename = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            out.append({"id": eid, "event": ename, "data": json.loads("\n".join(data))})
    return out


def test_operational_token_board_five_sections_full_cards_and_sse_sync(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")

    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    other_canteen = next(c for c in canteens if c["slug"] != "main-canteen")
    food = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/items").json()[0]

    # Unauthorized customer must be rejected
    assert client.get("/api/v1/pickup/token-board", headers=student["headers"]).status_code == 403
    assert client.get("/api/v1/pickup/token-board").status_code == 401
    # Canteen-scoped manager requesting another canteen must be rejected
    assert (
        client.get(f"/api/v1/pickup/token-board?canteen_id={other_canteen['id']}", headers=manager["headers"]).status_code
        == 403
    )

    # Create & pay order via Razorpay verify
    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main_canteen["id"],
            "order_type": "pickup",
            "order_channel": "web",
            "payment_method": "razorpay",
            "idempotency_key": f"ops-{uuid4().hex[:12]}",
            "accepted_policy": True,
            "use_cart": False,
            "direct_items": [{"food_item_id": food["id"], "quantity": 2}],
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
        headers=student["headers"],
        json={
            "order_id": order["id"],
            "razorpay_order_id": order["razorpay_order_id"],
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    )
    assert ver.status_code == 200
    paid = ver.json()

    # Check New Orders section + complete card metadata
    ops_1 = client.get("/api/v1/pickup/token-board", headers=manager["headers"])
    assert ops_1.status_code == 200
    b1 = ops_1.json()
    assert len(b1["new_orders"]) == 1
    card = b1["new_orders"][0]
    assert card["token_code"] == paid["pickup_token_code"]
    assert card["order_number"] == paid["order_number"]
    assert card["qr_reference"].startswith("QR-")
    assert card["payment_status"] == "CONFIRMED"
    assert card["customer_label"]
    assert card["items"][0]["quantity"] == 2
    assert card["items"][0]["item_name"] == food["name"]

    # Stream snapshot 1
    sse_1 = client.get("/api/v1/realtime/token-board/stream?once=true", headers=manager["headers"])
    assert sse_1.status_code == 200
    ev1 = _parse_sse(sse_1.text)[0]
    assert ev1["event"] == "token_board.snapshot"
    ver_1 = ev1["id"]

    # Advance through Accepted -> Preparing -> Ready -> Completed
    assert client.post(f"/api/v1/kitchen/orders/{paid['id']}/accept", headers=kitchen["headers"]).status_code == 200
    b2 = client.get("/api/v1/pickup/token-board", headers=manager["headers"]).json()
    assert len(b2["new_orders"]) == 0 and len(b2["accepted_orders"]) == 1

    assert client.post(f"/api/v1/kitchen/orders/{paid['id']}/start-preparing", headers=kitchen["headers"]).status_code == 200
    b3 = client.get("/api/v1/pickup/token-board", headers=manager["headers"]).json()
    assert len(b3["accepted_orders"]) == 0 and len(b3["preparing_orders"]) == 1

    assert client.post(f"/api/v1/kitchen/orders/{paid['id']}/mark-ready", headers=kitchen["headers"]).status_code == 200
    b4 = client.get("/api/v1/pickup/token-board", headers=manager["headers"]).json()
    assert len(b4["preparing_orders"]) == 0 and len(b4["ready_for_pickup"]) == 1

    assert client.post(
        "/api/v1/pickup/handover",
        headers=pickup["headers"],
        json={"order_id": paid["id"], "verification_method": "manual_token"},
    ).status_code == 200

    # Reconnect SSE carrying old Last-Event-ID -> catches up directly to Completed Orders section
    sse_catchup = client.get(
        "/api/v1/realtime/token-board/stream?once=true",
        headers={**manager["headers"], "Last-Event-ID": ver_1},
    )
    ev2 = _parse_sse(sse_catchup.text)[0]
    assert ev2["id"] != ver_1
    assert len(ev2["data"]["ready_for_pickup"]) == 0
    assert any(c["order_id"] == paid["id"] for c in ev2["data"]["completed_orders"])
