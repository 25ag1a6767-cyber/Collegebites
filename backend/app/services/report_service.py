import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.college import Counter
from app.models.engagement import Review
from app.models.inventory import InventoryItem, PurchaseOrder, StockBatch, StockMovement, WastageRecord
from app.models.menu import FoodCategory, FoodItem, Ingredient
from app.models.order import Order, OrderItem
from app.models.payment import Payment


def get_analytics_report(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, Any]:
    s_date = start_date or (date.today() - timedelta(days=30))
    e_date = end_date or date.today()
    s_dt = datetime.combine(s_date, time.min, tzinfo=timezone.utc)
    e_dt = datetime.combine(e_date, time.max, tzinfo=timezone.utc)

    order_filters = [Order.created_at >= s_dt, Order.created_at <= e_dt]
    if canteen_id:
        order_filters.append(Order.canteen_id == canteen_id)

    paid_filters = order_filters + [Order.payment_status == "CONFIRMED"]

    # 1. Sales metrics
    total_orders = db.scalar(select(func.count(Order.id)).where(*paid_filters)) or 0
    gross_sales = db.scalar(select(func.coalesce(func.sum(Order.subtotal_amount), 0)).where(*paid_filters)) or Decimal("0.00")
    discounts = db.scalar(select(func.coalesce(func.sum(Order.discount_amount), 0)).where(*paid_filters)) or Decimal("0.00")
    tax_collected = db.scalar(select(func.coalesce(func.sum(Order.tax_amount), 0)).where(*paid_filters)) or Decimal("0.00")
    net_sales = db.scalar(select(func.coalesce(func.sum(Order.total_amount), 0)).where(*paid_filters)) or Decimal("0.00")
    aov = (Decimal(str(net_sales)) / Decimal(max(1, total_orders))).quantize(Decimal("0.01")) if total_orders else Decimal("0.00")

    # Daily trend
    paid_orders = db.scalars(select(Order).where(*paid_filters).order_by(Order.created_at.asc())).all()
    daily_map: dict[str, dict[str, Any]] = {}
    hourly_counts: dict[int, int] = {h: 0 for h in range(24)}
    prep_durations: list[float] = []
    wait_durations: list[float] = []
    for o in paid_orders:
        day_key = o.created_at.strftime("%Y-%m-%d")
        if day_key not in daily_map:
            daily_map[day_key] = {"date": day_key, "orders": 0, "revenue": Decimal("0.00")}
        daily_map[day_key]["orders"] += 1
        daily_map[day_key]["revenue"] += o.total_amount
        hourly_counts[o.created_at.hour] = hourly_counts.get(o.created_at.hour, 0) + 1
        if o.confirmed_at and o.ready_at:
            prep_durations.append(max(0.0, (o.ready_at - o.confirmed_at).total_seconds() / 60.0))
        if o.ready_at and o.completed_at:
            wait_durations.append(max(0.0, (o.completed_at - o.ready_at).total_seconds() / 60.0))

    daily_series = [
        {"date": v["date"], "orders": v["orders"], "revenue": float(v["revenue"])}
        for v in sorted(daily_map.values(), key=lambda x: x["date"])
    ]
    peak_hours = [{"hour": f"{h:02d}:00", "orders": c} for h, c in hourly_counts.items() if c > 0]

    # Top food items & categories
    item_rows = db.execute(
        select(
            OrderItem.item_name,
            func.sum(OrderItem.quantity),
            func.coalesce(func.sum(OrderItem.line_total), 0),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(*paid_filters)
        .group_by(OrderItem.item_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(15)
    ).all()
    top_items = [
        {"item_name": name, "quantity_sold": int(qty), "revenue": float(rev)}
        for name, qty, rev in item_rows
    ]

    cat_rows = db.execute(
        select(
            FoodCategory.name,
            func.sum(OrderItem.quantity),
            func.coalesce(func.sum(OrderItem.line_total), 0),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .join(FoodItem, FoodItem.id == OrderItem.food_item_id)
        .join(FoodCategory, FoodCategory.id == FoodItem.category_id)
        .where(*paid_filters)
        .group_by(FoodCategory.name)
    ).all()
    category_sales = [{"category": name, "quantity": int(qty), "revenue": float(rev)} for name, qty, rev in cat_rows]

    counter_rows = db.execute(
        select(Counter.name, func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
        .join(Counter, Counter.id == Order.counter_id)
        .where(*paid_filters)
        .group_by(Counter.name)
    ).all()
    counter_sales = [{"counter": name, "orders": int(cnt), "revenue": float(rev)} for name, cnt, rev in counter_rows]

    pay_rows = db.execute(
        select(Order.payment_method, func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
        .where(*paid_filters)
        .group_by(Order.payment_method)
    ).all()
    payment_breakdown = [{"method": m, "orders": int(cnt), "amount": float(amt)} for m, cnt, amt in pay_rows]

    # 2. Operations metrics
    completed_orders = db.scalar(select(func.count(Order.id)).where(*order_filters, Order.status == "COMPLETED")) or 0
    cancelled_orders = db.scalar(select(func.count(Order.id)).where(*order_filters, Order.status.in_(("CANCELLED", "REJECTED")))) or 0
    delayed_orders = db.scalar(select(func.count(Order.id)).where(*order_filters, Order.delayed_minutes > 0)) or 0

    # 3. Inventory metrics
    inv_stmt = select(InventoryItem, Ingredient.name).join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
    if canteen_id:
        inv_stmt = inv_stmt.where(InventoryItem.canteen_id == canteen_id)
    inv_rows = db.execute(inv_stmt).all()
    low_stock_count = sum(1 for inv, _ in inv_rows if inv.current_quantity <= inv.reorder_level)
    total_wastage = db.scalar(select(func.coalesce(func.sum(WastageRecord.estimated_loss), 0))) or Decimal("0.00")
    total_purchases = db.scalar(select(func.coalesce(func.sum(PurchaseOrder.total_cost), 0)).where(PurchaseOrder.status == "received")) or Decimal("0.00")
    expiring_count = db.scalar(
        select(func.count(StockBatch.id)).where(
            StockBatch.remaining_quantity > 0,
            StockBatch.expiry_date.is_not(None),
            StockBatch.expiry_date <= date.today() + timedelta(days=7),
        )
    ) or 0

    # 4. Customer metrics
    total_customers = db.scalar(select(func.count(User.id)).where(User.user_kind == "customer")) or 0
    cust_order_counts = db.execute(
        select(Order.customer_id, func.count(Order.id))
        .where(*paid_filters, Order.customer_id.is_not(None))
        .group_by(Order.customer_id)
    ).all()
    returning_customers = sum(1 for _cid, cnt in cust_order_counts if cnt > 1)
    repeat_rate = round((returning_customers / max(1, len(cust_order_counts))) * 100.0, 1) if cust_order_counts else 0.0
    avg_rating = db.scalar(select(func.coalesce(func.avg(Review.rating), 0))) or 0

    return {
        "range": {"start_date": s_date.isoformat(), "end_date": e_date.isoformat()},
        "sales": {
            "total_orders": int(total_orders),
            "gross_sales": f"{Decimal(str(gross_sales)):.2f}",
            "discounts": f"{Decimal(str(discounts)):.2f}",
            "tax_collected": f"{Decimal(str(tax_collected)):.2f}",
            "net_sales": f"{Decimal(str(net_sales)):.2f}",
            "average_order_value": f"{aov:.2f}",
            "daily_series": daily_series,
            "top_items": top_items,
            "category_sales": category_sales,
            "counter_sales": counter_sales,
            "payment_breakdown": payment_breakdown,
        },
        "operations": {
            "completed_orders": int(completed_orders),
            "cancelled_orders": int(cancelled_orders),
            "delayed_orders": int(delayed_orders),
            "avg_prep_minutes": round(sum(prep_durations) / len(prep_durations), 1) if prep_durations else 0.0,
            "avg_pickup_wait_minutes": round(sum(wait_durations) / len(wait_durations), 1) if wait_durations else 0.0,
            "peak_hours": peak_hours,
        },
        "inventory": {
            "tracked_ingredients": len(inv_rows),
            "low_stock_count": low_stock_count,
            "expiring_within_7_days": int(expiring_count),
            "total_wastage_loss": f"{Decimal(str(total_wastage)):.2f}",
            "total_purchases_received": f"{Decimal(str(total_purchases)):.2f}",
        },
        "customers": {
            "registered_customers": int(total_customers),
            "active_ordering_customers": len(cust_order_counts),
            "returning_customers": returning_customers,
            "repeat_order_rate_percent": repeat_rate,
            "average_food_rating": round(float(avg_rating), 2),
        },
    }


def export_report_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["CollegeBites Analytics Report", report["range"]["start_date"], report["range"]["end_date"]])
    writer.writerow([])
    writer.writerow(["SALES SUMMARY"])
    for k, v in report["sales"].items():
        if not isinstance(v, list):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["TOP FOOD ITEMS", "QUANTITY SOLD", "REVENUE"])
    for it in report["sales"]["top_items"]:
        writer.writerow([it["item_name"], it["quantity_sold"], it["revenue"]])
    writer.writerow([])
    writer.writerow(["OPERATIONS SUMMARY"])
    for k, v in report["operations"].items():
        if not isinstance(v, list):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["INVENTORY SUMMARY"])
    for k, v in report["inventory"].items():
        writer.writerow([k, v])
    return buf.getvalue()


def export_report_pdf(report: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 40
    c.setFont("Helvetica-Bold", 15)
    c.drawString(40, y, "CollegeBites Operational & Financial Report")
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Date Range: {report['range']['start_date']} to {report['range']['end_date']}")
    y -= 24

    def section(title: str, rows: list[tuple[str, Any]]):
        nonlocal y
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, title)
        y -= 16
        c.setFont("Helvetica", 10)
        for label, val in rows:
            c.drawString(52, y, f"{label}: {val}")
            y -= 14
        y -= 10

    s = report["sales"]
    section("Sales Summary", [
        ("Total Confirmed Orders", s["total_orders"]),
        ("Gross Sales", f"Rs.{s['gross_sales']}"),
        ("Discounts", f"Rs.{s['discounts']}"),
        ("Tax Collected", f"Rs.{s['tax_collected']}"),
        ("Net Sales", f"Rs.{s['net_sales']}"),
        ("Average Order Value", f"Rs.{s['average_order_value']}"),
    ])
    op = report["operations"]
    section("Operations", [
        ("Completed Orders", op["completed_orders"]),
        ("Cancelled / Rejected Orders", op["cancelled_orders"]),
        ("Delayed Orders", op["delayed_orders"]),
        ("Average Prep Minutes", op["avg_prep_minutes"]),
    ])
    inv = report["inventory"]
    section("Inventory & Wastage", [
        ("Tracked Ingredients", inv["tracked_ingredients"]),
        ("Low Stock Alerts", inv["low_stock_count"]),
        ("Expiring Within 7 Days", inv["expiring_within_7_days"]),
        ("Wastage Loss", f"Rs.{inv['total_wastage_loss']}"),
    ])
    c.showPage()
    c.save()
    return buf.getvalue()
