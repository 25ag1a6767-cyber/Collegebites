from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_current_principal,
    require_roles,
    scoped_canteen_for_principal,
)
from app.models.engagement import Announcement
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications & Announcements"])


class PreferencesUpdateIn(BaseModel):
    in_app_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None
    whatsapp_enabled: Optional[bool] = None
    expo_push_token: Optional[str] = None


class PushTokenRegisterIn(BaseModel):
    token: str = Field(min_length=5, max_length=300)
    platform: Optional[str] = Field(default="android", max_length=32)
    device_name: Optional[str] = Field(default=None, max_length=120)


class AnnouncementCreateIn(BaseModel):
    canteen_id: Optional[UUID] = None
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=2)
    severity: str = Field(default="info", pattern="^(info|warning|urgent)$")
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


@router.get("/my")
def get_my_notifications(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return notification_service.list_my_notifications(
        db, principal.user.id, principal.roles, assigned_canteen_id=principal.assigned_canteen_id
    )


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return notification_service.mark_notification_read(db, notification_id, principal.user.id, principal.roles)


@router.post("/mark-all-read")
def mark_all_read(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    count = notification_service.mark_all_notifications_read(db, principal.user.id, principal.roles)
    return {"marked_read": count}


@router.get("/preferences")
def get_preferences(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return notification_service.get_or_create_preferences(db, principal.user.id)


@router.put("/preferences")
def update_preferences(
    payload: PreferencesUpdateIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return notification_service.update_preferences(db, principal.user.id, payload.model_dump(exclude_unset=True))


@router.post("/push-tokens")
def register_push_token(
    payload: PushTokenRegisterIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    pref = notification_service.update_preferences(
        db,
        principal.user.id,
        {"expo_push_token": payload.token.strip(), "push_enabled": True},
    )
    return {
        "status": "registered",
        "platform": payload.platform,
        "push_enabled": pref.push_enabled,
        "expo_push_token": pref.expo_push_token,
    }


@router.get("/announcements")
def list_announcements(canteen_id: Optional[UUID] = Query(default=None), db: Session = Depends(get_db)):
    return notification_service.list_active_announcements(db, canteen_id=canteen_id)


@router.post("/announcements", status_code=status.HTTP_201_CREATED)
def create_announcement(
    payload: AnnouncementCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    data = payload.model_dump()
    if ROLE_CANTEEN_MANAGER in principal.roles and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        data["canteen_id"] = scoped_canteen_for_principal(principal, payload.canteen_id)
    return notification_service.create_announcement(db, data, principal.user.id)


@router.delete("/announcements/{announcement_id}")
def deactivate_announcement(
    announcement_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    ann = db.get(Announcement, announcement_id)
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")
    enforce_canteen_scope(principal, ann.canteen_id)
    ann.is_active = False
    db.commit()
    return {"status": "deactivated", "id": str(announcement_id)}
