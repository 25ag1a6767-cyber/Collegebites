from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    get_current_principal,
    require_roles,
)
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications & Announcements"])


class PreferencesUpdateIn(BaseModel):
    in_app_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None
    whatsapp_enabled: Optional[bool] = None
    expo_push_token: Optional[str] = None


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
    return notification_service.list_my_notifications(db, principal.user.id, principal.roles)


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return notification_service.mark_notification_read(db, notification_id, principal.user.id)


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


@router.get("/announcements")
def list_announcements(canteen_id: Optional[UUID] = Query(default=None), db: Session = Depends(get_db)):
    return notification_service.list_active_announcements(db, canteen_id=canteen_id)


@router.post("/announcements", status_code=status.HTTP_201_CREATED)
def create_announcement(
    payload: AnnouncementCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    return notification_service.create_announcement(db, payload.model_dump(), principal.user.id)
