from datetime import date
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http_cache import apply_etag_and_check_304, set_private_no_store
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_FOOD_SAFETY_INSPECTOR,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_optional_principal,
    require_roles,
    scoped_canteen_for_principal,
)
from app.core.rate_limit import limiter
from app.services import campus_intelligence_service, voice_assistant_service

router = APIRouter(prefix="/campus-intelligence", tags=["Smart Campus Intelligence (System A)"])

OPS_VIEW_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
    ROLE_CASHIER,
    ROLE_INVENTORY_MANAGER,
    ROLE_FOOD_SAFETY_INSPECTOR,
)
MANAGER_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
TRAY_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF, ROLE_PICKUP_STAFF)


class PriorityUpdateIn(BaseModel):
    is_priority: bool
    reason: str = Field(min_length=3, max_length=300)


class TrayVerifyItemIn(BaseModel):
    item_name: str = Field(min_length=1, max_length=160)
    quantity: int = Field(ge=0, le=100)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class TrayVerificationSubmitIn(BaseModel):
    order_id: UUID
    verified_items: list[TrayVerifyItemIn] = Field(default_factory=list)
    verification_mode: str = Field(default="manual_checklist", pattern="^(manual_checklist|camera_assisted)$")
    cv_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    human_confirmed: bool = False
    notes: Optional[str] = Field(default=None, max_length=500)


class MenuAvailabilityOverrideIn(BaseModel):
    is_available: bool
    reason: str = Field(min_length=3, max_length=300)


class SeatingZoneUpsertIn(BaseModel):
    zone_code: str = Field(min_length=2, max_length=32)
    zone_name: str = Field(min_length=2, max_length=120)
    total_seats: int = Field(ge=1, le=2000)
    canteen_id: Optional[UUID] = None
    layout_x: int = 0
    layout_y: int = 0
    layout_w: int = 200
    layout_h: int = 120


class SeatingOccupancyUpdateIn(BaseModel):
    occupied_seats: int = Field(ge=0, le=2000)
    data_source: str = Field(default="manual", pattern="^(manual|sensor|estimated)$")
    notes: Optional[str] = Field(default=None, max_length=300)


class VoiceQueryIn(BaseModel):
    transcript: str = Field(min_length=0, max_length=1000)
    language: str = Field(default="en", pattern="^(en|te|en-IN|te-IN)$")
    canteen_id: Optional[UUID] = None


# --- Feature 1: Live Cafeteria Crowd Intelligence ---
@router.get("/crowd/live")
def get_live_crowd(
    request: Request,
    response: Response,
    days: int = Query(default=7, ge=1, le=60),
    db: Session = Depends(get_db),
):
    data = campus_intelligence_service.get_live_crowd_intelligence(db, days=days)
    not_mod = apply_etag_and_check_304(request, response, data, s_maxage=15, swr=30)
    if not_mod is not None:
        return not_mod
    return data


@router.post("/crowd/snapshot")
def capture_crowd_snapshot(
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return {"snapshots": campus_intelligence_service.capture_crowd_snapshots(db, actor_user_id=principal.user.id)}


# --- Feature 2: AI Smart Pickup Time Prediction ---
@router.get("/pickup-predictions/{canteen_id}")
def get_pickup_prediction(
    canteen_id: UUID,
    request: Request,
    response: Response,
    order_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_db),
):
    data = campus_intelligence_service.get_smart_pickup_prediction(db, canteen_id, order_id=order_id)
    if order_id is not None:
        set_private_no_store(response)
        return data
    not_mod = apply_etag_and_check_304(request, response, data, s_maxage=15, swr=30)
    if not_mod is not None:
        return not_mod
    return data


# --- Feature 3: Virtual Queue Overview & Priority ---
@router.get("/queue/overview")
def get_queue_overview(
    canteen_id: Optional[UUID] = Query(default=None),
    status: Optional[str] = Query(default=None),
    counter_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*OPS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, canteen_id) if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) else canteen_id
    return campus_intelligence_service.get_virtual_queue_overview(
        db, canteen_id=eff_cid, status_filter=status, counter_id=counter_id
    )


@router.post("/queue/orders/{order_id}/priority")
def set_order_priority(
    order_id: UUID,
    payload: PriorityUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES, ROLE_KITCHEN_STAFF)),
    db: Session = Depends(get_db),
):
    assigned_cid = None if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) else principal.assigned_canteen_id
    return campus_intelligence_service.update_order_queue_priority(
        db,
        order_id=order_id,
        is_priority=payload.is_priority,
        reason=payload.reason,
        actor_user_id=principal.user.id,
        assigned_canteen_id=assigned_cid,
    )


# --- Feature 4: AI Order-to-Tray Verification ---
@router.get("/tray-verification/order/{order_ref}")
def get_tray_verification_order(
    order_ref: str,
    principal: AuthenticatedPrincipal = Depends(require_roles(*TRAY_ROLES)),
    db: Session = Depends(get_db),
):
    assigned_cid = None if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) else principal.assigned_canteen_id
    return campus_intelligence_service.get_tray_verification_context(db, order_ref, assigned_canteen_id=assigned_cid)


@router.post("/tray-verification/verify")
def verify_order_tray(
    payload: TrayVerificationSubmitIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*TRAY_ROLES)),
    db: Session = Depends(get_db),
):
    assigned_cid = None if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) else principal.assigned_canteen_id
    return campus_intelligence_service.submit_tray_verification(
        db,
        order_id=payload.order_id,
        verified_items=[v.model_dump() for v in payload.verified_items],
        verification_mode=payload.verification_mode,
        cv_confidence=payload.cv_confidence,
        human_confirmed=payload.human_confirmed,
        notes=payload.notes,
        actor_user_id=principal.user.id,
        assigned_canteen_id=assigned_cid,
    )


@router.get("/tray-verification/history")
def list_tray_verification_history(
    canteen_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(*OPS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, canteen_id) if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) else canteen_id
    return campus_intelligence_service.list_tray_verifications(db, canteen_id=eff_cid, limit=limit, offset=offset)


# --- Feature 5: Class Timetable-Based Food Demand Prediction ---
@router.post("/timetables/import")
async def import_timetable(
    file: UploadFile = File(...),
    canteen_id: Optional[UUID] = Form(default=None),
    academic_term: Optional[str] = Form(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    raw = await file.read()
    return campus_intelligence_service.import_academic_timetable(
        db,
        file_bytes=raw,
        filename=file.filename or "timetable.csv",
        canteen_id=canteen_id,
        academic_term=academic_term,
        actor_user_id=principal.user.id,
    )


@router.get("/timetables")
def get_timetables(
    canteen_id: Optional[UUID] = Query(default=None),
    day_of_week: Optional[int] = Query(default=None, ge=0, le=6),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(*OPS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    return campus_intelligence_service.list_timetable_slots(
        db, canteen_id=canteen_id, day_of_week=day_of_week, limit=limit, offset=offset
    )


@router.delete("/timetables/{slot_id}")
def remove_timetable_slot(
    slot_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    campus_intelligence_service.delete_timetable_slot(db, slot_id, principal.user.id)
    return {"deleted": True, "slot_id": str(slot_id)}


@router.get("/timetables/demand-prediction")
def get_timetable_demand_prediction(
    canteen_id: Optional[UUID] = Query(default=None),
    target_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*OPS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, canteen_id) if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) else canteen_id
    return campus_intelligence_service.get_timetable_demand_prediction(db, canteen_id=eff_cid, target_date=target_date)


# --- Feature 6: Intelligent Menu Availability Display ---
@router.get("/menu-availability/{canteen_id}")
def get_menu_availability(
    canteen_id: UUID,
    request: Request,
    response: Response,
    include_history: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    data = campus_intelligence_service.get_intelligent_menu_availability(db, canteen_id, include_history=include_history)
    not_mod = apply_etag_and_check_304(request, response, data, s_maxage=15, swr=30)
    if not_mod is not None:
        return not_mod
    return data


@router.post("/menu-availability/{food_item_id}/override")
def override_menu_availability(
    food_item_id: UUID,
    payload: MenuAvailabilityOverrideIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES, ROLE_INVENTORY_MANAGER)),
    db: Session = Depends(get_db),
):
    assigned_cid = None if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) else principal.assigned_canteen_id
    return campus_intelligence_service.override_menu_item_availability(
        db,
        food_item_id=food_item_id,
        is_available=payload.is_available,
        reason=payload.reason,
        actor_user_id=principal.user.id,
        assigned_canteen_id=assigned_cid,
    )


# --- Feature 7: Live Order Journey Tracking ---
@router.get("/orders/{order_number}/journey")
def get_order_journey(
    order_number: str,
    guest_token: Optional[str] = Query(default=None),
    x_guest_access_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(*OPS_VIEW_ROLES))
    staff_cid = (
        None
        if (not principal or principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN))
        else principal.assigned_canteen_id
    )
    return campus_intelligence_service.get_live_order_journey(
        db,
        order_number,
        user_id=principal.user.id if principal else None,
        guest_access_token=guest_token or x_guest_access_token,
        is_staff=is_staff,
        staff_canteen_id=staff_cid,
    )


# --- Feature 8: Smart Seating Availability Intelligence ---
@router.get("/seating")
def get_seating(
    request: Request,
    response: Response,
    canteen_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_db),
):
    data = campus_intelligence_service.list_seating_availability(db, canteen_id=canteen_id)
    not_mod = apply_etag_and_check_304(request, response, data, s_maxage=15, swr=30)
    if not_mod is not None:
        return not_mod
    return data


@router.post("/seating/zones")
def upsert_seating_zone(
    payload: SeatingZoneUpsertIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    if payload.canteen_id:
        enforce_canteen_scope(principal, payload.canteen_id)
    return campus_intelligence_service.upsert_seating_zone(
        db,
        zone_code=payload.zone_code,
        zone_name=payload.zone_name,
        total_seats=payload.total_seats,
        canteen_id=payload.canteen_id,
        layout_x=payload.layout_x,
        layout_y=payload.layout_y,
        layout_w=payload.layout_w,
        layout_h=payload.layout_h,
        actor_user_id=principal.user.id,
    )


@router.patch("/seating/zones/{zone_id}/occupancy")
def update_seating_occupancy(
    zone_id: UUID,
    payload: SeatingOccupancyUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES, ROLE_PICKUP_STAFF, ROLE_CASHIER)),
    db: Session = Depends(get_db),
):
    return campus_intelligence_service.update_seating_occupancy(
        db,
        zone_id=zone_id,
        occupied_seats=payload.occupied_seats,
        data_source=payload.data_source,
        notes=payload.notes,
        actor_user_id=principal.user.id,
    )


@router.get("/seating/analytics")
def get_seating_analytics(
    days: int = Query(default=14, ge=1, le=90),
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*OPS_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    return campus_intelligence_service.get_seating_analytics(db, days=days, canteen_id=canteen_id)


# --- Feature 9: Voice-Based Campus Food Assistant (English & Telugu) ---
@router.post("/voice-assistant/query")
@limiter.limit("30/minute")
def query_voice_assistant(
    payload: VoiceQueryIn,
    request: Request,
    x_guest_session_id: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    return voice_assistant_service.process_voice_query(
        db,
        transcript=payload.transcript,
        language=payload.language,
        canteen_id=payload.canteen_id,
        user_id=principal.user.id if principal else None,
        guest_session_id=x_guest_session_id,
    )


@router.get("/voice-assistant/analytics")
def get_voice_analytics(
    days: int = Query(default=14, ge=1, le=90),
    principal: AuthenticatedPrincipal = Depends(require_roles(*MANAGER_ROLES)),
    db: Session = Depends(get_db),
):
    return voice_assistant_service.get_voice_assistant_analytics(db, days=days)

