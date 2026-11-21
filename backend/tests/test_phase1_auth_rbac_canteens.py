from datetime import date, time
from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_health_and_college_info(client: TestClient):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    college_res = client.get("/api/v1/canteens/college")
    assert college_res.status_code == 200
    body = college_res.json()
    assert body["college_name"] == "ACE Engineering College"
    assert body["kiosk_enabled"] is False
    assert "finance office" in body["cancellation_policy_text"].lower()


def test_universal_customer_registration_login_refresh_logout(client: TestClient):
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Priya Nair",
            "email": "priya@aceec.ac.in",
            "phone": "+919123456789",
            "password": "StrongPassword123",
            "college_id_number": "25AG1A0010",
            "department": "CSE",
        },
    )
    assert reg.status_code == 201, reg.text
    tokens = reg.json()
    assert "customer" in tokens["user"]["roles"]
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["email"] == "priya@aceec.ac.in"

    # Refresh token rotation
    ref = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert ref.status_code == 200
    new_refresh = ref.json()["refresh_token"]
    assert new_refresh != refresh

    # Reusing old rotated refresh token must fail and revoke session
    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert reused.status_code == 401

    # New refresh token is now also invalidated because session was revoked
    after_revoke = client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert after_revoke.status_code == 401

    # Normalized 10-digit phone & formatted +91 phone + pasted whitespace password login work seamlessly
    p_login = client.post("/api/v1/auth/login", json={"identifier": "9123456789", "password": " StrongPassword123 "})
    assert p_login.status_code == 200, p_login.text
    p_login2 = client.post("/api/v1/auth/login", json={"identifier": "+91 9123456789", "password": "StrongPassword123"})
    assert p_login2.status_code == 200, p_login2.text


def test_otp_request_and_verification(client: TestClient):
    req = client.post("/api/v1/auth/otp/request", json={"target": "+919988776655", "purpose": "guest_checkout"})
    assert req.status_code == 200
    otp = req.json()["dev_otp"]
    assert len(otp) == 6

    bad = client.post("/api/v1/auth/otp/verify", json={"target": "+919988776655", "purpose": "guest_checkout", "code": "000000"})
    assert bad.status_code in (400, 429)

    ok = client.post("/api/v1/auth/otp/verify", json={"target": "+919988776655", "purpose": "guest_checkout", "code": otp})
    assert ok.status_code == 200
    assert ok.json()["verified"] is True
    assert ok.json()["verification_token"].startswith("OTPVER.")


def test_rbac_enforced_on_admin_and_canteen_routes(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")

    # Student and kitchen staff cannot create canteens or view audit logs
    for actor in (student, kitchen):
        r1 = client.post(
            "/api/v1/admin/canteens",
            headers=actor["headers"],
            json={"name": "Night Cafe", "slug": "night-cafe", "code": "NGT", "location": "Hostel"},
        )
        assert r1.status_code == 403
        r2 = client.get("/api/v1/admin/audit-logs", headers=actor["headers"])
        assert r2.status_code == 403

    # College Admin can create a new canteen + counter + kitchen + holiday
    created = client.post(
        "/api/v1/admin/canteens",
        headers=admin["headers"],
        json={
            "name": "Food Court Express",
            "slug": "food-court",
            "code": "FCE",
            "token_prefix": "F",
            "location": "North Lawn",
            "canteen_type": "food_court",
        },
    )
    assert created.status_code == 201, created.text
    canteen_id = created.json()["id"]

    # Detail includes auto-created Counter 1 and Kitchen
    detail = client.get(f"/api/v1/canteens/{canteen_id}")
    assert detail.status_code == 200
    assert len(detail.json()["counters"]) >= 1
    assert len(detail.json()["kitchens"]) >= 1

    # Add holiday and verify canteen temporarily unavailable on that date
    hol = client.post(
        "/api/v1/admin/holidays",
        headers=admin["headers"],
        json={
            "canteen_id": canteen_id,
            "holiday_date": date.today().isoformat(),
            "title": "Maintenance Day",
            "is_full_day": True,
        },
    )
    assert hol.status_code == 201
    detail_after = client.get(f"/api/v1/canteens/{canteen_id}").json()
    assert detail_after["is_open_now"] is False
    assert detail_after["crowd_level"] == "TEMPORARILY_UNAVAILABLE"


def test_email_otp_delivery_and_prod_sms_guard(client: TestClient, monkeypatch):
    from app.core.config import settings
    from app.services import auth_service

    sent_emails = []
    monkeypatch.setattr(
        auth_service,
        "send_email",
        lambda to_email, subject, body: sent_emails.append((to_email, subject, body)) or (True, "sent_smtp"),
    )
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SMS_PROVIDER", "none")

    email_res = client.post(
        "/api/v1/auth/otp/request",
        json={"target": "student@collegebites.edu", "purpose": "login"},
    )
    assert email_res.status_code == 200, email_res.text
    payload = email_res.json()
    assert payload["delivery_channel"] == "email"
    assert payload["dev_otp"] is None
    assert len(sent_emails) == 1
    assert sent_emails[0][0] == "student@collegebites.edu"

    # Phone OTP in production without SMS provider MUST fail explicitly with 400/503
    sms_res = client.post(
        "/api/v1/auth/otp/request",
        json={"target": "+919988776611", "purpose": "guest_checkout"},
    )
    assert sms_res.status_code in (400, 503)

    caps = client.get("/api/v1/auth/otp/capabilities")
    assert caps.status_code == 200
    assert caps.json()["sms_otp_enabled"] is False
    assert caps.json()["dev_echo_enabled"] is False
