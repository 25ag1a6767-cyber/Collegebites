import base64
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.security import mask_mobile, sha256_hex
from app.integrations.printers.escpos import build_escpos_receipt_bytes, send_escpos_network_tcp
from app.models.auth import User
from app.models.college import Canteen, Counter
from app.models.order import Order, OrderItem
from app.models.payment import (
    OrderQRCode,
    Payment,
    PickupToken,
    Receipt,
    ReceiptPrintHistory,
    ReceiptPrintJob,
)
from app.schemas.payment import PrintReceiptRequest
from app.services.audit_service import record_audit_log
from app.services.college_service import get_or_create_college_settings
from app.services.qr_location_service import render_qr_base64, render_qr_png_bytes

PICKUP_INSTRUCTIONS = [
    "Show this token at the pickup counter.",
    "Keep the QR code available.",
    "Collect food only after the order is marked READY.",
    "Each order can be handed over only once.",
]


def create_receipt_for_order(db: Session, order: Order, pickup_token: PickupToken, qr_row: OrderQRCode, payment: Payment) -> Receipt:
    """Create a complete immutable historical receipt snapshot after payment confirmation."""
    existing = db.scalar(select(Receipt).where(Receipt.order_id == order.id))
    if existing:
        return existing

    college = get_or_create_college_settings(db)
    canteen = db.get(Canteen, order.canteen_id)
    counter = db.get(Counter, order.counter_id)
    customer = db.get(User, order.customer_id) if order.customer_id else None

    customer_name = order.guest_name if order.is_guest else (customer.full_name if customer else "Customer")
    raw_phone = order.guest_phone if order.is_guest else (customer.phone if customer else None)
    masked_phone = mask_mobile(raw_phone) if raw_phone else None

    loaded_items = db.scalars(
        select(OrderItem).options(selectinload(OrderItem.customizations)).where(OrderItem.order_id == order.id)
    ).all()

    items_snapshot: list[dict[str, Any]] = []
    for oi in loaded_items:
        items_snapshot.append({
            "item_name": oi.item_name,
            "variant_name": oi.variant_name,
            "quantity": oi.quantity,
            "unit_price": f"{oi.unit_price:.2f}",
            "addon_total_per_unit": f"{oi.addon_total_per_unit:.2f}",
            "line_subtotal": f"{oi.line_subtotal:.2f}",
            "tax_amount": f"{oi.tax_amount:.2f}",
            "line_total": f"{oi.line_total:.2f}",
            "special_instructions": oi.special_instructions,
            "customizations": [
                {
                    "customization_type": c.customization_type,
                    "option_name": c.option_name,
                    "option_value": c.option_value,
                    "quantity": c.quantity,
                    "unit_price": f"{c.unit_price:.2f}",
                    "total_price": f"{c.total_price:.2f}",
                }
                for c in oi.customizations
            ],
        })

    confirmed_ts = payment.confirmed_at or datetime.now(timezone.utc)
    est_pickup_ts = order.estimated_pickup_at or confirmed_ts
    receipt_number = f"REC-{order.order_number[3:]}" if order.order_number.startswith("CB-") else f"REC-{order.order_number}"

    snapshot: dict[str, Any] = {
        "brand": "COLLEGEBITES",
        "college_name": college.college_name,
        "college_short_code": college.college_short_code,
        "college_logo_url": college.logo_url,
        "college_address": college.address,
        "college_phone": college.contact_phone,
        "college_email": college.contact_email,
        "canteen_name": canteen.name if canteen else "Main Canteen",
        "canteen_location": canteen.location if canteen else "",
        "canteen_contact": canteen.contact_phone if canteen else None,
        "counter_name": counter.name if counter else "Counter 1",
        "receipt_number": receipt_number,
        "order_number": order.order_number,
        "pickup_token": pickup_token.token_code,
        "qr_verification_path": qr_row.verification_path,
        "qr_payload": qr_row.qr_payload_encoded,
        "order_date": confirmed_ts.strftime("%d-%m-%Y"),
        "order_time": confirmed_ts.strftime("%I:%M %p"),
        "estimated_pickup_time": est_pickup_ts.strftime("%I:%M %p"),
        "payment_reference": payment.payment_reference or payment.provider_payment_id or f"PAY-{order.order_number}",
        "payment_method": payment.method or order.payment_method,
        "payment_status": "PAID",
        "order_type": order.order_type,
        "order_status": "CONFIRMED",
        "customer_name": customer_name or "Guest",
        "customer_type_label": "Guest" if order.is_guest else "Customer",
        "customer_mobile_masked": masked_phone,
        "items": items_snapshot,
        "subtotal_amount": f"{order.subtotal_amount:.2f}",
        "discount_amount": f"{order.discount_amount:.2f}",
        "tax_amount": f"{order.tax_amount:.2f}",
        "total_paid": f"{order.total_amount:.2f}",
        "currency_symbol": college.currency_symbol or "₹",
        "pickup_instructions": PICKUP_INSTRUCTIONS,
    }

    receipt = Receipt(
        order_id=order.id,
        receipt_number=receipt_number,
        pickup_token_code=pickup_token.token_code,
        reprint_count=0,
        receipt_snapshot=snapshot,
    )
    db.add(receipt)
    db.flush()
    return receipt


def _resolve_order_and_receipt(
    db: Session,
    order_id_or_number: str,
    *,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    guest_access_token: Optional[str] = None,
) -> tuple[Order, Receipt]:
    try:
        oid = UUID(order_id_or_number)
        order = db.get(Order, oid)
    except ValueError:
        order = db.scalar(select(Order).where(Order.order_number == order_id_or_number))

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if not is_staff:
        if order.is_guest:
            if not guest_access_token or order.guest_access_token_hash != sha256_hex(guest_access_token):
                raise HTTPException(status_code=403, detail="Valid guest access token required")
        elif order.customer_id != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to access this receipt")

    receipt = db.scalar(select(Receipt).where(Receipt.order_id == order.id))
    if not receipt:
        raise HTTPException(status_code=409, detail="Receipt is only available after payment confirmation")
    return order, receipt


def get_receipt_payload(
    db: Session,
    order_id_or_number: str,
    *,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    guest_access_token: Optional[str] = None,
) -> dict[str, Any]:
    order, receipt = _resolve_order_and_receipt(
        db, order_id_or_number, user_id=user_id, is_staff=is_staff, guest_access_token=guest_access_token
    )
    snap = dict(receipt.receipt_snapshot)
    snap["order_status"] = order.status
    snap["receipt_id"] = str(receipt.id)
    snap["reprint_count"] = receipt.reprint_count
    snap["is_reprint"] = receipt.reprint_count > 0
    snap["reprint_label"] = f"REPRINT #{receipt.reprint_count}" if receipt.reprint_count > 0 else None
    snap["qr_image_base64"] = render_qr_base64(snap["qr_payload"], box_size=8)
    return snap


def generate_receipt_pdf_bytes(
    db: Session,
    order_id_or_number: str,
    *,
    paper_format: str = "a4",
    is_reprint_view: bool = False,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    guest_access_token: Optional[str] = None,
) -> tuple[bytes, str]:
    snap = get_receipt_payload(
        db, order_id_or_number, user_id=user_id, is_staff=is_staff, guest_access_token=guest_access_token
    )
    show_reprint = is_reprint_view or snap.get("reprint_count", 0) > 0

    buf = io.BytesIO()
    if paper_format == "80mm":
        page_w = 80 * mm
        page_h = max(210 * mm, (145 + len(snap.get("items", [])) * 18) * mm)
        c = canvas.Canvas(buf, pagesize=(page_w, page_h))
        margin = 5 * mm
    else:
        page_w, page_h = A4
        c = canvas.Canvas(buf, pagesize=A4)
        margin = 18 * mm

    y = page_h - margin
    center_x = page_w / 2.0

    def draw_center(text: str, font: str = "Helvetica-Bold", size: int = 11, dy: float = 5 * mm, color=colors.black):
        nonlocal y
        c.setFillColor(color)
        c.setFont(font, size)
        c.drawCentredString(center_x, y, text)
        y -= dy

    def draw_lr(left: str, right: str, font: str = "Helvetica", size: int = 9, dy: float = 4.5 * mm):
        nonlocal y
        c.setFillColor(colors.black)
        c.setFont(font, size)
        c.drawString(margin, y, left)
        c.drawRightString(page_w - margin, y, right)
        y -= dy

    def draw_sep():
        nonlocal y
        c.setStrokeColor(colors.grey)
        c.setLineWidth(0.5)
        c.line(margin, y, page_w - margin, y)
        y -= 4 * mm

    draw_center("COLLEGEBITES", "Helvetica-Bold", 14 if paper_format == "a4" else 11, 5.5 * mm)
    draw_center(snap["college_name"].upper(), "Helvetica-Bold", 10 if paper_format == "a4" else 8.5, 4.5 * mm)
    draw_center(f"{snap['canteen_name']} ({snap.get('canteen_location', '')})", "Helvetica", 8.5, 4.5 * mm)
    if show_reprint:
        draw_center(f"*** REPRINT #{max(1, snap.get('reprint_count', 1))} ***", "Helvetica-Bold", 10, 5 * mm, colors.red)
    draw_sep()

    draw_lr(f"ORDER NO: {snap['order_number']}", f"RECEIPT: {snap['receipt_number']}", "Helvetica-Bold", 8.5)
    draw_center("PICKUP TOKEN", "Helvetica-Bold", 9, 6 * mm)
    draw_center(snap["pickup_token"], "Helvetica-Bold", 24 if paper_format == "a4" else 18, 9 * mm)

    # Crisp QR code image
    qr_png = render_qr_png_bytes(snap["qr_payload"], box_size=8)
    qr_size = 34 * mm if paper_format == "a4" else 28 * mm
    c.drawImage(ImageReader(io.BytesIO(qr_png)), center_x - qr_size / 2, y - qr_size + 2 * mm, width=qr_size, height=qr_size)
    y -= qr_size + 3 * mm
    draw_sep()

    draw_lr(f"CUSTOMER: {snap['customer_name']} ({snap['customer_type_label']})", f"MOBILE: {snap.get('customer_mobile_masked') or 'N/A'}", "Helvetica", 8.5)
    draw_lr(f"DATE: {snap['order_date']}  TIME: {snap['order_time']}", f"EST PICKUP: {snap['estimated_pickup_time']}", "Helvetica", 8.5)
    draw_lr(f"COUNTER: {snap['counter_name']}", f"TYPE: {snap['order_type'].upper()}", "Helvetica-Bold", 8.5)
    draw_sep()

    draw_lr("ORDERED ITEMS", "QTY / AMOUNT", "Helvetica-Bold", 9)
    for idx, item in enumerate(snap.get("items", []), start=1):
        var_label = f" ({item['variant_name']})" if item.get("variant_name") else ""
        draw_lr(
            f"{idx}. {item['item_name']}{var_label}",
            f"{item['quantity']} x Rs.{Decimal(item['unit_price']):.2f} = Rs.{Decimal(item['line_subtotal']):.2f}",
            "Helvetica-Bold",
            8.5,
            4.2 * mm,
        )
        for cust in item.get("customizations", []):
            price_txt = f"Rs.{Decimal(cust['total_price']):.2f}" if Decimal(cust["total_price"]) > 0 else "Included"
            draw_lr(f"    {cust['option_name']}: {cust['option_value']}", price_txt, "Helvetica", 8, 3.8 * mm)
        if item.get("special_instructions"):
            draw_lr(f"    Note: {item['special_instructions']}", "", "Helvetica-Oblique", 7.8, 3.8 * mm)

    draw_sep()
    draw_lr("SUBTOTAL", f"Rs.{Decimal(snap['subtotal_amount']):.2f}", "Helvetica", 9)
    draw_lr("DISCOUNT", f"-Rs.{Decimal(snap['discount_amount']):.2f}", "Helvetica", 9)
    draw_lr("TAX", f"Rs.{Decimal(snap['tax_amount']):.2f}", "Helvetica", 9)
    draw_lr("TOTAL PAID", f"Rs.{Decimal(snap['total_paid']):.2f}", "Helvetica-Bold", 11, 5.5 * mm)
    draw_lr(f"PAYMENT STATUS: {snap['payment_status']}", f"METHOD: {snap['payment_method'].upper()}", "Helvetica-Bold", 8.5)
    draw_lr(f"PAYMENT REF: {snap['payment_reference']}", f"STATUS: {snap['order_status']}", "Helvetica", 8)
    draw_sep()

    for line in snap.get("pickup_instructions", []):
        draw_center(line, "Helvetica", 7.5, 3.6 * mm)
    draw_center("THANK YOU FOR ORDERING WITH COLLEGEBITES!", "Helvetica-Bold", 8.5, 4 * mm)

    c.showPage()
    c.save()
    return buf.getvalue(), snap["order_number"]


def get_escpos_payload(
    db: Session,
    order_id_or_number: str,
    *,
    paper_width: str = "80mm",
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    guest_access_token: Optional[str] = None,
) -> dict[str, Any]:
    order, receipt = _resolve_order_and_receipt(
        db, order_id_or_number, user_id=user_id, is_staff=is_staff, guest_access_token=guest_access_token
    )
    raw_bytes = build_escpos_receipt_bytes(
        receipt.receipt_snapshot,
        paper_width=paper_width,
        is_reprint=receipt.reprint_count > 0,
        reprint_number=receipt.reprint_count,
    )
    return {
        "order_number": order.order_number,
        "pickup_token": receipt.pickup_token_code,
        "paper_width": paper_width,
        "escpos_base64": base64.b64encode(raw_bytes).decode("ascii"),
        "byte_length": len(raw_bytes),
    }


def trigger_print_job(
    db: Session,
    order_id_or_number: str,
    payload: PrintReceiptRequest,
    *,
    actor_user_id: Optional[UUID],
    actor_label: str,
    is_staff: bool = False,
    guest_access_token: Optional[str] = None,
) -> ReceiptPrintJob:
    order, receipt = _resolve_order_and_receipt(
        db, order_id_or_number, user_id=actor_user_id, is_staff=is_staff, guest_access_token=guest_access_token
    )

    # First print is original if no prior successful print exists, otherwise automatically mark reprint
    prior_prints = db.scalar(select(func.count(ReceiptPrintHistory.id)).where(ReceiptPrintHistory.receipt_id == receipt.id)) or 0
    is_reprint = payload.is_reprint or prior_prints > 0
    if is_reprint:
        receipt.reprint_count += 1

    job = ReceiptPrintJob(
        receipt_id=receipt.id,
        order_id=order.id,
        printer_target=payload.printer_target,
        printer_name=payload.printer_name,
        paper_width=payload.paper_width,
        is_reprint=is_reprint,
        status="queued",
        requested_by_user_id=actor_user_id,
    )
    db.add(job)
    db.flush()

    now = datetime.now(timezone.utc)
    if payload.printer_target == "network_escpos":
        host = payload.network_host or settings.DEFAULT_PRINTER_IP
        port = payload.network_port or settings.DEFAULT_PRINTER_PORT
        if not settings.NETWORK_PRINTER_ENABLED and not payload.network_host:
            job.status = "failed"
            job.error_message = "Network thermal printer is not configured or disabled"
        else:
            esc_bytes = build_escpos_receipt_bytes(
                receipt.receipt_snapshot,
                paper_width="80mm" if payload.paper_width == "a4" else payload.paper_width,
                is_reprint=is_reprint,
                reprint_number=receipt.reprint_count,
            )
            try:
                send_escpos_network_tcp(host, port, esc_bytes)
                job.status = "completed"
            except Exception as exc:
                job.status = "failed"
                job.error_message = f"Thermal printer unreachable at {host}:{port} ({exc})"
    else:
        job.status = "completed"

    db.add(
        ReceiptPrintHistory(
            receipt_id=receipt.id,
            print_job_id=job.id,
            printed_by_user_id=actor_user_id,
            printed_by_label=actor_label,
            printer_target=payload.printer_target,
            is_reprint=is_reprint,
            reprint_number=receipt.reprint_count if is_reprint else 0,
            status=job.status,
            printed_at=now,
        )
    )
    record_audit_log(
        db,
        action="receipt.reprinted" if is_reprint else "receipt.printed",
        entity_type="receipt",
        entity_id=receipt.receipt_number,
        actor_user_id=actor_user_id,
        details={
            "order_number": order.order_number,
            "pickup_token": receipt.pickup_token_code,
            "printer_target": payload.printer_target,
            "reprint_count": receipt.reprint_count,
            "status": job.status,
        },
    )
    db.commit()
    db.refresh(job)
    return job


def retry_print_job(db: Session, job_id: UUID, actor_user_id: UUID, actor_label: str) -> ReceiptPrintJob:
    job = db.get(ReceiptPrintJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Print job not found")
    receipt = db.get(Receipt, job.receipt_id)
    job.retry_count += 1

    if job.printer_target == "network_escpos":
        host = settings.DEFAULT_PRINTER_IP
        port = settings.DEFAULT_PRINTER_PORT
        try:
            esc_bytes = build_escpos_receipt_bytes(
                receipt.receipt_snapshot,
                paper_width="80mm" if job.paper_width == "a4" else job.paper_width,
                is_reprint=job.is_reprint,
                reprint_number=receipt.reprint_count,
            )
            send_escpos_network_tcp(host, port, esc_bytes)
            job.status = "completed"
            job.error_message = None
        except Exception as exc:
            job.status = "failed"
            job.error_message = f"Retry #{job.retry_count} failed: {exc}"
    else:
        job.status = "completed"
        job.error_message = None

    db.add(
        ReceiptPrintHistory(
            receipt_id=receipt.id,
            print_job_id=job.id,
            printed_by_user_id=actor_user_id,
            printed_by_label=actor_label,
            printer_target=job.printer_target,
            is_reprint=job.is_reprint,
            reprint_number=receipt.reprint_count,
            status=job.status,
            printed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    db.refresh(job)
    return job
