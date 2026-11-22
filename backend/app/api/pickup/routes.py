from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
)
from app.models.order import Order
from app.schemas.operations import (
    DigitalBoardResponse,
    HandoverConfirmRequest,
    HandoverRecordOut,
    PickupVerifyRequest,
    PickupVerifyResponse,
)
from app.services import pickup_service

router = APIRouter(prefix="/pickup", tags=["QR Pickup Verification & Token Board"])

PICKUP_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER, ROLE_PICKUP_STAFF)


@router.post("/verify", response_model=PickupVerifyResponse)
def verify_pickup(
    payload: PickupVerifyRequest,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PICKUP_ROLES)),
    db: Session = Depends(get_db),
):
    if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        enforce_canteen_scope(principal, payload.canteen_id)
        if not payload.canteen_id:
            payload.canteen_id = principal.assigned_canteen_id
    return pickup_service.verify_pickup(db, payload, principal.user.id)


@router.post("/handover", response_model=HandoverRecordOut)
def confirm_handover(
    payload: HandoverConfirmRequest,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PICKUP_ROLES)),
    db: Session = Depends(get_db),
):
    ord_row = db.get(Order, payload.order_id)
    if not ord_row:
        raise HTTPException(status_code=404, detail="Order not found")
    enforce_canteen_scope(principal, ord_row.canteen_id)
    return pickup_service.confirm_handover(db, payload, principal.user.id)


@router.get("/board", response_model=DigitalBoardResponse)
def get_digital_board_all_or_filtered(
    canteen_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_db),
):
    return pickup_service.get_digital_token_board(db, canteen_id)


@router.get("/board/{canteen_id}", response_model=DigitalBoardResponse)
def get_digital_board(canteen_id: UUID, db: Session = Depends(get_db)):
    return pickup_service.get_digital_token_board(db, canteen_id)
