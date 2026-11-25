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
    printer_target: str = Field(
        default="browser",
        pattern="^(browser|58mm|80mm|a4_pdf|network_escpos|usb|bluetooth|local_agent_escpos)$",
    )
    printer_name: Optional[str] = None
    paper_width: str = Field(default="80mm", pattern="^(58mm|80mm|a4)$")
    is_reprint: bool = False
    network_host: Optional[str] = None
    network_port: int = Field(default=9100, ge=1, le=65535)


class PrintJobOut(ORMModel):
    id: UUID
    receipt_id: UUID
    order_id: UUID
    canteen_id: Optional[UUID] = None
    payment_id: Optional[UUID] = None
    printer_device_id: Optional[UUID] = None
    order_number: Optional[str] = None
    pickup_token_code: Optional[str] = None
    customer_name: Optional[str] = None
    total_amount: Optional[str] = None
    job_type: str = "customer_receipt"
    idempotency_key: Optional[str] = None
    printer_target: str
    printer_name: Optional[str]
    paper_width: str
    is_reprint: bool
    status: str
    retry_count: int
    max_retries: int = 10
    payload_checksum: Optional[str] = None
    total_bytes: int = 0
    total_segments: int = 0
    last_printed_byte_offset: int = 0
    last_printed_segment_index: int = 0
    resume_mode: str = "exact_offset"
    paused_reason: Optional[str] = None
    paused_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    claimed_by_agent: Optional[str] = None
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


class PrinterDeviceCreateRequest(BaseModel):
    canteen_id: UUID
    counter_id: Optional[UUID] = None
    department: str = Field(default="kitchen", pattern="^(kitchen|counter)$")
    device_name: str = Field(min_length=2, max_length=120)
    agent_id: Optional[str] = Field(default=None, min_length=3, max_length=120)
    connection_type: str = Field(default="local_usb", pattern="^(local_usb|local_serial|network_escpos|os_spooler)$")
    network_host: Optional[str] = Field(default=None, max_length=120)
    network_port: Optional[int] = Field(default=9100, ge=1, le=65535)
    paper_width: str = Field(default="80mm", pattern="^(58mm|80mm)$")
    supports_realtime_status: bool = True
    supports_resume_offset: bool = True


class PrinterDeviceOut(ORMModel):
    id: UUID
    canteen_id: UUID
    counter_id: Optional[UUID] = None
    department: str
    device_name: str
    agent_id: str
    connection_type: str
    network_host: Optional[str] = None
    network_port: Optional[int] = None
    paper_width: str
    status: str
    is_connected: bool
    is_online: bool
    paper_status: str
    supports_realtime_status: bool
    supports_resume_offset: bool
    current_job_id: Optional[UUID] = None
    current_order_number: Optional[str] = None
    last_heartbeat_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PrinterRegistrationOut(BaseModel):
    printer: PrinterDeviceOut
    agent_id: str
    agent_token: str


class AgentHeartbeatRequest(BaseModel):
    is_connected: bool = True
    is_online: bool = True
    paper_status: str = Field(default="available", pattern="^(available|low|out_of_paper|unknown)$")
    status: Optional[str] = Field(default=None, pattern="^(online|offline|paused|error)$")
    supports_realtime_status: Optional[bool] = None
    supports_resume_offset: Optional[bool] = None
    current_job_id: Optional[UUID] = None
    last_error: Optional[str] = Field(default=None, max_length=255)


class AgentJobProgressRequest(BaseModel):
    printed_segment_index: int = Field(ge=0)
    printed_byte_offset: int = Field(ge=0)
    supports_resume_offset: bool = True


class AgentJobPauseRequest(BaseModel):
    reason: str = Field(default="out_of_paper", min_length=2, max_length=255)
    paper_status: str = Field(default="out_of_paper", pattern="^(out_of_paper|low|available|unknown)$")
    printed_segment_index: int = Field(default=0, ge=0)
    printed_byte_offset: int = Field(default=0, ge=0)
    supports_resume_offset: bool = True
    is_connected: bool = True
    is_online: bool = False


class AgentJobCompleteRequest(BaseModel):
    printed_segment_index: Optional[int] = Field(default=None, ge=0)
    printed_byte_offset: Optional[int] = Field(default=None, ge=0)
    printed_by_label: Optional[str] = Field(default=None, max_length=120)


class AgentJobFailRequest(BaseModel):
    error_message: str = Field(min_length=2, max_length=255)
    printer_offline: bool = False
    retry_delay_seconds: int = Field(default=15, ge=5, le=3600)
    printed_segment_index: int = Field(default=0, ge=0)
    printed_byte_offset: int = Field(default=0, ge=0)


class KitchenPrintSummaryOut(BaseModel):
    total_jobs: int
    pending_count: int
    printing_count: int
    paused_count: int
    completed_count: int
    failed_count: int
    currently_printing_order: Optional[str] = None
    currently_printing_token: Optional[str] = None
    online_printers: int
    total_printers: int
    out_of_paper_printers: int


class KitchenPrintDashboardOut(BaseModel):
    canteen_id: Optional[UUID] = None
    printers: list[PrinterDeviceOut]
    summary: KitchenPrintSummaryOut
    jobs: list[PrintJobOut]
