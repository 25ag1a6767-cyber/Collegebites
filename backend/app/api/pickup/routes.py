from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    require_roles,
)
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
    return pickup_service.verify_pickup(db, payload, principal.user.id)


@router.post("/handover", response_model=HandoverRecordOut)
def confirm_handover(
    payload: HandoverConfirmRequest,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PICKUP_ROLES)),
    db: Session = Depends(get_db),
):
    return pickup_service.confirm_handover(db, payload, principal.user.id)


@router.get("/board/{canteen_id}", response_model=DigitalBoardResponse)
def get_digital_board(canteen_id: UUID, db: Session = Depends(get_db)):
    return pickup_service.get_digital_token_board(db, canteen_id)
