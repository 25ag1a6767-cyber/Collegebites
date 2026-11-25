from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.time_utils import now_college, today_college
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PickupToken
from app.models.staff import StaffShift
from app.schemas.operations import POSWalkInOrderRequest, ShiftCloseRequest, ShiftOpenRequest, ShiftOut
from app.schemas.order import CheckoutRequest, OrderOut
from app.services.audit_service import record_audit_log
from app.services.order_service import checkout_order, serialize_orders_batch
from app.services.payment_service import collect_counter_payment
from app.schemas.payment import CounterPaymentCollectRequest


def create_pos_walkin_order(
    db: Session, payload: POSWalkInOrderRequest, cashier_user_id: UUID, ip_address: Optional[str] = None
) -> OrderOut:
    """Create a walk-in POS order using digital payment methods (UPI/Card POS only — no cash)."""
    if payload.coupon_code and payload.coupon_code.strip():
        raise HTTPException(status_code=400, detail="Coupons are disabled and not supported")
    if payload.payment_method == "cash":
        raise HTTPException(status_code=400, detail="Cash payments are disabled. Use UPI POS or Card POS.")
    co_req = CheckoutRequest(
        canteen_id=payload.canteen_id,
        counter_id=payload.counter_id,
        order_type="walk_in",
        order_channel="pos",
        payment_method=payload.payment_method,
        coupon_code=None,
        guest_name=payload.customer_name or "Walk-in Customer",
        guest_phone=payload.customer_phone or "0000000000",
        notes=payload.notes,
        use_cart=False,
        direct_items=payload.items,
        accepted_policy=True,
    )
    pending = checkout_order(
        db,
        co_req,
        user_id=None,
        cashier_user_id=cashier_user_id,
        ip_address=ip_address,
    )
    confirmed = collect_counter_payment(
        db,
        CounterPaymentCollectRequest(
            order_id=pending.id,
            payment_method=payload.payment_method,
            external_reference=f"POS-{pending.order_number}",
        ),
        cashier_user_id=cashier_user_id,
    )
    return confirmed


def list_pending_counter_orders(db: Session, canteen_id: Optional[UUID] = None) -> list[OrderOut]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(
            Order.status == "PAYMENT_PENDING",
            Order.payment_status == "PENDING",
        )
        .order_by(Order.created_at.desc())
        .limit(40)
    )
    if canteen_id:
        stmt = stmt.where(Order.canteen_id == canteen_id)
    orders = db.scalars(stmt).all()
    return serialize_orders_batch(db, list(orders))


def list_active_canteen_orders(db: Session, canteen_id: Optional[UUID] = None) -> list[OrderOut]:
    """List confirmed orders currently flowing through kitchen and pickup (PLACED/ACCEPTED/PREPARING/READY)."""
    stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(
            Order.payment_status == "CONFIRMED",
            Order.status.in_(("PLACED", "ACCEPTED", "PREPARING", "READY")),
        )
        .order_by(Order.created_at.desc())
        .limit(60)
    )
    if canteen_id:
        stmt = stmt.where(Order.canteen_id == canteen_id)
    orders = db.scalars(stmt).all()
    return serialize_orders_batch(db, list(orders))


def search_pos_orders(db: Session, query: str, canteen_id: Optional[UUID] = None) -> list[OrderOut]:
    q = query.strip()
    token_order_ids = list(
        db.scalars(select(PickupToken.order_id).where(PickupToken.token_code.ilike(f"%{q}%"))).all()
    )
    stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(
            or_(
                Order.order_number.ilike(f"%{q}%"),
                Order.guest_name.ilike(f"%{q}%"),
                Order.guest_phone.ilike(f"%{q}%"),
                Order.id.in_(token_order_ids) if token_order_ids else False,
            )
        )
        .order_by(Order.created_at.desc())
        .limit(30)
    )
    if canteen_id:
        stmt = stmt.where(Order.canteen_id == canteen_id)
    orders = db.scalars(stmt).all()
    return serialize_orders_batch(db, list(orders))


def _shift_sales_summary(db: Session, shift: StaffShift) -> dict:
    start_dt = shift.created_at
    end_dt = shift.closed_at or datetime.now(timezone.utc)
    rows = db.execute(
        select(Payment.method, func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0))
        .join(Order, Order.id == Payment.order_id)
        .where(
            Order.canteen_id == shift.canteen_id,
            Payment.recorded_by_user_id == shift.staff_user_id,
            Payment.status == "CONFIRMED",
            Payment.confirmed_at >= start_dt,
            Payment.confirmed_at <= end_dt,
        )
        .group_by(Payment.method)
    ).all()
    by_method = {method or "unknown": {"count": int(cnt), "amount": f"{Decimal(str(amt)):.2f}"} for method, cnt, amt in rows}
    cash_sales = Decimal(by_method.get("cash", {}).get("amount", "0.00"))
    total_collected = sum((Decimal(str(v["amount"])) for v in by_method.values()), Decimal("0.00"))
    return {
        "by_method": by_method,
        "cash_sales": f"{cash_sales:.2f}",
        "total_collected": f"{total_collected:.2f}",
        "expected_cash_in_drawer": f"{(shift.opening_cash_amount + cash_sales):.2f}",
    }


def open_cashier_shift(db: Session, payload: ShiftOpenRequest, cashier_user_id: UUID) -> ShiftOut:
    existing = db.scalar(
        select(StaffShift).where(StaffShift.staff_user_id == cashier_user_id, StaffShift.status == "open")
    )
    if existing:
        if existing.canteen_id != payload.canteen_id:
            raise HTTPException(
                status_code=409,
                detail="Close your existing open shift in the previous canteen before opening one here",
            )
        out = ShiftOut.model_validate(existing)
        out.shift_sales_summary = _shift_sales_summary(db, existing)
        return out
    now = now_college()
    shift = StaffShift(
        staff_user_id=cashier_user_id,
        canteen_id=payload.canteen_id,
        counter_id=payload.counter_id,
        shift_date=now.date(),
        start_time=now.time(),
        end_time=time(23, 59),
        shift_type="cashier",
        status="open",
        opening_cash_amount=payload.opening_cash_amount,
    )
    db.add(shift)
    record_audit_log(
        db,
        action="cashier.shift_opened",
        entity_type="staff_shift",
        entity_id=str(cashier_user_id),
        actor_user_id=cashier_user_id,
        details={"opening_cash": str(payload.opening_cash_amount)},
    )
    db.commit()
    db.refresh(shift)
    out = ShiftOut.model_validate(shift)
    out.shift_sales_summary = _shift_sales_summary(db, shift)
    return out


def get_current_cashier_shift(db: Session, cashier_user_id: UUID) -> Optional[ShiftOut]:
    shift = db.scalar(
        select(StaffShift).where(StaffShift.staff_user_id == cashier_user_id, StaffShift.status == "open")
    )
    if not shift:
        return None
    out = ShiftOut.model_validate(shift)
    out.shift_sales_summary = _shift_sales_summary(db, shift)
    return out


def close_cashier_shift(db: Session, payload: ShiftCloseRequest, cashier_user_id: UUID) -> ShiftOut:
    shift = db.scalar(
        select(StaffShift).where(StaffShift.staff_user_id == cashier_user_id, StaffShift.status == "open").with_for_update()
    )
    if not shift:
        raise HTTPException(status_code=404, detail="No open cashier shift found")
    summary = _shift_sales_summary(db, shift)
    expected_cash = Decimal(summary["expected_cash_in_drawer"])
    shift.status = "closed"
    shift.closing_cash_amount = payload.closing_cash_amount
    shift.expected_cash_amount = expected_cash
    shift.closed_at = datetime.now(timezone.utc)
    shift.closing_notes = payload.closing_notes
    record_audit_log(
        db,
        action="cashier.shift_closed",
        entity_type="staff_shift",
        entity_id=str(shift.id),
        actor_user_id=cashier_user_id,
        details={"expected_cash": str(expected_cash), "closing_cash": str(payload.closing_cash_amount)},
    )
    db.commit()
    db.refresh(shift)
    out = ShiftOut.model_validate(shift)
    out.shift_sales_summary = summary
    return out
