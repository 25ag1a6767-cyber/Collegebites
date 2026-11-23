from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.time_utils import today_college
from tests.conftest import login_as


def test_phase29_vendor_procurement_lifecycle_grn_and_payments(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = canteen["id"]
    today_col = today_college()

    # 1. Create Vendor with business details, supplied products, payment terms
    v_res = client.post(
        "/api/v1/inventory/suppliers",
        headers=inv_mgr["headers"],
        json={
            "name": "Apex Campus Agro & Packaging Ltd",
            "contact_person": "Ramesh Mehta",
            "phone": "+919812345670",
            "email": "orders@apexagro.in",
            "address": "Plot 42, Industrial Estate",
            "gst_number": "29AABCA1234F1Z5",
            "business_details": "FSSAI Lic 10023041, HDFC IFSC HDFC0001234",
            "supplied_products": ["Raw Ingredients", "Packaging Supplies", "Beverages"],
            "payment_terms": "Net 15 Days",
        },
    )
    assert v_res.status_code == 201, v_res.text
    vendor = v_res.json()
    vid = vendor["id"]
    assert "Packaging Supplies" in vendor["supplied_products"]
    assert vendor["payment_terms"] == "Net 15 Days"

    # Search and filter vendors
    s_search = client.get("/api/v1/inventory/suppliers?search=Apex&product=Packaging&is_active=true", headers=inv_mgr["headers"])
    assert s_search.status_code == 200
    assert any(s["id"] == vid for s in s_search.json())

    # 2. Create ingredient to track stock accurately
    ing_res = client.post(
        "/api/v1/inventory/ingredients",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": cid,
            "name": "Premium Basmati Rice P29",
            "sku": "RICE-P29-01",
            "category": "Grains",
            "unit": "kg",
            "initial_quantity": "10.000",
            "reorder_level": "15.000",
            "unit_cost": "80.00",
            "preferred_supplier_id": vid,
        },
    )
    assert ing_res.status_code == 201, ing_res.text
    ing_id = ing_res.json()["ingredient_id"]
    inv_item_id = ing_res.json()["inventory_item_id"]

    # 3. Create PO in pending_approval status with both ingredient and packaging item + tax
    po_res = client.post(
        "/api/v1/inventory/purchase-orders",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": cid,
            "supplier_id": vid,
            "initial_status": "pending_approval",
            "expected_delivery_date": (today_col + timedelta(days=3)).isoformat(),
            "notes": "Monthly grain and takeaway box order",
            "items": [
                {
                    "ingredient_id": ing_id,
                    "quantity_ordered": "50.000",
                    "unit_cost": "80.00",
                    "tax_rate_percent": "5.00",
                    "expiry_date": (today_col + timedelta(days=90)).isoformat(),
                },
                {
                    "item_name": "Biodegradable Meal Boxes (Pack of 100)",
                    "unit": "packs",
                    "quantity_ordered": "10.000",
                    "unit_cost": "100.00",
                    "tax_rate_percent": "18.00",
                },
            ],
        },
    )
    assert po_res.status_code == 201, po_res.text
    po = po_res.json()
    po_id = po["id"]
    assert po["status"] == "pending_approval"
    # Subtotal = (50*80) + (10*100) = 4000 + 1000 = 5000.00; Tax = 200 + 180 = 380.00; Total = 5380.00
    assert Decimal(po["subtotal_amount"]) == Decimal("5000.00")
    assert Decimal(po["tax_amount"]) == Decimal("380.00")
    assert Decimal(po["total_cost"]) == Decimal("5380.00")

    # Receiving before approval must be blocked
    premature_rec = client.post(
        f"/api/v1/inventory/purchase-orders/{po_id}/receive",
        headers=inv_mgr["headers"],
    )
    assert premature_rec.status_code == 400

    # Inventory manager cannot self-approve PO; College Admin approves and marks ordered
    deny_approve = client.post(
        f"/api/v1/inventory/purchase-orders/{po_id}/status",
        headers=inv_mgr["headers"],
        json={"status": "approved"},
    )
    assert deny_approve.status_code == 403

    ok_approve = client.post(
        f"/api/v1/inventory/purchase-orders/{po_id}/status",
        headers=admin["headers"],
        json={"status": "approved", "notes": "Approved for monthly procurement"},
    )
    assert ok_approve.status_code == 200
    assert ok_approve.json()["status"] == "approved"
    assert ok_approve.json()["approved_at"] is not None

    ok_order = client.post(
        f"/api/v1/inventory/purchase-orders/{po_id}/status",
        headers=inv_mgr["headers"],
        json={"status": "ordered"},
    )
    assert ok_order.status_code == 200
    assert ok_order.json()["status"] == "ordered"

    # Printable PO PDF generation
    pdf_res = client.get(f"/api/v1/inventory/purchase-orders/{po_id}/pdf", headers=inv_mgr["headers"])
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    assert pdf_res.content.startswith(b"%PDF")

    # 4. Partial Goods Receipt (GRN 1): 30 kg accepted, 4 kg damaged, 2 kg rejected -> only 30 kg added to stock!
    rice_po_item = next(it for it in ok_order.json()["items"] if it["ingredient_id"] == ing_id)
    box_po_item = next(it for it in ok_order.json()["items"] if it["ingredient_id"] is None)

    grn1 = client.post(
        f"/api/v1/inventory/purchase-orders/{po_id}/receive",
        headers=inv_mgr["headers"],
        json={
            "idempotency_key": "grn-idem-p29-001",
            "delivery_challan_ref": "DC-APEX-001",
            "notes": "First partial truck delivery",
            "received_items": [
                {
                    "po_item_id": rice_po_item["id"],
                    "ingredient_id": ing_id,
                    "quantity_delivered": "36.000",
                    "quantity_received": "30.000",
                    "quantity_damaged": "4.000",
                    "quantity_rejected": "2.000",
                    "quantity_missing": "0.000",
                }
            ],
        },
    )
    assert grn1.status_code == 200, grn1.text
    assert grn1.json()["status"] == "partial"
    assert grn1.json()["lifecycle_status"] == "partially_received"

    # Duplicate GRN submission with same idempotency_key must NOT duplicate stock
    grn1_dup = client.post(
        f"/api/v1/inventory/purchase-orders/{po_id}/receive",
        headers=inv_mgr["headers"],
        json={
            "idempotency_key": "grn-idem-p29-001",
            "received_items": [{"po_item_id": rice_po_item["id"], "quantity_received": "30.000"}],
        },
    )
    assert grn1_dup.status_code == 200
    assert grn1_dup.json().get("idempotent_replay") is True

    # Verify inventory stock increased by exactly 30.000 (from 10.000 to 40.000), excluding damaged/rejected
    inv_items = client.get(f"/api/v1/inventory/canteens/{cid}/items", headers=inv_mgr["headers"]).json()
    rice_inv = next(i for i in inv_items if i["inventory_item_id"] == inv_item_id)
    assert Decimal(rice_inv["current_quantity"]) == Decimal("40.000")

    # Over-receiving beyond remaining balance (20.000 left) must fail
    over_rec = client.post(
        f"/api/v1/inventory/purchase-orders/{po_id}/receive",
        headers=inv_mgr["headers"],
        json={
            "received_items": [{"po_item_id": rice_po_item["id"], "quantity_received": "25.000"}],
        },
    )
    assert over_rec.status_code == 400

    # Complete remaining delivery (20 kg rice + 10 packs meal boxes)
    grn2 = client.post(
        f"/api/v1/inventory/purchase-orders/{po_id}/receive",
        headers=inv_mgr["headers"],
        json={
            "idempotency_key": "grn-idem-p29-002",
            "delivery_challan_ref": "DC-APEX-002",
            "received_items": [
                {"po_item_id": rice_po_item["id"], "quantity_received": "20.000"},
                {"po_item_id": box_po_item["id"], "quantity_received": "10.000"},
            ],
        },
    )
    assert grn2.status_code == 200, grn2.text
    assert grn2.json()["status"] == "received"

    grn_list = client.get(f"/api/v1/inventory/purchase-orders/{po_id}/receipts", headers=inv_mgr["headers"])
    assert grn_list.status_code == 200
    assert len(grn_list.json()) == 2

    # 5. Vendor Payments: cannot mark verified without reference; pending -> verified updates statement balance
    bad_pay = client.post(
        "/api/v1/inventory/vendor-payments",
        headers=inv_mgr["headers"],
        json={
            "supplier_id": vid,
            "canteen_id": cid,
            "purchase_order_id": po_id,
            "amount": "2000.00",
            "payment_method": "neft_rtgs",
            "status": "verified",
        },
    )
    assert bad_pay.status_code == 400

    pend_pay = client.post(
        "/api/v1/inventory/vendor-payments",
        headers=inv_mgr["headers"],
        json={
            "supplier_id": vid,
            "canteen_id": cid,
            "purchase_order_id": po_id,
            "amount": "3380.00",
            "payment_method": "neft_rtgs",
            "notes": "First installment",
        },
    )
    assert pend_pay.status_code == 201, pend_pay.text
    assert pend_pay.json()["status"] == "pending_verification"
    pay_id = pend_pay.json()["id"]

    # Verify payment with UTR reference
    ver_pay = client.post(
        f"/api/v1/inventory/vendor-payments/{pay_id}/verify",
        headers=admin["headers"],
        json={"payment_reference": "UTR-HDFC-20261123-9901", "document_url": "https://cdn.collegebites.edu/docs/utr9901.pdf"},
    )
    assert ver_pay.status_code == 200
    assert ver_pay.json()["status"] == "verified"

    # Check vendor account statement
    stmt = client.get(f"/api/v1/inventory/suppliers/{vid}/statement", headers=inv_mgr["headers"])
    assert stmt.status_code == 200
    st_data = stmt.json()
    assert Decimal(st_data["vendor"]["total_billed_amount"]) == Decimal("5380.00")
    assert Decimal(st_data["vendor"]["total_paid_amount"]) == Decimal("3380.00")
    assert Decimal(st_data["vendor"]["outstanding_balance"]) == Decimal("2000.00")
    assert Decimal(st_data["vendor"]["total_damaged_rejected_qty"]) == Decimal("6.000")
    assert len(st_data["ledger"]) == 2
