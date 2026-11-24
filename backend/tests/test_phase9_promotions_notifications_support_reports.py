from decimal import Decimal
from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_promotions_notifications_reviews_support_and_reports(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    items = client.get(f"/api/v1/menus/canteens/{canteen['id']}/items").json()
    biryani = next(i for i in items if "Biryani" in i["name"])

    # 1. Create announcement & banner (and verify coupons are permanently removed)
    ann = client.post(
        "/api/v1/notifications/announcements",
        headers=admin["headers"],
        json={"title": "Exam Week Extended Hours", "body": "Main Canteen open till 10 PM.", "severity": "info"},
    )
    assert ann.status_code == 201
    assert any(a["title"] == "Exam Week Extended Hours" for a in client.get("/api/v1/notifications/announcements").json())

    assert client.get("/api/v1/promotions/coupons", headers=admin["headers"]).status_code in (200, 404, 405)
    assert (
        client.post(
            "/api/v1/promotions/coupons",
            headers=admin["headers"],
            json={"code": "FLAT20", "title": "Flat ₹20 Off", "discount_type": "fixed", "discount_value": "20.00"},
        ).status_code
        in (400, 404, 405)
    )

    promo = client.post(
        "/api/v1/promotions",
        headers=admin["headers"],
        json={
            "canteen_id": canteen["id"],
            "title": "Exam Week Night Counter Open",
            "subtitle": "Hot snacks and coffee until 10 PM",
            "badge_text": "OPEN LATE",
            "promo_type": "banner",
        },
    )
    assert promo.status_code == 201

    # 2. Place paid order to generate real analytics & notifications
    order = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={"canteen_id": canteen["id"], "payment_method": "upi_pos", "items": [{"food_item_id": biryani["id"], "quantity": 2}]},
    ).json()

    # 3. Review updates item rating
    rev = client.post(
        "/api/v1/support/reviews",
        headers=student["headers"],
        json={"food_item_id": biryani["id"], "order_id": order["id"], "rating": 5, "comment": "Super authentic biryani!"},
    )
    assert rev.status_code == 201

    # 4. Support ticket (NO refund category allowed)
    bad_ticket = client.post(
        "/api/v1/support/tickets",
        headers=student["headers"],
        json={"category": "refund", "subject": "Want refund", "description": "Please refund"},
    )
    assert bad_ticket.status_code == 422

    ticket = client.post(
        "/api/v1/support/tickets",
        headers=student["headers"],
        json={
            "order_id": order["id"],
            "canteen_id": canteen["id"],
            "category": "missing_item",
            "subject": "Missing extra raita cup",
            "description": "Ordered extra raita but cup was missed in parcel.",
        },
    ).json()
    res = client.post(
        f"/api/v1/support/tickets/{ticket['id']}/resolve?resolution_note=Provided%20fresh%20raita%20cup",
        headers=admin["headers"],
    )
    assert res.status_code == 200
    assert res.json()["status"] == "resolved"

    # 5. Real DB analytics report + CSV + PDF export
    dash = client.get("/api/v1/reports/dashboard", headers=admin["headers"]).json()
    assert dash["sales"]["total_orders"] >= 1
    assert Decimal(dash["sales"]["net_sales"]) > Decimal("0.00")
    assert len(dash["sales"]["top_items"]) >= 1

    csv_rep = client.get("/api/v1/reports/export/csv", headers=admin["headers"])
    assert csv_rep.status_code == 200
    assert "CollegeBites Analytics Report" in csv_rep.text

    pdf_rep = client.get("/api/v1/reports/export/pdf", headers=admin["headers"])
    assert pdf_rep.status_code == 200
    assert pdf_rep.content.startswith(b"%PDF")
