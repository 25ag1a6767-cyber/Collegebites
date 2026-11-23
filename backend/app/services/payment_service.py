import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.redis_client import safe_redis
from app.core.security import sha256_hex
from app.core.time_utils import get_college_tz
from app.integrations.razorpay_client import razorpay_gateway
from app.integrations.stripe_client import stripe_gateway
from app.models.college import Canteen
from app.models.menu import FoodCategory, FoodItem, Recipe, RecipeIngredient
from app.models.order import Order, OrderItem, OrderStatusHistory, PickupSlot, SlotReservation
from app.models.payment import (
    Payment,
    PaymentReconciliation,
    PaymentTransaction,
    PaymentWebhookEvent,
)
from app.schemas.order import OrderOut
from app.schemas.payment import (
    CounterPaymentCollectRequest,
    RazorpayFailureRequest,
    RazorpayVerifyRequest,
    ReconcileRequest,
    StripeFailureRequest,
    StripeVerifyRequest,
)
from app.services import security_service
from app.services.audit_service import record_audit_log
from app.services.order_service import rollback_unpaid_incentives, serialize_order, transition_order_status
from app.services.receipt_service import create_receipt_for_order
from app.services.token_service import generate_token_and_qr_for_confirmed_order
from app.websockets import emit_order_event_sync


def _authorize_payment_actor(
    order: Order,
    *,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
    guest_access_token: Optional[str] = None,
    provider_order_id: Optional[str] = None,
    expected_provider_order_id: Optional[str] = None,
) -> None:
    if is_staff:
        if staff_canteen_id and order.canteen_id != staff_canteen_id:
            raise HTTPException(status_code=403, detail="Staff user is not authorized for this canteen")
        return
    if order.customer_id and user_id == order.customer_id:
        return
    if order.is_guest and guest_access_token and order.guest_access_token_hash == sha256_hex(guest_access_token):
        return
    if provider_order_id and expected_provider_order_id and provider_order_id == expected_provider_order_id:
        return
    if not user_id and not guest_access_token and not provider_order_id:
        raise HTTPException(status_code=401, detail="Authentication or guest access token required")
    raise HTTPException(status_code=403, detail="Not authorized to update payment state for this order")


def _finalize_confirmed_payment(
    db: Session,
    *,
    order: Order,
    payment: Payment,
    provider_payment_id: Optional[str],
    payment_method: Optional[str],
    payment_reference: str,
    actor_user_id: Optional[UUID],
    raw_summary: Optional[dict[str, Any]] = None,
) -> OrderOut:
    """
    Shared atomic finalization when payment is verified by Razorpay signature,
    Razorpay webhook, or authorized cashier counter collection.
    Idempotent across retries and duplicate webhook deliveries.
    """
    now = datetime.now(timezone.utc)
    if order.status in ("CANCELLED", "REJECTED", "PAYMENT_FAILED"):
        db.add(
            PaymentTransaction(
                payment_id=payment.id,
                order_id=order.id,
                transaction_type="late_capture_conflict",
                amount=payment.amount,
                status="CONFLICT",
                external_reference=payment_reference,
                raw_summary={"order_status": order.status, **(raw_summary or {})},
            )
        )
        record_audit_log(
            db,
            action="payment.late_conflict_retained",
            entity_type="order",
            entity_id=order.order_number,
            actor_user_id=actor_user_id,
            details={"order_status": order.status, "payment_reference": payment_reference},
        )
        security_service.create_security_alert(
            db,
            alert_type="duplicate_payment_callback",
            severity="high",
            title=f"Late payment capture on terminal order {order.order_number}",
            description=f"Captured payment callback ({payment_reference}) arrived for {order.status} order {order.order_number}. Retained under no-refund ledger conflict review.",
            canteen_id=order.canteen_id,
            order_id=order.id,
            metadata={"order_status": order.status, "payment_reference": payment_reference},
            dedupe_minutes=15,
        )
        db.commit()
        raise HTTPException(
            status_code=409,
            detail=f"Order {order.order_number} is already {order.status}; token cannot be issued.",
        )

    if provider_payment_id:
        dup_pay = db.scalar(
            select(Payment).where(
                Payment.provider_payment_id == provider_payment_id,
                Payment.id != payment.id,
            )
        )
        if dup_pay:
            security_service.create_security_alert(
                db,
                alert_type="duplicate_payment_callback",
                severity="high",
                title=f"Duplicate payment reference {provider_payment_id} blocked",
                description=f"Payment reference {provider_payment_id} was submitted for order {order.order_number} but belongs to payment {dup_pay.id}.",
                canteen_id=order.canteen_id,
                order_id=order.id,
                metadata={"existing_payment_id": str(dup_pay.id), "provider_payment_id": provider_payment_id},
            )
            db.commit()
            raise HTTPException(status_code=409, detail="Payment reference already used for another order")

    if payment.status == "CONFIRMED" and order.payment_status == "CONFIRMED":
        # Already finalized cleanly; ensure token/QR/receipt exist and return without duplicating
        token, qr = generate_token_and_qr_for_confirmed_order(db, order)
        create_receipt_for_order(db, order, token, qr, payment)
        db.commit()
        db.expire_all()
        loaded = db.scalar(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
            .where(Order.id == order.id)
        )
        return serialize_order(db, loaded)

    payment.status = "CONFIRMED"
    if provider_payment_id:
        payment.provider_payment_id = provider_payment_id
    if payment_method:
        payment.method = payment_method
    payment.payment_reference = payment_reference
    payment.confirmed_at = now
    payment.recorded_by_user_id = actor_user_id

    db.add(
        PaymentTransaction(
            payment_id=payment.id,
            order_id=order.id,
            transaction_type="capture" if payment.provider in ("razorpay", "stripe") else "cash_collect",
            amount=payment.amount,
            status="CONFIRMED",
            external_reference=payment_reference,
            raw_summary=raw_summary or {},
        )
    )

    order.payment_status = "CONFIRMED"
    order.payment_method = payment.method or order.payment_method
    if order.status in ("CREATED", "PAYMENT_PENDING"):
        transition_order_status(db, order, "PAYMENT_CONFIRMED", actor_user_id=actor_user_id, reason="Payment verified on backend")
    if order.status == "PAYMENT_CONFIRMED":
        transition_order_status(db, order, "PLACED", actor_user_id=actor_user_id, reason="Order dispatched to canteen kitchen")

    token, qr = generate_token_and_qr_for_confirmed_order(db, order)
    create_receipt_for_order(db, order, token, qr, payment)

    # Deduct inventory idempotently (service defined in inventory_service when available)
    try:
        from app.services.inventory_service import deduct_inventory_for_order
        deduct_inventory_for_order(db, order, actor_user_id=actor_user_id)
    except ImportError:
        pass

    # Create notification if notification service available
    try:
        from app.services.notification_service import notify_order_confirmed
        notify_order_confirmed(db, order, token.token_code)
    except ImportError:
        pass

    record_audit_log(
        db,
        action="payment.confirmed",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=actor_user_id,
        details={
            "payment_id": str(payment.id),
            "payment_reference": payment_reference,
            "pickup_token": token.token_code,
            "amount": str(payment.amount),
        },
    )
    db.commit()
    db.expire_all()

    emit_order_event_sync(
        str(order.canteen_id),
        str(order.id),
        "order.placed",
        {"order_number": order.order_number, "pickup_token": token.token_code, "status": "PLACED"},
    )

    loaded = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order.id)
    )
    return serialize_order(db, loaded)


def _record_invalid_webhook_and_alert(
    db: Session,
    *,
    provider: str,
    raw_body: bytes,
    reason: str,
) -> None:
    parsed_snippet: dict[str, Any] = {}
    try:
        raw_obj = json.loads(raw_body.decode("utf-8", errors="ignore"))
        if isinstance(raw_obj, dict):
            parsed_snippet = {
                "event": raw_obj.get("event") or raw_obj.get("type"),
                "event_id": raw_obj.get("event_id") or raw_obj.get("id"),
            }
    except Exception:
        parsed_snippet = {"raw_preview": raw_body[:300].decode("utf-8", errors="ignore")}

    evt_id = f"invalid_{provider}_{uuid4().hex[:12]}"
    db.add(
        PaymentWebhookEvent(
            provider=provider,
            event_id=evt_id,
            event_type=str(parsed_snippet.get("event") or "invalid_signature")[:120],
            signature_verified=False,
            processed=False,
            processing_error=reason[:500],
            payload=parsed_snippet,
        )
    )
    security_service.create_security_alert(
        db,
        alert_type="webhook_signature_invalid",
        severity="high",
        title=f"Invalid {provider.title()} webhook signature rejected",
        description=f"Webhook callback failed cryptographic verification: {reason}",
        metadata={"provider": provider, **parsed_snippet},
        dedupe_minutes=10,
    )
    db.commit()


def _resolve_payment_by_provider_order(
    db: Session, *, provider_order_id: str, provider: Optional[str] = None
) -> Optional[Payment]:
    stmt = select(Payment).where(Payment.provider_order_id == provider_order_id)
    if provider:
        stmt = stmt.where(Payment.provider == provider)
    row = db.scalar(stmt)
    if row:
        return row
    tx = db.scalar(
        select(PaymentTransaction)
        .where(PaymentTransaction.external_reference == provider_order_id)
        .order_by(PaymentTransaction.created_at.desc())
    )
    return db.get(Payment, tx.payment_id) if tx else None


def _validate_gateway_amount_currency(
    db: Session,
    *,
    order: Order,
    payment: Payment,
    amount_paise: Optional[Any],
    currency: Optional[str],
    source: str,
    gateway_ref: Optional[str],
) -> bool:
    expected_paise = int((payment.amount * 100).quantize(Decimal("1")))
    expected_currency = (payment.currency or "INR").upper()
    mismatch_type: Optional[str] = None
    settled_dec = payment.amount
    detail_msg = ""

    if amount_paise is not None:
        try:
            actual_paise = int(amount_paise)
            settled_dec = (Decimal(actual_paise) / Decimal("100")).quantize(Decimal("0.01"))
            if actual_paise < expected_paise:
                mismatch_type = "amount_mismatch"
                detail_msg = f"Paid ₹{settled_dec} is less than expected ₹{payment.amount}"
        except (TypeError, ValueError):
            pass

    if currency and str(currency).upper() != expected_currency:
        mismatch_type = mismatch_type or "currency_mismatch"
        detail_msg = f"Gateway currency {currency} does not match expected {expected_currency}"

    if not mismatch_type:
        return True

    discrepancy = (payment.amount - settled_dec).quantize(Decimal("0.01"))
    db.add(
        PaymentTransaction(
            payment_id=payment.id,
            order_id=order.id,
            transaction_type="amount_mismatch",
            amount=settled_dec,
            status="DISCREPANCY",
            external_reference=gateway_ref,
            raw_summary={"source": source, "reason": detail_msg, "currency": currency},
        )
    )
    existing_rec = db.scalar(select(PaymentReconciliation).where(PaymentReconciliation.payment_id == payment.id))
    if existing_rec:
        existing_rec.settled_amount = settled_dec
        existing_rec.discrepancy_amount = discrepancy
        existing_rec.status = "discrepancy"
        existing_rec.discrepancy_type = mismatch_type
        existing_rec.reconciliation_source = source
        existing_rec.gateway_provider = payment.provider
        existing_rec.gateway_reference = gateway_ref
        existing_rec.notes = detail_msg
    else:
        db.add(
            PaymentReconciliation(
                payment_id=payment.id,
                order_id=order.id,
                gateway_provider=payment.provider,
                gateway_reference=gateway_ref,
                expected_amount=payment.amount,
                settled_amount=settled_dec,
                discrepancy_amount=discrepancy,
                status="discrepancy",
                reconciliation_source=source,
                discrepancy_type=mismatch_type,
                notes=detail_msg,
            )
        )
    security_service.create_security_alert(
        db,
        alert_type="payment_amount_mismatch",
        severity="high",
        title=f"Payment discrepancy on {order.order_number}",
        description=detail_msg,
        canteen_id=order.canteen_id,
        order_id=order.id,
        metadata={"expected": str(payment.amount), "received": str(settled_dec), "source": source},
    )
    db.commit()
    return False


def verify_razorpay_checkout_payment(
    db: Session, payload: RazorpayVerifyRequest, actor_user_id: Optional[UUID] = None
) -> OrderOut:
    order = db.scalar(select(Order).where(Order.id == payload.order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    payment = db.scalar(
        select(Payment).where(Payment.order_id == order.id, Payment.provider == "razorpay").with_for_update()
    )
    if not payment or payment.provider_order_id != payload.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Razorpay order reference does not match this order")

    _authorize_payment_actor(
        order,
        user_id=actor_user_id,
        provider_order_id=payload.razorpay_order_id,
        expected_provider_order_id=payment.provider_order_id,
    )

    if not razorpay_gateway.verify_payment_signature(
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    ):
        db.add(
            PaymentTransaction(
                payment_id=payment.id,
                order_id=order.id,
                transaction_type="authorize",
                amount=payment.amount,
                status="FAILED",
                external_reference=payload.razorpay_payment_id,
                raw_summary={"error": "signature_verification_failed"},
            )
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid Razorpay payment signature")

    if razorpay_gateway.use_live_api:
        gw_pay = razorpay_gateway.fetch_payment(payload.razorpay_payment_id)
        if gw_pay:
            ok_amt = _validate_gateway_amount_currency(
                db,
                order=order,
                payment=payment,
                amount_paise=gw_pay.get("amount"),
                currency=gw_pay.get("currency"),
                source="gateway_verify",
                gateway_ref=payload.razorpay_payment_id,
            )
            if not ok_amt:
                raise HTTPException(status_code=400, detail="Gateway payment amount or currency does not match order total")

    return _finalize_confirmed_payment(
        db,
        order=order,
        payment=payment,
        provider_payment_id=payload.razorpay_payment_id,
        payment_method=payload.payment_method or "upi",
        payment_reference=payload.razorpay_payment_id,
        actor_user_id=actor_user_id or order.customer_id,
        raw_summary={"method": payload.payment_method, "razorpay_order_id": payload.razorpay_order_id},
    )


def handle_razorpay_webhook(db: Session, raw_body: bytes, x_razorpay_signature: Optional[str]) -> dict[str, Any]:
    if not x_razorpay_signature or not razorpay_gateway.verify_webhook_signature(
        raw_body=raw_body, x_razorpay_signature=x_razorpay_signature
    ):
        _record_invalid_webhook_and_alert(
            db,
            provider="razorpay",
            raw_body=raw_body,
            reason="Missing or invalid X-Razorpay-Signature header",
        )
        raise HTTPException(status_code=400, detail="Invalid Razorpay webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        _record_invalid_webhook_and_alert(
            db,
            provider="razorpay",
            raw_body=raw_body,
            reason="Malformed Razorpay webhook JSON payload",
        )
        raise HTTPException(status_code=400, detail="Malformed Razorpay webhook JSON payload") from exc
    event_type = payload.get("event", "unknown")
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    event_id = payload.get("event_id") or f"{event_type}:{payment_entity.get('id', 'none')}"

    existing_evt = db.scalar(
        select(PaymentWebhookEvent).where(
            PaymentWebhookEvent.provider == "razorpay", PaymentWebhookEvent.event_id == event_id
        )
    )
    if existing_evt and existing_evt.processed:
        return {"status": "already_processed", "event_id": event_id}

    evt = existing_evt or PaymentWebhookEvent(
        provider="razorpay",
        event_id=event_id,
        event_type=event_type,
        signature_verified=True,
        processed=False,
        payload=payload,
    )
    if not existing_evt:
        db.add(evt)
        db.flush()

    rzp_order_id = payment_entity.get("order_id")
    rzp_payment_id = payment_entity.get("id")
    if event_type in ("payment.captured", "order.paid") and rzp_order_id:
        pay_row_ro = _resolve_payment_by_provider_order(db, provider_order_id=rzp_order_id, provider="razorpay")
        if pay_row_ro:
            # Always acquire Order lock BEFORE Payment lock to avoid deadlocks with verify endpoint
            order = db.scalar(select(Order).where(Order.id == pay_row_ro.order_id).with_for_update())
            payment = db.scalar(select(Payment).where(Payment.id == pay_row_ro.id).with_for_update())
            if order and payment:
                ok_amt = _validate_gateway_amount_currency(
                    db,
                    order=order,
                    payment=payment,
                    amount_paise=payment_entity.get("amount"),
                    currency=payment_entity.get("currency"),
                    source="webhook",
                    gateway_ref=rzp_payment_id or rzp_order_id,
                )
                if not ok_amt:
                    evt.processed = True
                    evt.processing_error = "amount_or_currency_mismatch"
                    evt.processed_at = datetime.now(timezone.utc)
                    db.commit()
                    return {"status": "discrepancy_flagged", "event_id": event_id}

                evt.processed = True
                evt.processed_at = datetime.now(timezone.utc)
                if order.status in ("CANCELLED", "REJECTED", "PAYMENT_FAILED"):
                    db.commit()
                    return {"status": "ignored_terminal_order", "event_id": event_id}
                _finalize_confirmed_payment(
                    db,
                    order=order,
                    payment=payment,
                    provider_payment_id=rzp_payment_id,
                    payment_method=payment_entity.get("method", "razorpay"),
                    payment_reference=rzp_payment_id or rzp_order_id,
                    actor_user_id=order.customer_id,
                    raw_summary={"webhook_event": event_type, "method": payment_entity.get("method")},
                )
                return {"status": "processed", "event_id": event_id}

    elif event_type == "payment.failed" and rzp_order_id:
        pay_row_ro = _resolve_payment_by_provider_order(db, provider_order_id=rzp_order_id, provider="razorpay")
        if pay_row_ro:
            order = db.scalar(select(Order).where(Order.id == pay_row_ro.order_id).with_for_update())
            payment = db.scalar(select(Payment).where(Payment.id == pay_row_ro.id).with_for_update())
            if payment and payment.status == "PENDING" and order and order.status == "PAYMENT_PENDING":
                evt.processed = True
                evt.processed_at = datetime.now(timezone.utc)
                mark_payment_failed(db, order=order, payment=payment, reason=payment_entity.get("error_description") or "Webhook payment failed")
                return {"status": "processed", "event_id": event_id}

    evt.processed = True
    evt.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "processed", "event_id": event_id}


def mark_payment_failed(db: Session, *, order: Order, payment: Payment, reason: str) -> Order:
    if payment.status == "CONFIRMED":
        raise HTTPException(status_code=409, detail="Cannot mark an already confirmed payment as failed")
    was_pending = order.status in ("CREATED", "PAYMENT_PENDING")
    payment.status = "FAILED"
    payment.failure_reason = reason
    order.payment_status = "FAILED"
    if was_pending:
        transition_order_status(db, order, "PAYMENT_FAILED", reason=reason)
        try:
            from app.services.inventory_service import release_inventory_reservation_for_order
            release_inventory_reservation_for_order(db, order)
        except ImportError:
            pass
    rollback_unpaid_incentives(db, order)

    # Release reserved slot
    resv = db.scalar(select(SlotReservation).where(SlotReservation.order_id == order.id))
    if resv and resv.status == "reserved":
        resv.status = "released"
        slot = db.scalar(select(PickupSlot).where(PickupSlot.id == resv.pickup_slot_id).with_for_update())
        if slot and slot.reserved_count > 0:
            slot.reserved_count -= 1
            safe_redis(lambda r: r.decr(f"cb:slot:{slot.id}:reserved"))

    db.add(
        PaymentTransaction(
            payment_id=payment.id,
            order_id=order.id,
            transaction_type="fail",
            amount=payment.amount,
            status="FAILED",
            raw_summary={"reason": reason},
        )
    )
    db.commit()
    return order


def record_razorpay_failure(
    db: Session,
    payload: RazorpayFailureRequest,
    *,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
    guest_access_token: Optional[str] = None,
) -> OrderOut:
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == payload.order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id).with_for_update())
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found")
    _authorize_payment_actor(
        order,
        user_id=user_id,
        is_staff=is_staff,
        staff_canteen_id=staff_canteen_id,
        guest_access_token=guest_access_token,
        provider_order_id=payload.razorpay_order_id,
        expected_provider_order_id=payment.provider_order_id,
    )
    mark_payment_failed(db, order=order, payment=payment, reason=payload.reason)
    db.expire_all()
    loaded = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order.id)
    )
    return serialize_order(db, loaded)


def verify_stripe_checkout_payment(
    db: Session, payload: StripeVerifyRequest, actor_user_id: Optional[UUID] = None
) -> OrderOut:
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == payload.order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    payment = db.scalar(
        select(Payment).where(Payment.order_id == order.id, Payment.provider == "stripe").with_for_update()
    )
    if not payment or not payment.provider_order_id:
        raise HTTPException(status_code=400, detail="Stripe payment record not found for this order")

    ref_pi = (payload.stripe_payment_intent_id or "").strip() or None
    ref_sess = (payload.stripe_session_id or "").strip() or None
    if not ref_pi and not ref_sess:
        raise HTTPException(status_code=400, detail="Provide stripe_payment_intent_id or stripe_session_id")

    is_pi_order = payment.provider_order_id.startswith("pi_")
    if is_pi_order:
        if ref_pi != payment.provider_order_id:
            raise HTTPException(status_code=400, detail="Stripe PaymentIntent reference does not match this order")
        intent_id = payment.provider_order_id
    else:
        if ref_sess != payment.provider_order_id and ref_pi != payment.provider_order_id:
            raise HTTPException(status_code=400, detail="Stripe session reference does not match this order")
        intent_id = ref_pi or payment.provider_order_id

    if payment.status == "CONFIRMED" and order.payment_status == "CONFIRMED":
        return serialize_order(db, order)
    if order.status in ("CANCELLED", "REJECTED", "PAYMENT_FAILED"):
        raise HTTPException(status_code=409, detail=f"Cannot verify payment for {order.status} order")

    if stripe_gateway.use_live_api:
        if is_pi_order:
            pi_obj = stripe_gateway.retrieve_payment_intent(intent_id)
            pi_status = pi_obj.get("status")
            if pi_status == "processing":
                db.add(
                    PaymentTransaction(
                        payment_id=payment.id,
                        order_id=order.id,
                        transaction_type="processing",
                        amount=payment.amount,
                        status="PENDING",
                        external_reference=intent_id,
                        raw_summary={"stripe_status": "processing"},
                    )
                )
                db.commit()
                return serialize_order(db, order)
            if pi_status != "succeeded":
                err_detail = pi_obj.get("last_payment_error") or f"Stripe payment status is {pi_status}, not succeeded"
                db.add(
                    PaymentTransaction(
                        payment_id=payment.id,
                        order_id=order.id,
                        transaction_type="authorize",
                        amount=payment.amount,
                        status="FAILED",
                        external_reference=intent_id,
                        raw_summary={"stripe_status": pi_status, "error": err_detail},
                    )
                )
                db.commit()
                raise HTTPException(status_code=400, detail=err_detail)
            expected_paise = int((payment.amount * 100).quantize(Decimal("1")))
            received_paise = int(pi_obj.get("amount_received") or pi_obj.get("amount") or 0)
            if received_paise < expected_paise:
                raise HTTPException(status_code=400, detail="Stripe received amount is less than order total")
        else:
            session_obj = stripe_gateway.retrieve_checkout_session(payment.provider_order_id)
            if session_obj.get("payment_status") != "paid":
                raise HTTPException(status_code=400, detail="Stripe checkout session is not marked as paid")
            intent_id = session_obj.get("payment_intent") or intent_id
    else:
        if not payload.stripe_signature or not stripe_gateway.verify_test_payment_signature(
            stripe_payment_intent_id=intent_id,
            stripe_session_id=ref_sess,
            stripe_signature=payload.stripe_signature,
        ):
            db.add(
                PaymentTransaction(
                    payment_id=payment.id,
                    order_id=order.id,
                    transaction_type="authorize",
                    amount=payment.amount,
                    status="FAILED",
                    external_reference=intent_id,
                    raw_summary={"error": "stripe_signature_verification_failed"},
                )
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid Stripe payment signature")

    return _finalize_confirmed_payment(
        db,
        order=order,
        payment=payment,
        provider_payment_id=intent_id,
        payment_method=payload.payment_method or "card",
        payment_reference=intent_id,
        actor_user_id=actor_user_id or order.customer_id,
        raw_summary={
            "method": payload.payment_method or "card",
            "stripe_payment_intent_id": intent_id,
            "stripe_session_id": ref_sess,
        },
    )


def handle_stripe_webhook(db: Session, raw_body: bytes, stripe_signature_header: Optional[str]) -> dict[str, Any]:
    if not stripe_signature_header:
        _record_invalid_webhook_and_alert(
            db,
            provider="stripe",
            raw_body=raw_body,
            reason="Missing Stripe-Signature header",
        )
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")

    try:
        payload = stripe_gateway.construct_webhook_event(
            raw_body=raw_body, stripe_signature_header=stripe_signature_header
        )
    except HTTPException as exc:
        _record_invalid_webhook_and_alert(
            db,
            provider="stripe",
            raw_body=raw_body,
            reason=str(exc.detail),
        )
        raise
    event_type = payload.get("type", "unknown")
    event_id = payload.get("id") or f"evt_stripe_{event_type}"
    obj = payload.get("data", {}).get("object", {})

    existing_evt = db.scalar(
        select(PaymentWebhookEvent).where(
            PaymentWebhookEvent.provider == "stripe", PaymentWebhookEvent.event_id == event_id
        )
    )
    if existing_evt and existing_evt.processed:
        return {"status": "already_processed", "event_id": event_id}

    evt = existing_evt or PaymentWebhookEvent(
        provider="stripe",
        event_id=event_id,
        event_type=event_type,
        signature_verified=True,
        processed=False,
        payload=payload,
    )
    if not existing_evt:
        db.add(evt)
        db.flush()

    pay_ro: Optional[Payment] = None
    if event_type.startswith("payment_intent."):
        pi_id = obj.get("id")
        if pi_id:
            pay_ro = db.scalar(
                select(Payment).where(Payment.provider == "stripe", Payment.provider_order_id == pi_id)
            )
    elif event_type.startswith("checkout.session."):
        session_id = obj.get("id")
        if session_id:
            pay_ro = db.scalar(
                select(Payment).where(Payment.provider == "stripe", Payment.provider_order_id == session_id)
            )

    if pay_ro:
        order = db.scalar(select(Order).where(Order.id == pay_ro.order_id).with_for_update())
        payment = db.scalar(select(Payment).where(Payment.id == pay_ro.id).with_for_update())
        if order and payment:
            if event_type in ("payment_intent.succeeded", "checkout.session.completed"):
                pi_id = obj.get("id") if event_type == "payment_intent.succeeded" else (obj.get("payment_intent") or obj.get("id"))
                amt_val = obj.get("amount_received") if obj.get("amount_received") is not None else (obj.get("amount") or obj.get("amount_total"))
                if not _validate_gateway_amount_currency(
                    db,
                    order=order,
                    payment=payment,
                    amount_paise=amt_val,
                    currency=obj.get("currency"),
                    source="webhook",
                    gateway_ref=pi_id,
                ):
                    evt.processed = True
                    evt.processing_error = "amount_or_currency_mismatch"
                    evt.processed_at = datetime.now(timezone.utc)
                    db.commit()
                    return {"status": "discrepancy_flagged", "event_id": event_id}
            evt.processed = True
            evt.processed_at = datetime.now(timezone.utc)
            if event_type in ("payment_intent.succeeded", "checkout.session.completed"):
                if order.status in ("CANCELLED", "REJECTED", "PAYMENT_FAILED"):
                    db.commit()
                    return {"status": "ignored_terminal_order", "event_id": event_id}
                pi_id = obj.get("id") if event_type == "payment_intent.succeeded" else (obj.get("payment_intent") or obj.get("id"))
                _finalize_confirmed_payment(
                    db,
                    order=order,
                    payment=payment,
                    provider_payment_id=pi_id,
                    payment_method="stripe",
                    payment_reference=pi_id,
                    actor_user_id=order.customer_id,
                    raw_summary={"webhook_event": event_type, "stripe_id": obj.get("id")},
                )
                return {"status": "processed", "event_id": event_id}

            if event_type == "payment_intent.processing":
                db.add(
                    PaymentTransaction(
                        payment_id=payment.id,
                        order_id=order.id,
                        transaction_type="processing",
                        amount=payment.amount,
                        status="PENDING",
                        external_reference=obj.get("id"),
                        raw_summary={"webhook_event": event_type},
                    )
                )
                db.commit()
                return {"status": "processed", "event_id": event_id}

            if event_type in ("checkout.session.expired", "payment_intent.payment_failed", "payment_intent.canceled"):
                if payment.status == "PENDING" and order.status == "PAYMENT_PENDING":
                    err_msg = (
                        (obj.get("last_payment_error") or {}).get("message")
                        or obj.get("cancellation_reason")
                        or f"Stripe webhook {event_type}"
                    )
                    mark_payment_failed(db, order=order, payment=payment, reason=err_msg[:255])
                    return {"status": "processed", "event_id": event_id}
                db.commit()
                return {"status": "ignored_non_pending", "event_id": event_id}

    evt.processed = True
    evt.processed_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "processed", "event_id": event_id}


def record_stripe_failure(
    db: Session,
    payload: StripeFailureRequest,
    *,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
    guest_access_token: Optional[str] = None,
) -> OrderOut:
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == payload.order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    payment = db.scalar(select(Payment).where(Payment.order_id == order.id).with_for_update())
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found")
    _authorize_payment_actor(
        order,
        user_id=user_id,
        is_staff=is_staff,
        staff_canteen_id=staff_canteen_id,
        guest_access_token=guest_access_token,
        provider_order_id=payload.stripe_payment_intent_id or payload.stripe_session_id,
        expected_provider_order_id=payment.provider_order_id,
    )
    mark_payment_failed(db, order=order, payment=payment, reason=payload.reason)
    db.expire_all()
    loaded = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order.id)
    )
    return serialize_order(db, loaded)


def retry_online_payment(
    db: Session,
    order_id: UUID,
    method: str,
    *,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    guest_access_token: Optional[str] = None,
) -> OrderOut:
    if method not in ("razorpay", "stripe"):
        raise HTTPException(status_code=400, detail="Only razorpay or stripe can be retried online")
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _authorize_payment_actor(order, user_id=user_id, is_staff=is_staff, guest_access_token=guest_access_token)
    if order.payment_status == "CONFIRMED":
        return serialize_order(db, order)
    if order.status in ("CANCELLED", "REJECTED"):
        raise HTTPException(status_code=409, detail="Cancelled or rejected orders cannot be retried")

    canteen = db.get(Canteen, order.canteen_id)
    if not canteen or not canteen.allow_online_payment:
        raise HTTPException(status_code=400, detail="Online payment is disabled for this canteen")

    # Validate current availability & schedule before retrying payment
    from app.services.menu_service import compute_schedule_availability_map

    food_ids = [oi.food_item_id for oi in order.items if oi.food_item_id]
    food_map = {f.id: f for f in db.scalars(select(FoodItem).where(FoodItem.id.in_(food_ids))).all()} if food_ids else {}
    slot_target_dt = None
    if order.pickup_slot_id:
        ps = db.get(PickupSlot, order.pickup_slot_id)
        if ps:
            slot_target_dt = datetime.combine(ps.slot_date, ps.start_time, tzinfo=get_college_tz())
    sched_map = compute_schedule_availability_map(db, food_ids, target_dt=slot_target_dt, food_items_map=food_map)
    needed_ingredients: dict[UUID, Decimal] = {}
    for oi in order.items:
        if not oi.food_item_id:
            continue
        food = food_map.get(oi.food_item_id)
        if not food or not food.is_active:
            raise HTTPException(status_code=400, detail=f"{oi.item_name} is no longer available")
        cat = db.get(FoodCategory, food.category_id)
        if not cat or not cat.is_active:
            raise HTTPException(status_code=400, detail=f"{oi.item_name}'s category is currently inactive")
        if not food.is_available or food.insufficient_ingredients:
            raise HTTPException(status_code=400, detail=f"{food.name} is currently out of stock or unavailable")
        if not sched_map.get(food.id, True):
            raise HTTPException(status_code=400, detail=f"{food.name} is outside its scheduled serving hours or validity period")
        recipe = db.scalar(select(Recipe).where(Recipe.food_item_id == food.id))
        if recipe:
            for req in db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)).all():
                per_unit = (req.quantity_required * Decimal(oi.quantity)) / Decimal(max(1, recipe.yield_portions))
                needed_ingredients[req.ingredient_id] = needed_ingredients.get(req.ingredient_id, Decimal("0.000")) + per_unit

    if order.status == "PAYMENT_FAILED":
        if needed_ingredients:
            from app.services.inventory_service import reserve_inventory_for_order
            reserve_inventory_for_order(db, order.canteen_id, needed_ingredients)
        order.status = "PAYMENT_PENDING"
        order.payment_status = "PENDING"
        db.add(OrderStatusHistory(order_id=order.id, from_status="PAYMENT_FAILED", to_status="PAYMENT_PENDING", changed_by_user_id=user_id, reason="Customer initiated online payment retry"))

    order.payment_method = method
    provider_order_id = None
    gateway_meta: dict[str, Any] = {}
    if method == "razorpay":
        rzp = razorpay_gateway.create_order(amount_inr=order.total_amount, receipt_ref=f"{order.order_number}-R", notes={"order_number": order.order_number})
        provider_order_id = rzp["id"]
    else:
        pi = stripe_gateway.create_payment_intent(
            amount_inr=order.total_amount,
            order_number=order.order_number,
            idempotency_key=f"cb-retry-{order.id}-{int(datetime.now(timezone.utc).timestamp())}",
            metadata={"order_id": str(order.id), "retry": "true"},
        )
        provider_order_id = pi["id"]
        gateway_meta = {
            "payment_intent_id": pi["id"],
            "client_secret": pi.get("client_secret"),
        }

    payment = db.scalar(select(Payment).where(Payment.order_id == order.id).with_for_update())
    if not payment:
        payment = Payment(
            order_id=order.id,
            provider=method,
            method=method,
            provider_order_id=provider_order_id,
            amount=order.total_amount,
            currency="INR",
            status="PENDING",
            gateway_metadata=gateway_meta,
        )
        db.add(payment)
    else:
        existing_meta = dict(payment.gateway_metadata or {})
        prev_orders = list(existing_meta.get("previous_provider_orders") or [])
        if payment.provider_order_id and payment.provider_order_id != provider_order_id:
            prev_orders.append(
                {
                    "provider": payment.provider,
                    "provider_order_id": payment.provider_order_id,
                    "replaced_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        if prev_orders:
            gateway_meta["previous_provider_orders"] = prev_orders[-10:]
        payment.provider = method
        payment.method = method
        payment.provider_order_id = provider_order_id
        payment.status = "PENDING"
        payment.failure_reason = None
        payment.gateway_metadata = gateway_meta
    db.flush()
    db.add(PaymentTransaction(payment_id=payment.id, order_id=order.id, transaction_type="retry_initiate", amount=order.total_amount, status="PENDING", external_reference=provider_order_id))
    db.commit()
    db.expire_all()
    loaded = db.scalar(select(Order).options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history)).where(Order.id == order.id))
    return serialize_order(db, loaded)


def collect_counter_payment(db: Session, payload: CounterPaymentCollectRequest, cashier_user_id: UUID) -> OrderOut:
    if payload.payment_method in ("cash", "pay_at_pickup"):
        raise HTTPException(status_code=400, detail="Cash and Pay-at-Pickup are disabled. Collect via UPI POS or Card POS.")
    order = db.scalar(select(Order).where(Order.id == payload.order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status in ("CANCELLED", "REJECTED", "PAYMENT_FAILED"):
        raise HTTPException(status_code=409, detail=f"Cannot collect payment for {order.status} order")

    payment = db.scalar(select(Payment).where(Payment.order_id == order.id).with_for_update())
    if not payment:
        payment = Payment(order_id=order.id, provider="counter_pos", method=payload.payment_method, amount=order.total_amount, status="PENDING")
        db.add(payment)
        db.flush()

    ref = payload.external_reference or f"POS-{order.order_number}"
    return _finalize_confirmed_payment(
        db,
        order=order,
        payment=payment,
        provider_payment_id=ref,
        payment_method=payload.payment_method,
        payment_reference=ref,
        actor_user_id=cashier_user_id,
        raw_summary={"collected_by": str(cashier_user_id), "method": payload.payment_method},
    )


def reconcile_payment(db: Session, payload: ReconcileRequest, actor_user_id: UUID) -> PaymentReconciliation:
    payment = db.get(Payment, payload.payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    discrepancy = (payment.amount - payload.settled_amount).quantize(Decimal("0.01"))
    rec_status = "matched" if discrepancy == Decimal("0.00") else "discrepancy"
    disc_type = "none" if discrepancy == Decimal("0.00") else "amount_mismatch"
    now = datetime.now(timezone.utc)

    rec = db.scalar(select(PaymentReconciliation).where(PaymentReconciliation.payment_id == payment.id))
    if rec:
        rec.gateway_provider = payment.provider
        rec.gateway_settlement_id = payload.gateway_settlement_id or rec.gateway_settlement_id
        rec.gateway_reference = payment.payment_reference or payment.provider_order_id
        rec.expected_amount = payment.amount
        rec.settled_amount = payload.settled_amount
        rec.discrepancy_amount = discrepancy
        rec.gateway_fee = payload.gateway_fee
        rec.status = rec_status
        rec.reconciliation_source = "manual"
        rec.discrepancy_type = disc_type
        rec.reconciled_at = now
        rec.reconciled_by_user_id = actor_user_id
        rec.notes = payload.notes
    else:
        rec = PaymentReconciliation(
            payment_id=payment.id,
            order_id=payment.order_id,
            gateway_provider=payment.provider,
            gateway_settlement_id=payload.gateway_settlement_id,
            gateway_reference=payment.payment_reference or payment.provider_order_id,
            expected_amount=payment.amount,
            settled_amount=payload.settled_amount,
            discrepancy_amount=discrepancy,
            gateway_fee=payload.gateway_fee,
            status=rec_status,
            reconciliation_source="manual",
            discrepancy_type=disc_type,
            reconciled_at=now,
            reconciled_by_user_id=actor_user_id,
            notes=payload.notes,
        )
        db.add(rec)

    record_audit_log(
        db,
        action="payment.reconciled",
        entity_type="payment",
        entity_id=str(payment.id),
        actor_user_id=actor_user_id,
        details={
            "status": rec_status,
            "discrepancy": str(discrepancy),
            "settlement_id": payload.gateway_settlement_id,
        },
    )
    db.commit()
    db.refresh(rec)
    return rec
