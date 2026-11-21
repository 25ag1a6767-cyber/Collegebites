from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    get_optional_principal,
    require_roles,
)
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
def fail_razorpay(payload: RazorpayFailureRequest, db: Session = Depends(get_db)):
    return payment_service.record_razorpay_failure(db, payload)


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
def fail_stripe(payload: StripeFailureRequest, db: Session = Depends(get_db)):
    return payment_service.record_stripe_failure(db, payload)


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
    return payment_service.collect_counter_payment(db, payload, principal.user.id)


@router.get("", response_model=list[PaymentOut])
def list_payments(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER)
    ),
    db: Session = Depends(get_db),
):
    stmt = select(Payment).order_by(Payment.created_at.desc()).limit(limit)
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
