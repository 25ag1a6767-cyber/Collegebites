from fastapi import APIRouter, Depends, Header, Query, Response, status
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import ROLE_CANTEEN_MANAGER, ROLE_COLLEGE_ADMIN, ROLE_SUPER_ADMIN, AuthenticatedPrincipal, require_roles
from app.schemas.college import LocationQRCreate, LocationQROut
from app.services import qr_location_service

router = APIRouter(prefix="/qr", tags=["QR Ordering & Location Codes"])


@router.get("/locations", response_model=list[LocationQROut])
def list_location_qrs(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    return qr_location_service.list_location_qrs(db, canteen_id=canteen_id)


@router.post("/locations", response_model=LocationQROut, status_code=status.HTTP_201_CREATED)
def create_location_qr(
    payload: LocationQRCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    return qr_location_service.create_location_qr(db, payload, principal.user.id)


@router.post("/locations/{qr_id}/revoke", response_model=LocationQROut)
def revoke_location_qr(
    qr_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    return qr_location_service.revoke_location_qr(db, qr_id, principal.user.id)


@router.post("/locations/{qr_id}/replace", response_model=LocationQROut)
def replace_location_qr(
    qr_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    return qr_location_service.replace_location_qr(db, qr_id, principal.user.id)


@router.get("/locations/resolve/{code}")
def resolve_location_qr(code: str, db: Session = Depends(get_db)):
    return qr_location_service.resolve_location_qr(db, code)


@router.get("/locations/{qr_id}/image")
def get_location_qr_image(qr_id: UUID, db: Session = Depends(get_db)):
    from app.models.college import LocationQRCode
    from app.core.config import settings

    row = db.get(LocationQRCode, qr_id)
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Location QR not found")
    url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/scan/{row.code}"
    png = qr_location_service.render_qr_png_bytes(url, box_size=10)
    return Response(content=png, media_type="image/png")
