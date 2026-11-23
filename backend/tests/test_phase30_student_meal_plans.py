from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.time_utils import today_college
from app.integrations.razorpay_client import razorpay_gateway
from tests.conftest import login_as


def test_phase30_student_meal_plans_subscription_and_redemption(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]
    menu_items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    eligible_item = menu_items[0]
    ineligible_item = menu_items[1]
    today_col = today_college()

    # 1. Admin creates a Meal Plan restricted to eligible_item
    mp_res = client.post(
        "/api/v1/meal-plans",
        headers=admin["headers"],
        json={
            "canteen_id": cid,
            "code": "CAMPUS-WEEKLY-2",
            "name": "Campus Weekly Combo Plan (2 Meals)",
            "description": "2 nutritious campus meals valid for 7 days",
            "plan_type": "weekly",
            "price": "180.00",
            "tax_rate_percent": "5.00",
            "validity_days": 7,
            "total_meals": 2,
            "eligible_food_item_ids": [eligible_item["id"]],
            "start_date": (today_col - timedelta(days=1)).isoformat(),
            "expiry_date": (today_col + timedelta(days=30)).isoformat(),
            "is_active": True,
        },
    )
    assert mp_res.status_code == 201, mp_res.text
    plan = mp_res.json()
    plan_id = plan["id"]
    assert Decimal(plan["total_price"]) == Decimal("189.00")

    # 2. Student subscribes to the meal plan -> starts in pending_payment (NOT active before payment verification)
    sub_res = client.post(
        f"/api/v1/meal-plans/{plan_id}/subscribe",
        headers=student["headers"],
        json={"payment_method": "razorpay"},
    )
    assert sub_res.status_code == 201, sub_res.text
    sub = sub_res.json()
    sub_id = sub["id"]
    assert sub["status"] == "pending_payment"
    assert sub["payment_status"] == "PENDING"
    assert sub["redemption_code"] is None  # Hidden until payment is verified!

    # Attempting to redeem before payment verification must fail
    unpaid_redeem = client.post(
        "/api/v1/meal-plans/redeem",
        headers=pickup["headers"],
        json={"canteen_id": cid, "subscription_id": sub_id, "food_item_id": eligible_item["id"]},
    )
    assert unpaid_redeem.status_code == 400

    # 3. Verify Razorpay payment signature -> activates subscription
    rzp_order_id = sub["razorpay_order_id"]
    rzp_pay_id = "pay_mealplan_p30_001"
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=rzp_order_id, razorpay_payment_id=rzp_pay_id
    )

    ver_res = client.post(
        f"/api/v1/meal-plans/subscriptions/{sub_id}/verify-payment",
        headers=student["headers"],
        json={
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": rzp_pay_id,
            "razorpay_signature": sig,
        },
    )
    assert ver_res.status_code == 200, ver_res.text
    active_sub = ver_res.json()
    assert active_sub["status"] == "active"
    assert active_sub["payment_status"] == "CONFIRMED"
    assert active_sub["remaining_meals"] == 2
    assert active_sub["redemption_code"] is not None
    assert active_sub["redemption_qr_payload"].startswith("COLLEGEBITES:MEALPLAN:")

    # 4. Ineligible food item redemption must be rejected
    bad_item_redeem = client.post(
        "/api/v1/meal-plans/redeem",
        headers=pickup["headers"],
        json={
            "canteen_id": cid,
            "qr_payload": active_sub["redemption_qr_payload"],
            "food_item_id": ineligible_item["id"],
        },
    )
    assert bad_item_redeem.status_code == 400

    # 5. Valid QR meal redemption #1 (with idempotency protection)
    r1 = client.post(
        "/api/v1/meal-plans/redeem",
        headers=pickup["headers"],
        json={
            "canteen_id": cid,
            "qr_payload": active_sub["redemption_qr_payload"],
            "food_item_id": eligible_item["id"],
            "meals_to_deduct": 1,
            "idempotency_key": "mp-redeem-idem-001",
        },
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["remaining_meals_after"] == 1
    assert r1.json()["subscription"]["status"] == "active"

    # Duplicate scan with same idempotency_key must NOT deduct another meal
    r1_dup = client.post(
        "/api/v1/meal-plans/redeem",
        headers=pickup["headers"],
        json={
            "canteen_id": cid,
            "qr_payload": active_sub["redemption_qr_payload"],
            "food_item_id": eligible_item["id"],
            "meals_to_deduct": 1,
            "idempotency_key": "mp-redeem-idem-001",
        },
    )
    assert r1_dup.status_code == 200
    assert r1_dup.json()["idempotent_replay"] is True
    assert r1_dup.json()["remaining_meals_after"] == 1

    # 6. Redeem 2nd meal -> transitions subscription to exhausted (remaining_meals == 0)
    r2 = client.post(
        "/api/v1/meal-plans/redeem",
        headers=pickup["headers"],
        json={
            "canteen_id": cid,
            "redemption_code": active_sub["redemption_code"],
            "food_item_id": eligible_item["id"],
            "meals_to_deduct": 1,
            "idempotency_key": "mp-redeem-idem-002",
        },
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["remaining_meals_after"] == 0
    assert r2.json()["subscription"]["status"] == "exhausted"

    # 7. Redeeming when balance is 0 (exhausted) must fail (no negative meal balance!)
    r3_over = client.post(
        "/api/v1/meal-plans/redeem",
        headers=pickup["headers"],
        json={
            "canteen_id": cid,
            "redemption_code": active_sub["redemption_code"],
            "food_item_id": eligible_item["id"],
            "meals_to_deduct": 1,
        },
    )
    assert r3_over.status_code == 400

    # 8. Student dashboard shows accurate remaining balance and 2 redemption records
    my_subs = client.get("/api/v1/meal-plans/my-subscriptions", headers=student["headers"])
    assert my_subs.status_code == 200
    sub_entry = next(s for s in my_subs.json() if s["id"] == sub_id)
    assert sub_entry["remaining_meals"] == 0
    assert sub_entry["used_meals"] == 2
    assert len(sub_entry["redemptions"]) == 2
