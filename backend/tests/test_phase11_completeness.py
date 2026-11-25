from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import httpx
import respx
from sqlalchemy import select

from app.core.config import settings
from app.integrations.expo_push_provider import EXPO_PUSH_URL, send_expo_push
from app.integrations.razorpay_client import razorpay_gateway
from app.integrations.sms_provider import send_sms_or_whatsapp
from app.models.auth import PasswordResetToken, User
from app.models.college import Canteen
from app.models.inventory import InventoryItem
from app.models.menu import Ingredient
from app.workers import tasks
from tests.conftest import login_as


def test_admin_orders_and_user_status_controls(client):
    admin_hdrs = login_as(client, "admin@collegebites.edu", "Admin@12345")["headers"]
    student_hdrs = login_as(client, "student@collegebites.edu", "Student@12345")["headers"]

    # Students must never access admin orders or user management
    assert client.get("/api/v1/admin/orders", headers=student_hdrs).status_code == 403

    orders_res = client.get("/api/v1/admin/orders", headers=admin_hdrs)
    assert orders_res.status_code == 200
    assert isinstance(orders_res.json(), list)

    users_res = client.get("/api/v1/admin/users", headers=admin_hdrs)
    assert users_res.status_code == 200
    student = next(u for u in users_res.json() if u["email"] == "student@collegebites.edu")

    # Suspend then reactivate customer account
    deact = client.patch(f"/api/v1/admin/users/{student['id']}/status", json={"is_active": False}, headers=admin_hdrs)
    assert deact.status_code == 200
    assert deact.json()["is_active"] is False

    react = client.patch(f"/api/v1/admin/users/{student['id']}/status", json={"is_active": True}, headers=admin_hdrs)
    assert react.status_code == 200
    assert react.json()["is_active"] is True


def test_sms_webhook_and_twilio_dispatch(monkeypatch):
    with respx.mock:
        route = respx.post("https://sms.example.edu/send").mock(return_value=httpx.Response(200, json={"ok": True}))
        monkeypatch.setattr(settings, "SMS_PROVIDER", "webhook")
        monkeypatch.setattr(settings, "SMS_WEBHOOK_URL", "https://sms.example.edu/send")
        ok, status = send_sms_or_whatsapp("+919876543210", "Token A001 ready", channel="sms")
        assert ok is True
        assert status == "dispatched_webhook"
        assert route.called


def test_celery_maintenance_tasks(clean_db_and_seed, monkeypatch):
    db_session = clean_db_and_seed

    @contextmanager
    def _test_session_ctx():
        yield db_session

    monkeypatch.setattr(tasks, "SessionLocal", lambda: _test_session_ctx())

    # Expired password-reset token cleanup (OTP permanently removed)
    any_user = db_session.scalar(select(User))
    db_session.add(
        PasswordResetToken(
            user_id=any_user.id,
            token_hash="deadbeef" * 8,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
    )
    db_session.commit()
    res = tasks.cleanup_expired_auth_artifacts_task()
    assert res["deleted_password_reset_tokens"] >= 1

    # Low stock alert scan creates notification once
    canteen = db_session.scalar(select(Canteen))
    ing = Ingredient(canteen_id=canteen.id, name="Cardamom Test", sku="CARD-T01", unit="grams")
    db_session.add(ing)
    db_session.flush()
    db_session.add(
        InventoryItem(
            canteen_id=canteen.id,
            ingredient_id=ing.id,
            unit="grams",
            current_quantity=5,
            reorder_level=20,
        )
    )
    db_session.commit()

    scan1 = tasks.scan_inventory_alerts_task()
    assert scan1["alerts_created"] >= 1
    scan2 = tasks.scan_inventory_alerts_task()
    assert scan2["alerts_created"] == 0


def test_scheduled_maintenance_http_cron_and_rbac(client, monkeypatch):
    from app.core.config import settings

    # Unauthenticated and short secrets must be rejected cleanly
    assert client.post("/api/v1/admin/maintenance/run").status_code == 401
    monkeypatch.setattr(settings, "CRON_SECRET", "too-short")
    assert client.post("/api/v1/admin/maintenance/run", headers={"Authorization": "Bearer too-short"}).status_code == 401

    # Non-admin student JWT forbidden
    student_hdrs = login_as(client, "student@collegebites.edu", "Student@12345")["headers"]
    assert client.post("/api/v1/admin/maintenance/run", headers=student_hdrs).status_code == 403

    # Valid CRON_SECRET (Vercel Schedule) succeeds
    valid_secret = "cb_prod_cron_secret_at_least_32_characters"
    monkeypatch.setattr(settings, "CRON_SECRET", valid_secret)
    bad = client.post("/api/v1/admin/maintenance/run", headers={"Authorization": "Bearer wrong-secret"})
    assert bad.status_code == 401
    cron_ok = client.post("/api/v1/admin/maintenance/run", headers={"Authorization": f"Bearer {valid_secret}"})
    assert cron_ok.status_code == 200
    assert cron_ok.json()["trigger"] == "vercel_schedule"

    # Admin JWT manual trigger also succeeds
    admin_hdrs = login_as(client, "admin@collegebites.edu", "Admin@12345")["headers"]
    adm_ok = client.post("/api/v1/admin/maintenance/run", headers=admin_hdrs)
    assert adm_ok.status_code == 200
    assert adm_ok.json()["trigger"] == "admin_manual"


def test_expo_push_kitchen_ingredient_unavailable_and_favourites_list(client):
    # Expo push dispatch via respx
    with respx.mock:
        push_route = respx.post(EXPO_PUSH_URL).mock(return_value=httpx.Response(200, json={"data": {"status": "ok"}}))
        ok, st = send_expo_push("ExponentPushToken[test123]", "Ready", "Token A001 is ready")
        assert ok is True
        assert st == "sent_expo_push"
        assert push_route.called

    # Kitchen ingredient listing & mark unavailable
    kitchen_hdrs = login_as(client, "kitchen@collegebites.edu", "Staff@12345")["headers"]
    canteens = client.get("/api/v1/canteens").json()
    main = next(c for c in canteens if c["code"] == "MAIN")

    ings = client.get(f"/api/v1/kitchen/canteens/{main['id']}/ingredients", headers=kitchen_hdrs)
    assert ings.status_code == 200
    assert len(ings.json()) >= 1
    first_ing = ings.json()[0]
    rep = client.post(
        f"/api/v1/kitchen/ingredients/{first_ing['inventory_item_id']}/unavailable",
        json={"reason": "Finished in kitchen"},
        headers=kitchen_hdrs,
    )
    assert rep.status_code == 200
    assert rep.json()["current_quantity"] == "0.000"

    # Saved favourites full item list & push token registration
    student_hdrs = login_as(client, "student@collegebites.edu", "Student@12345")["headers"]
    pt = client.post(
        "/api/v1/notifications/push-tokens",
        json={"token": "ExponentPushToken[mobile123]", "platform": "android"},
        headers=student_hdrs,
    )
    assert pt.status_code == 200
    assert pt.json()["expo_push_token"] == "ExponentPushToken[mobile123]"
    menu_items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    assert client.post(f"/api/v1/customers/favourites/{menu_items[0]['id']}", headers=student_hdrs).status_code == 200
    fav_list = client.get("/api/v1/customers/favourites", headers=student_hdrs)
    assert fav_list.status_code == 200
    assert len(fav_list.json()) >= 1
    assert fav_list.json()[0]["id"] == menu_items[0]["id"]


def test_razorpay_checkout_verify_webhook_idempotency_and_failure(client):
    import json

    student_hdrs = login_as(client, "student@collegebites.edu", "Student@12345")["headers"]
    canteens = client.get("/api/v1/canteens").json()
    snacks = next(c for c in canteens if c["code"] == "MAIN")
    items = client.get(f"/api/v1/menus/canteens/{snacks['id']}/items").json()
    food = items[0]

    assert (
        client.post(
            "/api/v1/carts/items",
            json={"canteen_id": snacks["id"], "food_item_id": food["id"], "quantity": 1},
            headers=student_hdrs,
        ).status_code
        == 200
    )

    co = client.post(
        "/api/v1/orders/checkout",
        json={"canteen_id": snacks["id"], "payment_method": "razorpay", "accepted_policy": True},
        headers=student_hdrs,
    )
    assert co.status_code == 201, co.text
    ord_data = co.json()
    rzp_oid = ord_data["razorpay_order_id"]
    assert rzp_oid.startswith("order_")
    assert ord_data["pickup_token_code"] is None

    # Config endpoint must never expose secrets
    cfg = client.get("/api/v1/payments/razorpay/config")
    assert cfg.status_code == 200
    assert "secret" not in str(cfg.json()).lower()

    # Invalid Razorpay signature must be rejected
    bad = client.post(
        "/api/v1/payments/razorpay/verify",
        json={
            "order_id": ord_data["id"],
            "razorpay_order_id": rzp_oid,
            "razorpay_payment_id": "pay_bad_001",
            "razorpay_signature": "bad_sig_value",
        },
        headers=student_hdrs,
    )
    assert bad.status_code == 400

    # Valid signature generates token + receipt
    pay_id = "pay_p11_001"
    sig = razorpay_gateway.compute_test_payment_signature(razorpay_order_id=rzp_oid, razorpay_payment_id=pay_id)
    ok = client.post(
        "/api/v1/payments/razorpay/verify",
        json={
            "order_id": ord_data["id"],
            "razorpay_order_id": rzp_oid,
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
        headers=student_hdrs,
    )
    assert ok.status_code == 200, ok.text
    token_code = ok.json()["pickup_token_code"]
    assert token_code is not None

    # Duplicate Razorpay payment.captured webhook delivery must stay idempotent without duplicating token
    wh_payload = json.dumps(
        {
            "event_id": f"evt_test_{ord_data['order_number']}",
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": pay_id,
                        "order_id": rzp_oid,
                        "amount": int(float(ord_data["total_amount"]) * 100),
                        "currency": "INR",
                        "status": "captured",
                    }
                }
            },
        }
    ).encode("utf-8")
    wh_sig = razorpay_gateway.compute_test_webhook_signature(raw_body=wh_payload)
    w1 = client.post("/api/v1/payments/razorpay/webhook", content=wh_payload, headers={"X-Razorpay-Signature": wh_sig})
    w2 = client.post("/api/v1/payments/razorpay/webhook", content=wh_payload, headers={"X-Razorpay-Signature": wh_sig})
    assert w1.status_code == 200 and w2.status_code == 200
    assert w2.json()["status"] == "already_processed"

    # Delayed / out-of-order payment.failed webhook MUST NOT downgrade an already confirmed order
    late_fail = json.dumps(
        {
            "event_id": f"evt_late_fail_{ord_data['order_number']}",
            "event": "payment.failed",
            "payload": {"payment": {"entity": {"id": pay_id, "order_id": rzp_oid, "error_description": "Delayed event"}}},
        }
    ).encode("utf-8")
    late_fail_sig = razorpay_gateway.compute_test_webhook_signature(raw_body=late_fail)
    lf_res = client.post("/api/v1/payments/razorpay/webhook", content=late_fail, headers={"X-Razorpay-Signature": late_fail_sig})
    assert lf_res.status_code == 200
    assert lf_res.json()["status"] in ("processed", "ignored_non_pending")
    assert client.get(f"/api/v1/orders/{ord_data['order_number']}", headers=student_hdrs).json()["payment_status"] == "CONFIRMED"

    # Invalid webhook signature rejection
    bad_wh = client.post("/api/v1/payments/razorpay/webhook", content=late_fail, headers={"X-Razorpay-Signature": "bad_sig"})
    assert bad_wh.status_code == 400

    # Separate order failure endpoint path + late capture conflict detection
    assert (
        client.post(
            "/api/v1/carts/items",
            json={"canteen_id": snacks["id"], "food_item_id": food["id"], "quantity": 1},
            headers=student_hdrs,
        ).status_code
        == 200
    )
    co3 = client.post(
        "/api/v1/orders/checkout",
        json={"canteen_id": snacks["id"], "payment_method": "razorpay", "accepted_policy": True},
        headers=student_hdrs,
    )
    assert co3.status_code == 201
    f_res = client.post(
        "/api/v1/payments/razorpay/fail",
        json={"order_id": co3.json()["id"], "reason": "UPI declined"},
        headers=student_hdrs,
    )
    assert f_res.status_code == 200
    assert f_res.json()["status"] == "PAYMENT_FAILED"


def test_razorpay_live_sdk_order_and_payment_verification(client, monkeypatch):
    """Exercise Razorpay live API order/payment verification paths with mocked gateway transport."""
    student_hdrs = login_as(client, "student@collegebites.edu", "Student@12345")["headers"]
    canteens = client.get("/api/v1/canteens").json()
    main_c = next(c for c in canteens if c["code"] == "MAIN")
    items = client.get(f"/api/v1/menus/canteens/{main_c['id']}/items").json()
    food = items[0]

    assert (
        client.post(
            "/api/v1/carts/items",
            json={"canteen_id": main_c["id"], "food_item_id": food["id"], "quantity": 1},
            headers=student_hdrs,
        ).status_code
        == 200
    )

    state = {"status": "captured", "amount": 0, "currency": "INR"}

    monkeypatch.setattr(settings, "RAZORPAY_TEST_MODE", False)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_mock_pub")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "rzp_test_mock_secret_key_value_123")

    def _fake_create_order(*, amount_inr, receipt_ref: str, notes=None):
        amount_paise = int((amount_inr * 100).quantize(amount_inr)) if hasattr(amount_inr, "quantize") else int(float(amount_inr) * 100)
        state["amount"] = int(float(amount_inr) * 100)
        return {"id": "order_live_mock_001", "amount": state["amount"], "currency": "INR", "status": "created"}

    def _fake_fetch_payment(payment_id: str):
        return {
            "id": payment_id,
            "order_id": "order_live_mock_001",
            "status": state["status"],
            "amount": state["amount"],
            "currency": state["currency"],
            "method": "upi",
        }

    monkeypatch.setattr(razorpay_gateway, "create_order", _fake_create_order)
    monkeypatch.setattr(razorpay_gateway, "fetch_payment", _fake_fetch_payment)

    co = client.post(
        "/api/v1/orders/checkout",
        json={"canteen_id": main_c["id"], "payment_method": "razorpay", "accepted_policy": True},
        headers=student_hdrs,
    )
    assert co.status_code == 201, co.text
    ord_data = co.json()
    assert ord_data["razorpay_order_id"] == "order_live_mock_001"
    assert ord_data["razorpay_key_id"] == "rzp_test_mock_pub"

    import hashlib
    import hmac

    pay_id = "pay_live_mock_001"
    valid_sig = hmac.new(
        b"rzp_test_mock_secret_key_value_123",
        f"order_live_mock_001|{pay_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Underpaid gateway amount mismatch must be rejected
    expected_amt = state["amount"]
    state["amount"] = max(1, expected_amt - 100)
    underpaid = client.post(
        "/api/v1/payments/razorpay/verify",
        json={
            "order_id": ord_data["id"],
            "razorpay_order_id": "order_live_mock_001",
            "razorpay_payment_id": pay_id,
            "razorpay_signature": valid_sig,
        },
        headers=student_hdrs,
    )
    assert underpaid.status_code == 400

    # Exact amount captured -> order confirmed & idempotent repeat verify returns same token
    state["amount"] = expected_amt
    ok = client.post(
        "/api/v1/payments/razorpay/verify",
        json={
            "order_id": ord_data["id"],
            "razorpay_order_id": "order_live_mock_001",
            "razorpay_payment_id": pay_id,
            "razorpay_signature": valid_sig,
        },
        headers=student_hdrs,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["payment_status"] == "CONFIRMED"
    tok = ok.json()["pickup_token_code"]
    assert tok is not None

    ok_again = client.post(
        "/api/v1/payments/razorpay/verify",
        json={
            "order_id": ord_data["id"],
            "razorpay_order_id": "order_live_mock_001",
            "razorpay_payment_id": pay_id,
            "razorpay_signature": valid_sig,
        },
        headers=student_hdrs,
    )
    assert ok_again.status_code == 200
    assert ok_again.json()["pickup_token_code"] == tok
