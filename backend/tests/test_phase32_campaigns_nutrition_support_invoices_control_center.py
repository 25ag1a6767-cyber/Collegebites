from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.integrations.razorpay_client import razorpay_gateway
from tests.conftest import login_as


def test_phase32_campaigns_nutrition_support_invoices_and_control_center(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Friend Student P32",
            "email": "friend_p32@collegebites.edu",
            "phone": "+919777665544",
            "password": "Student@12345",
        },
    )
    friend = login_as(client, "friend_p32@collegebites.edu", "Student@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    item_1 = items[0]
    item_2 = items[1]
    now = datetime.now(timezone.utc)

    # =========================================================================
    # PHASE 4: Offers & Campaign Management
    # =========================================================================
    # 1. Create active percentage campaign coupon with per-user limit=1 and min_order_amount=100
    cp_res = client.post(
        "/api/v1/promotions/coupons",
        headers=admin["headers"],
        json={
            "code": "FESTIVE20",
            "title": "Festive 20% Off Campus Dining",
            "description": "20% off orders above Rs.100",
            "canteen_id": cid,
            "discount_type": "percentage",
            "discount_value": "20.00",
            "min_order_amount": "100.00",
            "max_discount_amount": "75.00",
            "usage_limit_total": 10,
            "usage_limit_per_user": 1,
            "starts_at": (now - timedelta(hours=2)).isoformat(),
            "expires_at": (now + timedelta(days=5)).isoformat(),
            "is_active": True,
        },
    )
    assert cp_res.status_code == 201, cp_res.text

    # 2. Create expired coupon -> must be rejected at checkout
    client.post(
        "/api/v1/promotions/coupons",
        headers=admin["headers"],
        json={
            "code": "EXPIRED50",
            "title": "Expired Offer",
            "canteen_id": cid,
            "discount_type": "fixed",
            "discount_value": "50.00",
            "starts_at": (now - timedelta(days=5)).isoformat(),
            "expires_at": (now - timedelta(hours=1)).isoformat(),
            "is_active": True,
        },
    )
    exp_val = client.post(
        "/api/v1/promotions/coupons/validate",
        headers=student["headers"],
        json={"canteen_id": cid, "coupon_code": "EXPIRED50", "subtotal_amount": "200.00"},
    )
    assert exp_val.status_code == 400

    # 3. Create fixed coupon larger than item price to verify payable amount is NEVER negative
    client.post(
        "/api/v1/promotions/coupons",
        headers=admin["headers"],
        json={
            "code": "HUGE500",
            "title": "Rs.500 Mega Voucher",
            "canteen_id": cid,
            "discount_type": "fixed",
            "discount_value": "500.00",
            "min_order_amount": "10.00",
            "usage_limit_per_user": 5,
            "is_active": True,
        },
    )
    clamp_val = client.post(
        "/api/v1/promotions/coupons/validate",
        headers=student["headers"],
        json={"canteen_id": cid, "coupon_code": "HUGE500", "subtotal_amount": "120.00"},
    )
    assert clamp_val.status_code == 200
    assert Decimal(clamp_val.json()["discount_amount"]) == Decimal("120.00")
    assert Decimal(clamp_val.json()["payable_before_tax"]) == Decimal("0.00")

    # 4. Checkout with FESTIVE20 and verify payment -> auto-generates tax invoice
    co_res = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "payment_method": "razorpay",
            "coupon_code": "FESTIVE20",
            "use_cart": False,
            "direct_items": [{"food_item_id": item_1["id"], "quantity": 3}],
            "accepted_policy": True,
        },
    )
    assert co_res.status_code == 201, co_res.text
    order = co_res.json()
    assert order["coupon_code"] == "FESTIVE20"
    assert Decimal(order["discount_amount"]) > Decimal("0.00")
    assert Decimal(order["total_amount"]) > Decimal("0.00")

    # Duplicate redemption beyond per-customer limit (1) must be rejected!
    dup_co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "payment_method": "razorpay",
            "coupon_code": "FESTIVE20",
            "use_cart": False,
            "direct_items": [{"food_item_id": item_1["id"], "quantity": 3}],
            "accepted_policy": True,
        },
    )
    assert dup_co.status_code == 400

    # Campaign report tracks usage & performance
    camp_rep = client.get(f"/api/v1/promotions/campaigns/report?canteen_id={cid}", headers=admin["headers"])
    assert camp_rep.status_code == 200
    assert camp_rep.json()["total_redemptions"] >= 1

    # =========================================================================
    # PHASE 5: Nutrition & Allergen Management
    # =========================================================================
    # Unverified item clearly states nutrition/allergen information is unverified
    raw_item = client.get(f"/api/v1/menus/items/{item_2['id']}").json()
    assert raw_item["nutrition_verified"] is False
    assert "unverified" in (raw_item["nutrition_disclaimer"] or "").lower()

    # Update item with verified macros and allergens
    upd_nut = client.patch(
        f"/api/v1/menus/items/{item_1['id']}",
        headers=manager["headers"],
        json={
            "calories": 540,
            "nutrition_verified": True,
            "nutrition_info": {
                "protein_g": 22.5,
                "carbs_g": 64.0,
                "fat_g": 18.0,
                "fiber_g": 6.5,
            },
            "ingredients_text": "Basmati rice, paneer cubes, curd, ghee, whole spices, cashews",
            "allergen_names": ["Dairy", "Tree Nuts"],
        },
    )
    assert upd_nut.status_code == 200, upd_nut.text
    nut_data = upd_nut.json()
    assert nut_data["nutrition_verified"] is True
    assert nut_data["calories"] == 540
    assert nut_data["nutrition_info"]["protein_g"] == 22.5
    alg_names = {a["name"] for a in nut_data["allergens"]}
    assert "Dairy" in alg_names and "Tree Nuts" in alg_names

    # =========================================================================
    # PHASE 6: Advanced Customer Support
    # =========================================================================
    # Student submits a payment_issue ticket linked to order
    t_res = client.post(
        "/api/v1/support/tickets",
        headers=student["headers"],
        json={
            "order_id": order["id"],
            "canteen_id": cid,
            "category": "payment_issue",
            "priority": "high",
            "subject": "UPI debit notification received twice",
            "description": "Please verify my order payment reference.",
        },
    )
    assert t_res.status_code == 201, t_res.text
    ticket = t_res.json()
    tid = ticket["id"]
    assert ticket["category"] == "payment_issue"
    assert ticket["status"] == "open"

    # Other customer cannot view student's ticket messages
    other_view = client.get(f"/api/v1/support/tickets/{tid}/messages", headers=friend["headers"])
    assert other_view.status_code == 403

    # Manager transitions ticket: open -> in_progress -> resolved -> closed
    for st_val in ("in_progress", "resolved", "closed"):
        st_upd = client.patch(
            f"/api/v1/support/tickets/{tid}/status",
            headers=manager["headers"],
            json={"status": st_val, "note": f"Updated status to {st_val}"},
        )
        assert st_upd.status_code == 200
        assert st_upd.json()["status"] == st_val

    # Admin filters & support summary report
    filt_t = client.get(f"/api/v1/support/tickets?canteen_id={cid}&category=payment_issue&status_filter=closed", headers=manager["headers"])
    assert filt_t.status_code == 200
    assert any(t["id"] == tid for t in filt_t.json())

    sup_rep = client.get(f"/api/v1/support/reports/summary?canteen_id={cid}", headers=manager["headers"])
    assert sup_rep.status_code == 200
    assert sup_rep.json()["closed_count"] >= 1
    assert sup_rep.json()["by_category"].get("payment_issue", 0) >= 1

    # =========================================================================
    # PHASE 7: Billing & Invoice Management
    # =========================================================================
    # Before payment verification, order has NO invoice
    unpaid_inv = client.get(f"/api/v1/invoices/{order['id']}", headers=student["headers"])
    assert unpaid_inv.status_code == 404

    # Verify payment on order -> automatically issues tax invoice
    rzp_oid = order["razorpay_order_id"]
    rzp_pid = "pay_p32_order_001"
    sig = razorpay_gateway.compute_test_payment_signature(razorpay_order_id=rzp_oid, razorpay_payment_id=rzp_pid)
    pay_ver = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": order["id"],
            "razorpay_order_id": rzp_oid,
            "razorpay_payment_id": rzp_pid,
            "razorpay_signature": sig,
        },
    )
    assert pay_ver.status_code == 200, pay_ver.text

    inv_res = client.get(f"/api/v1/invoices/{order['id']}", headers=student["headers"])
    assert inv_res.status_code == 200, inv_res.text
    inv = inv_res.json()
    assert inv["invoice_number"].startswith("INV-")
    assert inv["reference_number"] == order["order_number"]
    assert Decimal(inv["total_amount"]) == Decimal(order["total_amount"])
    assert Decimal(inv["discount_amount"]) == Decimal(order["discount_amount"])
    assert "cgst_amount" in inv["tax_breakdown"] and "sgst_amount" in inv["tax_breakdown"]

    # Other customer cannot download student's invoice
    assert client.get(f"/api/v1/invoices/{inv['invoice_number']}", headers=friend["headers"]).status_code == 403

    # Student downloads PDF tax invoice
    inv_pdf = client.get(f"/api/v1/invoices/{inv['invoice_number']}/pdf", headers=student["headers"])
    assert inv_pdf.status_code == 200
    assert inv_pdf.headers["content-type"] == "application/pdf"
    assert inv_pdf.content.startswith(b"%PDF")

    # =========================================================================
    # PHASE 8: Canteen Operations Control Center
    # =========================================================================
    occ = client.get(
        f"/api/v1/reports/operations-control-center?canteen_id={cid}&operational_category=all",
        headers=manager["headers"],
    )
    assert occ.status_code == 200, occ.text
    occ_data = occ.json()
    for required_key in (
        "current_orders",
        "pending_orders",
        "preparing_orders",
        "ready_orders",
        "completed_orders",
        "active_meal_plans",
        "meal_plan_redemptions",
        "inventory_alerts",
        "low_stock_items",
        "pending_purchase_orders",
        "vendor_outstanding_balances",
        "event_bulk_orders",
        "support_tickets",
        "sales_and_operational_summaries",
    ):
        assert required_key in occ_data, f"Missing {required_key} in control center payload"
    assert occ_data["sales_and_operational_summaries"]["invoices_issued_count"] >= 1
    assert occ_data["sales_and_operational_summaries"]["active_promotional_campaigns_count"] >= 1
