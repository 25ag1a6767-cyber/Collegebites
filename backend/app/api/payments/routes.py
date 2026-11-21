from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_optional_principal,
    require_roles,
    scoped_canteen_for_principal,
)
from app.models.order import Order
from app.models.payment import Payment, PaymentReconciliation
from app.schemas.order import OrderOut
from app.schemas.payment import (
    CounterPaymentCollectRequest,
    PaymentOut,
    RazorpayFailureRequest,
    RazorpayVerifyRequest,
    ReconcileRequest,
    ReconciliationOut,
    StripeFailureRequest,
    StripeVerifyRequest,
)
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["Payments (No Refunds)"])


@router.post("/razorpay/verify", response_model=OrderOut)
def verify_razorpay(
    payload: RazorpayVerifyRequest,
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    return payment_service.verify_razorpay_checkout_payment(
        db, payload, actor_user_id=principal.user.id if principal else None
    )


@router.post("/razorpay/fail", response_model=OrderOut)
def fail_razorpay(
    payload: RazorpayFailureRequest,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER))
    staff_cid = None if (not is_staff or principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)) else principal.assigned_canteen_id
    return payment_service.record_razorpay_failure(
        db,
        payload,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        staff_canteen_id=staff_cid,
        guest_access_token=guest_token or x_guest_token,
    )


@router.post("/razorpay/webhook")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    return payment_service.handle_razorpay_webhook(db, raw_body, x_razorpay_signature)


@router.post("/stripe/verify", response_model=OrderOut)
def verify_stripe(
    payload: StripeVerifyRequest,
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    return payment_service.verify_stripe_checkout_payment(
        db, payload, actor_user_id=principal.user.id if principal else None
    )


@router.post("/stripe/fail", response_model=OrderOut)
def fail_stripe(
    payload: StripeFailureRequest,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER))
    staff_cid = None if (not is_staff or principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)) else principal.assigned_canteen_id
    return payment_service.record_stripe_failure(
        db,
        payload,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        staff_canteen_id=staff_cid,
        guest_access_token=guest_token or x_guest_token,
    )


class RetryPaymentRequest(BaseModel):
    payment_method: str = Field(default="razorpay", pattern="^(razorpay|stripe)$")


@router.post("/retry/{order_id}", response_model=OrderOut)
def retry_payment(
    order_id: UUID,
    payload: RetryPaymentRequest,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER))
    return payment_service.retry_online_payment(
        db,
        order_id,
        payload.payment_method,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        guest_access_token=guest_token or x_guest_token,
    )


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    return payment_service.handle_stripe_webhook(db, raw_body, stripe_signature)


@router.post("/counter/collect", response_model=OrderOut)
def collect_counter_payment(
    payload: CounterPaymentCollectRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER)
    ),
    db: Session = Depends(get_db),
):
    ord_row = db.get(Order, payload.order_id)
    if ord_row:
        enforce_canteen_scope(principal, ord_row.canteen_id)
    return payment_service.collect_counter_payment(db, payload, principal.user.id)


@router.get("", response_model=list[PaymentOut])
def list_payments(
    status: Optional[str] = Query(default=None),
    canteen_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER)
    ),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    stmt = select(Payment).order_by(Payment.created_at.desc()).limit(limit)
    if scoped_cid:
        stmt = stmt.join(Order, Order.id == Payment.order_id).where(Order.canteen_id == scoped_cid)
    if status:
        stmt = stmt.where(Payment.status == status)
    return list(db.scalars(stmt).all())


@router.post("/reconcile", response_model=ReconciliationOut)
def reconcile_payment(
    payload: ReconcileRequest,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return payment_service.reconcile_payment(db, payload, principal.user.id)


@router.get("/reconciliations", response_model=list[ReconciliationOut])
def list_reconciliations(
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(PaymentReconciliation).order_by(PaymentReconciliation.created_at.desc()).limit(200)).all())
