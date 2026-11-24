from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
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
from app.services.audit_service import record_audit_log

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


class WebPushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)
    keys: dict = Field(default_factory=dict)
    device_name: Optional[str] = Field(default=None, max_length=120)


class AnnouncementCreateIn(BaseModel):
    canteen_id: Optional[UUID] = None
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=2)
    severity: str = Field(default="info", pattern="^(info|warning|urgent)$")
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class SystemMaintenanceIn(BaseModel):
    canteen_id: Optional[UUID] = None
    title: str = Field(min_length=2, max_length=200)
    message: str = Field(min_length=2, max_length=1000)
    priority: str = Field(default="high", pattern="^(low|normal|high|critical)$")


@router.get("/my")
def get_my_notifications(
    q: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    delivery_status: Optional[str] = Query(default=None),
    is_read: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    rows = notification_service.list_my_notifications(
        db,
        principal.user.id,
        principal.roles,
        assigned_canteen_id=principal.assigned_canteen_id,
        q=q,
        priority=priority,
        category=category,
        event_type=event_type,
        delivery_status=delivery_status,
        is_read=is_read,
        limit=limit,
        offset=offset,
    )
    return [notification_service.serialize_notification_for_user(n, principal.user.id) for n in rows]


@router.get("/unread-count")
def get_unread_count(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return {
        "unread_count": notification_service.get_unread_count(
            db, principal.user.id, principal.roles, assigned_canteen_id=principal.assigned_canteen_id
        )
    }


@router.get("/history")
def get_notification_history(
    q: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    delivery_status: Optional[str] = Query(default=None),
    is_read: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return notification_service.get_notification_history(
        db,
        principal.user.id,
        principal.roles,
        assigned_canteen_id=principal.assigned_canteen_id,
        q=q,
        priority=priority,
        category=category,
        event_type=event_type,
        delivery_status=delivery_status,
        is_read=is_read,
        limit=limit,
        offset=offset,
    )


@router.get("/deliveries")
def list_deliveries(
    canteen_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None),
    channel: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, canteen_id)
    return notification_service.list_notification_deliveries(
        db, canteen_id=eff_cid, status_filter=status_filter, channel=channel, limit=limit, offset=offset
    )


@router.post("/{notification_id}/retry")
def retry_notification(
    notification_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    scoped_cid = (
        principal.assigned_canteen_id
        if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)
        else None
    )
    return notification_service.retry_failed_notification(
        db, notification_id, principal.user.id, assigned_canteen_id=scoped_cid
    )


@router.post("/system-maintenance", status_code=status.HTTP_201_CREATED)
def broadcast_system_maintenance(
    payload: SystemMaintenanceIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    rows = notification_service.notify_system_maintenance(
        db,
        title=payload.title,
        message=payload.message,
        priority=payload.priority,
        canteen_id=payload.canteen_id,
        actor_user_id=principal.user.id,
    )
    return {"broadcasted_targets": len(rows), "title": payload.title, "priority": payload.priority}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return notification_service.mark_notification_read(
        db,
        notification_id,
        principal.user.id,
        principal.roles,
        assigned_canteen_id=principal.assigned_canteen_id,
    )


@router.post("/mark-all-read")
def mark_all_read(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    count = notification_service.mark_all_notifications_read(
        db, principal.user.id, principal.roles, assigned_canteen_id=principal.assigned_canteen_id
    )
    return {"marked_read": count}


@router.get("/web-push/public-key")
def get_vapid_public_key():
    return {
        "public_key": settings.VAPID_PUBLIC_KEY or None,
        "supported": bool(settings.VAPID_PUBLIC_KEY),
    }


@router.post("/web-push/subscribe")
def subscribe_web_push(
    payload: WebPushSubscriptionIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    pref = notification_service.register_web_push_subscription(db, principal.user.id, payload.model_dump())
    return {"status": "subscribed", "subscription_count": len(pref.web_push_subscriptions or [])}


@router.delete("/web-push/subscribe")
def unsubscribe_web_push(
    endpoint: str = Query(min_length=10),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    pref = notification_service.unregister_web_push_subscription(db, principal.user.id, endpoint)
    return {"status": "unsubscribed", "subscription_count": len(pref.web_push_subscriptions or [])}


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
    record_audit_log(
        db,
        action="notification.announcement_deactivated",
        entity_type="announcement",
        entity_id=str(announcement_id),
        actor_user_id=principal.user.id,
        details={"title": ann.title},
    )
    db.commit()
    return {"status": "deactivated", "id": str(announcement_id)}
