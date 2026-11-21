from fastapi import APIRouter, Depends, Header, Query, Response, status
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    require_permissions,
    require_roles,
)
from app.schemas.college import LocationQRCreate, LocationQROut
from app.services import qr_location_service, website_qr_service

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


class WebsiteQRGenerateIn(BaseModel):
    target_type: str = Field(default="website", pattern="^(website|canteen|menu)$")
    canteen_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    box_size: int = Field(default=12, ge=6, le=24)


@router.get("/website/config")
def get_website_qr_config(
    principal: AuthenticatedPrincipal = Depends(require_permissions("qr:website_manage")),
    db: Session = Depends(get_db),
):
    return website_qr_service.get_website_qr_config(db)


@router.post("/website/generate")
def generate_website_qr(
    payload: WebsiteQRGenerateIn,
    principal: AuthenticatedPrincipal = Depends(require_permissions("qr:website_manage")),
    db: Session = Depends(get_db),
):
    return website_qr_service.generate_website_qr_payload(
        db,
        target_type=payload.target_type,
        canteen_id=payload.canteen_id,
        category_id=payload.category_id,
        box_size=payload.box_size,
        actor_user_id=principal.user.id,
    )


@router.get("/website/download")
def download_website_qr(
    format: str = Query(default="png", pattern="^(png|svg)$"),
    target_type: str = Query(default="website", pattern="^(website|canteen|menu)$"),
    canteen_id: Optional[UUID] = Query(default=None),
    category_id: Optional[UUID] = Query(default=None),
    box_size: int = Query(default=12, ge=6, le=24),
    principal: AuthenticatedPrincipal = Depends(require_permissions("qr:website_manage")),
    db: Session = Depends(get_db),
):
    meta = website_qr_service.build_website_qr_target(
        db,
        target_type=target_type,
        canteen_id=canteen_id,
        category_id=category_id,
    )
    if format == "svg":
        svg = website_qr_service.render_website_qr_svg(meta["target_url"], box_size=box_size)
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={"Content-Disposition": f"attachment; filename={meta['filename_base']}.svg"},
        )
    png = website_qr_service.render_website_qr_png(meta["target_url"], box_size=box_size)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Content-Disposition": f"attachment; filename={meta['filename_base']}.png"},
    )
