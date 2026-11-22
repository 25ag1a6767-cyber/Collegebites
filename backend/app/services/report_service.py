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

from app.core.time_utils import get_college_tz, today_college
from app.models.auth import StaffProfile, User
from app.models.college import Counter
from app.models.engagement import Review, SupportTicket
from app.models.inventory import InventoryItem, PurchaseOrder, StockBatch, WastageRecord
from app.models.menu import FoodCategory, FoodItem, Ingredient
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.payment import Payment
from app.models.staff import StaffAttendance, StaffTask

PENDING_ACTIVE_STATUSES = ("PAYMENT_PENDING", "PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING", "READY")


def _to_local_dt(dt: datetime, tz) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def get_analytics_report(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict[str, Any]:
    college_tz = get_college_tz()
    local_today = today_college()
    s_date = start_date or (local_today - timedelta(days=30))
    e_date = end_date or local_today
    s_dt = datetime.combine(s_date, time.min, tzinfo=college_tz)
    e_dt = datetime.combine(e_date, time.max, tzinfo=college_tz)

    order_filters = [Order.created_at >= s_dt, Order.created_at <= e_dt]
    if canteen_id:
        order_filters.append(Order.canteen_id == canteen_id)

    paid_filters = order_filters + [Order.payment_status == "CONFIRMED"]

    # 1. Sales metrics (strictly from real database rows)
    total_orders = db.scalar(select(func.count(Order.id)).where(*paid_filters)) or 0
    gross_sales = db.scalar(select(func.coalesce(func.sum(Order.subtotal_amount), 0)).where(*paid_filters)) or Decimal("0.00")
    discounts = db.scalar(select(func.coalesce(func.sum(Order.discount_amount), 0)).where(*paid_filters)) or Decimal("0.00")
    tax_collected = db.scalar(select(func.coalesce(func.sum(Order.tax_amount), 0)).where(*paid_filters)) or Decimal("0.00")
    net_sales = db.scalar(select(func.coalesce(func.sum(Order.total_amount), 0)).where(*paid_filters)) or Decimal("0.00")
    aov = (Decimal(str(net_sales)) / Decimal(max(1, total_orders))).quantize(Decimal("0.01")) if total_orders else Decimal("0.00")

    # Today's real-time snapshot in college timezone
    today_s_dt = datetime.combine(local_today, time.min, tzinfo=college_tz)
    today_e_dt = datetime.combine(local_today, time.max, tzinfo=college_tz)
    today_base = [Order.created_at >= today_s_dt, Order.created_at <= today_e_dt]
    if canteen_id:
        today_base.append(Order.canteen_id == canteen_id)
    total_orders_today = db.scalar(select(func.count(Order.id)).where(*today_base, Order.payment_status == "CONFIRMED")) or 0
    completed_orders_today = db.scalar(select(func.count(Order.id)).where(*today_base, Order.status == "COMPLETED")) or 0
    pending_orders_today = db.scalar(select(func.count(Order.id)).where(*today_base, Order.status.in_(PENDING_ACTIVE_STATUSES))) or 0
    revenue_today = db.scalar(select(func.coalesce(func.sum(Order.total_amount), 0)).where(*today_base, Order.payment_status == "CONFIRMED")) or Decimal("0.00")

    active_pending_stmt = select(func.count(Order.id)).where(
        Order.status.in_(("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING", "READY"))
    )
    if canteen_id:
        active_pending_stmt = active_pending_stmt.where(Order.canteen_id == canteen_id)
    active_pending_orders = db.scalar(active_pending_stmt) or 0

    # Daily, weekly, monthly & hourly series in college timezone
    paid_orders = db.scalars(select(Order).where(*paid_filters).order_by(Order.created_at.asc())).all()
    daily_map: dict[str, dict[str, Any]] = {}
    weekly_map: dict[str, dict[str, Any]] = {}
    monthly_map: dict[str, dict[str, Any]] = {}
    hourly_counts: dict[int, int] = {h: 0 for h in range(24)}
    hourly_revenue: dict[int, Decimal] = {h: Decimal("0.00") for h in range(24)}
    prep_durations: list[float] = []
    wait_durations: list[float] = []
    for o in paid_orders:
        local_dt = _to_local_dt(o.created_at, college_tz)
        day_key = local_dt.strftime("%Y-%m-%d")
        iso = local_dt.isocalendar()
        week_key = f"{iso.year}-W{iso.week:02d}"
        week_start = (local_dt.date() - timedelta(days=local_dt.weekday())).isoformat()
        month_key = local_dt.strftime("%Y-%m")

        if day_key not in daily_map:
            daily_map[day_key] = {"date": day_key, "orders": 0, "revenue": Decimal("0.00")}
        daily_map[day_key]["orders"] += 1
        daily_map[day_key]["revenue"] += o.total_amount

        if week_key not in weekly_map:
            weekly_map[week_key] = {"week": week_key, "week_start": week_start, "orders": 0, "revenue": Decimal("0.00")}
        weekly_map[week_key]["orders"] += 1
        weekly_map[week_key]["revenue"] += o.total_amount

        if month_key not in monthly_map:
            monthly_map[month_key] = {"month": month_key, "orders": 0, "revenue": Decimal("0.00")}
        monthly_map[month_key]["orders"] += 1
        monthly_map[month_key]["revenue"] += o.total_amount

        hr = local_dt.hour
        hourly_counts[hr] = hourly_counts.get(hr, 0) + 1
        hourly_revenue[hr] = hourly_revenue.get(hr, Decimal("0.00")) + o.total_amount

        if o.confirmed_at and o.ready_at:
            prep_durations.append(max(0.0, (o.ready_at - o.confirmed_at).total_seconds() / 60.0))
        if o.ready_at and o.completed_at:
            wait_durations.append(max(0.0, (o.completed_at - o.ready_at).total_seconds() / 60.0))

    daily_series = [
        {"date": v["date"], "orders": v["orders"], "revenue": float(v["revenue"])}
        for v in sorted(daily_map.values(), key=lambda x: x["date"])
    ]
    weekly_series = [
        {"week": v["week"], "week_start": v["week_start"], "orders": v["orders"], "revenue": float(v["revenue"])}
        for v in sorted(weekly_map.values(), key=lambda x: x["week"])
    ]
    monthly_series = [
        {"month": v["month"], "orders": v["orders"], "revenue": float(v["revenue"])}
        for v in sorted(monthly_map.values(), key=lambda x: x["month"])
    ]
    peak_hours = [
        {"hour": f"{h:02d}:00", "orders": c, "revenue": float(hourly_revenue[h])}
        for h, c in sorted(hourly_counts.items(), key=lambda kv: (-kv[1], -float(hourly_revenue[kv[0]]), kv[0]))
        if c > 0
    ]

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

    # Real gateway/POS payment attempt stats from Payment rows
    pay_att_stmt = (
        select(Payment.status, func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0))
        .join(Order, Order.id == Payment.order_id)
        .where(Payment.created_at >= s_dt, Payment.created_at <= e_dt)
    )
    if canteen_id:
        pay_att_stmt = pay_att_stmt.where(Order.canteen_id == canteen_id)
    pay_att_rows = db.execute(pay_att_stmt.group_by(Payment.status)).all()
    pay_status_map = {st: (int(cnt), Decimal(str(amt))) for st, cnt, amt in pay_att_rows}
    confirmed_cnt, confirmed_amt = pay_status_map.get("CONFIRMED", (0, Decimal("0.00")))
    failed_cnt, failed_amt = pay_status_map.get("FAILED", (0, Decimal("0.00")))
    pending_pay_cnt, _ = pay_status_map.get("PENDING", (0, Decimal("0.00")))
    total_attempts = sum(c for c, _ in pay_status_map.values())
    pay_success_rate = round((confirmed_cnt / max(1, total_attempts)) * 100.0, 1) if total_attempts else 0.0

    # 2. Operations metrics
    completed_orders = db.scalar(select(func.count(Order.id)).where(*order_filters, Order.status == "COMPLETED")) or 0
    cancelled_orders = db.scalar(select(func.count(Order.id)).where(*order_filters, Order.status.in_(("CANCELLED", "REJECTED")))) or 0
    pending_orders = db.scalar(select(func.count(Order.id)).where(*order_filters, Order.status.in_(PENDING_ACTIVE_STATUSES))) or 0
    delayed_orders = db.scalar(select(func.count(Order.id)).where(*order_filters, Order.delayed_minutes > 0)) or 0
    completion_rate = min(100.0, round((completed_orders / max(1, total_orders)) * 100.0, 1)) if total_orders else 0.0

    # 3. Inventory metrics (exclude archived items from active counts & alerts)
    inv_stmt = (
        select(InventoryItem, Ingredient.name)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.is_archived.is_(False))
    )
    if canteen_id:
        inv_stmt = inv_stmt.where(InventoryItem.canteen_id == canteen_id)
    inv_rows = db.execute(inv_stmt.order_by(InventoryItem.current_quantity.asc())).all()
    low_stock_rows = [(inv, ing_name) for inv, ing_name in inv_rows if inv.current_quantity <= inv.reorder_level]
    low_stock_items = [
        {
            "inventory_item_id": str(inv.id),
            "ingredient_name": ing_name,
            "current_quantity": str(inv.current_quantity),
            "reorder_level": str(inv.reorder_level),
            "unit": inv.unit,
        }
        for inv, ing_name in low_stock_rows[:25]
    ]

    wastage_rows_stmt = (
        select(WastageRecord.loss_type, func.coalesce(func.sum(WastageRecord.quantity), 0), func.coalesce(func.sum(WastageRecord.estimated_loss), 0))
        .join(InventoryItem, InventoryItem.id == WastageRecord.inventory_item_id)
        .where(WastageRecord.created_at >= s_dt, WastageRecord.created_at <= e_dt)
        .group_by(WastageRecord.loss_type)
    )
    if canteen_id:
        wastage_rows_stmt = wastage_rows_stmt.where(InventoryItem.canteen_id == canteen_id)
    wastage_grouped = db.execute(wastage_rows_stmt).all()
    wastage_breakdown: dict[str, dict[str, str]] = {
        "damaged": {"quantity": "0.000", "loss_amount": "0.00"},
        "expired": {"quantity": "0.000", "loss_amount": "0.00"},
        "wastage": {"quantity": "0.000", "loss_amount": "0.00"},
    }
    total_wastage = Decimal("0.00")
    for lt, q_sum, l_sum in wastage_grouped:
        l_dec = Decimal(str(l_sum))
        total_wastage += l_dec
        if lt in wastage_breakdown:
            wastage_breakdown[lt] = {"quantity": f"{Decimal(str(q_sum)):.3f}", "loss_amount": f"{l_dec:.2f}"}

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
            InventoryItem.is_archived.is_(False),
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

    # 6. Staff performance & activity metrics
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

    hist_stmt = (
        select(OrderStatusHistory.changed_by_user_id, func.count(OrderStatusHistory.id))
        .join(Order, Order.id == OrderStatusHistory.order_id)
        .where(
            OrderStatusHistory.created_at >= s_dt,
            OrderStatusHistory.created_at <= e_dt,
            OrderStatusHistory.changed_by_user_id.is_not(None),
        )
        .group_by(OrderStatusHistory.changed_by_user_id)
    )
    if canteen_id:
        hist_stmt = hist_stmt.where(Order.canteen_id == canteen_id)
    status_action_counts = {uid: int(cnt) for uid, cnt in db.execute(hist_stmt).all()}

    staff_stmt = select(User, StaffProfile).join(StaffProfile, StaffProfile.user_id == User.id)
    if canteen_id:
        staff_stmt = staff_stmt.where(StaffProfile.assigned_canteen_id == canteen_id)
    staff_profiles = db.execute(staff_stmt.order_by(User.full_name.asc())).all()
    staff_breakdown = []
    for u, sp in staff_profiles:
        u_checkins = sum(1 for a in att_rows if a.user_id == u.id and a.status == "present")
        u_tasks_tot = sum(1 for t in tasks if t.assigned_to_user_id == u.id)
        u_tasks_done = sum(1 for t in tasks if t.assigned_to_user_id == u.id and t.status == "done")
        u_cashier = sum(1 for o in paid_orders if o.cashier_id == u.id)
        u_actions = status_action_counts.get(u.id, 0)
        staff_breakdown.append({
            "user_id": str(u.id),
            "full_name": u.full_name,
            "employee_code": sp.employee_code,
            "checkins": u_checkins,
            "tasks_total": u_tasks_tot,
            "tasks_completed": u_tasks_done,
            "cashier_orders": u_cashier,
            "status_updates": u_actions,
        })

    return {
        "range": {"start_date": s_date.isoformat(), "end_date": e_date.isoformat()},
        "today_summary": {
            "date": local_today.isoformat(),
            "total_orders_today": int(total_orders_today),
            "completed_orders_today": int(completed_orders_today),
            "pending_orders_today": int(pending_orders_today),
            "active_pending_orders": int(active_pending_orders),
            "revenue_today": f"{Decimal(str(revenue_today)):.2f}",
        },
        "sales": {
            "total_orders": int(total_orders),
            "gross_sales": f"{Decimal(str(gross_sales)):.2f}",
            "discounts": f"{Decimal(str(discounts)):.2f}",
            "tax_collected": f"{Decimal(str(tax_collected)):.2f}",
            "net_sales": f"{Decimal(str(net_sales)):.2f}",
            "average_order_value": f"{aov:.2f}",
            "daily_series": daily_series,
            "weekly_series": weekly_series,
            "monthly_series": monthly_series,
            "top_items": top_items,
            "category_sales": category_sales,
            "counter_sales": counter_sales,
            "payment_breakdown": payment_breakdown,
        },
        "payment_stats": {
            "total_attempts": total_attempts,
            "confirmed_count": confirmed_cnt,
            "failed_count": failed_cnt,
            "pending_count": pending_pay_cnt,
            "confirmed_amount": f"{confirmed_amt:.2f}",
            "failed_amount": f"{failed_amt:.2f}",
            "success_rate_percent": pay_success_rate,
        },
        "operations": {
            "completed_orders": int(completed_orders),
            "cancelled_orders": int(cancelled_orders),
            "pending_orders": int(pending_orders),
            "delayed_orders": int(delayed_orders),
            "completion_rate_percent": completion_rate,
            "avg_prep_minutes": round(sum(prep_durations) / len(prep_durations), 1) if prep_durations else 0.0,
            "avg_pickup_wait_minutes": round(sum(wait_durations) / len(wait_durations), 1) if wait_durations else 0.0,
            "peak_hours": peak_hours,
        },
        "inventory": {
            "tracked_ingredients": len(inv_rows),
            "low_stock_count": len(low_stock_rows),
            "low_stock_items": low_stock_items,
            "expiring_within_7_days": int(expiring_count),
            "total_wastage_loss": f"{Decimal(str(total_wastage)):.2f}",
            "wastage_breakdown": wastage_breakdown,
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
            "staff_breakdown": staff_breakdown,
        },
    }


def export_report_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["CollegeBites Analytics Report", report["range"]["start_date"], report["range"]["end_date"]])
    writer.writerow([])
    if report.get("today_summary"):
        writer.writerow(["TODAY SUMMARY"])
        for k, v in report["today_summary"].items():
            writer.writerow([k, v])
        writer.writerow([])
    writer.writerow(["SALES SUMMARY"])
    for k, v in report["sales"].items():
        if not isinstance(v, list):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["DAILY SERIES", "ORDERS", "REVENUE"])
    for ds in report["sales"].get("daily_series", []):
        writer.writerow([ds["date"], ds["orders"], ds["revenue"]])
    writer.writerow([])
    writer.writerow(["WEEKLY SERIES", "WEEK START", "ORDERS", "REVENUE"])
    for ws in report["sales"].get("weekly_series", []):
        writer.writerow([ws["week"], ws["week_start"], ws["orders"], ws["revenue"]])
    writer.writerow([])
    writer.writerow(["MONTHLY SERIES", "ORDERS", "REVENUE"])
    for ms in report["sales"].get("monthly_series", []):
        writer.writerow([ms["month"], ms["orders"], ms["revenue"]])
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
    if report.get("payment_stats"):
        writer.writerow(["PAYMENT STATISTICS"])
        for k, v in report["payment_stats"].items():
            writer.writerow([k, v])
        writer.writerow([])
    writer.writerow(["OPERATIONS SUMMARY"])
    for k, v in report["operations"].items():
        if not isinstance(v, list):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["PEAK HOURS", "ORDERS", "REVENUE"])
    for ph in report["operations"].get("peak_hours", []):
        writer.writerow([ph["hour"], ph["orders"], ph.get("revenue", 0)])
    writer.writerow([])
    writer.writerow(["INVENTORY SUMMARY"])
    for k, v in report["inventory"].items():
        if not isinstance(v, (list, dict)):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["LOW STOCK SHORTAGES", "CURRENT QTY", "REORDER LEVEL", "UNIT"])
    for ls in report["inventory"].get("low_stock_items", []):
        writer.writerow([ls["ingredient_name"], ls["current_quantity"], ls["reorder_level"], ls["unit"]])
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
        if not isinstance(v, list):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["STAFF ACTIVITY BREAKDOWN", "EMP CODE", "CHECKINS", "TASKS DONE", "WALK-IN ORDERS", "STATUS UPDATES"])
    for sb in report.get("staff_performance", {}).get("staff_breakdown", []):
        writer.writerow([sb["full_name"], sb["employee_code"], sb["checkins"], sb["tasks_completed"], sb["cashier_orders"], sb["status_updates"]])
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

    td = report.get("today_summary", {})
    if td:
        section("Today's Real-Time Snapshot", [
            ("Local Date", td.get("date", "")),
            ("Total Confirmed Orders Today", td.get("total_orders_today", 0)),
            ("Completed Today", td.get("completed_orders_today", 0)),
            ("Pending Active Queue", td.get("active_pending_orders", 0)),
            ("Revenue Today", f"Rs.{td.get('revenue_today', '0.00')}"),
        ])

    s = report["sales"]
    section("Sales Summary", [
        ("Total Confirmed Orders", s["total_orders"]),
        ("Gross Sales", f"Rs.{s['gross_sales']}"),
        ("Discounts", f"Rs.{s['discounts']}"),
        ("Tax Collected", f"Rs.{s['tax_collected']}"),
        ("Net Sales", f"Rs.{s['net_sales']}"),
        ("Average Order Value", f"Rs.{s['average_order_value']}"),
    ])
    ps = report.get("payment_stats", {})
    if ps:
        section("Payment Gateway & POS Statistics", [
            ("Total Payment Attempts", ps.get("total_attempts", 0)),
            ("Confirmed Payments", f"{ps.get('confirmed_count', 0)} (Rs.{ps.get('confirmed_amount', '0.00')})"),
            ("Failed Payments", f"{ps.get('failed_count', 0)} (Rs.{ps.get('failed_amount', '0.00')})"),
            ("Payment Success Rate", f"{ps.get('success_rate_percent', 0)}%"),
        ])
    op = report["operations"]
    section("Operations", [
        ("Completed Orders", op["completed_orders"]),
        ("Pending Orders (In Range)", op.get("pending_orders", 0)),
        ("Cancelled / Rejected Orders", op["cancelled_orders"]),
        ("Order Completion Rate", f"{op.get('completion_rate_percent', 0)}%"),
        ("Delayed Orders", op["delayed_orders"]),
        ("Average Prep Minutes", op["avg_prep_minutes"]),
        ("Average Pickup Wait Minutes", op.get("avg_pickup_wait_minutes", 0)),
    ])
    inv = report["inventory"]
    section("Inventory & Wastage", [
        ("Tracked Ingredients (Active)", inv["tracked_ingredients"]),
        ("Low Stock Alerts", inv["low_stock_count"]),
        ("Expiring Within 7 Days", inv["expiring_within_7_days"]),
        ("Wastage Loss", f"Rs.{inv['total_wastage_loss']}"),
        ("Purchases Received", f"Rs.{inv['total_purchases_received']}"),
    ])
    if inv.get("low_stock_items"):
        section(
            "Low Stock Shortage Items",
            [(it["ingredient_name"], f"{it['current_quantity']} / {it['reorder_level']} {it['unit']}") for it in inv["low_stock_items"][:10]],
        )
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
    if sp.get("staff_breakdown"):
        section(
            "Staff Activity Records",
            [
                (f"{sb['full_name']} ({sb['employee_code'] or 'Staff'})", f"Checkins: {sb['checkins']} | Tasks: {sb['tasks_completed']}/{sb['tasks_total']} | POS: {sb['cashier_orders']} | Updates: {sb['status_updates']}")
                for sb in sp["staff_breakdown"][:12]
            ],
        )
    if op.get("peak_hours"):
        section("Peak Ordering Hours", [(ph["hour"], f"{ph['orders']} orders (Rs.{ph.get('revenue', 0):.2f})") for ph in op["peak_hours"][:8]])
    if s.get("monthly_series"):
        section("Monthly Sales Trend", [(m["month"], f"{m['orders']} orders (Rs.{m['revenue']:.2f})") for m in s["monthly_series"][-6:]])
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
