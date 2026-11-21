from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_menu_browsing_filters_and_sorting(client: TestClient):
    canteens = client.get("/api/v1/canteens").json()
    main = next(c for c in canteens if c["slug"] == "main-canteen")
    cid = main["id"]

    all_items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    assert len(all_items) >= 4

    veg_items = client.get(f"/api/v1/menus/canteens/{cid}/items?is_veg=true").json()
    assert all(item["is_veg"] is True for item in veg_items)

    search = client.get(f"/api/v1/menus/canteens/{cid}/items?q=Biryani").json()
    assert len(search) == 1
    assert "Biryani" in search[0]["name"]
    assert len(search[0]["variants"]) >= 2
    assert len(search[0]["addons"]) >= 1

    sorted_desc = client.get(f"/api/v1/menus/canteens/{cid}/items?sort_by=price_desc").json()
    prices = [float(i["base_price"]) for i in sorted_desc]
    assert prices == sorted(prices, reverse=True)


def test_menu_crud_csv_import_export_and_favourites(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    main = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = main["id"]
    cats = client.get(f"/api/v1/menus/canteens/{cid}/categories").json()
    cat_id = cats[0]["id"]

    # Student cannot create menu item
    deny = client.post(
        "/api/v1/menus/items",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "category_id": cat_id,
            "name": "Unauthorized Dish",
            "slug": "unauth-dish",
            "base_price": "50.00",
        },
    )
    assert deny.status_code == 403

    # Admin creates item
    created = client.post(
        "/api/v1/menus/items",
        headers=admin["headers"],
        json={
            "canteen_id": cid,
            "category_id": cat_id,
            "name": "Paneer Tikka Rice Bowl",
            "slug": "paneer-tikka-bowl",
            "base_price": "110.00",
            "is_veg": True,
            "prep_time_minutes": 14,
            "variants": [
                {"name": "Regular", "price_delta": "0.00", "is_default": True},
                {"name": "Large", "price_delta": "40.00", "is_default": False},
            ],
            "allergen_names": ["Dairy"],
        },
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]

    # Student adds & removes favourite
    fav_add = client.post(f"/api/v1/customers/favourites/{item_id}", headers=student["headers"])
    assert fav_add.status_code == 200
    assert item_id in fav_add.json()["favourite_item_ids"]

    fav_del = client.delete(f"/api/v1/customers/favourites/{item_id}", headers=student["headers"])
    assert fav_del.status_code == 200
    assert item_id not in fav_del.json()["favourite_item_ids"]

    # CSV Export & Import
    csv_export = client.get(f"/api/v1/menus/canteens/{cid}/export-csv", headers=admin["headers"])
    assert csv_export.status_code == 200
    assert "Paneer Tikka Rice Bowl" in csv_export.text

    csv_payload = "name,slug,category,base_price,is_veg,prep_time_minutes\nIdli Vada Combo,idli-vada-combo,South Indian Tiffins,45.00,true,6\n"
    imp = client.post(
        f"/api/v1/menus/canteens/{cid}/import-csv",
        headers=admin["headers"],
        files={"file": ("menu.csv", csv_payload.encode("utf-8"), "text/csv")},
    )
    assert imp.status_code == 200
    assert imp.json()["created"] == 1
