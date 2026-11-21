from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import httpx
import respx
from sqlalchemy import select

from app.core.config import settings
from app.integrations.expo_push_provider import EXPO_PUSH_URL, send_expo_push
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

    # Saved favourites full item list
    student_hdrs = login_as(client, "student@collegebites.edu", "Student@12345")["headers"]
    menu_items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    assert client.post(f"/api/v1/customers/favourites/{menu_items[0]['id']}", headers=student_hdrs).status_code == 200
    fav_list = client.get("/api/v1/customers/favourites", headers=student_hdrs)
    assert fav_list.status_code == 200
    assert len(fav_list.json()) >= 1
    assert fav_list.json()[0]["id"] == menu_items[0]["id"]
