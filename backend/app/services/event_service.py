import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.razorpay_client import razorpay_gateway
from app.integrations.stripe_client import stripe_gateway
from app.models.auth import User
from app.models.college import Canteen, Counter, Kitchen
from app.models.event import CollegeEvent, EventBulkOrder, EventBulkOrderItem
from app.models.menu import FoodItem
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.payment import Payment
from app.services.audit_service import record_audit_log
from app.services.order_service import _generate_order_number
from app.services.receipt_service import create_receipt_for_order
from app.services.token_service import generate_token_and_qr_for_confirmed_order
from app.websockets import emit_order_event_sync


def _quantize(val: Decimal) -> Decimal:
    return Decimal(str(val)).quantize(Decimal("0.01"))


def _serialize_event(
    ev: CollegeEvent,
    *,
    canteen_name: Optional[str] = None,
    food_map: Optional[dict[str, dict]] = None,
    bulk_orders_count: int = 0,
) -> dict:
    fids = [str(x) for x in (ev.eligible_food_item_ids or [])]
    now = datetime.now(timezone.utc)
    deadline_passed = bool(ev.ordering_deadline and ev.ordering_deadline <= now)
    return {
        "id": str(ev.id),
        "event_code": ev.event_code,
        "canteen_id": str(ev.canteen_id),
        "canteen_name": canteen_name,
        "name": ev.name,
        "department": ev.department,
        "organizer_user_id": str(ev.organizer_user_id) if ev.organizer_user_id else None,
        "organizer_name": ev.organizer_name,
        "contact_phone": ev.contact_phone,
        "contact_email": ev.contact_email,
        "event_date": ev.event_date.isoformat() if ev.event_date else None,
        "location": ev.location,
        "description": ev.description,
        "ordering_deadline": ev.ordering_deadline.isoformat() if ev.ordering_deadline else None,
        "deadline_passed": deadline_passed,
        "eligible_food_item_ids": fids,
        "eligible_food_items": [food_map[fid] for fid in fids if food_map and fid in food_map],
        "min_order_quantity": ev.min_order_quantity,
        "max_order_quantity": ev.max_order_quantity,
        "is_active": ev.is_active,
        "bulk_orders_count": bulk_orders_count,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }


def list_events(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    include_inactive: bool = False,
) -> list[dict]:
    stmt = select(CollegeEvent)
    if canteen_id:
        stmt = stmt.where(CollegeEvent.canteen_id == canteen_id)
    if not include_inactive:
        stmt = stmt.where(CollegeEvent.is_active.is_(True))
    events = list(db.scalars(stmt.order_by(CollegeEvent.event_date.desc(), CollegeEvent.created_at.desc())).all())
    if not events:
        return []
    cids = {e.canteen_id for e in events}
    canteen_map = {c.id: c.name for c in db.scalars(select(Canteen).where(Canteen.id.in_(cids))).all()}
    foods = db.scalars(select(FoodItem).where(FoodItem.canteen_id.in_(cids))).all()
    food_map = {
        str(f.id): {"id": str(f.id), "name": f.name, "base_price": str(f.base_price), "is_veg": f.is_veg}
        for f in foods
    }
    ev_ids = [e.id for e in events]
    all_orders = db.scalars(select(EventBulkOrder).where(EventBulkOrder.event_id.in_(ev_ids))).all()
    count_map: dict[UUID, int] = {}
    for o in all_orders:
        count_map[o.event_id] = count_map.get(o.event_id, 0) + 1
    return [
        _serialize_event(
            e,
            canteen_name=canteen_map.get(e.canteen_id),
            food_map=food_map,
            bulk_orders_count=count_map.get(e.id, 0),
        )
        for e in events
    ]


def create_event(db: Session, data: dict, actor_user_id: UUID) -> dict:
    canteen = db.get(Canteen, data["canteen_id"])
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    min_q = int(data.get("min_order_quantity", 5))
    max_q = int(data.get("max_order_quantity", 500))
    if min_q > max_q:
        raise HTTPException(status_code=400, detail="min_order_quantity cannot exceed max_order_quantity")

    code = (data.get("event_code") or "").strip().upper() or f"EVT-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:5].upper()}"
    if db.scalar(select(CollegeEvent).where(CollegeEvent.event_code == code)):
        raise HTTPException(status_code=409, detail="Event code already exists")

    ev = CollegeEvent(
        event_code=code,
        canteen_id=canteen.id,
        name=data["name"].strip(),
        department=data["department"].strip(),
        organizer_user_id=data.get("organizer_user_id") or actor_user_id,
        organizer_name=data["organizer_name"].strip(),
        contact_phone=data["contact_phone"].strip(),
        contact_email=(data.get("contact_email") or "").strip() or None,
        event_date=data["event_date"],
        location=data["location"].strip(),
        description=(data.get("description") or "").strip() or None,
        ordering_deadline=data["ordering_deadline"],
        eligible_food_item_ids=[str(x) for x in (data.get("eligible_food_item_ids") or [])],
        min_order_quantity=min_q,
        max_order_quantity=max_q,
        is_active=bool(data.get("is_active", True)),
        created_by_user_id=actor_user_id,
    )
    db.add(ev)
    record_audit_log(
        db,
        action="event.created",
        entity_type="college_event",
        entity_id=ev.event_code,
        actor_user_id=actor_user_id,
        details={"name": ev.name, "department": ev.department, "event_date": ev.event_date.isoformat()},
    )
    db.commit()
    db.refresh(ev)
    return _serialize_event(ev, canteen_name=canteen.name)


def update_event(db: Session, event_id: UUID, data: dict, actor_user_id: UUID) -> dict:
    ev = db.get(CollegeEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    for k, v in data.items():
        if v is None:
            continue
        if k == "eligible_food_item_ids":
            setattr(ev, k, [str(x) for x in v])
        else:
            setattr(ev, k, v)
    if ev.min_order_quantity > ev.max_order_quantity:
        raise HTTPException(status_code=400, detail="min_order_quantity cannot exceed max_order_quantity")
    record_audit_log(
        db,
        action="event.updated",
        entity_type="college_event",
        entity_id=ev.event_code,
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(ev)
    canteen = db.get(Canteen, ev.canteen_id)
    return _serialize_event(ev, canteen_name=canteen.name if canteen else None)


def _serialize_bulk_order(
    db: Session,
    bo: EventBulkOrder,
    *,
    event: Optional[CollegeEvent] = None,
    items: Optional[list[EventBulkOrderItem]] = None,
) -> dict:
    ev = event or db.get(CollegeEvent, bo.event_id)
    bo_items = (
        items
        if items is not None
        else list(db.scalars(select(EventBulkOrderItem).where(EventBulkOrderItem.bulk_order_id == bo.id)).all())
    )
    organizer = db.get(User, bo.organizer_user_id)
    linked_order = db.get(Order, bo.linked_order_id) if bo.linked_order_id else None
    return {
        "id": str(bo.id),
        "bulk_order_number": bo.bulk_order_number,
        "idempotency_key": bo.idempotency_key,
        "event_id": str(bo.event_id),
        "event_name": ev.name if ev else "College Event",
        "event_code": ev.event_code if ev else None,
        "department": ev.department if ev else None,
        "event_date": ev.event_date.isoformat() if (ev and ev.event_date) else None,
        "event_location": ev.location if ev else None,
        "canteen_id": str(bo.canteen_id),
        "organizer_user_id": str(bo.organizer_user_id),
        "organizer_name": (organizer.full_name or organizer.email) if organizer else (ev.organizer_name if ev else "Organizer"),
        "linked_order_id": str(bo.linked_order_id) if bo.linked_order_id else None,
        "linked_order_number": linked_order.order_number if linked_order else None,
        "scheduled_prep_at": bo.scheduled_prep_at.isoformat() if bo.scheduled_prep_at else None,
        "scheduled_pickup_at": bo.scheduled_pickup_at.isoformat() if bo.scheduled_pickup_at else None,
        "pickup_arrangement": bo.pickup_arrangement,
        "group_pickup_token": bo.group_pickup_token,
        "individual_tokens": list(bo.individual_tokens_json or []),
        "status": bo.status,
        "payment_method": bo.payment_method,
        "payment_status": bo.payment_status,
        "provider_order_id": bo.provider_order_id,
        "provider_payment_id": bo.provider_payment_id,
        "payment_reference": bo.payment_reference,
        "razorpay_order_id": bo.provider_order_id if bo.payment_method == "razorpay" else None,
        "razorpay_key_id": razorpay_gateway.public_key_id if bo.payment_method == "razorpay" else None,
        "total_quantity": bo.total_quantity,
        "subtotal_amount": str(_quantize(bo.subtotal_amount)),
        "tax_amount": str(_quantize(bo.tax_amount)),
        "total_amount": str(_quantize(bo.total_amount)),
        "approved_by_user_id": str(bo.approved_by_user_id) if bo.approved_by_user_id else None,
        "approved_at": bo.approved_at.isoformat() if bo.approved_at else None,
        "rejection_reason": bo.rejection_reason,
        "notes": bo.notes,
        "created_at": bo.created_at.isoformat() if bo.created_at else None,
        "items": [
            {
                "id": str(it.id),
                "food_item_id": str(it.food_item_id),
                "item_name": it.item_name,
                "quantity": it.quantity,
                "unit_price": str(_quantize(it.unit_price)),
                "tax_rate_percent": str(_quantize(it.tax_rate_percent)),
                "tax_amount": str(_quantize(it.tax_amount)),
                "line_total": str(_quantize(it.line_total)),
            }
            for it in bo_items
        ],
    }


def create_bulk_order(
    db: Session,
    *,
    event_id: UUID,
    organizer_user_id: UUID,
    data: dict,
) -> dict:
    idem_key = (data.get("idempotency_key") or "").strip() or None
    if idem_key:
        existing = db.scalar(select(EventBulkOrder).where(EventBulkOrder.idempotency_key == idem_key))
        if existing:
            return _serialize_bulk_order(db, existing)

    ev = db.get(CollegeEvent, event_id)
    if not ev or not ev.is_active:
        raise HTTPException(status_code=404, detail="College event not found or inactive")

    now = datetime.now(timezone.utc)
    deadline = ev.ordering_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if now > deadline:
        raise HTTPException(status_code=400, detail="Event bulk ordering deadline has already passed")

    canteen = db.get(Canteen, ev.canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Event canteen not found")

    allowed_ids = {str(x) for x in (ev.eligible_food_item_ids or [])}
    total_qty = 0
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")
    prepared_items: list[dict] = []

    for spec in data["items"]:
        food = db.get(FoodItem, spec["food_item_id"])
        if not food or food.canteen_id != canteen.id or not food.is_active:
            raise HTTPException(status_code=400, detail="Food item not found in event canteen")
        if allowed_ids and str(food.id) not in allowed_ids:
            raise HTTPException(status_code=400, detail=f"'{food.name}' is not eligible for event '{ev.name}'")
        qty = int(spec["quantity"])
        total_qty += qty
        unit_p = _quantize(food.base_price)
        t_rate = _quantize(food.tax_rate_percent if food.tax_rate_percent is not None else canteen.tax_rate_percent)
        line_sub = _quantize(unit_p * Decimal(qty))
        line_tax = _quantize((line_sub * t_rate) / Decimal("100"))
        line_tot = _quantize(line_sub + line_tax)
        subtotal += line_sub
        tax_total += line_tax
        prepared_items.append({
            "food_item_id": food.id,
            "item_name": food.name,
            "quantity": qty,
            "unit_price": unit_p,
            "tax_rate_percent": t_rate,
            "tax_amount": line_tax,
            "line_total": line_tot,
        })

    if total_qty < ev.min_order_quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Bulk order total quantity ({total_qty}) is below event minimum ({ev.min_order_quantity})",
        )
    if total_qty > ev.max_order_quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Bulk order total quantity ({total_qty}) exceeds event maximum ({ev.max_order_quantity})",
        )

    total_amount = _quantize(subtotal + tax_total)
    method = (data.get("payment_method") or "razorpay").strip().lower()
    if method not in ("razorpay", "stripe"):
        raise HTTPException(status_code=400, detail="Bulk orders require verified online payment (razorpay or stripe)")

    bo_number = f"EBO-{now.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
    provider_order_id = None
    if method == "razorpay":
        rzp = razorpay_gateway.create_order(
            amount_inr=total_amount,
            receipt_ref=bo_number,
            notes={"bulk_order_number": bo_number, "event_code": ev.event_code},
        )
        provider_order_id = rzp["id"]
    elif method == "stripe":
        pi = stripe_gateway.create_payment_intent(
            amount_inr=total_amount,
            order_number=bo_number,
            idempotency_key=f"cb-ebo-{bo_number}",
            metadata={"bulk_order_number": bo_number, "event_code": ev.event_code},
        )
        provider_order_id = pi["id"]

    bo = EventBulkOrder(
        bulk_order_number=bo_number,
        idempotency_key=idem_key,
        event_id=ev.id,
        canteen_id=canteen.id,
        organizer_user_id=organizer_user_id,
        scheduled_prep_at=data["scheduled_prep_at"],
        scheduled_pickup_at=data["scheduled_pickup_at"],
        pickup_arrangement=data.get("pickup_arrangement") or "grouped_token",
        status="pending_approval",
        payment_method=method,
        payment_status="PENDING",
        provider_order_id=provider_order_id,
        total_quantity=total_qty,
        subtotal_amount=subtotal,
        tax_amount=tax_total,
        total_amount=total_amount,
        notes=data.get("notes"),
    )
    db.add(bo)
    db.flush()

    created_items: list[EventBulkOrderItem] = []
    for item_data in prepared_items:
        row = EventBulkOrderItem(bulk_order_id=bo.id, **item_data)
        db.add(row)
        created_items.append(row)
    db.flush()

    record_audit_log(
        db,
        action="event_bulk_order.created",
        entity_type="event_bulk_order",
        entity_id=bo.bulk_order_number,
        actor_user_id=organizer_user_id,
        details={"event_code": ev.event_code, "total_quantity": total_qty, "total_amount": str(total_amount)},
    )
    db.commit()
    db.refresh(bo)
    return _serialize_bulk_order(db, bo, event=ev, items=created_items)


def _dispatch_bulk_order_to_canteen_pipeline(
    db: Session,
    bo: EventBulkOrder,
    *,
    actor_user_id: UUID,
) -> None:
    """
    When a bulk order is both APPROVED and PAYMENT CONFIRMED, create its linked canteen Order,
    generate grouped / individual pickup tokens, and emit real-time kitchen/token board event.
    Idempotent: if bo.linked_order_id is already set, does not duplicate.
    """
    if bo.linked_order_id or bo.status != "approved" or bo.payment_status != "CONFIRMED":
        return

    ev = db.get(CollegeEvent, bo.event_id)
    canteen = db.get(Canteen, bo.canteen_id)
    counter = db.scalar(
        select(Counter).where(Counter.canteen_id == bo.canteen_id, Counter.is_active.is_(True)).order_by(Counter.code)
    )
    kitchen = db.scalar(
        select(Kitchen).where(Kitchen.canteen_id == bo.canteen_id, Kitchen.is_active.is_(True)).order_by(Kitchen.code)
    )
    if not canteen or not counter:
        return

    now = datetime.now(timezone.utc)
    order = Order(
        order_number=_generate_order_number(db),
        idempotency_key=f"ebo-ord-{bo.id}",
        canteen_id=bo.canteen_id,
        counter_id=counter.id,
        kitchen_id=kitchen.id if kitchen else None,
        customer_id=bo.organizer_user_id,
        is_guest=False,
        order_type="event_bulk",
        order_channel="event",
        status="PLACED",
        payment_status="CONFIRMED",
        payment_method=bo.payment_method,
        subtotal_amount=bo.subtotal_amount,
        discount_amount=Decimal("0.00"),
        tax_amount=bo.tax_amount,
        total_amount=bo.total_amount,
        estimated_prep_minutes=30,
        estimated_pickup_at=bo.scheduled_pickup_at,
        confirmed_at=now,
        is_priority=True,
        notes=f"[EVENT BULK ORDER {bo.bulk_order_number} - {ev.name if ev else 'Event'}] {bo.notes or ''}".strip(),
    )
    db.add(order)
    db.flush()

    bo_items = db.scalars(select(EventBulkOrderItem).where(EventBulkOrderItem.bulk_order_id == bo.id)).all()
    for bi in bo_items:
        food = db.get(FoodItem, bi.food_item_id)
        db.add(
            OrderItem(
                order_id=order.id,
                food_item_id=bi.food_item_id,
                station_id=food.station_id if food else None,
                prep_status="PENDING",
                item_name=f"[EVENT] {bi.item_name}",
                quantity=bi.quantity,
                unit_price=bi.unit_price,
                addon_total_per_unit=Decimal("0.00"),
                line_subtotal=_quantize(bi.unit_price * Decimal(bi.quantity)),
                tax_amount=bi.tax_amount,
                line_total=bi.line_total,
            )
        )
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status="CREATED",
            to_status="PLACED",
            changed_by_user_id=actor_user_id,
            reason=f"Dispatched verified Event Bulk Order {bo.bulk_order_number}",
        )
    )
    pay = Payment(
        order_id=order.id,
        provider=bo.payment_method,
        method=bo.payment_method,
        provider_order_id=f"ebo-{bo.provider_order_id or bo.id}",
        provider_payment_id=f"ebo-{bo.provider_payment_id or bo.id}",
        amount=bo.total_amount,
        status="CONFIRMED",
        payment_reference=bo.payment_reference or bo.bulk_order_number,
        confirmed_at=now,
        recorded_by_user_id=actor_user_id,
    )
    db.add(pay)
    db.flush()

    token, qr = generate_token_and_qr_for_confirmed_order(db, order)
    create_receipt_for_order(db, order, token, qr, pay)

    bo.linked_order_id = order.id
    bo.group_pickup_token = token.token_code
    if bo.pickup_arrangement == "individual_tokens":
        cap = min(bo.total_quantity, 50)
        bo.individual_tokens_json = [f"{token.token_code}-{i:02d}" for i in range(1, cap + 1)]
    else:
        bo.individual_tokens_json = [token.token_code]

    emit_order_event_sync(
        str(order.canteen_id),
        str(order.id),
        "order.placed",
        {
            "order_number": order.order_number,
            "pickup_token": token.token_code,
            "status": "PLACED",
            "order_type": "event_bulk",
            "bulk_order_number": bo.bulk_order_number,
        },
    )


def review_bulk_order(
    db: Session,
    *,
    bulk_order_id: UUID,
    decision: str,
    rejection_reason: Optional[str],
    actor_user_id: UUID,
) -> dict:
    bo = db.scalar(select(EventBulkOrder).where(EventBulkOrder.id == bulk_order_id).with_for_update())
    if not bo:
        raise HTTPException(status_code=404, detail="Event bulk order not found")
    if bo.status not in ("pending_approval", "approved"):
        raise HTTPException(status_code=409, detail=f"Cannot review bulk order in '{bo.status}' status")

    now = datetime.now(timezone.utc)
    if decision == "approve":
        bo.status = "approved"
        bo.approved_by_user_id = actor_user_id
        bo.approved_at = now
        bo.rejection_reason = None
        _dispatch_bulk_order_to_canteen_pipeline(db, bo, actor_user_id=actor_user_id)
    else:
        bo.status = "rejected"
        bo.rejection_reason = (rejection_reason or "Rejected by canteen manager").strip()

    record_audit_log(
        db,
        action=f"event_bulk_order.{bo.status}",
        entity_type="event_bulk_order",
        entity_id=bo.bulk_order_number,
        actor_user_id=actor_user_id,
        details={"decision": decision, "rejection_reason": bo.rejection_reason},
    )
    db.commit()
    db.refresh(bo)
    return _serialize_bulk_order(db, bo)


def verify_bulk_order_payment(
    db: Session,
    *,
    bulk_order_id: UUID,
    actor_user_id: UUID,
    razorpay_order_id: Optional[str] = None,
    razorpay_payment_id: Optional[str] = None,
    razorpay_signature: Optional[str] = None,
    stripe_payment_intent_id: Optional[str] = None,
) -> dict:
    bo = db.scalar(select(EventBulkOrder).where(EventBulkOrder.id == bulk_order_id).with_for_update())
    if not bo:
        raise HTTPException(status_code=404, detail="Event bulk order not found")
    if bo.status in ("rejected", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Cannot confirm payment for {bo.status} bulk order")
    if bo.payment_status == "CONFIRMED":
        return _serialize_bulk_order(db, bo)

    provider_payment_id: Optional[str] = None
    if bo.payment_method == "razorpay":
        ord_id = razorpay_order_id or bo.provider_order_id
        if not ord_id or not razorpay_payment_id or not razorpay_signature:
            raise HTTPException(status_code=400, detail="Razorpay order_id, payment_id, and signature are required")
        if ord_id != bo.provider_order_id:
            raise HTTPException(status_code=400, detail="Razorpay order_id mismatch")
        if not razorpay_gateway.verify_payment_signature(
            razorpay_order_id=ord_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
        ):
            bo.payment_status = "FAILED"
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid Razorpay payment signature")
        provider_payment_id = razorpay_payment_id
    elif bo.payment_method == "stripe":
        pi_id = stripe_payment_intent_id or bo.provider_order_id
        if not pi_id or pi_id != bo.provider_order_id:
            raise HTTPException(status_code=400, detail="Stripe payment_intent_id mismatch")
        pi_data = stripe_gateway.retrieve_payment_intent(pi_id)
        if pi_data.get("status") != "succeeded":
            raise HTTPException(status_code=400, detail="Stripe payment intent has not succeeded")
        provider_payment_id = pi_id

    bo.payment_status = "CONFIRMED"
    bo.provider_payment_id = provider_payment_id
    bo.payment_reference = provider_payment_id
    _dispatch_bulk_order_to_canteen_pipeline(db, bo, actor_user_id=actor_user_id)

    try:
        from app.services.invoice_service import ensure_invoice_for_bulk_order

        ensure_invoice_for_bulk_order(db, bo)
    except ImportError:
        pass

    record_audit_log(
        db,
        action="event_bulk_order.payment_confirmed",
        entity_type="event_bulk_order",
        entity_id=bo.bulk_order_number,
        actor_user_id=actor_user_id,
        details={"payment_reference": provider_payment_id, "amount": str(bo.total_amount)},
    )
    db.commit()
    db.refresh(bo)
    return _serialize_bulk_order(db, bo)


def update_bulk_order_status(
    db: Session,
    *,
    bulk_order_id: UUID,
    target_status: str,
    actor_user_id: UUID,
) -> dict:
    bo = db.scalar(select(EventBulkOrder).where(EventBulkOrder.id == bulk_order_id).with_for_update())
    if not bo:
        raise HTTPException(status_code=404, detail="Event bulk order not found")
    target = target_status.strip().lower()
    if target not in ("preparing", "ready", "completed", "cancelled"):
        raise HTTPException(status_code=400, detail="Invalid bulk order status")
    if target in ("preparing", "ready", "completed") and bo.payment_status != "CONFIRMED":
        raise HTTPException(status_code=400, detail="Bulk order payment must be confirmed before preparation/completion")
    bo.status = target
    if bo.linked_order_id:
        ord_row = db.get(Order, bo.linked_order_id)
        if ord_row:
            status_map = {
                "preparing": "PREPARING",
                "ready": "READY",
                "completed": "COMPLETED",
                "cancelled": "CANCELLED",
            }
            ord_row.status = status_map.get(target, ord_row.status)
    record_audit_log(
        db,
        action=f"event_bulk_order.{target}",
        entity_type="event_bulk_order",
        entity_id=bo.bulk_order_number,
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(bo)
    return _serialize_bulk_order(db, bo)


def list_bulk_orders(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    event_id: Optional[UUID] = None,
    organizer_user_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
) -> list[dict]:
    stmt = select(EventBulkOrder)
    if canteen_id:
        stmt = stmt.where(EventBulkOrder.canteen_id == canteen_id)
    if event_id:
        stmt = stmt.where(EventBulkOrder.event_id == event_id)
    if organizer_user_id:
        stmt = stmt.where(EventBulkOrder.organizer_user_id == organizer_user_id)
    if status_filter and status_filter != "all":
        stmt = stmt.where(EventBulkOrder.status == status_filter)
    rows = list(db.scalars(stmt.order_by(EventBulkOrder.created_at.desc())).all())
    return [_serialize_bulk_order(db, r) for r in rows]


def get_events_report_summary(db: Session, *, canteen_id: Optional[UUID] = None) -> dict:
    ev_stmt = select(CollegeEvent)
    bo_stmt = select(EventBulkOrder)
    if canteen_id:
        ev_stmt = ev_stmt.where(CollegeEvent.canteen_id == canteen_id)
        bo_stmt = bo_stmt.where(EventBulkOrder.canteen_id == canteen_id)

    events = list(db.scalars(ev_stmt.order_by(CollegeEvent.event_date.desc())).all())
    orders = list(db.scalars(bo_stmt.order_by(EventBulkOrder.created_at.desc())).all())
    order_ids = [o.id for o in orders]
    items = (
        list(db.scalars(select(EventBulkOrderItem).where(EventBulkOrderItem.bulk_order_id.in_(order_ids))).all())
        if order_ids
        else []
    )
    order_by_id = {o.id: o for o in orders}
    ev_by_id = {e.id: e for e in events}

    total_revenue = Decimal("0.00")
    pending_count = 0
    approved_active_count = 0
    completed_count = 0
    rejected_cancelled_count = 0

    event_breakdown: dict[UUID, dict] = {
        e.id: {
            "event_id": str(e.id),
            "event_code": e.event_code,
            "event_name": e.name,
            "department": e.department,
            "event_date": e.event_date.isoformat() if e.event_date else None,
            "orders_count": 0,
            "total_portions": 0,
            "confirmed_revenue": Decimal("0.00"),
            "items_ordered": {},
        }
        for e in events
    }

    for o in orders:
        eb = event_breakdown.get(o.event_id)
        if eb:
            eb["orders_count"] += 1
            if o.status not in ("rejected", "cancelled"):
                eb["total_portions"] += o.total_quantity
        if o.payment_status == "CONFIRMED" and o.status not in ("rejected", "cancelled"):
            amt = _quantize(o.total_amount)
            total_revenue += amt
            if eb:
                eb["confirmed_revenue"] += amt
        if o.status == "pending_approval":
            pending_count += 1
        elif o.status in ("approved", "preparing", "ready"):
            approved_active_count += 1
        elif o.status == "completed":
            completed_count += 1
        else:
            rejected_cancelled_count += 1

    for it in items:
        o_row = order_by_id.get(it.bulk_order_id)
        if not o_row or o_row.status in ("rejected", "cancelled"):
            continue
        eb = event_breakdown.get(o_row.event_id)
        if eb:
            eb["items_ordered"][it.item_name] = eb["items_ordered"].get(it.item_name, 0) + it.quantity

    event_rows = []
    for eb in event_breakdown.values():
        event_rows.append({
            **eb,
            "confirmed_revenue": str(_quantize(eb["confirmed_revenue"])),
            "items_ordered": [
                {"item_name": k, "quantity": v} for k, v in sorted(eb["items_ordered"].items(), key=lambda x: -x[1])
            ],
        })

    return {
        "total_events": len(events),
        "total_bulk_orders": len(orders),
        "pending_event_orders": pending_count,
        "active_event_orders": approved_active_count,
        "completed_event_orders": completed_count,
        "rejected_or_cancelled_orders": rejected_cancelled_count,
        "total_event_revenue": str(_quantize(total_revenue)),
        "events": event_rows,
        "orders": [_serialize_bulk_order(db, o, event=ev_by_id.get(o.event_id)) for o in orders],
    }


def export_events_report_csv(summary: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["CollegeBites Events & Bulk Orders Report"])
    w.writerow(["Total Events", summary["total_events"]])
    w.writerow(["Total Bulk Orders", summary["total_bulk_orders"]])
    w.writerow(["Pending Approval", summary["pending_event_orders"]])
    w.writerow(["Active Orders", summary["active_event_orders"]])
    w.writerow(["Completed Orders", summary["completed_event_orders"]])
    w.writerow(["Confirmed Event Revenue (INR)", summary["total_event_revenue"]])
    w.writerow([])
    w.writerow(["EVENT CODE", "EVENT NAME", "DEPARTMENT", "DATE", "ORDERS", "TOTAL PORTIONS", "REVENUE (INR)", "ITEMS ORDERED"])
    for ev in summary["events"]:
        items_str = "; ".join(f"{i['item_name']} x{i['quantity']}" for i in ev["items_ordered"])
        w.writerow([
            ev["event_code"],
            ev["event_name"],
            ev["department"],
            ev["event_date"],
            ev["orders_count"],
            ev["total_portions"],
            ev["confirmed_revenue"],
            items_str,
        ])
    return buf.getvalue()
