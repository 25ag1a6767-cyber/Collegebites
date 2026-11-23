from datetime import date, timedelta
from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_advanced_staff_rbac_weekly_schedules_attendance_and_workload(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")

    canteens = client.get("/api/v1/canteens").json()
    canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    cid = canteen["id"]

    # 1. Manager views dashboard KPIs and updates kitchen staff profile
    dash = client.get(f"/api/v1/staff/dashboard?canteen_id={cid}", headers=manager["headers"])
    assert dash.status_code == 200, dash.text
    assert dash.json()["total_staff"] >= 3

    upd = client.patch(
        f"/api/v1/staff/{kitchen['user']['id']}",
        headers=manager["headers"],
        json={"designation": "Head Chef", "weekly_hours_target": 40, "phone": "+919876500112"},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["designation"] == "Head Chef"
    assert upd.json()["weekly_hours_target"] == 40

    # Canteen Manager CANNOT edit College Admin profile
    assert client.patch(
        f"/api/v1/staff/{admin['user']['id']}",
        headers=manager["headers"],
        json={"designation": "Hacked"},
    ).status_code in (403, 404)

    # 2. Granular per-user permission override (grant extra + revoke existing)
    perms_list = client.get("/api/v1/admin/permissions", headers=admin["headers"]).json()
    assert len(perms_list) >= 10
    set_perms = client.put(
        f"/api/v1/admin/users/{kitchen['user']['id']}/permissions",
        headers=admin["headers"],
        json={"grant": ["report:view"], "revoke": ["kitchen:report_delay"]},
    )
    assert set_perms.status_code == 200, set_perms.text
    kitchen_perms = set_perms.json()["permissions"]
    assert "report:view" in kitchen_perms
    assert "kitchen:report_delay" not in kitchen_perms

    # Kitchen user logging in or fetching /auth/me immediately sees updated permissions
    me = client.get("/api/v1/auth/me", headers=kitchen["headers"]).json()
    assert "report:view" in me["permissions"]
    assert "kitchen:report_delay" not in me["permissions"]

    # 3. Weekly duty schedule template + generate week shifts + conflict prevention
    today = date.today()
    wk = client.post(
        "/api/v1/staff/weekly-schedules",
        headers=manager["headers"],
        json={
            "staff_user_id": kitchen["user"]["id"],
            "canteen_id": cid,
            "day_of_week": today.weekday(),
            "start_time": "08:00:00",
            "end_time": "14:00:00",
            "shift_type": "morning",
        },
    )
    assert wk.status_code == 201, wk.text

    gen = client.post(
        "/api/v1/staff/weekly-schedules/generate-week",
        headers=manager["headers"],
        json={"canteen_id": cid, "week_start_date": today.isoformat()},
    )
    assert gen.status_code == 200, gen.text
    assert gen.json()["created"] == 1

    # Duplicate overlapping shift on same day must be rejected (409)
    overlap = client.post(
        "/api/v1/staff/shifts",
        headers=manager["headers"],
        json={
            "staff_user_id": kitchen["user"]["id"],
            "canteen_id": cid,
            "shift_date": today.isoformat(),
            "start_time": "10:00:00",
            "end_time": "16:00:00",
            "shift_type": "afternoon",
        },
    )
    assert overlap.status_code == 409

    # 4. Self-service portal for non-manager staff (check-in/out, availability, leave request, review)
    assert client.post(f"/api/v1/staff/attendance/check-in?canteen_id={cid}", headers=kitchen["headers"]).status_code == 200
    assert client.patch("/api/v1/staff/me/availability", headers=kitchen["headers"], json={"availability_status": "on_break"}).status_code == 200
    assert client.post("/api/v1/staff/attendance/check-out", headers=kitchen["headers"]).status_code == 200

    next_week = today + timedelta(days=7)
    leave_req = client.post(
        "/api/v1/staff/attendance/leave/request",
        headers=cashier["headers"],
        json={
            "attendance_date": next_week.isoformat(),
            "end_date": (next_week + timedelta(days=1)).isoformat(),
            "leave_type": "casual",
            "reason": "Family event",
        },
    )
    assert leave_req.status_code == 201, leave_req.text
    att_id = leave_req.json()["id"]

    rev = client.patch(
        f"/api/v1/staff/attendance/{att_id}/review",
        headers=manager["headers"],
        json={"approved": True, "review_notes": "Backup cashier assigned"},
    )
    assert rev.status_code == 200
    assert rev.json()["status"] == "leave"
    assert rev.json()["approval_status"] == "approved"

    overview = client.get("/api/v1/staff/me/overview", headers=kitchen["headers"])
    assert overview.status_code == 200, overview.text
    assert len(overview.json()["upcoming_shifts"]) >= 1
    assert len(overview.json()["weekly_schedules"]) >= 1
    assert len(overview.json()["activity_logs"]) >= 1

    # 5. Workload & activity report reflect actual shifts, tasks, and orders
    biryani = next(i for i in client.get(f"/api/v1/menus/canteens/{cid}/items").json() if "Biryani" in i["name"])
    assert client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={"canteen_id": cid, "payment_method": "upi_pos", "items": [{"food_item_id": biryani["id"], "quantity": 1}]},
    ).status_code == 201

    workload = client.get(f"/api/v1/staff/workload?canteen_id={cid}", headers=manager["headers"]).json()
    cashier_metric = next(m for m in workload["staff_metrics"] if m["user_id"] == cashier["user"]["id"])
    assert cashier_metric["pos_payments_processed"] >= 1
    assert len(client.get(f"/api/v1/staff/activity?canteen_id={cid}", headers=manager["headers"]).json()) >= 1
