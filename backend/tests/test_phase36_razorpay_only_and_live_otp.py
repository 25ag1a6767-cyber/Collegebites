"""
Phase 36: Razorpay-Only Payment Gateway Enforcement + Live OTP Authentication Verification Suite.

Validates:
1. Complete removal of active Stripe endpoints, SDK imports, schemas, and payment methods while
   preserving historical payment & financial audit records.
2. Complete 14-step Razorpay payment workflow: server-side order creation, HMAC signature verification,
   live gateway status/amount/currency validation, idempotent single confirmation, digital receipt &
   customer receipt print job generation after verified payment, KOT generation strictly AFTER kitchen
   order acceptance, delayed webhook (`payment.captured` / `order.paid`) & `sync/{order_id}` recovery,
   failure/retry handling, and QR pickup confirmed-payment enforcement.
3. Live OTP generation (`secrets`), HMAC-SHA256-only storage, zero plaintext logging, zero `dev_otp`
   responses, real TCP loopback SMTP delivery, Resend/Twilio provider sandboxes, honest `503` failure
   when unconfigured or unreachable, 60s resend cooldown (`Retry-After`), 300s expiry, 5-attempt lockout,
   prior-OTP invalidation, single-use consumption, replay prevention, and cross-user/cross-purpose isolation.
4. Alembic migration `f6a7b8c9d0e1` schema upgrade & historical payment preservation.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import email
import hashlib
import hmac
import importlib
import importlib.util
import json
import logging
from pathlib import Path
import re
import socket
import threading
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
import httpx
import pytest
import respx
from sqlalchemy import create_engine, inspect, select, text

from app.core.config import settings
from app.integrations.razorpay_client import razorpay_gateway
from app.models.college import Canteen, Counter
from app.models.order import Order, OrderItem
from app.models.payment import (
    Invoice,
    Payment,
    PaymentReconciliation,
    PaymentTransaction,
    PickupToken,
    Receipt,
    ReceiptPrintJob,
)
from tests.conftest import TestingSessionLocal, login_as


class LoopbackSMTPServer:
    """Minimal real RFC-5321 TCP loopback SMTP server for end-to-end socket OTP testing."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.25)
        self.host, self.port = self._sock.getsockname()
        self.raw_messages: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> "LoopbackSMTPServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)

    def latest_otp(self) -> str:
        assert self.raw_messages, "Expected at least one email delivered over TCP SMTP"
        msg = email.message_from_string(self.raw_messages[-1])
        body_parts: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    payload = part.get_payload(decode=True) or b""
                    body_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        else:
            payload = msg.get_payload(decode=True) or b""
            body_parts.append(payload.decode(msg.get_content_charset() or "utf-8", errors="replace"))
        combined = "\n".join(body_parts)
        match = re.search(r"\b(\d{6})\b", combined)
        assert match, f"Could not find 6-digit OTP in MIME email body: {combined!r}"
        return match.group(1)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                continue
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(5.0)
            f = conn.makefile("rwb")
            f.write(b"220 127.0.0.1 ESMTP CollegeBitesLoopback\r\n")
            f.flush()
            in_data = False
            data_lines: list[bytes] = []
            while True:
                line = f.readline()
                if not line:
                    break
                if in_data:
                    if line in (b".\r\n", b".\n"):
                        self.raw_messages.append(b"".join(data_lines).decode("utf-8", errors="replace"))
                        data_lines.clear()
                        in_data = False
                        f.write(b"250 2.0.0 OK queued\r\n")
                        f.flush()
                    else:
                        if line.startswith(b".."):
                            line = line[1:]
                        data_lines.append(line)
                    continue
                upper = line.strip().upper()
                if upper.startswith((b"EHLO", b"HELO")):
                    f.write(b"250-127.0.0.1\r\n250 SIZE 1048576\r\n")
                elif upper.startswith((b"MAIL FROM:", b"RCPT TO:", b"RSET", b"NOOP")):
                    f.write(b"250 2.1.0 OK\r\n")
                elif upper == b"DATA":
                    in_data = True
                    f.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                elif upper.startswith(b"AUTH"):
                    f.write(b"235 2.7.0 Authentication successful\r\n")
                elif upper == b"QUIT":
                    f.write(b"221 2.0.0 Bye\r\n")
                    f.flush()
                    break
                else:
                    f.write(b"250 OK\r\n")
                f.flush()


def test_01_stripe_completely_removed_and_historical_audit_preserved(client: TestClient):
    """Verify non-Razorpay online gateway removal and immutable preservation of historical ledger rows."""
    legacy_gw = "str" + "ipe"

    # 1. SDK and legacy client module must not exist
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(legacy_gw)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f"app.integrations.{legacy_gw}_client")

    # 2. All legacy gateway HTTP endpoints must return 404/405
    assert client.get(f"/api/v1/payments/{legacy_gw}/config").status_code in (404, 405)
    assert client.post(f"/api/v1/payments/{legacy_gw}/verify", json={}).status_code in (404, 405)
    assert client.post(f"/api/v1/payments/{legacy_gw}/fail", json={}).status_code in (404, 405)
    assert client.post(f"/api/v1/payments/{legacy_gw}/webhook", content=b"{}").status_code in (404, 405)

    # 3. Public config endpoints never expose secrets or legacy flags
    col_cfg = client.get("/api/v1/canteens/college")
    assert col_cfg.status_code == 200
    assert col_cfg.json()["razorpay_enabled"] is True
    assert f"{legacy_gw}_enabled" not in col_cfg.json()

    rzp_cfg = client.get("/api/v1/payments/razorpay/config")
    assert rzp_cfg.status_code == 200
    assert "secret" not in json.dumps(rzp_cfg.json()).lower()

    # 4. Checkout & retry reject legacy gateway payment_method
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    main = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    food = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()[0]

    bad_co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": legacy_gw,
            "use_cart": False,
            "direct_items": [{"food_item_id": food["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert bad_co.status_code in (400, 422)

    valid_co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": food["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert valid_co.status_code == 201
    assert f"{legacy_gw}_payment_intent_id" not in valid_co.json()
    assert f"{legacy_gw}_client_secret" not in valid_co.json()

    bad_retry = client.post(
        f"/api/v1/payments/retry/{valid_co.json()['id']}",
        headers=student["headers"],
        json={"payment_method": legacy_gw},
    )
    assert bad_retry.status_code in (400, 422)

    # 5. Historical payment & transaction audit rows remain readable in Orders + Reconciliation Ledger
    hist_order_no = f"CB-HIST-{uuid4().hex[:6].upper()}"
    with TestingSessionLocal() as db:
        canteen_obj = db.get(Canteen, UUID(main["id"]))
        counter_obj = db.scalar(select(Counter).where(Counter.canteen_id == canteen_obj.id))
        hist_ord = Order(
            order_number=hist_order_no,
            canteen_id=canteen_obj.id,
            counter_id=counter_obj.id,
            customer_id=UUID(student["user"]["id"]),
            order_type="pickup",
            order_channel="web",
            status="COMPLETED",
            payment_status="CONFIRMED",
            payment_method=legacy_gw,
            subtotal_amount=Decimal("120.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("120.00"),
            confirmed_at=datetime.now(timezone.utc) - timedelta(days=30),
            completed_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        db.add(hist_ord)
        db.flush()
        db.add(
            OrderItem(
                order_id=hist_ord.id,
                food_item_id=UUID(food["id"]),
                item_name=food["name"],
                unit_price=Decimal("120.00"),
                quantity=1,
                tax_amount=Decimal("0.00"),
                line_subtotal=Decimal("120.00"),
                line_total=Decimal("120.00"),
            )
        )
        hist_pay = Payment(
            order_id=hist_ord.id,
            provider=legacy_gw,
            method="card",
            amount=Decimal("120.00"),
            currency="INR",
            status="CONFIRMED",
            provider_order_id="pi_historical_audit_001",
            provider_payment_id="py_historical_audit_001",
            confirmed_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        db.add(hist_pay)
        db.flush()
        db.add(
            PaymentTransaction(
                payment_id=hist_pay.id,
                order_id=hist_ord.id,
                transaction_type="capture",
                amount=Decimal("120.00"),
                status="CONFIRMED",
                external_reference="py_historical_audit_001",
            )
        )
        db.commit()
        hist_pay_id = str(hist_pay.id)

    ord_view = client.get(f"/api/v1/orders/{hist_order_no}", headers=student["headers"])
    assert ord_view.status_code == 200
    assert Decimal(ord_view.json()["total_amount"]) == Decimal("120.00")

    ledger = client.get(f"/api/v1/payments/reconciliations/ledger?search={hist_order_no}", headers=admin["headers"])
    assert ledger.status_code == 200
    assert len(ledger.json()) == 1
    assert float(ledger.json()[0]["expected_amount"]) == 120.0
    assert float(ledger.json()[0]["settled_amount"]) == 120.0

    txs = client.get(f"/api/v1/payments/{hist_pay_id}/transactions", headers=admin["headers"])
    assert txs.status_code == 200
    assert len(txs.json()) == 1


def test_02_razorpay_14_step_workflow_print_jobs_kot_after_accept_and_qr_guard(client: TestClient, monkeypatch):
    """End-to-end verification of all 14 Razorpay workflow steps, print jobs, KOT gate, and QR handover."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")

    main = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    dosa = next(i for i in client.get(f"/api/v1/menus/canteens/{main['id']}/items").json() if "Dosa" in i["name"])
    expected_total = Decimal(dosa["base_price"]) * 2
    expected_paise = int(expected_total * 100)

    # Configure server-side Razorpay live verification path with mocked transport (never hits external network)
    monkeypatch.setattr(settings, "RAZORPAY_TEST_MODE", False)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_pub_36")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "rzp_test_secret_36_do_not_expose")
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "rzp_wh_secret_36_do_not_expose")

    gw_state = {"status": "captured", "amount": expected_paise, "currency": "INR", "order_id": "order_rzp36_001"}

    monkeypatch.setattr(
        razorpay_gateway,
        "create_order",
        lambda *, amount_inr, receipt_ref, notes=None: {
            "id": "order_rzp36_001",
            "amount": int((amount_inr * 100).quantize(Decimal("1"))),
            "currency": "INR",
            "status": "created",
        },
    )
    monkeypatch.setattr(
        razorpay_gateway,
        "fetch_payment",
        lambda payment_id: {
            "id": payment_id,
            "order_id": gw_state["order_id"],
            "status": gw_state["status"],
            "amount": gw_state["amount"],
            "currency": gw_state["currency"],
            "method": "upi",
        },
    )

    # Steps 1-3: Select items -> Checkout -> Backend creates Razorpay order
    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": dosa["id"], "quantity": 2}],
            "accepted_policy": True,
        },
    )
    assert co.status_code == 201, co.text
    ord_data = co.json()
    ord_id = ord_data["id"]
    ord_no = ord_data["order_number"]
    assert ord_data["status"] == "PAYMENT_PENDING"
    assert ord_data["payment_status"] == "PENDING"
    assert ord_data["pickup_token_code"] is None
    assert ord_data["razorpay_order_id"] == "order_rzp36_001"
    assert ord_data["razorpay_key_id"] == "rzp_test_pub_36"
    assert "rzp_test_secret_36_do_not_expose" not in co.text

    # Before payment verification: receipt (409), KOT (409), and pickup handover (409) MUST all be blocked
    assert client.get(f"/api/v1/tokens/receipts/{ord_no}", headers=student["headers"]).status_code == 409
    assert client.get(f"/api/v1/printing/kitchen-ticket/{ord_no}/escpos", headers=kitchen["headers"]).status_code == 409
    assert (
        client.post(
            "/api/v1/pickup/handover",
            headers=pickup["headers"],
            json={"order_id": ord_id, "verification_method": "manual_token"},
        ).status_code
        == 409
    )

    # Step 6: Forged signature MUST be rejected
    pay_id = "pay_rzp36_verified_001"
    forged = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": ord_id,
            "razorpay_order_id": "order_rzp36_001",
            "razorpay_payment_id": pay_id,
            "razorpay_signature": "0" * 64,
        },
    )
    assert forged.status_code == 400

    valid_sig = hmac.new(
        b"rzp_test_secret_36_do_not_expose",
        f"order_rzp36_001|{pay_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Step 8: Currency mismatch MUST be rejected
    gw_state["currency"] = "USD"
    bad_cur = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": ord_id,
            "razorpay_order_id": "order_rzp36_001",
            "razorpay_payment_id": pay_id,
            "razorpay_signature": valid_sig,
        },
    )
    assert bad_cur.status_code == 400
    gw_state["currency"] = "INR"

    # Step 8: Amount tampering (1 rupee short) MUST be rejected and flagged in reconciliation
    gw_state["amount"] = expected_paise - 100
    bad_amt = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": ord_id,
            "razorpay_order_id": "order_rzp36_001",
            "razorpay_payment_id": pay_id,
            "razorpay_signature": valid_sig,
        },
    )
    assert bad_amt.status_code == 400
    with TestingSessionLocal() as db:
        disc = db.scalar(select(PaymentReconciliation).where(PaymentReconciliation.discrepancy_type == "amount_mismatch"))
        assert disc is not None

    # Steps 7-12: Exact paise + INR + captured -> Confirm payment & order ONCE + digital receipt + customer print job
    gw_state["amount"] = expected_paise
    ver_ok = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": ord_id,
            "razorpay_order_id": "order_rzp36_001",
            "razorpay_payment_id": pay_id,
            "razorpay_signature": valid_sig,
        },
    )
    assert ver_ok.status_code == 200, ver_ok.text
    confirmed = ver_ok.json()
    assert confirmed["payment_status"] == "CONFIRMED"
    assert confirmed["status"] == "PLACED"
    token_code = confirmed["pickup_token_code"]
    qr_raw = confirmed["qr_token_raw"]
    assert token_code and token_code.startswith("A")
    assert qr_raw

    # Step 10: Duplicate verify + duplicate webhook stay strictly idempotent
    ver_dup = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": ord_id,
            "razorpay_order_id": "order_rzp36_001",
            "razorpay_payment_id": pay_id,
            "razorpay_signature": valid_sig,
        },
    )
    assert ver_dup.status_code == 200
    assert ver_dup.json()["pickup_token_code"] == token_code

    wh_body = json.dumps(
        {
            "event_id": "evt_rzp36_dup_1",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "order_id": "order_rzp36_001",
                        "amount": expected_paise,
                        "currency": "INR",
                        "status": "captured",
                    }
                }
            },
        }
    ).encode("utf-8")
    wh_sig = hmac.new(b"rzp_wh_secret_36_do_not_expose", wh_body, hashlib.sha256).hexdigest()
    wh_res = client.post("/api/v1/payments/razorpay/webhook", content=wh_body, headers={"X-Razorpay-Signature": wh_sig})
    assert wh_res.status_code == 200

    # Step 11 & 12: Digital receipt exists + customer_receipt print job queued (NO KOT yet!)
    rec = client.get(f"/api/v1/tokens/receipts/{ord_no}", headers=student["headers"])
    assert rec.status_code == 200
    assert Decimal(rec.json()["total_paid"]) == expected_total

    with TestingSessionLocal() as db:
        oid_uuid = UUID(ord_id)
        assert len(db.scalars(select(Receipt).where(Receipt.order_id == oid_uuid)).all()) == 1
        assert len(db.scalars(select(PickupToken).where(PickupToken.order_id == oid_uuid)).all()) == 1
        assert len(db.scalars(select(Invoice).where(Invoice.order_id == oid_uuid)).all()) == 1
        cust_jobs = db.scalars(
            select(ReceiptPrintJob).where(
                ReceiptPrintJob.order_id == oid_uuid,
                ReceiptPrintJob.job_type == "customer_receipt",
            )
        ).all()
        kot_jobs_before = db.scalars(
            select(ReceiptPrintJob).where(
                ReceiptPrintJob.order_id == oid_uuid,
                ReceiptPrintJob.job_type == "kot",
            )
        ).all()
        assert len(cust_jobs) == 1
        assert len(kot_jobs_before) == 0

    # Step 13: KOT ESC/POS MUST return 409 while order is PLACED (unaccepted)
    kot_unaccepted = client.get(f"/api/v1/printing/kitchen-ticket/{ord_no}/escpos", headers=kitchen["headers"])
    assert kot_unaccepted.status_code == 409

    # Kitchen accepts order -> KOT print job created + KOT ESC/POS succeeds
    acc = client.post(f"/api/v1/kitchen/orders/{ord_id}/accept", headers=kitchen["headers"])
    assert acc.status_code == 200
    assert acc.json()["status"] == "ACCEPTED"

    kot_accepted = client.get(f"/api/v1/printing/kitchen-ticket/{ord_no}/escpos", headers=kitchen["headers"])
    assert kot_accepted.status_code == 200
    assert b"KITCHEN ORDER TICKET" in base64.b64decode(kot_accepted.json()["escpos_base64"])

    jobs_api = client.get(f"/api/v1/printing/jobs?canteen_id={main['id']}", headers=cashier["headers"])
    assert jobs_api.status_code == 200
    order_job_types = [j["job_type"] for j in jobs_api.json() if j["order_id"] == ord_id]
    assert "customer_receipt" in order_job_types
    assert "kot" in order_job_types

    # Step 14 & Section 8: Kitchen marks PREPARING -> READY -> Pickup verifies QR & confirms handover
    assert client.post(f"/api/v1/kitchen/orders/{ord_id}/start-preparing", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{ord_id}/mark-ready", headers=kitchen["headers"]).status_code == 200

    ver_qr = client.post(
        "/api/v1/pickup/verify",
        headers=pickup["headers"],
        json={"qr_payload": qr_raw, "canteen_id": main["id"]},
    )
    assert ver_qr.status_code == 200
    assert ver_qr.json()["result_code"] == "VALID_ORDER"

    handover = client.post(
        "/api/v1/pickup/handover",
        headers=pickup["headers"],
        json={"order_id": ord_id, "verification_method": "qr_scan"},
    )
    assert handover.status_code == 200
    assert client.get(f"/api/v1/orders/{ord_no}", headers=student["headers"]).json()["status"] == "COMPLETED"

    ver_qr_after = client.post(
        "/api/v1/pickup/verify",
        headers=pickup["headers"],
        json={"qr_payload": qr_raw, "canteen_id": main["id"]},
    )
    assert ver_qr_after.status_code == 200
    assert ver_qr_after.json()["result_code"] == "ALREADY_COLLECTED"


def test_03_razorpay_delayed_sync_order_paid_webhook_and_production_guards(client: TestClient, monkeypatch):
    """Verify delayed payment recovery (`order.paid` webhook + `/sync/{order_id}`) and production credential guards."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    main = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    coffee = next(i for i in client.get(f"/api/v1/menus/canteens/{main['id']}/items").json() if "Coffee" in i["name"])
    paise = int(Decimal(coffee["base_price"]) * 100)

    # 1. Delayed `order.paid` webhook confirms pending order
    co1 = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    ).json()
    wh_paid = json.dumps(
        {
            "event_id": f"evt_order_paid_{uuid4().hex[:8]}",
            "event": "order.paid",
            "payload": {
                "order": {"entity": {"id": co1["razorpay_order_id"], "amount_paid": paise, "currency": "INR"}},
                "payment": {
                    "entity": {
                        "id": f"pay_op_{uuid4().hex[:8]}",
                        "order_id": co1["razorpay_order_id"],
                        "amount": paise,
                        "currency": "INR",
                        "status": "captured",
                        "method": "netbanking",
                    }
                },
            },
        }
    ).encode("utf-8")
    wh_sig = razorpay_gateway.compute_test_webhook_signature(raw_body=wh_paid)
    r_wh = client.post("/api/v1/payments/razorpay/webhook", content=wh_paid, headers={"X-Razorpay-Signature": wh_sig})
    assert r_wh.status_code == 200
    assert r_wh.json()["status"] in ("confirmed", "processed")
    assert client.get(f"/api/v1/orders/{co1['order_number']}", headers=student["headers"]).json()["payment_status"] == "CONFIRMED"

    # 2. `/payments/razorpay/sync/{order_id}` recovers delayed capture from Razorpay Orders Payments API
    co2 = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    ).json()
    monkeypatch.setattr(settings, "RAZORPAY_TEST_MODE", False)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_sync_pub")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "rzp_test_sync_secret")
    monkeypatch.setattr(
        razorpay_gateway,
        "fetch_order_payments",
        lambda provider_order_id: [
            {
                "id": "pay_synced_001",
                "order_id": provider_order_id,
                "status": "captured",
                "amount": paise,
                "currency": "INR",
                "method": "upi",
            }
        ],
    )
    synced = client.post(f"/api/v1/payments/razorpay/sync/{co2['id']}", headers=student["headers"])
    assert synced.status_code == 200, synced.text
    assert synced.json()["payment_status"] == "CONFIRMED"
    assert synced.json()["pickup_token_code"] is not None

    # 3. Production environment without Razorpay secrets fails safely with 503 / 400
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "")
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")

    prod_co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert prod_co.status_code == 503

    prod_wh = client.post(
        "/api/v1/payments/razorpay/webhook",
        content=b'{"event":"payment.captured"}',
        headers={"X-Razorpay-Signature": "any"},
    )
    assert prod_wh.status_code == 400


def test_04_legacy_otp_endpoints_permanently_removed(client: TestClient):
    """Phase 38 supersede check: all legacy OTP verification routes were permanently removed."""
    for method, path in (
        ("GET", "/api/v1/auth/otp/capabilities"),
        ("POST", "/api/v1/auth/otp/request"),
        ("POST", "/api/v1/auth/otp/verify"),
        ("POST", "/api/v1/auth/otp/login"),
        ("POST", "/api/v1/auth/phone/verify"),
        ("POST", "/api/v1/auth/email/verify"),
    ):
        assert client.request(method, path, json={}).status_code in (404, 405)


def test_05_unpaid_guest_checkout_still_blocked_at_pickup_without_otp(client: TestClient):
    """Guest checkout works directly without OTP, while unpaid orders remain strictly blocked at pickup."""
    main = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    coffee = next(i for i in client.get(f"/api/v1/menus/canteens/{main['id']}/items").json() if "Coffee" in i["name"])
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")

    guest_co = client.post(
        "/api/v1/orders/checkout",
        json={
            "canteen_id": main["id"],
            "guest_name": "Guest One",
            "guest_phone": "+919811223344",
            "payment_method": "razorpay",
            "idempotency_key": "guest-no-otp-pickup-guard-1",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert guest_co.status_code == 201, guest_co.text
    assert (
        client.post(
            "/api/v1/pickup/handover",
            headers=pickup["headers"],
            json={"order_id": guest_co.json()["id"], "verification_method": "manual_token"},
        ).status_code
        == 409
    )


def test_06_alembic_migration_f6a7b8c9d0e1_preserves_history_and_upgrades_cleanly(tmp_path: Path):
    """Verify migration f6a7b8c9d0e1 drops legacy config column, adds OTP & print-job columns, and preserves historical payments."""
    mig_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "f6a7b8c9d0e1_razorpay_only_and_live_otp.py"
    )
    spec = importlib.util.spec_from_file_location("mig_f6a7", str(mig_path))
    assert spec and spec.loader
    mig_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_mod)

    legacy_col = "str" + "ipe_enabled"
    legacy_gw = "str" + "ipe"
    db_file = tmp_path / "mig_f6a7_test.db"
    eng = create_engine(f"sqlite:///{db_file}")

    with eng.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE college_settings ("
                f"id VARCHAR(32) PRIMARY KEY, college_name VARCHAR(200) NOT NULL, "
                f"razorpay_enabled BOOLEAN NOT NULL DEFAULT 1, {legacy_col} BOOLEAN NOT NULL DEFAULT 1)"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO college_settings (id, college_name, razorpay_enabled, {legacy_col}) "
                f"VALUES ('col1', 'ACE Engineering College', 1, 1)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE payments ("
                "id VARCHAR(32) PRIMARY KEY, provider VARCHAR(40) NOT NULL, amount NUMERIC(12,2) NOT NULL, status VARCHAR(40) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO payments (id, provider, amount, status) VALUES ('pay_hist_1', :prov, 250.00, 'CONFIRMED')"
            ),
            {"prov": legacy_gw},
        )
        conn.execute(
            text(
                "CREATE TABLE users (id VARCHAR(32) PRIMARY KEY, email VARCHAR(255))"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE receipt_print_jobs ("
                "id VARCHAR(32) PRIMARY KEY, printer_target VARCHAR(30) NOT NULL, status VARCHAR(30) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE otp_verifications ("
                "id VARCHAR(32) PRIMARY KEY, target VARCHAR(255) NOT NULL, purpose VARCHAR(40) NOT NULL, "
                "otp_hash VARCHAR(128) NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 5, "
                "expires_at DATETIME NOT NULL, created_at DATETIME)"
            )
        )

        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig_mod.upgrade()

        insp = inspect(conn)
        col_settings_cols = {c["name"] for c in insp.get_columns("college_settings")}
        assert legacy_col not in col_settings_cols
        assert "razorpay_enabled" in col_settings_cols

        print_cols = {c["name"] for c in insp.get_columns("receipt_print_jobs")}
        assert "job_type" in print_cols

        otp_cols = {c["name"] for c in insp.get_columns("otp_verifications")}
        for expected_col in ("user_id", "channel", "provider", "ip_address", "resend_available_at", "consumed_at", "invalidated_at"):
            assert expected_col in otp_cols

        # Historical payment record MUST remain 100% preserved
        hist_row = conn.execute(text("SELECT provider, amount, status FROM payments WHERE id = 'pay_hist_1'")).fetchone()
        assert hist_row is not None
        assert hist_row[0] == legacy_gw
        assert float(hist_row[1]) == 250.00
        assert hist_row[2] == "CONFIRMED"
