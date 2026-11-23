from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.time_utils import today_college
from app.integrations.razorpay_client import razorpay_gateway
from tests.conftest import login_as


def test_phase31_college_events_bulk_ordering_and_reports(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    item_a = items[0]
    item_b = items[1]

    now = datetime.now(timezone.utc)
    today_col = today_college()

    # 1. Create active College Event with min=10, max=200 and future deadline
    ev_res = client.post(
        "/api/v1/events",
        headers=admin["headers"],
        json={
            "canteen_id": cid,
            "event_code": "TECHFEST-2026-MAIN",
            "name": "Annual AI & Robotics Symposium",
            "department": "Computer Science & Engineering",
            "organizer_name": "Dr. Priya Nair",
            "contact_phone": "+919845012345",
            "contact_email": "priya.nair@collegebites.edu",
            "event_date": (today_col + timedelta(days=5)).isoformat(),
            "location": "Main Auditorium Block B",
            "description": "Departmental symposium catering",
            "ordering_deadline": (now + timedelta(days=2)).isoformat(),
            "eligible_food_item_ids": [item_a["id"]],
            "min_order_quantity": 10,
            "max_order_quantity": 200,
            "is_active": True,
        },
    )
    assert ev_res.status_code == 201, ev_res.text
    ev = ev_res.json()
    ev_id = ev["id"]

    # 2. Validate bulk ordering rules:
    # 2a. Below min_order_quantity (5 < 10) must fail
    below_min = client.post(
        f"/api/v1/events/{ev_id}/bulk-orders",
        headers=student["headers"],
        json={
            "scheduled_prep_at": (now + timedelta(days=5, hours=2)).isoformat(),
            "scheduled_pickup_at": (now + timedelta(days=5, hours=3)).isoformat(),
            "items": [{"food_item_id": item_a["id"], "quantity": 5}],
        },
    )
    assert below_min.status_code == 400

    # 2b. Ineligible food item (item_b) must fail
    bad_item = client.post(
        f"/api/v1/events/{ev_id}/bulk-orders",
        headers=student["headers"],
        json={
            "scheduled_prep_at": (now + timedelta(days=5, hours=2)).isoformat(),
            "scheduled_pickup_at": (now + timedelta(days=5, hours=3)).isoformat(),
            "items": [{"food_item_id": item_b["id"], "quantity": 15}],
        },
    )
    assert bad_item.status_code == 400

    # 3. Create valid bulk order (20 portions of item_a) with individual_tokens arrangement + idempotency
    bo_res = client.post(
        f"/api/v1/events/{ev_id}/bulk-orders",
        headers=student["headers"],
        json={
            "idempotency_key": "ebo-idem-p31-001",
            "scheduled_prep_at": (now + timedelta(days=5, hours=2)).isoformat(),
            "scheduled_pickup_at": (now + timedelta(days=5, hours=3)).isoformat(),
            "pickup_arrangement": "individual_tokens",
            "payment_method": "razorpay",
            "notes": "Pack in 2 separate insulated crates",
            "items": [{"food_item_id": item_a["id"], "quantity": 20}],
        },
    )
    assert bo_res.status_code == 201, bo_res.text
    bo = bo_res.json()
    bo_id = bo["id"]
    assert bo["status"] == "pending_approval"
    assert bo["payment_status"] == "PENDING"
    assert bo["total_quantity"] == 20
    expected_sub = (Decimal(str(item_a["base_price"])) * Decimal("20")).quantize(Decimal("0.01"))
    assert Decimal(bo["subtotal_amount"]) == expected_sub

    # Duplicate submission with same idempotency_key returns existing bulk order
    bo_dup = client.post(
        f"/api/v1/events/{ev_id}/bulk-orders",
        headers=student["headers"],
        json={
            "idempotency_key": "ebo-idem-p31-001",
            "scheduled_prep_at": (now + timedelta(days=5, hours=2)).isoformat(),
            "scheduled_pickup_at": (now + timedelta(days=5, hours=3)).isoformat(),
            "items": [{"food_item_id": item_a["id"], "quantity": 20}],
        },
    )
    assert bo_dup.status_code == 201
    assert bo_dup.json()["id"] == bo_id

    # 4. Manager approves the bulk order, and organizer completes Razorpay payment verification
    rev_res = client.post(
        f"/api/v1/events/bulk-orders/{bo_id}/review",
        headers=manager["headers"],
        json={"decision": "approve"},
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["status"] == "approved"

    rzp_order_id = bo["razorpay_order_id"]
    rzp_pay_id = "pay_eventbulk_p31_001"
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=rzp_order_id, razorpay_payment_id=rzp_pay_id
    )

    pay_res = client.post(
        f"/api/v1/events/bulk-orders/{bo_id}/verify-payment",
        headers=student["headers"],
        json={
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": rzp_pay_id,
            "razorpay_signature": sig,
        },
    )
    assert pay_res.status_code == 200, pay_res.text
    confirmed_bo = pay_res.json()
    assert confirmed_bo["payment_status"] == "CONFIRMED"
    assert confirmed_bo["linked_order_id"] is not None
    assert confirmed_bo["group_pickup_token"] is not None
    assert len(confirmed_bo["individual_tokens"]) == 20

    # Progress bulk order through preparing -> ready -> completed
    for st in ("preparing", "ready", "completed"):
        st_res = client.post(
            f"/api/v1/events/bulk-orders/{bo_id}/status",
            headers=manager["headers"],
            json={"status": st},
        )
        assert st_res.status_code == 200
        assert st_res.json()["status"] == st

    # 5. Ordering after event ordering_deadline must be rejected
    expired_ev = client.post(
        "/api/v1/events",
        headers=admin["headers"],
        json={
            "canteen_id": cid,
            "event_code": "PAST-DEADLINE-EVT",
            "name": "Past Deadline Workshop",
            "department": "Mechanical",
            "organizer_name": "Prof. K. Rao",
            "contact_phone": "+919845099999",
            "event_date": (today_col + timedelta(days=1)).isoformat(),
            "location": "Seminar Hall 1",
            "ordering_deadline": (now - timedelta(hours=2)).isoformat(),
            "min_order_quantity": 5,
            "max_order_quantity": 100,
        },
    ).json()

    past_deadline_bo = client.post(
        f"/api/v1/events/{expired_ev['id']}/bulk-orders",
        headers=student["headers"],
        json={
            "scheduled_prep_at": (now + timedelta(hours=4)).isoformat(),
            "scheduled_pickup_at": (now + timedelta(hours=5)).isoformat(),
            "items": [{"food_item_id": item_a["id"], "quantity": 10}],
        },
    )
    assert past_deadline_bo.status_code == 400

    # 6. Event Reports & CSV export
    rep = client.get(f"/api/v1/events/reports/summary?canteen_id={cid}", headers=manager["headers"])
    assert rep.status_code == 200
    rep_data = rep.json()
    assert rep_data["completed_event_orders"] >= 1
    assert Decimal(rep_data["total_event_revenue"]) >= Decimal(confirmed_bo["total_amount"])

    csv_res = client.get(f"/api/v1/events/reports/csv?canteen_id={cid}", headers=manager["headers"])
    assert csv_res.status_code == 200
    assert "TECHFEST-2026-MAIN" in csv_res.text
