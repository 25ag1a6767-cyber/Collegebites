import io
from datetime import timedelta
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.core.time_utils import today_college
from tests.conftest import login_as


def test_bi_dashboard_presets_staff_fix_consumption_details_and_xlsx(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    other_canteen = next(c for c in canteens if c["id"] != main_canteen["id"])
    cid = main_canteen["id"]

    # Kitchen staff checks in today -> validates staff_user_id fix in report_service
    assert client.post(f"/api/v1/staff/attendance/check-in?canteen_id={cid}", headers=kitchen["headers"]).status_code in (200, 201)

    # Create a confirmed POS order & complete lifecycle
    detail = client.get(f"/api/v1/canteens/{cid}").json()
    c1 = next(c for c in detail["counters"] if c["counter_type"] in ("pickup", "both"))
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    dish = items[0]

    ord_res = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={
            "canteen_id": cid,
            "counter_id": c1["id"],
            "customer_name": "BI Analyst Buyer",
            "payment_method": "upi_pos",
            "items": [{"food_item_id": dish["id"], "quantity": 2}],
        },
    )
    assert ord_res.status_code == 201, ord_res.text
    order = ord_res.json()
    assert client.post(f"/api/v1/kitchen/orders/{order['id']}/accept", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{order['id']}/start-preparing", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{order['id']}/mark-ready", headers=kitchen["headers"]).status_code == 200
    assert (
        client.post(
            "/api/v1/pickup/handover",
            headers=pickup["headers"],
            json={"order_id": order["id"], "counter_id": c1["id"], "verification_method": "manual_token"},
        ).status_code
        == 200
    )

    # 1. Presets + continuous daily series + staff check-in attribution + least ordered items + counter perf
    r_today = client.get(f"/api/v1/reports/dashboard?canteen_id={cid}&preset=today", headers=manager["headers"])
    assert r_today.status_code == 200, r_today.text
    bi = r_today.json()
    assert bi["range"]["preset"] == "today"
    assert bi["sales"]["total_orders"] >= 1
    assert len(bi["sales"]["daily_series"]) == 1
    assert len(bi["sales"]["hourly_series"]) == 24
    assert len(bi["sales"]["least_ordered_items"]) >= 1
    assert len(bi["sales"]["counter_performance"]) >= 1

    # Check fixed staff_user_id check-in attribution
    k_row = next(s for s in bi["staff_performance"]["staff_breakdown"] if s["user_id"] == kitchen["user"]["id"])
    assert k_row["checkins"] >= 1
    assert k_row["status_updates"] >= 3

    # Last 7 days returns continuous 7 daily points (no missing dates)
    r_7d = client.get(f"/api/v1/reports/dashboard?canteen_id={cid}&preset=last_7_days", headers=manager["headers"])
    assert r_7d.status_code == 200
    assert len(r_7d.json()["sales"]["daily_series"]) == 7

    # Yesterday preset returns yesterday's empty/accurate date range without error
    r_yest = client.get(f"/api/v1/reports/dashboard?canteen_id={cid}&preset=yesterday", headers=manager["headers"])
    assert r_yest.status_code == 200
    assert r_yest.json()["range"]["start_date"] == (today_college() - timedelta(days=1)).isoformat()

    # Canteen Manager CANNOT pull report for an unassigned canteen (scoped strictly to assigned canteen!)
    r_cross = client.get(
        f"/api/v1/reports/dashboard?canteen_id={other_canteen['id']}&preset=today",
        headers=manager["headers"],
    )
    assert r_cross.status_code == 403

    # Customer cannot access BI dashboard
    assert client.get("/api/v1/reports/dashboard", headers=student["headers"]).status_code == 403

    # 2. Paginated Drill-Down Detail Endpoints
    d_orders = client.get(f"/api/v1/reports/details/orders?canteen_id={cid}&preset=today&page=1&page_size=5", headers=admin["headers"])
    assert d_orders.status_code == 200
    assert any(it["order_number"] == order["order_number"] for it in d_orders.json()["items"])

    d_items = client.get(
        f"/api/v1/reports/details/items?canteen_id={cid}&preset=today&sort=asc&page=1&page_size=5",
        headers=admin["headers"],
    )
    assert d_items.status_code == 200
    assert d_items.json()["total"] >= 1

    d_inv = client.get(
        f"/api/v1/reports/details/inventory?canteen_id={cid}&preset=today&page=1&page_size=10",
        headers=admin["headers"],
    )
    assert d_inv.status_code == 200
    assert d_inv.json()["total"] >= 1

    # 3. Excel (.xlsx), CSV & PDF exports
    xlsx_res = client.get(f"/api/v1/reports/export/xlsx?canteen_id={cid}&preset=last_7_days", headers=admin["headers"])
    assert xlsx_res.status_code == 200, xlsx_res.text
    assert xlsx_res.content[:2] == b"PK"
    wb = load_workbook(io.BytesIO(xlsx_res.content))
    assert wb.sheetnames == [
        "Summary",
        "Daily_Trend",
        "Item_Performance",
        "Counter_Queue",
        "Inventory_Consumption",
        "Staff_Performance",
    ]
    assert wb["Summary"]["A1"].value == "Metric"
    assert len(list(wb["Daily_Trend"].iter_rows())) == 8  # header + 7 days

    csv_res = client.get(f"/api/v1/reports/export/csv?canteen_id={cid}&preset=today", headers=admin["headers"])
    assert csv_res.status_code == 200
    assert "LEAST ORDERED FOOD ITEMS" in csv_res.text
    assert "COUNTER PERFORMANCE" in csv_res.text

    pdf_res = client.get(f"/api/v1/reports/export/pdf?canteen_id={cid}&preset=today", headers=admin["headers"])
    assert pdf_res.status_code == 200
    assert pdf_res.content[:4] == b"%PDF"
