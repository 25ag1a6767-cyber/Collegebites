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
    ROLE_KITCHEN_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_optional_principal,
    require_roles,
    scoped_canteen_for_principal,
)
from app.models.order import Order
from app.models.payment import Receipt, ReceiptPrintHistory, ReceiptPrintJob
from app.schemas.payment import PrintHistoryOut, PrintJobOut, PrintReceiptRequest
from app.services import receipt_service

router = APIRouter(prefix="/printing", tags=["Receipt & Thermal Printing"])

STAFF_PRINT_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER)
KOT_PRINT_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF, ROLE_CASHIER)


def _print_staff_cid(principal: Optional[AuthenticatedPrincipal]) -> Optional[UUID]:
    if not principal or not principal.has_role(*STAFF_PRINT_ROLES):
        return None
    if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return None
    return principal.assigned_canteen_id


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
        staff_canteen_id=_print_staff_cid(principal),
        guest_access_token=guest_token or x_guest_token,
    )


@router.get("/kitchen-ticket/{order_id_or_number}/escpos")
def get_escpos_kitchen_ticket(
    order_id_or_number: str,
    width: str = Query(default="80mm", pattern="^(58mm|80mm)$"),
    station_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*KOT_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, None)
    return receipt_service.get_kitchen_ticket_escpos_payload(
        db,
        order_id_or_number,
        paper_width=width,
        station_id=station_id,
        staff_canteen_id=scoped_cid,
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
        staff_canteen_id=_print_staff_cid(principal),
        guest_access_token=guest_token or x_guest_token,
    )


@router.post("/jobs/{job_id}/retry", response_model=PrintJobOut)
def retry_print_job(
    job_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    job = db.get(ReceiptPrintJob, job_id)
    if job:
        ord_row = db.get(Order, job.order_id)
        if ord_row:
            enforce_canteen_scope(principal, ord_row.canteen_id)
    return receipt_service.retry_print_job(db, job_id, principal.user.id, principal.user.full_name)


@router.get("/jobs", response_model=list[PrintJobOut])
def list_print_jobs(
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, None)
    stmt = select(ReceiptPrintJob).order_by(ReceiptPrintJob.created_at.desc()).limit(100)
    if scoped_cid:
        stmt = stmt.join(Order, Order.id == ReceiptPrintJob.order_id).where(Order.canteen_id == scoped_cid)
    return list(db.scalars(stmt).all())


@router.get("/history/{order_id_or_number}", response_model=list[PrintHistoryOut])
def get_print_history(
    order_id_or_number: str,
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    _order, receipt = receipt_service._resolve_order_and_receipt(
        db, order_id_or_number, is_staff=True, staff_canteen_id=_print_staff_cid(principal)
    )
    return list(
        db.scalars(
            select(ReceiptPrintHistory)
            .where(ReceiptPrintHistory.receipt_id == receipt.id)
            .order_by(ReceiptPrintHistory.printed_at.desc())
        ).all()
    )
