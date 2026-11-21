from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import httpx
import respx
from sqlalchemy import select

from app.core.config import settings
from app.integrations.sms_provider import send_sms_or_whatsapp
from app.models.auth import OTPVerification
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

    # Expired OTP cleanup
    db_session.add(
        OTPVerification(
            target="+919999988888",
            purpose="guest_checkout",
            otp_hash="deadbeef",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
    )
    db_session.commit()
    res = tasks.cleanup_expired_auth_artifacts_task()
    assert res["deleted_otps"] >= 1

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
