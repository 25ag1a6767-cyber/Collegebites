import json
from decimal import Decimal
from fastapi.testclient import TestClient

from app.integrations.razorpay_client import razorpay_gateway
from tests.conftest import login_as


def _create_student_order(client: TestClient, student_headers: dict, payment_method: str = "razorpay", idem: str = "idem-pay-1"):
    main = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = main["id"]
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    biryani = next(i for i in items if "Biryani" in i["name"])
    coffee = next(i for i in items if "Coffee" in i["name"])
    addon = biryani["addons"][0]

    resp = client.post(
        "/api/v1/orders/checkout",
        headers=student_headers,
        json={
            "canteen_id": cid,
            "payment_method": payment_method,
            "idempotency_key": idem,
            "use_cart": False,
            "accepted_policy": True,
            "direct_items": [
                {
                    "food_item_id": biryani["id"],
                    "quantity": 2,
                    "spice_level": "Extra Spicy",
                    "addons": [{"addon_id": addon["id"], "quantity": 1}],
                    "special_instructions": "Pack raita separately",
                },
                {
                    "food_item_id": coffee["id"],
                    "quantity": 1,
                    "sugar_level": "Less Sugar",
                },
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_razorpay_verification_webhook_idempotency_and_no_refunds(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    order = _create_student_order(client, student["headers"], "razorpay", "idem-rzp-1")
    rzp_order_id = order["razorpay_order_id"]

    # Bad signature must fail and NOT issue a token
    bad = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": order["id"],
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": "pay_fake_001",
            "razorpay_signature": "invalid_signature_value",
        },
    )
    assert bad.status_code == 400
    assert client.get(f"/api/v1/tokens/receipts/{order['id']}", headers=student["headers"]).status_code == 409

    # Valid signature confirms payment and generates token, QR, and receipt
    rzp_pay_id = "pay_valid_001"
    sig = razorpay_gateway.compute_test_payment_signature(razorpay_order_id=rzp_order_id, razorpay_payment_id=rzp_pay_id)
    ok = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": order["id"],
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": rzp_pay_id,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    )
    assert ok.status_code == 200, ok.text
    confirmed = ok.json()
    assert confirmed["payment_status"] == "CONFIRMED"
    assert confirmed["status"] == "PLACED"
    token1 = confirmed["pickup_token_code"]
    qr1 = confirmed["qr_token_raw"]
    assert token1 is not None and token1.startswith("A")
    assert qr1 is not None and "/pickup/verify#token=CBQR." in qr1

    # Duplicate webhook delivery must NOT create a new token or fail
    wh_body = json.dumps({
        "event_id": "evt_dup_001",
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": rzp_pay_id, "order_id": rzp_order_id, "method": "upi"}}},
    }).encode("utf-8")
    wh_sig = razorpay_gateway.compute_test_webhook_signature(raw_body=wh_body)
    wh1 = client.post("/api/v1/payments/razorpay/webhook", content=wh_body, headers={"X-Razorpay-Signature": wh_sig})
    assert wh1.status_code == 200
    wh2 = client.post("/api/v1/payments/razorpay/webhook", content=wh_body, headers={"X-Razorpay-Signature": wh_sig})
    assert wh2.status_code == 200
    assert wh2.json()["status"] == "already_processed"

    reloaded = client.get(f"/api/v1/orders/{order['order_number']}", headers=student["headers"]).json()
    assert reloaded["pickup_token_code"] == token1
    assert reloaded["qr_token_raw"] == qr1

    # Strict NO REFUNDS check: no refund endpoints exist, and cancelling retains payment record
    assert client.post(f"/api/v1/orders/{order['id']}/refund", headers=student["headers"]).status_code in (404, 405)
    assert client.post("/api/v1/payments/refund", headers=admin["headers"]).status_code in (404, 405)

    cancel_res = client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        headers=admin["headers"],
        json={"reason": "Student requested urgent cancellation before prep", "finance_note": "Refer to college office if exceptional"},
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"
    assert cancel_res.json()["payment_status"] == "CONFIRMED"


def test_payment_failure_and_online_only_policy(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    main = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    biryani = next(i for i in items if "Biryani" in i["name"])

    order_fail = _create_student_order(client, student["headers"], "razorpay", "idem-fail-1")
    unauth_fail = client.post(
        "/api/v1/payments/razorpay/fail",
        json={"order_id": order_fail["id"], "reason": "Unauthorized attempt"},
    )
    assert unauth_fail.status_code == 401
    fail_res = client.post(
        "/api/v1/payments/razorpay/fail",
        headers=student["headers"],
        json={"order_id": order_fail["id"], "reason": "UPI PIN declined"},
    )
    assert fail_res.status_code == 200
    assert fail_res.json()["status"] == "PAYMENT_FAILED"
    assert fail_res.json()["pickup_token_code"] is None

    # Strict Online-Only Policy: cash & pay_at_pickup MUST be rejected across Checkout, POS, Counter Collect, Admin & Canteen toggles
    for bad_method in ("cash", "pay_at_pickup"):
        bad_co = client.post(
            "/api/v1/orders/checkout",
            headers=student["headers"],
            json={
                "canteen_id": main["id"],
                "payment_method": bad_method,
                "idempotency_key": f"idem-bad-{bad_method}",
                "use_cart": False,
                "accepted_policy": True,
                "direct_items": [{"food_item_id": biryani["id"], "quantity": 1}],
            },
        )
        assert bad_co.status_code == 400

    assert (
        client.post(
            "/api/v1/pos/orders",
            headers=cashier["headers"],
            json={"canteen_id": main["id"], "payment_method": "cash", "items": [{"food_item_id": biryani["id"], "quantity": 1}]},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/payments/counter/collect",
            headers=cashier["headers"],
            json={"order_id": order_fail["id"], "payment_method": "cash"},
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/v1/admin/college",
            headers=admin["headers"],
            json={"cash_at_counter_enabled": True},
        ).status_code
        == 400
    )
    assert (
        client.patch(
            f"/api/v1/admin/canteens/{main['id']}",
            headers=admin["headers"],
            json={"allow_pay_at_pickup": True},
        ).status_code
        == 400
    )

    # Counter digital POS (upi_pos / card_pos): student cannot confirm counter payment; cashier can
    order_pending = _create_student_order(client, student["headers"], "razorpay", "idem-pos-digital-1")
    assert order_pending["pickup_token_code"] is None
    assert (
        client.post(
            "/api/v1/payments/counter/collect",
            headers=student["headers"],
            json={"order_id": order_pending["id"], "payment_method": "upi_pos"},
        ).status_code
        == 403
    )

    collected = client.post(
        "/api/v1/payments/counter/collect",
        headers=cashier["headers"],
        json={"order_id": order_pending["id"], "payment_method": "upi_pos"},
    )
    assert collected.status_code == 200
    assert collected.json()["payment_status"] == "CONFIRMED"
    assert collected.json()["pickup_token_code"] is not None
