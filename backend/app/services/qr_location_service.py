import base64
import io
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import qrcode
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_location_qr_code_slug
from app.models.college import Canteen, Counter, DiningTable, KioskDevice, LocationQRCode
from app.schemas.college import LocationQRCreate, LocationQROut
from app.services.audit_service import record_audit_log
from app.services.college_service import serialize_canteen


def render_qr_png_bytes(data: str, box_size: int = 8) -> bytes:
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_qr_base64(data: str, box_size: int = 8) -> str:
    return base64.b64encode(render_qr_png_bytes(data, box_size=box_size)).decode("ascii")


def serialize_location_qr(row: LocationQRCode, include_image: bool = True) -> LocationQROut:
    scan_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/scan/{row.code}"
    return LocationQROut(
        id=row.id,
        code=row.code,
        target_type=row.target_type,
        canteen_id=row.canteen_id,
        counter_id=row.counter_id,
        table_id=row.table_id,
        kiosk_device_id=row.kiosk_device_id,
        label=row.label,
        is_active=row.is_active,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        replaced_by_id=row.replaced_by_id,
        scan_url=scan_url,
        qr_image_base64=render_qr_base64(scan_url) if include_image else None,
    )


def list_location_qrs(db: Session, canteen_id: Optional[UUID] = None) -> list[LocationQROut]:
    stmt = select(LocationQRCode).order_by(LocationQRCode.created_at.desc())
    if canteen_id:
        stmt = stmt.where(LocationQRCode.canteen_id == canteen_id)
    return [serialize_location_qr(row, include_image=False) for row in db.scalars(stmt).all()]


def create_location_qr(db: Session, payload: LocationQRCreate, actor_user_id: UUID) -> LocationQROut:
    if not db.get(Canteen, payload.canteen_id):
        raise HTTPException(status_code=404, detail="Canteen not found")
    if payload.counter_id and not db.get(Counter, payload.counter_id):
        raise HTTPException(status_code=404, detail="Counter not found")
    if payload.table_id and not db.get(DiningTable, payload.table_id):
        raise HTTPException(status_code=404, detail="Table not found")
    if payload.kiosk_device_id and not db.get(KioskDevice, payload.kiosk_device_id):
        raise HTTPException(status_code=404, detail="Kiosk device not found")

    code = generate_location_qr_code_slug(payload.target_type[:3].upper())
    row = LocationQRCode(code=code, **payload.model_dump())
    db.add(row)
    record_audit_log(
        db,
        action="location_qr.created",
        entity_type="location_qr",
        entity_id=code,
        actor_user_id=actor_user_id,
        details={"target_type": payload.target_type, "canteen_id": str(payload.canteen_id)},
    )
    db.commit()
    db.refresh(row)
    return serialize_location_qr(row, include_image=True)


def revoke_location_qr(db: Session, qr_id: UUID, actor_user_id: UUID) -> LocationQROut:
    row = db.get(LocationQRCode, qr_id)
    if not row:
        raise HTTPException(status_code=404, detail="Location QR not found")
    row.is_active = False
    row.revoked_at = datetime.now(timezone.utc)
    record_audit_log(db, action="location_qr.revoked", entity_type="location_qr", entity_id=row.code, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(row)
    return serialize_location_qr(row, include_image=False)


def replace_location_qr(db: Session, qr_id: UUID, actor_user_id: UUID) -> LocationQROut:
    old = db.get(LocationQRCode, qr_id)
    if not old:
        raise HTTPException(status_code=404, detail="Location QR not found")
    new_code = generate_location_qr_code_slug(old.target_type[:3].upper())
    new_row = LocationQRCode(
        code=new_code,
        target_type=old.target_type,
        canteen_id=old.canteen_id,
        counter_id=old.counter_id,
        table_id=old.table_id,
        kiosk_device_id=old.kiosk_device_id,
        label=old.label,
        is_active=True,
        expires_at=old.expires_at,
    )
    db.add(new_row)
    db.flush()
    old.is_active = False
    old.revoked_at = datetime.now(timezone.utc)
    old.replaced_by_id = new_row.id
    record_audit_log(
        db,
        action="location_qr.replaced",
        entity_type="location_qr",
        entity_id=old.code,
        actor_user_id=actor_user_id,
        details={"new_code": new_code},
    )
    db.commit()
    db.refresh(new_row)
    return serialize_location_qr(new_row, include_image=True)


def resolve_location_qr(db: Session, code: str) -> dict:
    row = db.scalar(select(LocationQRCode).where(LocationQRCode.code == code.strip()))
    if not row:
        raise HTTPException(status_code=404, detail="QR code not recognized")
    if not row.is_active or row.revoked_at is not None:
        raise HTTPException(status_code=410, detail="This QR code has been revoked or replaced")
    if row.expires_at and row.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="This QR code has expired")

    canteen = db.get(Canteen, row.canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found for QR")
    counter = db.get(Counter, row.counter_id) if row.counter_id else None
    table = db.get(DiningTable, row.table_id) if row.table_id else None

    return {
        "qr": serialize_location_qr(row, include_image=False),
        "canteen": serialize_canteen(db, canteen),
        "counter": {"id": counter.id, "name": counter.name, "code": counter.code} if counter else None,
        "table": {"id": table.id, "table_number": table.table_number, "zone_label": table.zone_label} if table else None,
    }
