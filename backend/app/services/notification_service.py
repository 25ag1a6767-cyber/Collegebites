import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.integrations.email_provider import send_email
from app.integrations.expo_push_provider import send_expo_push
from app.integrations.sms_provider import send_sms_or_whatsapp
from app.models.auth import CustomerProfile, User
from app.models.engagement import Announcement, Notification, NotificationPreference
from app.models.order import Order
from app.websockets import emit_user_notification_sync

logger = logging.getLogger("collegebites.notifications")


def _safe_send_email(to_email: str, subject: str, body: str) -> None:
    try:
        send_email(to_email, subject, body)
    except Exception as exc:
        logger.warning("Non-fatal email delivery failure to %s: %s", to_email, exc)


def _safe_send_sms(phone: str, msg: str, channel: str = "sms") -> None:
    try:
        send_sms_or_whatsapp(phone, msg, channel)
    except Exception as exc:
        logger.warning("Non-fatal %s delivery failure to %s: %s", channel, phone, exc)


def _safe_send_push(token: str, title: str, msg: str, data: Optional[dict] = None) -> None:
    try:
        send_expo_push(token, title, msg, data or {})
    except Exception as exc:
        logger.warning("Non-fatal push delivery failure: %s", exc)


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


def _dispatch_user_notifications(
    db: Session,
    *,
    order: Order,
    title: str,
    msg: str,
    event_type: str,
    send_external: bool = True,
) -> None:
    if order.customer_id:
        pref = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == order.customer_id))
        cust_prof = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == order.customer_id))
        opt_in = True if cust_prof is None else cust_prof.notification_opt_in
        if not pref or pref.in_app_enabled:
            _create_notification(
                db,
                user_id=order.customer_id,
                canteen_id=order.canteen_id,
                order_id=order.id,
                title=title,
                message=msg,
                event_type=event_type,
            )
        if not opt_in or not send_external:
            return
        user = db.get(User, order.customer_id)
        if user and user.email and (not pref or pref.email_enabled):
            _safe_send_email(user.email, title, msg)
        if user and user.phone and (not pref or pref.sms_enabled):
            _safe_send_sms(user.phone, msg, "sms")
        if user and user.phone and pref and pref.whatsapp_enabled:
            _safe_send_sms(user.phone, msg, "whatsapp")
        if pref and pref.push_enabled and pref.expo_push_token:
            _safe_send_push(pref.expo_push_token, title, msg, {"order_number": order.order_number})
    elif order.guest_phone and send_external:
        _safe_send_sms(order.guest_phone, msg, "sms")


def notify_order_confirmed(db: Session, order: Order, pickup_token: str) -> None:
    title = f"Order Confirmed • Token {pickup_token}"
    msg = f"Payment confirmed for {order.order_number}. Show token {pickup_token} at pickup."
    _dispatch_user_notifications(db, order=order, title=title, msg=msg, event_type="order_confirmed", send_external=True)
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
    title = "Food Ready for Pickup!"
    msg = f"Order {order.order_number} is ready! Please proceed to your pickup counter with your QR code."
    _dispatch_user_notifications(db, order=order, title=title, msg=msg, event_type="order_ready", send_external=True)


def notify_order_completed(db: Session, order: Order) -> None:
    title = "Order Collected"
    msg = f"Order {order.order_number} handover completed. Enjoy your meal!"
    _dispatch_user_notifications(db, order=order, title=title, msg=msg, event_type="order_completed", send_external=False)


def notify_customer_order_event(
    db: Session, order: Order, *, event_type: str, title: str, message: str, send_external: bool = False
) -> None:
    _dispatch_user_notifications(db, order=order, title=title, msg=message, event_type=event_type, send_external=send_external)


def list_my_notifications(
    db: Session, user_id: UUID, roles: set[str], assigned_canteen_id: Optional[UUID] = None
) -> list[Notification]:
    conds = [Notification.user_id == user_id]
    if roles:
        conds.append(Notification.role_target.in_(list(roles)))
    rows = db.scalars(select(Notification).where(or_(*conds)).order_by(Notification.created_at.desc()).limit(150)).all()
    filtered = []
    for n in rows:
        if n.user_id is None and n.role_target and assigned_canteen_id and n.canteen_id and n.canteen_id != assigned_canteen_id:
            continue
        filtered.append(n)
    return filtered[:100]


def mark_notification_read(db: Session, notification_id: UUID, user_id: UUID, roles: Optional[set[str]] = None) -> Notification:
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    role_match = bool(n.role_target and roles and n.role_target in roles)
    if n.user_id != user_id and not role_match:
        raise HTTPException(status_code=403, detail="Not authorized to modify this notification")
    n.is_read = True
    n.read_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(n)
    return n


def mark_all_notifications_read(db: Session, user_id: UUID, roles: Optional[set[str]] = None) -> int:
    now = datetime.now(timezone.utc)
    conds = [Notification.user_id == user_id]
    if roles:
        conds.append(Notification.role_target.in_(list(roles)))
    rows = db.scalars(select(Notification).where(or_(*conds), Notification.is_read.is_(False))).all()
    for n in rows:
        n.is_read = True
        n.read_at = now
    db.commit()
    return len(rows)


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
