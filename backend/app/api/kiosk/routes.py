from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    client_ip_from_request,
    require_roles,
)
from app.models.college import KioskDevice
from app.models.menu import FoodItem
from app.schemas.order import CheckoutItemDirectIn, CheckoutRequest, OrderOut
from app.services import college_service, menu_service, order_service
from app.services.audit_service import record_audit_log

router = APIRouter(prefix="/kiosk", tags=["Self-Service Kiosk & Smart Recommendations"])


class KioskDeviceCreateIn(BaseModel):
    canteen_id: UUID
    counter_id: Optional[UUID] = None
    device_code: str = Field(min_length=3, max_length=64)
    device_name: str = Field(min_length=2, max_length=120)
    is_enabled: bool = False
    idle_timeout_seconds: int = Field(default=90, ge=15, le=600)
    supported_languages: list[str] = ["en", "hi", "te"]


class KioskDeviceUpdateIn(BaseModel):
    is_enabled: Optional[bool] = None
    idle_timeout_seconds: Optional[int] = Field(default=None, ge=15, le=600)
    supported_languages: Optional[list[str]] = None


class KioskOrderIn(BaseModel):
    device_code: str = Field(min_length=3, max_length=64)
    canteen_id: UUID
    payment_method: str = Field(default="razorpay", pattern="^(razorpay|stripe)$")
    guest_name: str = Field(default="Kiosk Guest", max_length=160)
    guest_phone: Optional[str] = Field(default="0000000000", max_length=32)
    language: str = "en"
    idempotency_key: Optional[str] = None
    items: list[CheckoutItemDirectIn] = Field(min_length=1)


@router.get("/status")
def kiosk_status(db: Session = Depends(get_db)):
    college = college_service.get_or_create_college_settings(db)
    devices = db.scalars(select(KioskDevice).order_by(KioskDevice.device_code)).all()
    return {
        "kiosk_enabled": college.kiosk_enabled,
        "devices": [
            {
                "id": str(d.id),
                "canteen_id": str(d.canteen_id),
                "counter_id": str(d.counter_id) if d.counter_id else None,
                "device_code": d.device_code,
                "device_name": d.device_name,
                "is_enabled": d.is_enabled,
                "idle_timeout_seconds": d.idle_timeout_seconds,
                "supported_languages": d.supported_languages,
                "last_heartbeat_at": d.last_heartbeat_at.isoformat() if d.last_heartbeat_at else None,
            }
            for d in devices
        ],
    }


@router.post("/devices", status_code=status.HTTP_201_CREATED)
def create_kiosk_device(
    payload: KioskDeviceCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    dup = db.scalar(select(KioskDevice).where(KioskDevice.device_code == payload.device_code))
    if dup:
        raise HTTPException(status_code=409, detail="Kiosk device code already exists")
    dev = KioskDevice(**payload.model_dump())
    db.add(dev)
    record_audit_log(db, action="kiosk.device_created", entity_type="kiosk_device", entity_id=dev.device_code, actor_user_id=principal.user.id)
    db.commit()
    db.refresh(dev)
    return dev


@router.patch("/devices/{device_id}")
def update_kiosk_device(
    device_id: UUID,
    payload: KioskDeviceUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    dev = db.get(KioskDevice, device_id)
    if not dev:
        raise HTTPException(status_code=404, detail="Kiosk device not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(dev, k, v)
    dev.last_heartbeat_at = datetime.now(timezone.utc)
    record_audit_log(db, action="kiosk.device_updated", entity_type="kiosk_device", entity_id=dev.device_code, actor_user_id=principal.user.id)
    db.commit()
    db.refresh(dev)
    return dev


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_kiosk_order(payload: KioskOrderIn, request: Request, db: Session = Depends(get_db)):
    college = college_service.get_or_create_college_settings(db)
    if not college.kiosk_enabled:
        raise HTTPException(status_code=403, detail="Self-service kiosk mode is disabled until hardware is enabled by college admin")
    dev = db.scalar(select(KioskDevice).where(KioskDevice.device_code == payload.device_code))
    if not dev or not dev.is_enabled:
        raise HTTPException(status_code=403, detail="Kiosk device is not registered or is disabled")
    if payload.canteen_id != dev.canteen_id:
        raise HTTPException(status_code=400, detail="Kiosk device belongs to a different canteen")
    if dev.supported_languages and payload.language not in dev.supported_languages:
        raise HTTPException(status_code=400, detail=f"Language '{payload.language}' is not enabled on this kiosk")

    dev.last_heartbeat_at = datetime.now(timezone.utc)
    co_req = CheckoutRequest(
        canteen_id=payload.canteen_id,
        counter_id=dev.counter_id,
        order_type="kiosk",
        order_channel="kiosk",
        payment_method=payload.payment_method,
        idempotency_key=payload.idempotency_key,
        guest_name=payload.guest_name,
        guest_phone=payload.guest_phone or "0000000000",
        notes=f"Kiosk {dev.device_code} (lang={payload.language})",
        use_cart=False,
        direct_items=payload.items,
        accepted_policy=True,
    )
    return order_service.checkout_order(db, co_req, ip_address=client_ip_from_request(request))


@router.get("/recommendations/{canteen_id}")
def smart_recommendations(
    canteen_id: UUID,
    veg_only: Optional[bool] = Query(default=None),
    max_prep_minutes: Optional[int] = Query(default=None, ge=1, le=60),
    db: Session = Depends(get_db),
):
    """Smart meal recommender combining popularity, ratings, crowd speed, and time-of-day suitability."""
    items = menu_service.list_food_items(
        db, canteen_id, is_veg=veg_only, available_only=True, sort_by="popularity"
    )
    if max_prep_minutes is not None:
        items = [i for i in items if i.prep_time_minutes <= max_prep_minutes]
    ranked = sorted(
        items,
        key=lambda x: (
            (float(x.average_rating) * 20.0)
            + float(x.popularity_score)
            + (15.0 if x.is_recommended else 0.0)
            + (10.0 if x.is_todays_special else 0.0)
            - (x.prep_time_minutes * 1.2)
        ),
        reverse=True,
    )
    return ranked[:6]
