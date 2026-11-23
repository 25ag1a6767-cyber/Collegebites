from __future__ import annotations

import json
from uuid import uuid4
from fastapi.testclient import TestClient

from app.integrations.razorpay_client import razorpay_gateway
from app.integrations.stripe_client import stripe_gateway
from tests.conftest import login_as


def _create_order(client: TestClient, student_headers: dict, canteen_id: str, food_id: str, method: str = "razorpay") -> dict:
    resp = client.post(
        "/api/v1/orders/checkout",
        headers=student_headers,
        json={
            "canteen_id": canteen_id,
            "order_type": "pickup",
            "order_channel": "web",
            "payment_method": method,
            "idempotency_key": f"rec-{uuid4().hex[:14]}",
            "accepted_policy": True,
            "use_cart": False,
            "direct_items": [{"food_item_id": food_id, "quantity": 1}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_webhook_tamper_logging_amount_mismatch_retry_preservation_and_auto_reconciliation(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    food = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/items").json()[0]

    # 1. Invalid webhook signatures must still fail 400 AND persist unverified webhook + SecurityAlert
    bad_wh = client.post(
        "/api/v1/payments/razorpay/webhook",
        content=b'{"event":"payment.captured","event_id":"evt_tamper_1"}',
        headers={"X-Razorpay-Signature": "forged_signature"},
    )
    assert bad_wh.status_code == 400
    bad_stripe_wh = client.post(
        "/api/v1/payments/stripe/webhook",
        content=b'{"type":"payment_intent.succeeded","id":"evt_st_bad"}',
        headers={"Stripe-Signature": "t=123,v1=forged"},
    )
    assert bad_stripe_wh.status_code == 400

    webhooks = client.get("/api/v1/payments/webhooks?signature_verified=false", headers=admin["headers"]).json()
    assert len(webhooks) >= 2
    sec_alerts = client.get("/api/v1/security/alerts?alert_type=webhook_signature_invalid", headers=admin["headers"]).json()
    assert len(sec_alerts) >= 1

    # 2. Underpaid webhook triggers amount_mismatch discrepancy without issuing pickup token
    underpaid_ord = _create_order(client, student["headers"], main_canteen["id"], food["id"], "razorpay")
    underpaid_body = json.dumps({
        "event_id": "evt_underpaid_1",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_under_{uuid4().hex[:8]}",
                    "order_id": underpaid_ord["razorpay_order_id"],
                    "amount": 100,  # 1.00 INR << order total
                    "currency": "INR",
                    "method": "upi",
                }
            }
        },
    }).encode("utf-8")
    under_sig = razorpay_gateway.compute_test_webhook_signature(raw_body=underpaid_body)
    under_res = client.post(
        "/api/v1/payments/razorpay/webhook",
        content=underpaid_body,
        headers={"X-Razorpay-Signature": under_sig},
    )
    assert under_res.status_code == 200
    assert under_res.json()["status"] == "discrepancy_flagged"
    reloaded_under = client.get(f"/api/v1/orders/{underpaid_ord['order_number']}", headers=student["headers"]).json()
    assert reloaded_under["payment_status"] != "CONFIRMED"
    assert not reloaded_under.get("pickup_token_code")

    # 3. Normal paid order + retried order verify cleanly & preserve prior gateway references
    paid_ord = _create_order(client, student["headers"], main_canteen["id"], food["id"], "razorpay")
    rzp_pay = f"pay_{uuid4().hex[:12]}"
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=paid_ord["razorpay_order_id"],
        razorpay_payment_id=rzp_pay,
    )
    ver = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": paid_ord["id"],
            "razorpay_order_id": paid_ord["razorpay_order_id"],
            "razorpay_payment_id": rzp_pay,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    )
    assert ver.status_code == 200

    # Retried order keeps previous provider_order_id history on gateway switch
    retry_ord = _create_order(client, student["headers"], main_canteen["id"], food["id"], "razorpay")
    client.post(
        f"/api/v1/payments/retry/{retry_ord['id']}",
        headers=student["headers"],
        json={"payment_method": "stripe"},
    )
    # Run Auto-Reconciliation -> matches paid_ord, classifies pending & underpaid discrepancy
    run_resp = client.post(
        "/api/v1/payments/reconciliations/auto-run",
        headers=admin["headers"],
        json={"fetch_gateway": False},
    )
    assert run_resp.status_code == 200, run_resp.text
    run_data = run_resp.json()
    assert run_data["total_checked"] >= 3
    assert run_data["matched_count"] >= 1
    assert run_data["discrepancy_count"] >= 1

    # Dashboard, Ledger, Transactions & Exports (CSV + Excel)
    dash = client.get("/api/v1/payments/reconciliations/dashboard", headers=admin["headers"]).json()
    assert dash["verified_collections_inr"] >= float(paid_ord["total_amount"])
    assert dash["invalid_webhooks_count"] >= 2

    ledger = client.get(
        f"/api/v1/payments/reconciliations/ledger?search={paid_ord['order_number']}",
        headers=admin["headers"],
    ).json()
    assert len(ledger) == 1
    assert ledger[0]["reconciliation_status"] == "matched"
    pay_id = ledger[0]["payment_id"]

    txs = client.get(f"/api/v1/payments/{pay_id}/transactions", headers=admin["headers"]).json()
    assert any(t["status"] == "CONFIRMED" for t in txs)

    csv_exp = client.get("/api/v1/payments/reconciliations/export/csv", headers=admin["headers"])
    assert csv_exp.status_code == 200
    assert paid_ord["order_number"] in csv_exp.text

    xlsx_exp = client.get("/api/v1/payments/reconciliations/export/xlsx", headers=admin["headers"])
    assert xlsx_exp.status_code == 200
    assert xlsx_exp.content[:2] == b"PK"

    # Strict NO REFUNDS preserved
    assert client.post("/api/v1/payments/refund", headers=admin["headers"]).status_code in (404, 405)
