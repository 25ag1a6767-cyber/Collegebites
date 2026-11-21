import base64
from decimal import Decimal
from fastapi.testclient import TestClient

from app.integrations.razorpay_client import razorpay_gateway
from tests.conftest import login_as


def _paid_order(client: TestClient, student_headers: dict):
    main = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    biryani = next(i for i in items if "Biryani" in i["name"])
    coffee = next(i for i in items if "Coffee" in i["name"])
    raita = next(a for a in biryani["addons"] if "Raita" in a["name"])

    order = client.post(
        "/api/v1/orders/checkout",
        headers=student_headers,
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "idempotency_key": "idem-rec-1",
            "use_cart": False,
            "accepted_policy": True,
            "direct_items": [
                {
                    "food_item_id": biryani["id"],
                    "quantity": 2,
                    "spice_level": "Extra Spicy",
                    "addons": [{"addon_id": raita["id"], "quantity": 1}],
                    "special_instructions": "Extra crispy onions",
                },
                {
                    "food_item_id": coffee["id"],
                    "quantity": 2,
                    "sugar_level": "No Sugar",
                },
            ],
        },
    ).json()
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=order["razorpay_order_id"], razorpay_payment_id="pay_rec_001"
    )
    verified = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student_headers,
        json={
            "order_id": order["id"],
            "razorpay_order_id": order["razorpay_order_id"],
            "razorpay_payment_id": "pay_rec_001",
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    ).json()
    return verified


def test_complete_receipt_pdf_escpos_and_reprint_preserving_token(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    order = _paid_order(client, student["headers"])

    # Fetch structured receipt
    rec = client.get(f"/api/v1/tokens/receipts/{order['order_number']}", headers=student["headers"]).json()
    assert rec["brand"] == "COLLEGEBITES"
    assert rec["college_name"] == "ACE Engineering College"
    assert rec["pickup_token"] == order["pickup_token_code"]
    assert rec["customer_mobile_masked"].endswith("3210") and "*" in rec["customer_mobile_masked"]
    assert len(rec["items"]) == 2
    assert any("Extra Spicy" in str(it["customizations"]) for it in rec["items"])
    assert any("Extra Raita" in str(it["customizations"]) for it in rec["items"])
    assert Decimal(rec["total_paid"]) == Decimal(order["total_amount"])
    assert len(rec["pickup_instructions"]) == 4

    # Download A4 and 80mm PDFs
    pdf_a4 = client.get(f"/api/v1/tokens/receipts/{order['order_number']}/pdf?format=a4", headers=student["headers"])
    assert pdf_a4.status_code == 200
    assert pdf_a4.headers["content-type"] == "application/pdf"
    assert pdf_a4.content.startswith(b"%PDF")

    pdf_80 = client.get(f"/api/v1/tokens/receipts/{order['order_number']}/pdf?format=80mm", headers=student["headers"])
    assert pdf_80.status_code == 200
    assert pdf_80.content.startswith(b"%PDF")

    # Download QR PNG
    qr_png = client.get(f"/api/v1/tokens/receipts/{order['order_number']}/qr.png", headers=student["headers"])
    assert qr_png.status_code == 200
    assert qr_png.content.startswith(b"\x89PNG")

    # ESC/POS thermal bytes for 58mm & 80mm
    esc58 = client.get(f"/api/v1/printing/receipts/{order['order_number']}/escpos?width=58mm", headers=cashier["headers"]).json()
    raw58 = base64.b64decode(esc58["escpos_base64"])
    assert b"COLLEGEBITES" in raw58
    assert order["pickup_token_code"].encode("ascii") in raw58

    # First print -> original; second print -> REPRINT preserving exact token & QR
    p1 = client.post(
        f"/api/v1/printing/receipts/{order['order_number']}/print",
        headers=cashier["headers"],
        json={"printer_target": "80mm", "paper_width": "80mm"},
    ).json()
    assert p1["is_reprint"] is False
    assert p1["status"] == "completed"

    p2 = client.post(
        f"/api/v1/printing/receipts/{order['order_number']}/print",
        headers=cashier["headers"],
        json={"printer_target": "80mm", "paper_width": "80mm"},
    ).json()
    assert p2["is_reprint"] is True

    rec_after = client.get(f"/api/v1/tokens/receipts/{order['order_number']}", headers=student["headers"]).json()
    assert rec_after["pickup_token"] == order["pickup_token_code"]
    assert rec_after["qr_payload"] == rec["qr_payload"]
    assert rec_after["is_reprint"] is True
    assert rec_after["reprint_label"] == "REPRINT #1"

    hist = client.get(f"/api/v1/printing/history/{order['order_number']}", headers=cashier["headers"]).json()
    assert len(hist) == 2
    assert hist[0]["is_reprint"] is True
    assert hist[0]["printed_by_label"] == "Counter Cashier"

    # Network print failure detection & retry
    p_fail = client.post(
        f"/api/v1/printing/receipts/{order['order_number']}/print",
        headers=cashier["headers"],
        json={"printer_target": "network_escpos", "paper_width": "80mm"},
    ).json()
    assert p_fail["status"] == "failed"
    retry = client.post(f"/api/v1/printing/jobs/{p_fail['id']}/retry", headers=cashier["headers"]).json()
    assert retry["retry_count"] == 1
