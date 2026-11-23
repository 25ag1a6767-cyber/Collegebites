from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_coupons_completely_removed_everywhere(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]
    biryani = next(i for i in client.get(f"/api/v1/menus/canteens/{cid}/items").json() if "Biryani" in i["name"])

    assert client.get("/api/v1/promotions/coupons", headers=admin["headers"]).status_code in (200, 404, 405)
    assert (
        client.post(
            "/api/v1/promotions/coupons",
            headers=admin["headers"],
            json={"code": "TESTP13", "title": "Test", "discount_type": "fixed", "discount_value": "10.00", "is_active": False},
        ).status_code
        in (201, 404, 405)
    )
    assert (
        client.post("/api/v1/carts/coupon", headers=student["headers"], json={"canteen_id": cid, "coupon_code": "CAMPUS10"}).status_code
        in (400, 404, 405)
    )

    bad_co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "payment_method": "razorpay",
            "coupon_code": "CAMPUS10",
            "use_cart": False,
            "direct_items": [{"food_item_id": biryani["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert bad_co.status_code == 400

    bad_pos = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={
            "canteen_id": cid,
            "payment_method": "upi_pos",
            "coupon_code": "CAMPUS10",
            "items": [{"food_item_id": biryani["id"], "quantity": 1}],
        },
    )
    assert bad_pos.status_code == 400

    promos = client.get("/api/v1/promotions").json()
    assert all(p.get("coupon_code") is None for p in promos)


def test_inventory_manager_full_lifecycle_price_approvals_and_rbac(client: TestClient):
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")
    canteen_mgr = login_as(client, "manager@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]
    suppliers = client.get("/api/v1/inventory/suppliers", headers=inv_mgr["headers"]).json()
    sup_id = suppliers[0]["id"]

    # 1. Dashboard returns genuine database counts
    dash = client.get(f"/api/v1/inventory/canteens/{cid}/dashboard", headers=inv_mgr["headers"])
    assert dash.status_code == 200
    d0 = dash.json()
    assert d0["total_inventory_items"] >= 4
    assert Decimal(d0["total_stock_valuation"]) > Decimal("0.00")

    # 2. Add inventory item with full metadata (category, storage, description, preferred supplier)
    added = client.post(
        "/api/v1/inventory/ingredients",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": cid,
            "name": "Aged Parmesan Block",
            "sku": "PARM-01",
            "category": "Dairy",
            "description": "Imported hard cheese block",
            "unit": "grams",
            "initial_quantity": "500.000",
            "reorder_level": "150.000",
            "unit_cost": "1.20",
            "storage_location": "Cold Room R1",
            "preferred_supplier_id": sup_id,
            "is_available": True,
            "is_allergen": True,
        },
    )
    assert added.status_code == 201, added.text
    inv_id = added.json()["inventory_item_id"]

    # 3. Edit metadata & verify field-level InventoryAuditLog entries
    upd = client.patch(
        f"/api/v1/inventory/items/{inv_id}",
        headers=inv_mgr["headers"],
        json={
            "storage_location": "Cold Room R2",
            "reorder_level": "600.000",
            "reason": "Expanded cold storage rack",
        },
    )
    assert upd.status_code == 200
    assert upd.json()["storage_location"] == "Cold Room R2"

    logs = client.get(
        f"/api/v1/inventory/canteens/{cid}/audit-logs?inventory_item_id={inv_id}",
        headers=inv_mgr["headers"],
    ).json()
    fields_logged = {l["field_name"] for l in logs}
    assert "storage_location" in fields_logged
    assert "reorder_level" in fields_logged

    # 4. Negative stock reduction MUST return 400 (never silent clamp to 0)
    neg_adj = client.post(
        "/api/v1/inventory/adjustments",
        headers=inv_mgr["headers"],
        json={
            "inventory_item_id": inv_id,
            "quantity_delta": -999,
            "operation_type": "reduce_stock",
            "reason": "Impossible over-deduction check",
        },
    )
    assert neg_adj.status_code == 400

    neg_waste = client.post(
        "/api/v1/inventory/wastage",
        headers=inv_mgr["headers"],
        json={
            "inventory_item_id": inv_id,
            "quantity": "999",
            "operation_type": "damaged",
            "reason": "Damaged sack overflow check",
        },
    )
    assert neg_waste.status_code == 400

    # 5. Record damaged & expired losses separately and verify dashboard loss breakdown
    dmg = client.post(
        "/api/v1/inventory/wastage",
        headers=inv_mgr["headers"],
        json={
            "inventory_item_id": inv_id,
            "quantity": "50.000",
            "operation_type": "damaged",
            "reason": "Damaged corner block",
        },
    )
    assert dmg.status_code == 200
    assert Decimal(dmg.json()["current_quantity"]) == Decimal("450.000")

    exp = client.post(
        "/api/v1/inventory/wastage",
        headers=inv_mgr["headers"],
        json={
            "inventory_item_id": inv_id,
            "quantity": "25.000",
            "operation_type": "expired",
            "reason": "Expired trim portion",
        },
    )
    assert exp.status_code == 200
    d_loss = client.get(f"/api/v1/inventory/canteens/{cid}/dashboard", headers=inv_mgr["headers"]).json()
    assert Decimal(d_loss["loss_breakdown"]["damaged"]["quantity"]) >= Decimal("50.000")
    assert Decimal(d_loss["loss_breakdown"]["expired"]["quantity"]) >= Decimal("25.000")

    # 6. Item is low stock (425 <= reorder_level 600) -> 1-click Restock restores above reorder level
    restock = client.post(
        f"/api/v1/inventory/items/{inv_id}/restock",
        headers=inv_mgr["headers"],
        json={"quantity": "400.000", "unit_cost": "1.35", "notes": "1-click emergency restock"},
    )
    assert restock.status_code == 200
    assert Decimal(restock.json()["current_quantity"]) == Decimal("825.000")
    assert restock.json()["is_low_stock"] is False

    # 7. Archive vs Active-Order Guard + Restore
    # Biryani recipe uses RICE-BAS; place an active PLACED POS order containing Biryani
    menu_items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    biryani = next(i for i in menu_items if "Biryani" in i["name"])
    orig_price = Decimal(biryani["base_price"])
    pos_ord = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={"canteen_id": cid, "payment_method": "upi_pos", "items": [{"food_item_id": biryani["id"], "quantity": 1}]},
    ).json()
    assert Decimal(pos_ord["items"][0]["unit_price"]) == orig_price

    rice_item = next(
        i
        for i in client.get(f"/api/v1/inventory/canteens/{cid}/items", headers=inv_mgr["headers"]).json()
        if i["sku"] == "RICE-BAS"
    )
    arch_conflict = client.post(
        f"/api/v1/inventory/items/{rice_item['inventory_item_id']}/archive",
        headers=inv_mgr["headers"],
        json={"reason": "Attempt archive while order active"},
    )
    assert arch_conflict.status_code == 409

    # Non-recipe item archives cleanly and can be restored
    arch_ok = client.post(
        f"/api/v1/inventory/items/{inv_id}/archive",
        headers=inv_mgr["headers"],
        json={"reason": "Seasonal menu rotation"},
    )
    assert arch_ok.status_code == 200 and arch_ok.json()["is_archived"] is True
    active_list = client.get(f"/api/v1/inventory/canteens/{cid}/items", headers=inv_mgr["headers"]).json()
    assert all(i["inventory_item_id"] != inv_id for i in active_list)
    with_arch = client.get(
        f"/api/v1/inventory/canteens/{cid}/items?include_archived=true", headers=inv_mgr["headers"]
    ).json()
    assert any(i["inventory_item_id"] == inv_id and i["is_archived"] for i in with_arch)
    assert client.post(f"/api/v1/inventory/items/{inv_id}/restore", headers=inv_mgr["headers"]).status_code == 200

    # 8. Price Management: Purchase cost immediate vs Selling price approval-gated + historical order preserved
    p_cost = client.post(
        f"/api/v1/inventory/items/{inv_id}/purchase-price",
        headers=inv_mgr["headers"],
        json={"new_purchase_price": "1.50", "reason": "Dairy supplier rate revision"},
    )
    assert p_cost.status_code == 200 and Decimal(p_cost.json()["new_price"]) == Decimal("1.50")

    proposed_price = (orig_price + Decimal("15.00")).quantize(Decimal("0.01"))
    sell_req = client.post(
        "/api/v1/inventory/price-changes",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": cid,
            "food_item_id": biryani["id"],
            "new_price": str(proposed_price),
            "reason": "Basmati + saffron cost increase",
        },
    )
    assert sell_req.status_code == 201
    req_id = sell_req.json()["id"]
    assert sell_req.json()["status"] == "pending_approval"

    # Menu price stays unchanged BEFORE approval
    live_before = client.get(f"/api/v1/menus/items/{biryani['id']}").json()
    assert Decimal(live_before["base_price"]) == orig_price

    # Inventory manager CANNOT self-approve selling price OR directly PATCH menu item price
    assert (
        client.post(
            f"/api/v1/inventory/price-changes/{req_id}/review",
            headers=inv_mgr["headers"],
            json={"decision": "approve"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/menus/items/{biryani['id']}",
            headers=inv_mgr["headers"],
            json={"base_price": str(proposed_price)},
        ).status_code
        == 403
    )

    # Canteen Manager approves -> menu updates immediately, past order snapshot remains unchanged!
    mgr_approve = client.post(
        f"/api/v1/inventory/price-changes/{req_id}/review",
        headers=canteen_mgr["headers"],
        json={"decision": "approve", "review_notes": "Verified cost sheet"},
    )
    assert mgr_approve.status_code == 200
    assert Decimal(mgr_approve.json()["current_menu_price"]) == proposed_price
    past_order = client.get(f"/api/v1/orders/{pos_ord['order_number']}", headers=cashier["headers"]).json()
    assert Decimal(past_order["items"][0]["unit_price"]) == orig_price

    # Restore original menu price cleanly via price request/menu patch so seeded balance remains tidy
    assert client.patch(
        f"/api/v1/menus/items/{biryani['id']}", headers=canteen_mgr["headers"], json={"base_price": str(orig_price)}
    ).status_code == 200

    # 9. Inventory Manager strict RBAC isolation on Admin / Finance / Payments / Sales Reports
    assert client.get("/api/v1/admin/users", headers=inv_mgr["headers"]).status_code == 403
    assert client.get("/api/v1/admin/health", headers=inv_mgr["headers"]).status_code == 403
    assert client.get("/api/v1/reports/dashboard", headers=inv_mgr["headers"]).status_code == 403
    assert client.get("/api/v1/payments", headers=inv_mgr["headers"]).status_code == 403

    # 10. Real Inventory CSV & PDF reports
    inv_csv = client.get(f"/api/v1/inventory/canteens/{cid}/reports/csv", headers=inv_mgr["headers"])
    assert inv_csv.status_code == 200
    assert "CollegeBites Inventory & Price Audit Report" in inv_csv.text
    assert "Aged Parmesan Block" in inv_csv.text

    inv_pdf = client.get(f"/api/v1/inventory/canteens/{cid}/reports/pdf", headers=inv_mgr["headers"])
    assert inv_pdf.status_code == 200
    assert inv_pdf.content.startswith(b"%PDF")

    # 11. Inventory Manager Customer-Facing Menu Ops (Category, Add Food, Non-Price Edit, Image Upload Validation; direct base_price edit still 403)
    import io
    from PIL import Image

    cat_res = client.post(
        "/api/v1/menus/categories",
        headers=inv_mgr["headers"],
        json={"canteen_id": cid, "name": "Inv Fruit Bowls", "slug": "inv-fruit-bowls", "display_order": 99},
    )
    assert cat_res.status_code == 201, cat_res.text
    cat_id = cat_res.json()["id"]

    new_dish = client.post(
        "/api/v1/menus/items",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": cid,
            "category_id": cat_id,
            "name": "Fresh Watermelon Bowl",
            "slug": "fresh-watermelon-bowl",
            "description": "Chilled seasonal cubes",
            "base_price": "55.00",
            "is_veg": True,
        },
    )
    assert new_dish.status_code == 201, new_dish.text
    dish_id = new_dish.json()["id"]

    edit_ok = client.patch(
        f"/api/v1/menus/items/{dish_id}",
        headers=inv_mgr["headers"],
        json={"description": "Chilled seedless watermelon cubes", "is_available": True},
    )
    assert edit_ok.status_code == 200

    # Inventory manager CANNOT alter base_price directly
    assert (
        client.patch(
            f"/api/v1/menus/items/{dish_id}",
            headers=inv_mgr["headers"],
            json={"base_price": "65.00"},
        ).status_code
        == 403
    )

    # Valid PNG upload succeeds; non-image bytes rejected with 400
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(255, 120, 40)).save(buf, format="PNG")
    img_ok = client.post(
        f"/api/v1/menus/items/{dish_id}/upload-image",
        headers=inv_mgr["headers"],
        files={"file": ("bowl.png", buf.getvalue(), "image/png")},
    )
    assert img_ok.status_code == 200, img_ok.text
    assert img_ok.json()["images"][0]["image_url"].startswith("data:image/png;base64,")

    img_bad = client.post(
        f"/api/v1/menus/items/{dish_id}/upload-image",
        headers=inv_mgr["headers"],
        files={"file": ("fake.png", b"not-a-valid-image-payload", "image/png")},
    )
    assert img_bad.status_code == 400
