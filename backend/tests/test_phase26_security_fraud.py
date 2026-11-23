from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.integrations.razorpay_client import razorpay_gateway
from app.models.auth import SessionRecord
from app.models.system import LoginAttempt, SecurityAlert
from tests.conftest import TestingSessionLocal, login_as


def test_brute_force_lockout_admin_unlock_and_security_dashboard(client: TestClient):
    # 1. Five consecutive wrong password attempts lock the student account and create SecurityAlert
    for _ in range(5):
        r = client.post(
            "/api/v1/auth/login",
            json={"identifier": "student@collegebites.edu", "password": "WrongPassword!1"},
        )
        assert r.status_code == 401

    # 6th attempt — even with the CORRECT password — must return 423 Locked
    locked_resp = client.post(
        "/api/v1/auth/login",
        json={"identifier": "student@collegebites.edu", "password": "Student@12345"},
    )
    assert locked_resp.status_code == 423, locked_resp.text

    # 2. College Admin inspects Security Dashboard, Login Attempts & Alerts
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    dash = client.get("/api/v1/security/dashboard", headers=admin["headers"]).json()
    assert dash["failed_logins_24h"] >= 5
    assert dash["locked_accounts_count"] >= 1
    assert dash["open_alerts"] >= 1

    alerts = client.get("/api/v1/security/alerts?status_filter=open", headers=admin["headers"]).json()
    brute_alerts = [a for a in alerts if a["alert_type"] == "brute_force_attempt"]
    assert brute_alerts
    locked_user_id = dash["locked_accounts"][0]["id"]

    # 3. Admin unlocks account -> student can log in again immediately
    unlock_resp = client.post(f"/api/v1/security/users/{locked_user_id}/unlock", headers=admin["headers"])
    assert unlock_resp.status_code == 200
    assert unlock_resp.json()["unlocked"] is True

    ok_resp = client.post(
        "/api/v1/auth/login",
        json={"identifier": "student@collegebites.edu", "password": "Student@12345"},
    )
    assert ok_resp.status_code == 200, ok_resp.text

    # Resolve the brute-force alert
    res_resp = client.post(
        f"/api/v1/security/alerts/{brute_alerts[0]['id']}/resolve",
        headers=admin["headers"],
        json={"status": "resolved", "notes": "Student verified and unlocked"},
    )
    assert res_resp.status_code == 200
    assert res_resp.json()["status"] == "resolved"


def test_session_expiry_deactivation_revocation_and_qr_tamper_alerts(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")

    # 1. Expiring the DB SessionRecord immediately rejects JWT access on HTTP and WS
    with TestingSessionLocal() as db:
        sess = db.scalars(
            select(SessionRecord).where(SessionRecord.user_id == UUID(student["user"]["id"]))
        ).first()
        assert sess is not None
        sess.expires_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        db.commit()

    me_expired = client.get("/api/v1/auth/me", headers=student["headers"])
    assert me_expired.status_code == 401

    # 2. Deactivating a user revokes their active sessions and refresh tokens
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    deact = client.patch(
        f"/api/v1/admin/users/{cashier['user']['id']}/status",
        headers=admin["headers"],
        json={"is_active": False},
    )
    assert deact.status_code == 200
    assert client.get("/api/v1/auth/me", headers=cashier["headers"]).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": cashier["refresh_token"]}).status_code in (401, 403)

    # Re-activate cashier cleanly
    client.patch(
        f"/api/v1/admin/users/{cashier['user']['id']}/status",
        headers=admin["headers"],
        json={"is_active": True},
    )

    # 3. Scanning a tampered QR raises qr_tamper_attempt alert + logs QRVerificationEvent
    bad_qr = client.post(
        "/api/v1/pickup/verify",
        headers=pickup["headers"],
        json={"qr_payload": "CBQR.tamperedpayload123456.badsignature000000"},
    )
    assert bad_qr.status_code == 200
    assert bad_qr.json()["result_code"] == "INVALID_QR"

    qr_events = client.get("/api/v1/security/qr-events?is_valid=false", headers=admin["headers"]).json()
    assert any(ev["result_code"] == "INVALID_QR" for ev in qr_events)

    alerts = client.get("/api/v1/security/alerts?status_filter=open", headers=admin["headers"]).json()
    assert any(a["alert_type"] == "qr_tamper_attempt" for a in alerts)

    # Audit log search filters cleanly
    audits = client.get("/api/v1/security/audit-logs?action=user.status_updated", headers=admin["headers"]).json()
    assert len(audits) >= 1


def test_duplicate_handover_fraud_alert_and_rate_limit_enforcement(client: TestClient):
    # Prepare a paid READY order and complete handover once
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")

    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    food = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/items").json()[0]

    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main_canteen["id"],
            "order_type": "pickup",
            "order_channel": "web",
            "payment_method": "razorpay",
            "idempotency_key": f"sec-{uuid4().hex[:14]}",
            "accepted_policy": True,
            "use_cart": False,
            "direct_items": [{"food_item_id": food["id"], "quantity": 1}],
        },
    ).json()
    rzp_pay = f"pay_{uuid4().hex[:14]}"
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=co["razorpay_order_id"],
        razorpay_payment_id=rzp_pay,
    )
    paid = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": co["id"],
            "razorpay_order_id": co["razorpay_order_id"],
            "razorpay_payment_id": rzp_pay,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    ).json()

    client.post(f"/api/v1/kitchen/orders/{paid['id']}/accept", headers=kitchen["headers"])
    client.post(f"/api/v1/kitchen/orders/{paid['id']}/start-preparing", headers=kitchen["headers"])
    client.post(f"/api/v1/kitchen/orders/{paid['id']}/mark-ready", headers=kitchen["headers"])

    ho1 = client.post(
        "/api/v1/pickup/handover",
        headers=pickup["headers"],
        json={"order_id": paid["id"], "verification_method": "manual_token"},
    )
    assert ho1.status_code == 200

    # Second handover attempt -> 409 + logs ALREADY_COLLECTED SecurityAlert
    ho2 = client.post(
        "/api/v1/pickup/handover",
        headers=pickup["headers"],
        json={"order_id": paid["id"], "verification_method": "manual_token"},
    )
    assert ho2.status_code == 409

    alerts = client.get("/api/v1/security/alerts?alert_type=duplicate_handover_attempt", headers=admin["headers"]).json()
    assert len(alerts) >= 1

    # Canteen Manager can inspect canteen-scoped security alerts; Student receives 403
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    assert client.get("/api/v1/security/dashboard", headers=manager["headers"]).status_code == 200
    assert client.get("/api/v1/security/dashboard", headers=student["headers"]).status_code == 403
    assert client.get("/api/v1/security/audit-logs", headers=manager["headers"]).status_code == 403

    # Explicitly exercise SlowAPI rate limiter on /otp/request (temporarily enabled)
    prev_enabled = limiter.enabled
    limiter.enabled = True
    try:
        hit_429 = False
        for idx in range(12):
            resp = client.post(
                "/api/v1/auth/otp/request",
                json={"target": f"rl{idx}@collegebites.edu", "purpose": "login"},
            )
            if resp.status_code == 429:
                hit_429 = True
                break
        assert hit_429, "Expected HTTP 429 from rate limiter on /auth/otp/request"
    finally:
        limiter.enabled = prev_enabled
