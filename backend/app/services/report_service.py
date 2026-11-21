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

from app.core.time_utils import today_college
from app.models.auth import User
from app.models.college import Counter
from app.models.engagement import Review, SupportTicket
from app.models.inventory import InventoryItem, PurchaseOrder, StockBatch, StockMovement, WastageRecord
from app.models.menu import FoodCategory, FoodItem, Ingredient
from app.models.order import Order, OrderItem
from app.models.payment import Payment
from app.models.staff import StaffAttendance, StaffTask


def get_analytics_report(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, Any]:
    local_today = today_college()
    s_date = start_date or (local_today - timedelta(days=30))
    e_date = end_date or local_today
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

    # 3. Inventory metrics (scoped to canteen and reporting window)
    inv_stmt = select(InventoryItem, Ingredient.name).join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
    if canteen_id:
        inv_stmt = inv_stmt.where(InventoryItem.canteen_id == canteen_id)
    inv_rows = db.execute(inv_stmt).all()
    low_stock_count = sum(1 for inv, _ in inv_rows if inv.current_quantity <= inv.reorder_level)

    wastage_stmt = (
        select(func.coalesce(func.sum(WastageRecord.estimated_loss), 0))
        .join(InventoryItem, InventoryItem.id == WastageRecord.inventory_item_id)
        .where(WastageRecord.created_at >= s_dt, WastageRecord.created_at <= e_dt)
    )
    if canteen_id:
        wastage_stmt = wastage_stmt.where(InventoryItem.canteen_id == canteen_id)
    total_wastage = db.scalar(wastage_stmt) or Decimal("0.00")

    po_stmt = select(func.coalesce(func.sum(PurchaseOrder.total_cost), 0)).where(
        PurchaseOrder.status == "received",
        PurchaseOrder.created_at >= s_dt,
        PurchaseOrder.created_at <= e_dt,
    )
    if canteen_id:
        po_stmt = po_stmt.where(PurchaseOrder.canteen_id == canteen_id)
    total_purchases = db.scalar(po_stmt) or Decimal("0.00")

    exp_stmt = (
        select(func.count(StockBatch.id))
        .join(InventoryItem, InventoryItem.id == StockBatch.inventory_item_id)
        .where(
            StockBatch.remaining_quantity > 0,
            StockBatch.expiry_date.is_not(None),
            StockBatch.expiry_date <= local_today + timedelta(days=7),
        )
    )
    if canteen_id:
        exp_stmt = exp_stmt.where(InventoryItem.canteen_id == canteen_id)
    expiring_count = db.scalar(exp_stmt) or 0

    # 4. Customer metrics
    total_customers = db.scalar(select(func.count(User.id)).where(User.user_kind == "customer")) or 0
    cust_order_counts = db.execute(
        select(Order.customer_id, func.count(Order.id))
        .where(*paid_filters, Order.customer_id.is_not(None))
        .group_by(Order.customer_id)
    ).all()
    returning_customers = sum(1 for _cid, cnt in cust_order_counts if cnt > 1)
    repeat_rate = round((returning_customers / max(1, len(cust_order_counts))) * 100.0, 1) if cust_order_counts else 0.0
    review_stmt = select(func.coalesce(func.avg(Review.rating), 0)).where(
        Review.is_visible.is_(True), Review.created_at >= s_dt, Review.created_at <= e_dt
    )
    if canteen_id:
        review_stmt = review_stmt.where(Review.canteen_id == canteen_id)
    avg_rating = db.scalar(review_stmt) or 0

    # 5. Support metrics
    sup_stmt = select(SupportTicket).where(SupportTicket.created_at >= s_dt, SupportTicket.created_at <= e_dt)
    if canteen_id:
        sup_stmt = sup_stmt.where(SupportTicket.canteen_id == canteen_id)
    tickets = db.scalars(sup_stmt).all()
    open_tickets = sum(1 for t in tickets if t.status in ("open", "assigned", "in_progress"))
    resolved_tickets = sum(1 for t in tickets if t.status in ("resolved", "closed"))
    res_mins = [
        max(0.0, (t.resolved_at - t.created_at).total_seconds() / 60.0)
        for t in tickets
        if t.resolved_at and t.created_at
    ]

    # 6. Staff performance metrics
    att_stmt = select(StaffAttendance).where(
        StaffAttendance.attendance_date >= s_date, StaffAttendance.attendance_date <= e_date
    )
    if canteen_id:
        att_stmt = att_stmt.where(StaffAttendance.canteen_id == canteen_id)
    att_rows = db.scalars(att_stmt).all()
    present_checkins = sum(1 for a in att_rows if a.status == "present")
    leave_days = sum(1 for a in att_rows if a.status == "leave")

    task_stmt = select(StaffTask).where(StaffTask.created_at >= s_dt, StaffTask.created_at <= e_dt)
    if canteen_id:
        task_stmt = task_stmt.where(StaffTask.canteen_id == canteen_id)
    tasks = db.scalars(task_stmt).all()
    tasks_done = sum(1 for t in tasks if t.status == "done")
    cashier_orders = sum(1 for o in paid_orders if o.cashier_id is not None)

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
        "support": {
            "total_tickets": len(tickets),
            "open_tickets": open_tickets,
            "resolved_tickets": resolved_tickets,
            "avg_resolution_minutes": round(sum(res_mins) / len(res_mins), 1) if res_mins else 0.0,
        },
        "staff_performance": {
            "present_checkins": present_checkins,
            "leave_records": leave_days,
            "tasks_total": len(tasks),
            "tasks_completed": tasks_done,
            "cashier_walkin_orders": cashier_orders,
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
    writer.writerow(["CATEGORY SALES", "QUANTITY", "REVENUE"])
    for cat in report["sales"].get("category_sales", []):
        writer.writerow([cat["category"], cat["quantity"], cat["revenue"]])
    writer.writerow([])
    writer.writerow(["COUNTER SALES", "ORDERS", "REVENUE"])
    for cnt in report["sales"].get("counter_sales", []):
        writer.writerow([cnt["counter"], cnt["orders"], cnt["revenue"]])
    writer.writerow([])
    writer.writerow(["PAYMENT BREAKDOWN", "ORDERS", "AMOUNT"])
    for pm in report["sales"].get("payment_breakdown", []):
        writer.writerow([pm["method"], pm["orders"], pm["amount"]])
    writer.writerow([])
    writer.writerow(["OPERATIONS SUMMARY"])
    for k, v in report["operations"].items():
        if not isinstance(v, list):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["PEAK HOURS", "ORDERS"])
    for ph in report["operations"].get("peak_hours", []):
        writer.writerow([ph["hour"], ph["orders"]])
    writer.writerow([])
    writer.writerow(["INVENTORY SUMMARY"])
    for k, v in report["inventory"].items():
        writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["CUSTOMER METRICS"])
    for k, v in report.get("customers", {}).items():
        writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["SUPPORT METRICS"])
    for k, v in report.get("support", {}).items():
        writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["STAFF PERFORMANCE"])
    for k, v in report.get("staff_performance", {}).items():
        writer.writerow([k, v])
    return buf.getvalue()


def export_report_pdf(report: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 40

    def ensure_space(needed: int = 24) -> None:
        nonlocal y
        if y - needed < 42:
            c.showPage()
            y = h - 42

    c.setFont("Helvetica-Bold", 15)
    c.drawString(40, y, "CollegeBites Operational & Financial Report")
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Date Range: {report['range']['start_date']} to {report['range']['end_date']}")
    y -= 24

    def section(title: str, rows: list[tuple[str, Any]]):
        nonlocal y
        ensure_space(40)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, title)
        y -= 16
        c.setFont("Helvetica", 10)
        for label, val in rows:
            ensure_space(16)
            c.drawString(52, y, f"{label}: {val}"[:96])
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
        ("Average Pickup Wait Minutes", op.get("avg_pickup_wait_minutes", 0)),
    ])
    inv = report["inventory"]
    section("Inventory & Wastage", [
        ("Tracked Ingredients", inv["tracked_ingredients"]),
        ("Low Stock Alerts", inv["low_stock_count"]),
        ("Expiring Within 7 Days", inv["expiring_within_7_days"]),
        ("Wastage Loss", f"Rs.{inv['total_wastage_loss']}"),
        ("Purchases Received", f"Rs.{inv['total_purchases_received']}"),
    ])
    cust = report.get("customers", {})
    section("Customers & Ratings", [
        ("Registered Customers", cust.get("registered_customers", 0)),
        ("Active Ordering Customers", cust.get("active_ordering_customers", 0)),
        ("Repeat Order Rate", f"{cust.get('repeat_order_rate_percent', 0)}%"),
        ("Average Food Rating", f"{cust.get('average_food_rating', 0)} / 5"),
    ])
    sup = report.get("support", {})
    sp = report.get("staff_performance", {})
    section("Support & Staff Operations", [
        ("Support Tickets (Open / Resolved)", f"{sup.get('open_tickets', 0)} / {sup.get('resolved_tickets', 0)}"),
        ("Avg Ticket Resolution", f"{sup.get('avg_resolution_minutes', 0)} mins"),
        ("Staff Check-ins / Leave Days", f"{sp.get('present_checkins', 0)} / {sp.get('leave_records', 0)}"),
        ("Staff Tasks Completed", f"{sp.get('tasks_completed', 0)} / {sp.get('tasks_total', 0)}"),
        ("Cashier Walk-in Orders", sp.get("cashier_walkin_orders", 0)),
    ])
    if s.get("top_items"):
        section("Top Food Items", [(it["item_name"], f"{it['quantity_sold']} sold (Rs.{it['revenue']:.2f})") for it in s["top_items"][:10]])
    if s.get("category_sales"):
        section("Category Sales", [(it["category"], f"{it['quantity']} sold (Rs.{it['revenue']:.2f})") for it in s["category_sales"]])
    if s.get("counter_sales"):
        section("Counter Sales", [(it["counter"], f"{it['orders']} orders (Rs.{it['revenue']:.2f})") for it in s["counter_sales"]])
    if s.get("payment_breakdown"):
        section("Payment Breakdown", [(it["method"], f"{it['orders']} orders (Rs.{it['amount']:.2f})") for it in s["payment_breakdown"]])
    c.showPage()
    c.save()
    return buf.getvalue()
