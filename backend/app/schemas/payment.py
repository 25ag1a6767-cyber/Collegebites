from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class RazorpayVerifyRequest(BaseModel):
    order_id: UUID
    razorpay_order_id: str = Field(min_length=4, max_length=120)
    razorpay_payment_id: str = Field(min_length=4, max_length=120)
    razorpay_signature: str = Field(min_length=8, max_length=256)
    payment_method: Optional[str] = Field(default="upi")


class RazorpayFailureRequest(BaseModel):
    order_id: UUID
    razorpay_order_id: Optional[str] = None
    reason: str = Field(default="Payment cancelled or failed at gateway", max_length=255)


class StripeVerifyRequest(BaseModel):
    order_id: UUID
    stripe_payment_intent_id: Optional[str] = Field(default=None, min_length=4, max_length=160)
    stripe_session_id: Optional[str] = Field(default=None, min_length=4, max_length=160)
    stripe_signature: Optional[str] = Field(default=None, max_length=256)
    payment_method: Optional[str] = Field(default="card")


class StripeFailureRequest(BaseModel):
    order_id: UUID
    stripe_payment_intent_id: Optional[str] = None
    stripe_session_id: Optional[str] = None
    reason: str = Field(default="Stripe checkout cancelled or failed", max_length=255)


class CounterPaymentCollectRequest(BaseModel):
    order_id: UUID
    payment_method: str = Field(default="upi_pos", pattern="^(upi_pos|card_pos|cash|pay_at_pickup)$")
    external_reference: Optional[str] = Field(default=None, max_length=120)


class PaymentOut(ORMModel):
    id: UUID
    order_id: UUID
    provider: str
    method: Optional[str]
    provider_order_id: Optional[str]
    provider_payment_id: Optional[str]
    amount: Decimal
    currency: str
    status: str
    payment_reference: Optional[str]
    failure_reason: Optional[str]
    confirmed_at: Optional[datetime]
    created_at: datetime


class ReconcileRequest(BaseModel):
    payment_id: UUID
    settled_amount: Decimal = Field(ge=0)
    gateway_settlement_id: Optional[str] = Field(default=None, max_length=120)
    gateway_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    notes: Optional[str] = None


class AutoReconcileRequest(BaseModel):
    canteen_id: Optional[UUID] = None
    fetch_gateway: bool = False


class ReconciliationOut(ORMModel):
    id: UUID
    payment_id: UUID
    order_id: UUID
    batch_id: Optional[UUID] = None
    gateway_provider: str = "razorpay"
    gateway_settlement_id: Optional[str] = None
    gateway_reference: Optional[str] = None
    expected_amount: Decimal
    settled_amount: Decimal
    discrepancy_amount: Decimal
    gateway_fee: Decimal = Decimal("0.00")
    tax_on_fee: Decimal = Decimal("0.00")
    status: str
    reconciliation_source: str = "manual"
    discrepancy_type: str = "none"
    reconciled_at: Optional[datetime]
    notes: Optional[str]


class PrintReceiptRequest(BaseModel):
    printer_target: str = Field(default="browser", pattern="^(browser|58mm|80mm|a4_pdf|network_escpos|usb|bluetooth)$")
    printer_name: Optional[str] = None
    paper_width: str = Field(default="80mm", pattern="^(58mm|80mm|a4)$")
    is_reprint: bool = False
    network_host: Optional[str] = None
    network_port: int = Field(default=9100, ge=1, le=65535)


class PrintJobOut(ORMModel):
    id: UUID
    receipt_id: UUID
    order_id: UUID
    printer_target: str
    printer_name: Optional[str]
    paper_width: str
    is_reprint: bool
    status: str
    retry_count: int
    error_message: Optional[str]
    created_at: datetime


class PrintHistoryOut(ORMModel):
    id: UUID
    receipt_id: UUID
    print_job_id: Optional[UUID]
    printed_by_label: str
    printer_target: str
    is_reprint: bool
    reprint_number: int
    status: str
    printed_at: datetime
