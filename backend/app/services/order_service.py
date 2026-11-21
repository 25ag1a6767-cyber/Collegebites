import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.core.redis_client import get_redis
from app.core.security import generate_guest_access_token, mask_mobile, sha256_hex
from app.integrations.razorpay_client import razorpay_gateway
from app.models.college import Canteen, Counter, DiningTable, Kitchen, LocationQRCode
from app.models.menu import FoodAddon, FoodItem, FoodItemAddon, FoodVariant
from app.models.order import (
    Cart,
    Order,
    OrderCancellation,
    OrderItem,
    OrderItemCustomization,
    OrderStatusHistory,
    PickupSlot,
    SlotReservation,
)
from app.models.payment import OrderQRCode, Payment, PaymentTransaction, PickupToken
from app.models.promotion import CouponRedemption
from app.schemas.order import CheckoutItemDirectIn, CheckoutRequest, OrderItemOut, OrderOut, PickupSlotOut
from app.services.audit_service import record_audit_log
from app.services.auth_service import validate_guest_otp_token
from app.services.cart_service import evaluate_coupon, get_active_cart
from app.services.college_service import compute_canteen_live_status, get_or_create_college_settings
from app.websockets import emit_order_event_sync

ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"PAYMENT_PENDING", "PAYMENT_FAILED", "CANCELLED"},
    "PAYMENT_PENDING": {"PAYMENT_CONFIRMED", "PAYMENT_FAILED", "CANCELLED"},
    "PAYMENT_CONFIRMED": {"PLACED"},
    "PLACED": {"ACCEPTED", "REJECTED", "CANCELLED"},
    "ACCEPTED": {"PREPARING", "REJECTED", "CANCELLED"},
    "PREPARING": {"READY"},
    "READY": {"COMPLETED"},
    "COMPLETED": set(),
    "PAYMENT_FAILED": set(),
    "CANCELLED": set(),
    "REJECTED": set(),
}


def _quantize(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"))


def _generate_order_number(db: Session) -> str:
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(918273645)"))
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"CB-{today_str}-"
    max_num = db.scalar(select(func.max(Order.order_number)).where(Order.order_number.like(f"{prefix}%")))
    if max_num:
        try:
            seq = int(max_num.rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    while True:
        candidate = f"{prefix}{seq:06d}"
        exists = db.scalar(select(Order.id).where(Order.order_number == candidate))
        if not exists:
            return candidate
        seq += 1


def serialize_order(db: Session, order: Order, *, raw_guest_token: Optional[str] = None) -> OrderOut:
    canteen = db.get(Canteen, order.canteen_id)
    counter = db.get(Counter, order.counter_id)
    token_row = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id))
    qr_row = db.scalar(select(OrderQRCode).where(OrderQRCode.order_id == order.id))
    pay_row = db.scalar(select(Payment).where(Payment.order_id == order.id).order_by(Payment.created_at.desc()))
    college = get_or_create_college_settings(db)

    items_out: list[OrderItemOut] = []
    for item in order.items:
        items_out.append(OrderItemOut.model_validate(item))

    return OrderOut(
        id=order.id,
        order_number=order.order_number,
        canteen_id=order.canteen_id,
        canteen_name=canteen.name if canteen else None,
        counter_id=order.counter_id,
        counter_name=counter.name if counter else None,
        kitchen_id=order.kitchen_id,
        table_id=order.table_id,
        customer_id=order.customer_id,
        is_guest=order.is_guest,
        guest_name=order.guest_name,
        guest_phone_masked=mask_mobile(order.guest_phone) if order.guest_phone else None,
        order_type=order.order_type,
        order_channel=order.order_channel,
        status=order.status,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        subtotal_amount=order.subtotal_amount,
        discount_amount=order.discount_amount,
        tax_amount=order.tax_amount,
        total_amount=order.total_amount,
        coupon_code=order.coupon_code,
        estimated_prep_minutes=order.estimated_prep_minutes,
        estimated_pickup_at=order.estimated_pickup_at,
        delayed_minutes=order.delayed_minutes,
        delay_reason=order.delay_reason,
        pickup_token_code=token_row.token_code if token_row else None,
        qr_verification_path=qr_row.verification_path if qr_row else None,
        qr_token_raw=qr_row.qr_payload_encoded if qr_row else None,
        guest_access_token=raw_guest_token,
        razorpay_order_id=pay_row.provider_order_id if (pay_row and pay_row.provider == "razorpay") else None,
        razorpay_key_id=razorpay_gateway.key_id if order.payment_method == "razorpay" else None,
        cancellation_policy_text=college.cancellation_policy_text,
        created_at=order.created_at,
        confirmed_at=order.confirmed_at,
        accepted_at=order.accepted_at,
        preparing_at=order.preparing_at,
        ready_at=order.ready_at,
        completed_at=order.completed_at,
        items=items_out,
        status_history=sorted(order.status_history, key=lambda s: s.created_at),
    )


def list_pickup_slots(db: Session, canteen_id: UUID) -> list[PickupSlotOut]:
    slots = db.scalars(
        select(PickupSlot)
        .where(PickupSlot.canteen_id == canteen_id, PickupSlot.is_active.is_(True))
        .order_by(PickupSlot.slot_date.asc(), PickupSlot.start_time.asc())
    ).all()
    results: list[PickupSlotOut] = []
    for s in slots:
        out = PickupSlotOut.model_validate(s)
        out.available_count = max(0, s.capacity - s.reserved_count)
        results.append(out)
    return results


def checkout_order(
    db: Session,
    payload: CheckoutRequest,
    *,
    user_id: Optional[UUID] = None,
    guest_session_id: Optional[str] = None,
    cashier_user_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
) -> OrderOut:
    # 1. Idempotency protection
    if payload.idempotency_key:
        existing_order = db.scalar(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
            .where(Order.idempotency_key == payload.idempotency_key)
        )
        if existing_order:
            return serialize_order(db, existing_order)

    if not payload.accepted_policy:
        raise HTTPException(status_code=400, detail="You must acknowledge the college cancellation and payment policy before checkout")

    college = get_or_create_college_settings(db)
    canteen = db.get(Canteen, payload.canteen_id)
    if not canteen or not canteen.is_active:
        raise HTTPException(status_code=404, detail="Selected canteen is unavailable")

    is_open, _crowd, eta, active_count = compute_canteen_live_status(db, canteen)
    if not is_open:
        raise HTTPException(status_code=400, detail="Canteen is currently closed, paused, or on holiday")
    if canteen.auto_throttle_enabled and active_count >= canteen.max_concurrent_orders:
        raise HTTPException(status_code=429, detail="Canteen queue is at full capacity. Please retry shortly.")

    # Payment method authorization per canteen
    if payload.payment_method == "razorpay" and not (college.razorpay_enabled and canteen.allow_online_payment):
        raise HTTPException(status_code=400, detail="Online payment is disabled for this canteen")
    if payload.payment_method == "cash" and not (cashier_user_id or (college.cash_at_counter_enabled and canteen.allow_cash_at_counter)):
        raise HTTPException(status_code=400, detail="Cash at counter is disabled for this canteen")
    if payload.payment_method == "pay_at_pickup" and not (college.pay_at_pickup_enabled and canteen.allow_pay_at_pickup):
        raise HTTPException(status_code=400, detail="Pay at pickup is disabled for this canteen")

    # Resolve location QR if passed
    location_qr_id: Optional[UUID] = None
    counter_id = payload.counter_id
    table_id = payload.table_id
    if payload.location_qr_code:
        loc_qr = db.scalar(select(LocationQRCode).where(LocationQRCode.code == payload.location_qr_code.strip()))
        if not loc_qr or not loc_qr.is_active or loc_qr.revoked_at is not None:
            raise HTTPException(status_code=400, detail="Scanned location QR code is invalid or revoked")
        if loc_qr.canteen_id != canteen.id:
            raise HTTPException(status_code=400, detail="Location QR belongs to a different canteen")
        location_qr_id = loc_qr.id
        counter_id = counter_id or loc_qr.counter_id
        table_id = table_id or loc_qr.table_id

    if table_id:
        table = db.get(DiningTable, table_id)
        if not table or table.canteen_id != canteen.id:
            raise HTTPException(status_code=400, detail="Invalid dining table")

    # Validate guest / customer identity
    is_guest = user_id is None
    if is_guest:
        if not payload.guest_name or not payload.guest_phone:
            raise HTTPException(status_code=400, detail="Guest name and mobile number are required")
        # Walk-in POS orders recorded by a cashier don't need guest SMS OTP
        if college.guest_otp_required and not cashier_user_id and payload.order_channel != "kiosk":
            if not validate_guest_otp_token(db, payload.guest_phone, payload.guest_otp_verification_token):
                raise HTTPException(status_code=400, detail="Guest mobile OTP verification is required before checkout")

    # Gather line items from cart or direct payload
    line_specs: list[CheckoutItemDirectIn] = list(payload.direct_items)
    cart: Optional[Cart] = None
    if not line_specs and payload.use_cart:
        cart = get_active_cart(db, canteen.id, user_id=user_id, guest_session_id=guest_session_id, create_if_missing=False)
        if cart:
            for ci in cart.items:
                spice = next((c.option_value for c in ci.customizations if c.customization_type == "spice"), None)
                sugar = next((c.option_value for c in ci.customizations if c.customization_type == "sugar"), None)
                rems = [c.option_value for c in ci.customizations if c.customization_type == "remove_ingredient"]
                addons = [
                    {"addon_id": c.addon_id, "quantity": c.quantity}
                    for c in ci.customizations
                    if c.customization_type == "addon" and c.addon_id
                ]
                line_specs.append(
                    CheckoutItemDirectIn(
                        food_item_id=ci.food_item_id,
                        variant_id=ci.variant_id,
                        quantity=ci.quantity,
                        spice_level=spice,
                        sugar_level=sugar,
                        removed_ingredients=rems,
                        addons=addons,
                        special_instructions=ci.special_instructions,
                    )
                )
            if not payload.coupon_code and cart.coupon_code:
                payload.coupon_code = cart.coupon_code

    if not line_specs:
        raise HTTPException(status_code=400, detail="Cart is empty; add items before checkout")

    # Resolve counter & kitchen
    first_food = db.get(FoodItem, line_specs[0].food_item_id)
    if not counter_id and first_food and first_food.counter_id:
        counter_id = first_food.counter_id
    if not counter_id:
        default_counter = db.scalar(
            select(Counter).where(Counter.canteen_id == canteen.id, Counter.is_active.is_(True)).order_by(Counter.code)
        )
        if not default_counter:
            raise HTTPException(status_code=400, detail="No active pickup counter configured for this canteen")
        counter_id = default_counter.id
    else:
        cnt = db.get(Counter, counter_id)
        if not cnt or cnt.canteen_id != canteen.id or not cnt.is_active:
            raise HTTPException(status_code=400, detail="Invalid pickup counter")

    kitchen_id = first_food.kitchen_id if (first_food and first_food.kitchen_id) else None
    if not kitchen_id:
        default_kitchen = db.scalar(
            select(Kitchen).where(Kitchen.canteen_id == canteen.id, Kitchen.is_active.is_(True)).order_by(Kitchen.code)
        )
        kitchen_id = default_kitchen.id if default_kitchen else None

    # Validate pickup slot capacity atomically with FOR UPDATE + Redis
    pickup_slot: Optional[PickupSlot] = None
    if payload.pickup_slot_id:
        pickup_slot = db.scalar(
            select(PickupSlot).where(PickupSlot.id == payload.pickup_slot_id).with_for_update()
        )
        if not pickup_slot or pickup_slot.canteen_id != canteen.id or not pickup_slot.is_active:
            raise HTTPException(status_code=400, detail="Invalid or inactive pickup slot")
        if pickup_slot.reserved_count >= pickup_slot.capacity:
            raise HTTPException(status_code=409, detail="Selected pickup slot is full")
        redis_client = get_redis()
        rkey = f"cb:slot:{pickup_slot.id}:reserved"
        if not redis_client.exists(rkey):
            redis_client.set(rkey, pickup_slot.reserved_count, ex=86400)
        new_count = redis_client.incr(rkey)
        if new_count > pickup_slot.capacity:
            redis_client.decr(rkey)
            raise HTTPException(status_code=409, detail="Selected pickup slot capacity reached")
        pickup_slot.reserved_count += 1

    # Recalculate ALL prices strictly on backend
    subtotal = Decimal("0.00")
    max_item_prep = canteen.default_prep_time_minutes
    items_for_coupon: list[tuple[UUID, UUID, Decimal]] = []
    prepared_items: list[tuple[FoodItem, Optional[FoodVariant], int, Decimal, Decimal, Decimal, Optional[str], list[dict]]] = []

    for spec in line_specs:
        food = db.get(FoodItem, spec.food_item_id)
        if not food or food.canteen_id != canteen.id or not food.is_active:
            raise HTTPException(status_code=400, detail="Food item not found in canteen")
        if not food.is_available or food.insufficient_ingredients:
            raise HTTPException(status_code=400, detail=f"{food.name} is currently out of stock or unavailable")

        max_item_prep = max(max_item_prep, food.prep_time_minutes)
        variant: Optional[FoodVariant] = None
        unit_price = food.base_price
        if spec.variant_id:
            variant = db.get(FoodVariant, spec.variant_id)
            if not variant or variant.food_item_id != food.id or not variant.is_available:
                raise HTTPException(status_code=400, detail=f"Selected variant for {food.name} is unavailable")
            unit_price = variant.absolute_price if variant.absolute_price is not None else (food.base_price + variant.price_delta)
        unit_price = _quantize(unit_price)

        addon_per_unit = Decimal("0.00")
        cust_dicts: list[dict] = []
        if spec.spice_level:
            cust_dicts.append({"customization_type": "spice", "option_name": "Spice Level", "option_value": spec.spice_level, "quantity": 1, "unit_price": Decimal("0.00"), "total_price": Decimal("0.00")})
        if spec.sugar_level:
            cust_dicts.append({"customization_type": "sugar", "option_name": "Sugar Level", "option_value": spec.sugar_level, "quantity": 1, "unit_price": Decimal("0.00"), "total_price": Decimal("0.00")})
        for rem in spec.removed_ingredients:
            cust_dicts.append({"customization_type": "remove_ingredient", "option_name": "Remove", "option_value": rem, "quantity": 1, "unit_price": Decimal("0.00"), "total_price": Decimal("0.00")})

        for ad in spec.addons:
            link = db.scalar(select(FoodItemAddon).where(FoodItemAddon.food_item_id == food.id, FoodItemAddon.addon_id == ad.addon_id))
            addon = db.get(FoodAddon, ad.addon_id)
            if not link or not addon or not addon.is_available:
                raise HTTPException(status_code=400, detail="Invalid or unavailable add-on")
            if ad.quantity > link.max_quantity:
                raise HTTPException(status_code=400, detail=f"Maximum {link.max_quantity} allowed for {addon.name}")
            line_addon_total = _quantize(addon.price * ad.quantity)
            addon_per_unit += line_addon_total
            cust_dicts.append({
                "customization_type": "addon",
                "option_name": addon.name,
                "option_value": f"x{ad.quantity}",
                "quantity": ad.quantity,
                "unit_price": addon.price,
                "total_price": line_addon_total,
            })

        line_sub = _quantize((unit_price + addon_per_unit) * spec.quantity)
        subtotal += line_sub
        items_for_coupon.append((food.id, food.category_id, line_sub))
        prepared_items.append((food, variant, spec.quantity, unit_price, addon_per_unit, line_sub, spec.special_instructions, cust_dicts))

    discount = Decimal("0.00")
    applied_coupon = None
    if payload.coupon_code:
        ok, discount, msg, applied_coupon = evaluate_coupon(
            db,
            payload.coupon_code,
            canteen.id,
            subtotal,
            items_for_coupon,
            user_id=user_id,
            guest_phone=payload.guest_phone,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=msg or "Invalid coupon code")

    taxable = max(Decimal("0.00"), subtotal - discount)
    tax_amount = _quantize((taxable * canteen.tax_rate_percent) / Decimal("100"))
    total_amount = _quantize(taxable + tax_amount)

    est_prep = max(eta, max_item_prep)
    now = datetime.now(timezone.utc)
    raw_guest_token = None
    guest_token_hash = None
    if is_guest:
        raw_guest_token, guest_token_hash = generate_guest_access_token()

    order = Order(
        order_number=_generate_order_number(db),
        idempotency_key=payload.idempotency_key,
        canteen_id=canteen.id,
        counter_id=counter_id,
        kitchen_id=kitchen_id,
        table_id=table_id,
        customer_id=user_id,
        cashier_id=cashier_user_id,
        pickup_slot_id=pickup_slot.id if pickup_slot else None,
        location_qr_id=location_qr_id,
        is_guest=is_guest,
        guest_name=payload.guest_name.strip() if payload.guest_name else None,
        guest_phone=payload.guest_phone.strip() if payload.guest_phone else None,
        guest_access_token_hash=guest_token_hash,
        order_type=payload.order_type,
        order_channel=payload.order_channel,
        status="PAYMENT_PENDING",
        payment_status="PENDING",
        payment_method=payload.payment_method,
        subtotal_amount=_quantize(subtotal),
        discount_amount=_quantize(discount),
        tax_amount=tax_amount,
        total_amount=total_amount,
        coupon_code=applied_coupon.code if applied_coupon else None,
        estimated_prep_minutes=est_prep,
        estimated_pickup_at=now + timedelta(minutes=est_prep),
        notes=payload.notes,
    )
    db.add(order)
    db.flush()

    # Distribute tax proportionally to order items for complete historical line details
    for food, variant, qty, unit_p, addon_u, line_sub, instr, custs in prepared_items:
        ratio = (line_sub / subtotal) if subtotal > Decimal("0.00") else Decimal("0.00")
        item_tax = _quantize(tax_amount * ratio)
        item_disc = _quantize(discount * ratio)
        line_total = _quantize(max(Decimal("0.00"), line_sub - item_disc) + item_tax)
        oi = OrderItem(
            order_id=order.id,
            food_item_id=food.id,
            variant_id=variant.id if variant else None,
            item_name=food.name,
            variant_name=variant.name if variant else None,
            quantity=qty,
            unit_price=unit_p,
            addon_total_per_unit=addon_u,
            line_subtotal=line_sub,
            tax_amount=item_tax,
            line_total=line_total,
            special_instructions=instr,
        )
        db.add(oi)
        db.flush()
        for c in custs:
            db.add(OrderItemCustomization(order_item_id=oi.id, **c))

    db.add(OrderStatusHistory(order_id=order.id, from_status="CREATED", to_status="PAYMENT_PENDING", changed_by_user_id=user_id or cashier_user_id, reason="Order created and awaiting payment"))

    if pickup_slot:
        db.add(SlotReservation(pickup_slot_id=pickup_slot.id, order_id=order.id, status="reserved"))

    if applied_coupon:
        applied_coupon.times_used += 1
        db.add(
            CouponRedemption(
                coupon_id=applied_coupon.id,
                order_id=order.id,
                user_id=user_id,
                guest_phone=payload.guest_phone,
                discount_applied=discount,
            )
        )

    # Create payment request
    provider = "razorpay" if payload.payment_method == "razorpay" else "cash"
    provider_order_id = None
    if provider == "razorpay":
        rzp_order = razorpay_gateway.create_order(
            amount_inr=total_amount,
            receipt_ref=order.order_number,
            notes={"order_number": order.order_number, "canteen": canteen.code},
        )
        provider_order_id = rzp_order["id"]

    payment = Payment(
        order_id=order.id,
        provider=provider,
        method=payload.payment_method,
        provider_order_id=provider_order_id,
        amount=total_amount,
        currency="INR",
        status="PENDING",
    )
    db.add(payment)
    db.flush()
    db.add(
        PaymentTransaction(
            payment_id=payment.id,
            order_id=order.id,
            transaction_type="initiate",
            amount=total_amount,
            status="PENDING",
            external_reference=provider_order_id,
        )
    )

    if cart:
        cart.status = "converted"

    record_audit_log(
        db,
        action="order.checkout_created",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=user_id or cashier_user_id,
        ip_address=ip_address,
        details={"total_amount": str(total_amount), "payment_method": payload.payment_method, "is_guest": is_guest},
    )
    db.commit()
    db.expire_all()

    loaded = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order.id)
    )
    return serialize_order(db, loaded, raw_guest_token=raw_guest_token)


def transition_order_status(
    db: Session,
    order: Order,
    to_status: str,
    *,
    actor_user_id: Optional[UUID] = None,
    reason: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Order:
    allowed = ALLOWED_STATUS_TRANSITIONS.get(order.status, set())
    if to_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid order status transition from {order.status} to {to_status}",
        )
    now = datetime.now(timezone.utc)
    from_status = order.status
    order.status = to_status
    if to_status == "PAYMENT_CONFIRMED":
        order.confirmed_at = now
    elif to_status == "ACCEPTED":
        order.accepted_at = now
    elif to_status == "PREPARING":
        order.preparing_at = now
    elif to_status == "READY":
        order.ready_at = now
    elif to_status == "COMPLETED":
        order.completed_at = now

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=from_status,
            to_status=to_status,
            changed_by_user_id=actor_user_id,
            reason=reason,
            metadata_json=metadata or {},
        )
    )
    return order


def cancel_or_reject_order(
    db: Session,
    order_id: UUID,
    *,
    cancellation_type: str,
    reason: str,
    actor_user_id: Optional[UUID],
    finance_note: Optional[str] = None,
    guest_access_token: Optional[str] = None,
    is_staff: bool = False,
) -> OrderOut:
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if not is_staff:
        if order.customer_id and order.customer_id != actor_user_id:
            raise HTTPException(status_code=403, detail="Not authorized to cancel this order")
        if order.is_guest:
            if not guest_access_token or order.guest_access_token_hash != sha256_hex(guest_access_token):
                raise HTTPException(status_code=403, detail="Valid guest access token required")

    target_status = "REJECTED" if cancellation_type == "rejected" else "CANCELLED"
    transition_order_status(db, order, target_status, actor_user_id=actor_user_id, reason=reason)

    # Release reserved slot if not yet fulfilled
    resv = db.scalar(select(SlotReservation).where(SlotReservation.order_id == order.id))
    if resv and resv.status == "reserved":
        resv.status = "released"
        slot = db.scalar(select(PickupSlot).where(PickupSlot.id == resv.pickup_slot_id).with_for_update())
        if slot and slot.reserved_count > 0:
            slot.reserved_count -= 1
            get_redis().decr(f"cb:slot:{slot.id}:reserved")

    # Payment is retained with ZERO automated refunds per policy
    db.add(
        OrderCancellation(
            order_id=order.id,
            cancellation_type=cancellation_type,
            reason=reason,
            cancelled_by_user_id=actor_user_id,
            payment_retained=True,
            finance_note=finance_note,
        )
    )
    record_audit_log(
        db,
        action=f"order.{cancellation_type}",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=actor_user_id,
        details={"reason": reason, "payment_retained": True, "refund_initiated": False},
    )
    db.commit()
    db.refresh(order)
    emit_order_event_sync(str(order.canteen_id), str(order.id), f"order.{target_status.lower()}", {"status": order.status})
    return serialize_order(db, order)


def get_order_authorized(
    db: Session,
    order_id_or_number: str,
    *,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    guest_access_token: Optional[str] = None,
) -> OrderOut:
    stmt = select(Order).options(
        selectinload(Order.items).selectinload(OrderItem.customizations),
        selectinload(Order.status_history),
    )
    try:
        oid = UUID(order_id_or_number)
        order = db.scalar(stmt.where(Order.id == oid))
    except ValueError:
        order = db.scalar(stmt.where(Order.order_number == order_id_or_number))

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if not is_staff:
        if order.is_guest:
            if not guest_access_token or order.guest_access_token_hash != sha256_hex(guest_access_token):
                raise HTTPException(status_code=403, detail="Valid guest access token required")
        elif order.customer_id != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to view this order")

    return serialize_order(db, order)
