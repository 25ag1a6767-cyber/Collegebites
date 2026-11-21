from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
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
from app.models.payment import Receipt, ReceiptPrintHistory, ReceiptPrintJob
from app.schemas.payment import PrintHistoryOut, PrintJobOut, PrintReceiptRequest
from app.services import receipt_service

router = APIRouter(prefix="/printing", tags=["Receipt & Thermal Printing"])

STAFF_PRINT_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER)


@router.get("/receipts/{order_id_or_number}/escpos")
def get_escpos_receipt(
    order_id_or_number: str,
    width: str = Query(default="80mm", pattern="^(58mm|80mm)$"),
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(*STAFF_PRINT_ROLES))
    return receipt_service.get_escpos_payload(
        db,
        order_id_or_number,
        paper_width=width,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        guest_access_token=guest_token or x_guest_token,
    )


@router.post("/receipts/{order_id_or_number}/print", response_model=PrintJobOut)
def print_receipt(
    order_id_or_number: str,
    payload: PrintReceiptRequest,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(*STAFF_PRINT_ROLES))
    actor_label = principal.user.full_name if principal else "Guest/Customer"
    return receipt_service.trigger_print_job(
        db,
        order_id_or_number,
        payload,
        actor_user_id=principal.user.id if principal else None,
        actor_label=actor_label,
        is_staff=is_staff,
        guest_access_token=guest_token or x_guest_token,
    )


@router.post("/jobs/{job_id}/retry", response_model=PrintJobOut)
def retry_print_job(
    job_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    return receipt_service.retry_print_job(db, job_id, principal.user.id, principal.user.full_name)


@router.get("/jobs", response_model=list[PrintJobOut])
def list_print_jobs(
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(ReceiptPrintJob).order_by(ReceiptPrintJob.created_at.desc()).limit(100)).all())


@router.get("/history/{order_id_or_number}", response_model=list[PrintHistoryOut])
def get_print_history(
    order_id_or_number: str,
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    _order, receipt = receipt_service._resolve_order_and_receipt(db, order_id_or_number, is_staff=True)
    return list(
        db.scalars(
            select(ReceiptPrintHistory)
            .where(ReceiptPrintHistory.receipt_id == receipt.id)
            .order_by(ReceiptPrintHistory.printed_at.desc())
        ).all()
    )
