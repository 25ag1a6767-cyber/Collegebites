from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.integrations.email_provider import send_email
from app.integrations.sms_provider import send_sms_or_whatsapp
from app.models.auth import User
from app.models.engagement import Announcement, Notification, NotificationPreference
from app.models.order import Order
from app.websockets import emit_user_notification_sync


def _create_notification(
    db: Session,
    *,
    user_id: Optional[UUID] = None,
    role_target: Optional[str] = None,
    canteen_id: Optional[UUID] = None,
    order_id: Optional[UUID] = None,
    channel: str = "in_app",
    title: str,
    message: str,
    event_type: str,
) -> Notification:
    n = Notification(
        user_id=user_id,
        role_target=role_target,
        canteen_id=canteen_id,
        order_id=order_id,
        channel=channel,
        title=title,
        message=message,
        event_type=event_type,
        delivery_status="sent",
    )
    db.add(n)
    if user_id:
        emit_user_notification_sync(str(user_id), event_type, {"title": title, "message": message})
    return n


def notify_order_confirmed(db: Session, order: Order, pickup_token: str) -> None:
    title = f"Order Confirmed • Token {pickup_token}"
    msg = f"Payment confirmed for {order.order_number}. Show token {pickup_token} at pickup."
    if order.customer_id:
        _create_notification(
            db,
            user_id=order.customer_id,
            canteen_id=order.canteen_id,
            order_id=order.id,
            title=title,
            message=msg,
            event_type="order_confirmed",
        )
        user = db.get(User, order.customer_id)
        if user and user.email:
            send_email(user.email, title, msg)
        if user and user.phone:
            send_sms_or_whatsapp(user.phone, msg, "sms")
    elif order.guest_phone:
        send_sms_or_whatsapp(order.guest_phone, msg, "sms")

    _create_notification(
        db,
        role_target="kitchen_staff",
        canteen_id=order.canteen_id,
        order_id=order.id,
        title=f"New Kitchen Order • {pickup_token}",
        message=f"Order {order.order_number} ready for acceptance.",
        event_type="kitchen_new_order",
    )


def notify_order_ready(db: Session, order: Order) -> None:
    if order.customer_id:
        _create_notification(
            db,
            user_id=order.customer_id,
            canteen_id=order.canteen_id,
            order_id=order.id,
            title="Food Ready for Pickup!",
            message=f"Order {order.order_number} is ready! Please proceed to your pickup counter with your QR code.",
            event_type="order_ready",
        )


def notify_order_completed(db: Session, order: Order) -> None:
    if order.customer_id:
        _create_notification(
            db,
            user_id=order.customer_id,
            canteen_id=order.canteen_id,
            order_id=order.id,
            title="Order Collected",
            message=f"Order {order.order_number} handover completed. Enjoy your meal!",
            event_type="order_completed",
        )


def list_my_notifications(db: Session, user_id: UUID, roles: set[str]) -> list[Notification]:
    conds = [Notification.user_id == user_id]
    if roles:
        conds.append(Notification.role_target.in_(list(roles)))
    return list(
        db.scalars(select(Notification).where(or_(*conds)).order_by(Notification.created_at.desc()).limit(100)).all()
    )


def mark_notification_read(db: Session, notification_id: UUID, user_id: UUID) -> Notification:
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    n.read_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(n)
    return n


def get_or_create_preferences(db: Session, user_id: UUID) -> NotificationPreference:
    pref = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    if not pref:
        pref = NotificationPreference(user_id=user_id)
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


def update_preferences(db: Session, user_id: UUID, data: dict) -> NotificationPreference:
    pref = get_or_create_preferences(db, user_id)
    for k, v in data.items():
        if v is not None:
            setattr(pref, k, v)
    db.commit()
    db.refresh(pref)
    return pref


def list_active_announcements(db: Session, canteen_id: Optional[UUID] = None) -> list[Announcement]:
    now = datetime.now(timezone.utc)
    stmt = select(Announcement).where(Announcement.is_active.is_(True)).order_by(Announcement.created_at.desc())
    if canteen_id:
        stmt = stmt.where(or_(Announcement.canteen_id == canteen_id, Announcement.canteen_id.is_(None)))
    rows = db.scalars(stmt).all()
    return [a for a in rows if (not a.starts_at or a.starts_at <= now) and (not a.ends_at or a.ends_at > now)]


def create_announcement(db: Session, data: dict, actor_user_id: UUID) -> Announcement:
    ann = Announcement(**data, created_by_user_id=actor_user_id)
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann
