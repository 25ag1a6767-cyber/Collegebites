import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.time_utils import today_college
from app.models.auth import User
from app.models.college import Canteen, CollegeSettings
from app.models.event import CollegeEvent, EventBulkOrder, EventBulkOrderItem
from app.models.meal_plan import MealPlan, StudentMealSubscription
from app.models.order import Order, OrderItem
from app.models.payment import Invoice, Payment


def _quantize(val: Decimal) -> Decimal:
    return Decimal(str(val)).quantize(Decimal("0.01"))


def _generate_invoice_number(db: Session) -> str:
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(918273701)"))
    today_str = today_college().strftime("%Y%m%d")
    prefix = f"INV-{today_str}-"
    max_num = db.scalar(select(func.max(Invoice.invoice_number)).where(Invoice.invoice_number.like(f"{prefix}%")))
    if max_num:
        try:
            seq = int(max_num.rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    while True:
        cand = f"{prefix}{seq:06d}"
        if not db.scalar(select(Invoice.id).where(Invoice.invoice_number == cand)):
            return cand
        seq += 1


def _build_tax_breakdown(tax_amount: Decimal, tax_rate_label: str = "GST") -> dict:
    tot_tax = _quantize(tax_amount)
    cgst = _quantize(tot_tax / Decimal("2.00"))
    sgst = _quantize(tot_tax - cgst)
    return {
        "tax_label": tax_rate_label,
        "cgst_amount": str(cgst),
        "sgst_amount": str(sgst),
        "total_tax_amount": str(tot_tax),
    }


def serialize_invoice(inv: Invoice, *, canteen_name: Optional[str] = None) -> dict:
    return {
        "id": str(inv.id),
        "invoice_number": inv.invoice_number,
        "invoice_type": inv.invoice_type,
        "order_id": str(inv.order_id) if inv.order_id else None,
        "bulk_order_id": str(inv.bulk_order_id) if inv.bulk_order_id else None,
        "subscription_id": str(inv.subscription_id) if inv.subscription_id else None,
        "canteen_id": str(inv.canteen_id) if inv.canteen_id else None,
        "canteen_name": canteen_name,
        "customer_user_id": str(inv.customer_user_id) if inv.customer_user_id else None,
        "reference_number": inv.reference_number,
        "customer_name": inv.customer_name,
        "customer_contact": inv.customer_contact,
        "subtotal_amount": str(_quantize(inv.subtotal_amount)),
        "discount_amount": str(_quantize(inv.discount_amount)),
        "tax_amount": str(_quantize(inv.tax_amount)),
        "total_amount": str(_quantize(inv.total_amount)),
        "tax_breakdown": inv.tax_breakdown_json or _build_tax_breakdown(inv.tax_amount),
        "items": list(inv.items_json or []),
        "payment_method": inv.payment_method,
        "payment_reference": inv.payment_reference,
        "payment_status": inv.payment_status,
        "issued_at": inv.issued_at.isoformat() if inv.issued_at else None,
    }


def ensure_invoice_for_order(db: Session, order: Order, *, payment: Optional[Payment] = None) -> Invoice:
    if order.payment_status != "CONFIRMED":
        raise HTTPException(status_code=400, detail="Invoices can only be generated for verified paid orders")
    existing = db.scalar(select(Invoice).where(Invoice.order_id == order.id))
    if existing:
        return existing

    user = db.get(User, order.customer_id) if order.customer_id else None
    cust_name = (user.full_name or user.email) if user else (order.guest_name or "Walk-in Customer")
    cust_contact = (user.email or user.phone) if user else (order.guest_email or order.guest_phone or None)
    pay = payment or db.scalar(
        select(Payment).where(Payment.order_id == order.id, Payment.status == "CONFIRMED")
    )
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    items_payload = [
        {
            "item_name": it.item_name + (f" ({it.variant_name})" if it.variant_name else ""),
            "quantity": it.quantity,
            "unit_price": str(_quantize(it.unit_price + it.addon_total_per_unit)),
            "line_subtotal": str(_quantize(it.line_subtotal)),
            "tax_amount": str(_quantize(it.tax_amount)),
            "line_total": str(_quantize(it.line_total)),
        }
        for it in items
    ]
    inv = Invoice(
        invoice_number=_generate_invoice_number(db),
        invoice_type="order",
        order_id=order.id,
        canteen_id=order.canteen_id,
        customer_user_id=order.customer_id,
        reference_number=order.order_number,
        customer_name=cust_name,
        customer_contact=cust_contact,
        subtotal_amount=_quantize(order.subtotal_amount),
        discount_amount=_quantize(order.discount_amount),
        tax_amount=_quantize(order.tax_amount),
        total_amount=_quantize(order.total_amount),
        tax_breakdown_json=_build_tax_breakdown(order.tax_amount),
        items_json=items_payload,
        payment_method=order.payment_method,
        payment_reference=(pay.payment_reference or pay.provider_payment_id) if pay else order.order_number,
        payment_status="CONFIRMED",
        issued_at=order.confirmed_at or datetime.now(timezone.utc),
    )
    db.add(inv)
    db.flush()
    return inv


def ensure_invoice_for_bulk_order(db: Session, bo: EventBulkOrder) -> Invoice:
    if bo.payment_status != "CONFIRMED":
        raise HTTPException(status_code=400, detail="Invoices can only be generated for verified paid event bulk orders")
    existing = db.scalar(select(Invoice).where(Invoice.bulk_order_id == bo.id))
    if existing:
        return existing

    ev = db.get(CollegeEvent, bo.event_id)
    user = db.get(User, bo.organizer_user_id)
    cust_name = (ev.organizer_name if ev else None) or ((user.full_name or user.email) if user else "Event Organizer")
    cust_contact = (ev.contact_email or ev.contact_phone) if ev else (user.email if user else None)
    items = db.scalars(select(EventBulkOrderItem).where(EventBulkOrderItem.bulk_order_id == bo.id)).all()
    items_payload = [
        {
            "item_name": f"[Event: {ev.name if ev else 'Bulk'}] {it.item_name}",
            "quantity": it.quantity,
            "unit_price": str(_quantize(it.unit_price)),
            "line_subtotal": str(_quantize(it.unit_price * Decimal(it.quantity))),
            "tax_amount": str(_quantize(it.tax_amount)),
            "line_total": str(_quantize(it.line_total)),
        }
        for it in items
    ]
    inv = Invoice(
        invoice_number=_generate_invoice_number(db),
        invoice_type="event_bulk",
        bulk_order_id=bo.id,
        canteen_id=bo.canteen_id,
        customer_user_id=bo.organizer_user_id,
        reference_number=bo.bulk_order_number,
        customer_name=cust_name,
        customer_contact=cust_contact,
        subtotal_amount=_quantize(bo.subtotal_amount),
        discount_amount=Decimal("0.00"),
        tax_amount=_quantize(bo.tax_amount),
        total_amount=_quantize(bo.total_amount),
        tax_breakdown_json=_build_tax_breakdown(bo.tax_amount),
        items_json=items_payload,
        payment_method=bo.payment_method,
        payment_reference=bo.payment_reference or bo.provider_payment_id or bo.bulk_order_number,
        payment_status="CONFIRMED",
        issued_at=datetime.now(timezone.utc),
    )
    db.add(inv)
    db.flush()
    return inv


def ensure_invoice_for_meal_subscription(
    db: Session,
    sub: StudentMealSubscription,
    *,
    plan: Optional[MealPlan] = None,
) -> Invoice:
    if sub.payment_status != "CONFIRMED":
        raise HTTPException(status_code=400, detail="Invoices can only be generated for verified paid meal subscriptions")
    existing = db.scalar(select(Invoice).where(Invoice.subscription_id == sub.id))
    if existing:
        return existing

    plan_obj = plan or db.get(MealPlan, sub.meal_plan_id)
    user = db.get(User, sub.student_user_id)
    cust_name = (user.full_name or user.email) if user else "Student"
    cust_contact = (user.email or user.phone) if user else None
    items_payload = [
        {
            "item_name": f"Student Meal Plan: {plan_obj.name if plan_obj else sub.subscription_number} ({sub.total_meals} Meals)",
            "quantity": 1,
            "unit_price": str(_quantize(sub.subtotal_amount)),
            "line_subtotal": str(_quantize(sub.subtotal_amount)),
            "tax_amount": str(_quantize(sub.tax_amount)),
            "line_total": str(_quantize(sub.total_amount)),
        }
    ]
    inv = Invoice(
        invoice_number=_generate_invoice_number(db),
        invoice_type="meal_plan",
        subscription_id=sub.id,
        canteen_id=sub.canteen_id,
        customer_user_id=sub.student_user_id,
        reference_number=sub.subscription_number,
        customer_name=cust_name,
        customer_contact=cust_contact,
        subtotal_amount=_quantize(sub.subtotal_amount),
        discount_amount=Decimal("0.00"),
        tax_amount=_quantize(sub.tax_amount),
        total_amount=_quantize(sub.total_amount),
        tax_breakdown_json=_build_tax_breakdown(sub.tax_amount),
        items_json=items_payload,
        payment_method=sub.payment_method,
        payment_reference=sub.payment_reference or sub.provider_payment_id or sub.subscription_number,
        payment_status="CONFIRMED",
        issued_at=sub.confirmed_at or datetime.now(timezone.utc),
    )
    db.add(inv)
    db.flush()
    return inv


def list_invoices(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    customer_user_id: Optional[UUID] = None,
    invoice_type: Optional[str] = None,
) -> list[dict]:
    stmt = select(Invoice)
    if canteen_id:
        stmt = stmt.where((Invoice.canteen_id == canteen_id) | (Invoice.canteen_id.is_(None)))
    if customer_user_id:
        stmt = stmt.where(Invoice.customer_user_id == customer_user_id)
    if invoice_type and invoice_type != "all":
        stmt = stmt.where(Invoice.invoice_type == invoice_type)
    rows = list(db.scalars(stmt.order_by(Invoice.issued_at.desc()).limit(250)).all())
    cids = {r.canteen_id for r in rows if r.canteen_id}
    c_map = {c.id: c.name for c in db.scalars(select(Canteen).where(Canteen.id.in_(cids))).all()} if cids else {}
    return [serialize_invoice(r, canteen_name=c_map.get(r.canteen_id)) for r in rows]


def resolve_invoice(db: Session, id_or_number: str) -> Invoice:
    inv: Optional[Invoice] = None
    try:
        uid = UUID(id_or_number)
        inv = db.get(Invoice, uid) or db.scalar(select(Invoice).where(Invoice.order_id == uid))
    except ValueError:
        pass
    if not inv:
        inv = db.scalar(
            select(Invoice).where(
                (Invoice.invoice_number == id_or_number.strip())
                | (Invoice.reference_number == id_or_number.strip())
            )
        )
    if not inv:
        order = db.scalar(select(Order).where(Order.order_number == id_or_number.strip()))
        if order and order.payment_status == "CONFIRMED":
            inv = ensure_invoice_for_order(db, order)
            db.commit()
    if not inv:
        raise HTTPException(status_code=404, detail="Tax invoice not found")
    return inv


def render_invoice_pdf(db: Session, inv: Invoice) -> bytes:
    canteen = db.get(Canteen, inv.canteen_id) if inv.canteen_id else None
    college = db.scalar(select(CollegeSettings))
    data = serialize_invoice(inv, canteen_name=canteen.name if canteen else "CollegeBites Campus Dining")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _w, h = A4
    y = h - 45

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, f"{college.college_name if college else 'CollegeBites'} — TAX INVOICE")
    y -= 18
    c.setFont("Helvetica", 9)
    c.drawString(40, y, f"Canteen: {data['canteen_name'] or 'Campus Dining'} | Invoice #: {data['invoice_number']} | Type: {data['invoice_type'].upper()}")
    y -= 14
    c.drawString(40, y, f"Reference #: {data['reference_number']} | Issued At: {(data['issued_at'] or '')[:19]} UTC")
    y -= 14
    c.drawString(40, y, f"Billed To: {data['customer_name']} ({data['customer_contact'] or 'Verified Customer'})")
    y -= 14
    c.drawString(40, y, f"Payment Status: {data['payment_status']} | Method: {data['payment_method'].upper()} | Ref: {data['payment_reference'] or '-'}")
    y -= 22

    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Item Description")
    c.drawString(290, y, "Qty")
    c.drawString(340, y, "Unit Price")
    c.drawString(415, y, "Tax")
    c.drawString(485, y, "Line Total")
    y -= 14
    c.setFont("Helvetica", 9)
    for it in data["items"]:
        if y < 90:
            c.showPage()
            y = h - 45
            c.setFont("Helvetica", 9)
        c.drawString(40, y, str(it.get("item_name", "Item"))[:46])
        c.drawString(290, y, str(it.get("quantity", 1)))
        c.drawString(340, y, f"Rs.{it.get('unit_price', '0.00')}")
        c.drawString(415, y, f"Rs.{it.get('tax_amount', '0.00')}")
        c.drawString(485, y, f"Rs.{it.get('line_total', '0.00')}")
        y -= 14

    y -= 14
    tb = data["tax_breakdown"]
    c.setFont("Helvetica-Bold", 10)
    c.drawString(360, y, f"Subtotal: Rs.{data['subtotal_amount']}")
    y -= 14
    c.drawString(360, y, f"Discount: -Rs.{data['discount_amount']}")
    y -= 14
    c.setFont("Helvetica", 9)
    c.drawString(360, y, f"CGST: Rs.{tb.get('cgst_amount', '0.00')} | SGST: Rs.{tb.get('sgst_amount', '0.00')}")
    y -= 14
    c.setFont("Helvetica-Bold", 11)
    c.drawString(360, y, f"Total Tax: Rs.{data['tax_amount']}")
    y -= 16
    c.drawString(360, y, f"Grand Total Paid: Rs.{data['total_amount']}")

    c.showPage()
    c.save()
    return buf.getvalue()
