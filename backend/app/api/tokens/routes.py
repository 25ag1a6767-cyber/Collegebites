from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    get_optional_principal,
)
from app.services import receipt_service
from app.services.qr_location_service import render_qr_png_bytes

router = APIRouter(prefix="/tokens", tags=["Tokens, QR & Receipts"])

STAFF_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
)


@router.get("/receipts/{order_id_or_number}")
def get_receipt(
    order_id_or_number: str,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(*STAFF_ROLES))
    return receipt_service.get_receipt_payload(
        db,
        order_id_or_number,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        guest_access_token=guest_token or x_guest_token,
    )


@router.get("/receipts/{order_id_or_number}/pdf")
def download_receipt_pdf(
    order_id_or_number: str,
    format: str = Query(default="a4", pattern="^(a4|80mm)$"),
    reprint: bool = Query(default=False),
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(*STAFF_ROLES))
    pdf_bytes, order_num = receipt_service.generate_receipt_pdf_bytes(
        db,
        order_id_or_number,
        paper_format=format,
        is_reprint_view=reprint,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        guest_access_token=guest_token or x_guest_token,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=CollegeBites-{order_num}.pdf"},
    )


@router.get("/receipts/{order_id_or_number}/qr.png")
def download_order_qr_png(
    order_id_or_number: str,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(*STAFF_ROLES))
    snap = receipt_service.get_receipt_payload(
        db,
        order_id_or_number,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        guest_access_token=guest_token or x_guest_token,
    )
    png_bytes = render_qr_png_bytes(snap["qr_payload"], box_size=10)
    return Response(content=png_bytes, media_type="image/png")
