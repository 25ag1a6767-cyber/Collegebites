from datetime import date, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_inventory_deduction_no_duplicate_po_wastage_and_auto_unavailability(client: TestClient):
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]

    inv_before = client.get(f"/api/v1/inventory/canteens/{cid}/items", headers=inv_mgr["headers"]).json()
    rice_before = next(i for i in inv_before if i["sku"] == "RICE-BAS")
    assert Decimal(rice_before["current_quantity"]) == Decimal("25000.000")

    # Place a confirmed order of 2 Chicken Biryani (recipe = 180g rice each -> 360g deducted)
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    biryani = next(i for i in items if "Biryani" in i["name"])
    order = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={"canteen_id": cid, "payment_method": "upi_pos", "items": [{"food_item_id": biryani["id"], "quantity": 2}]},
    ).json()
    assert order["payment_status"] == "CONFIRMED"

    inv_after = client.get(f"/api/v1/inventory/canteens/{cid}/items", headers=inv_mgr["headers"]).json()
    rice_after = next(i for i in inv_after if i["sku"] == "RICE-BAS")
    assert Decimal(rice_after["current_quantity"]) == Decimal("24640.000")

    # Calling counter collect again must NOT deduct inventory a second time!
    client.post(
        "/api/v1/payments/counter/collect",
        headers=cashier["headers"],
        json={"order_id": order["id"], "payment_method": "upi_pos"},
    )
    inv_after2 = client.get(f"/api/v1/inventory/canteens/{cid}/items", headers=inv_mgr["headers"]).json()
    rice_after2 = next(i for i in inv_after2 if i["sku"] == "RICE-BAS")
    assert Decimal(rice_after2["current_quantity"]) == Decimal("24640.000")

    # Wastage drops stock below recipe requirement -> biryani automatically marked insufficient_ingredients=True
    waste = client.post(
        "/api/v1/inventory/wastage",
        headers=inv_mgr["headers"],
        json={"inventory_item_id": rice_after2["inventory_item_id"], "quantity": "24600.000", "reason": "Spilled sack"},
    )
    assert waste.status_code == 200
    assert "Hyderabadi Chicken Dum Biryani" in waste.json()["blocked_items"]

    # Receive Purchase Order restores stock and unblocks biryani (manager approves before receipt)
    mgr = login_as(client, "manager@collegebites.edu", "Staff@12345")
    suppliers = client.get("/api/v1/inventory/suppliers", headers=inv_mgr["headers"]).json()
    po = client.post(
        "/api/v1/inventory/purchase-orders",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": cid,
            "supplier_id": suppliers[0]["id"],
            "items": [
                {
                    "ingredient_id": rice_after2["ingredient_id"],
                    "quantity_ordered": "10000.000",
                    "unit_cost": "0.12",
                    "expiry_date": (date.today() + timedelta(days=5)).isoformat(),
                }
            ],
        },
    ).json()
    assert po["status"] == "pending_approval"
    assert client.post(f"/api/v1/inventory/purchase-orders/{po['id']}/status", headers=mgr["headers"], json={"status": "approved"}).status_code == 200
    assert client.post(f"/api/v1/inventory/purchase-orders/{po['id']}/status", headers=inv_mgr["headers"], json={"status": "ordered"}).status_code == 200
    rec = client.post(f"/api/v1/inventory/purchase-orders/{po['id']}/receive", headers=inv_mgr["headers"])
    assert rec.status_code == 200
    alerts = client.get(f"/api/v1/inventory/canteens/{cid}/alerts", headers=inv_mgr["headers"]).json()
    assert len(alerts["expiring_soon"]) >= 1
    assert alerts["blocked_food_items"] == []


def test_staff_shifts_attendance_and_tasks(client: TestClient):
    mgr = login_as(client, "manager@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]

    assert client.post(f"/api/v1/staff/attendance/check-in?canteen_id={cid}", headers=kitchen["headers"]).status_code == 200
    assert client.post("/api/v1/staff/attendance/check-out", headers=kitchen["headers"]).status_code == 200

    task = client.post(
        "/api/v1/staff/tasks",
        headers=mgr["headers"],
        json={
            "canteen_id": cid,
            "assigned_to_user_id": kitchen["user"]["id"],
            "title": "Prep biryani base",
            "priority": "high",
            "is_urgent": True,
        },
    ).json()
    done = client.patch(f"/api/v1/staff/tasks/{task['id']}", headers=kitchen["headers"], json={"status": "done"})
    assert done.status_code == 200
    assert done.json()["status"] == "done"
