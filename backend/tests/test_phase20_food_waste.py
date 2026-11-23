from datetime import date, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_food_prep_vs_sold_unsold_waste_and_analytics(client: TestClient):
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Student Tester",
            "email": "student.waste@aceec.ac.in",
            "phone": "+919111222333",
            "password": "StrongPassword123",
            "college_id_number": "25AG1A0099",
            "department": "CSE",
        },
    )
    assert reg.status_code == 201, reg.text
    student = {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"}}

    canteens = client.get("/api/v1/canteens").json()
    canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    other_canteen = next(c for c in canteens if c["slug"] != "main-canteen")
    cid = canteen["id"]

    # Fetch menu items and canteen staff list
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    biryani = next(i for i in items if "Biryani" in i["name"])
    staff_list = client.get(f"/api/v1/inventory/canteens/{cid}/staff-members", headers=kitchen["headers"]).json()
    assert len(staff_list) >= 1

    today_str = date.today().isoformat()

    # Customer cannot log prep or waste
    assert client.post(
        "/api/v1/inventory/food-prep",
        headers=student["headers"],
        json={"canteen_id": cid, "food_item_id": biryani["id"], "prepared_quantity": 20},
    ).status_code == 403

    # Kitchen staff cannot log prep for another canteen
    assert client.post(
        "/api/v1/inventory/food-prep",
        headers=kitchen["headers"],
        json={"canteen_id": other_canteen["id"], "food_item_id": biryani["id"], "prepared_quantity": 20},
    ).status_code == 403

    # Kitchen logs 20 prepared portions of Biryani today
    prep_res = client.post(
        "/api/v1/inventory/food-prep",
        headers=kitchen["headers"],
        json={
            "canteen_id": cid,
            "food_item_id": biryani["id"],
            "prep_date": today_str,
            "meal_session": "lunch",
            "prepared_quantity": 20,
            "unit_cost": "45.00",
            "responsible_staff_id": kitchen["user"]["id"],
            "notes": "Lunch dum batch",
        },
    )
    assert prep_res.status_code == 201, prep_res.text
    prep_log = prep_res.json()
    assert prep_log["prepared_quantity"] == 20
    assert prep_log["sold_quantity"] == 0
    assert prep_log["unsold_quantity"] == 20

    # Sell 6 Biryani via POS so DB OrderItem reflects 6 sold
    order = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={"canteen_id": cid, "payment_method": "upi_pos", "items": [{"food_item_id": biryani["id"], "quantity": 6}]},
    )
    assert order.status_code == 201, order.text

    logs = client.get(f"/api/v1/inventory/canteens/{cid}/food-prep", headers=inv_mgr["headers"]).json()
    match = next(r for r in logs if r["id"] == prep_log["id"])
    assert match["sold_quantity"] == 6
    assert match["unsold_quantity"] == 14
    assert match["remaining_unlogged_unsold"] == 14

    # Attempting to record 15 unsold portions must fail (> 14 unsold)
    bad_waste = client.post(
        f"/api/v1/inventory/food-prep/{prep_log['id']}/record-waste",
        headers=kitchen["headers"],
        json={"quantity": "15", "reason": "Leftover lunch batch", "responsible_staff_id": kitchen["user"]["id"]},
    )
    assert bad_waste.status_code == 400

    # Record 10 unsold portions wasted -> loss = 10 * 45.00 = 450.00
    good_waste = client.post(
        f"/api/v1/inventory/food-prep/{prep_log['id']}/record-waste",
        headers=kitchen["headers"],
        json={"quantity": "10", "reason": "Unsold at closing", "responsible_staff_id": kitchen["user"]["id"]},
    )
    assert good_waste.status_code == 200, good_waste.text
    assert Decimal(good_waste.json()["estimated_loss"]) == Decimal("450.00")

    # Record ingredient waste with explicit batch_id, waste_date, and responsible_staff_id
    inv_items = client.get(f"/api/v1/inventory/canteens/{cid}/items", headers=inv_mgr["headers"]).json()
    rice = next(i for i in inv_items if i["sku"] == "RICE-BAS")
    batch_id = rice["batches"][0]["id"] if rice.get("batches") else None
    ing_waste = client.post(
        "/api/v1/inventory/wastage",
        headers=inv_mgr["headers"],
        json={
            "inventory_item_id": rice["inventory_item_id"],
            "batch_id": batch_id,
            "quantity": "100.000",
            "reason": "Spilled during prep",
            "operation_type": "wastage",
            "waste_date": today_str,
            "responsible_staff_id": kitchen["user"]["id"],
        },
    )
    assert ing_waste.status_code == 200, ing_waste.text

    # Filtered wastage history checks
    prep_only_waste = client.get(
        f"/api/v1/inventory/canteens/{cid}/wastage?source_type=prepared_food&loss_type=unsold&start_date={today_str}&end_date={today_str}",
        headers=inv_mgr["headers"],
    ).json()
    assert len(prep_only_waste) == 1
    assert prep_only_waste[0]["food_item_name"] == biryani["name"]
    assert prep_only_waste[0]["responsible_staff_id"] == kitchen["user"]["id"]

    # Daily / Weekly / Monthly analytics checks (strictly DB-computed)
    daily = client.get(
        f"/api/v1/inventory/canteens/{cid}/waste-analytics?period=daily&start_date={today_str}&end_date={today_str}",
        headers=inv_mgr["headers"],
    ).json()
    s = daily["summary"]
    assert s["total_food_prepared"] == 20
    assert s["total_food_sold"] == 6
    assert s["total_food_wasted"] == 10
    assert s["food_wastage_percent"] == 50.0
    assert Decimal(s["prepared_food_waste_cost"]) == Decimal("450.00")
    assert Decimal(s["ingredient_wasted_quantity"]) == Decimal("100.000")
    assert Decimal(s["estimated_wastage_cost"]) > Decimal("450.00")
    assert len(daily["most_wasted_items"]) >= 2
    assert daily["most_wasted_items"][0]["item_name"] == biryani["name"]
    assert len(daily["staff_breakdown"]) == 1

    monthly = client.get(f"/api/v1/inventory/canteens/{cid}/waste-analytics?period=monthly", headers=inv_mgr["headers"]).json()
    assert monthly["period"] == "monthly"
    assert len(monthly["monthly_trend"]) >= 1

    # Consumption variance report checks
    cons = client.get(
        f"/api/v1/inventory/canteens/{cid}/consumption-report?start_date={today_str}&end_date={today_str}",
        headers=inv_mgr["headers"],
    ).json()
    rice_cons = next(r for r in cons["items"] if r["inventory_item_id"] == rice["inventory_item_id"])
    # 6 Biryani x 180g = 1080g order deducted; + 100g wasted = 1180g actual consumed
    assert Decimal(rice_cons["theoretical_recipe_consumption"]) == Decimal("1080.000")
    assert Decimal(rice_cons["order_deducted"]) == Decimal("1080.000")
    assert Decimal(rice_cons["wasted"]) == Decimal("100.000")
    assert Decimal(rice_cons["actual_consumed"]) == Decimal("1180.000")
    assert Decimal(rice_cons["variance_quantity"]) == Decimal("100.000")

    # Data-driven recommendations (70% unsold/prepared > 15% threshold -> prep reduction recommendation!)
    recs = client.get(f"/api/v1/inventory/canteens/{cid}/waste-recommendations", headers=inv_mgr["headers"]).json()
    assert any("Reduce daily prep batch" in r["title"] and biryani["name"] in r["title"] for r in recs)

    # CSV export works and includes summary
    csv_resp = client.get(f"/api/v1/inventory/canteens/{cid}/wastage/csv?period=daily", headers=inv_mgr["headers"])
    assert csv_resp.status_code == 200
    assert "FOOD WASTE KPI SUMMARY" in csv_resp.text
