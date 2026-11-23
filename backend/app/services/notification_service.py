import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import event, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.email_provider import send_email
from app.integrations.expo_push_provider import send_expo_push
from app.integrations.sms_provider import send_sms_or_whatsapp
from app.integrations.web_push_provider import send_web_push
from app.models.auth import CustomerProfile, StaffProfile, User, UserRole
from app.models.auth import Role
from app.models.engagement import Announcement, Notification, NotificationPreference
from app.models.order import Order
from app.websockets import emit_user_notification_sync

logger = logging.getLogger("collegebites.notifications")


@event.listens_for(Session, "after_commit")
def _flush_after_commit_ws_notifications(session: Session) -> None:
    pending = session.info.pop("_pending_notif_ws", None)
    if not pending:
        return
    for target_type, target_id, event_type, payload in pending:
        if target_type == "user":
            emit_user_notification_sync(target_id, event_type, payload)


def _queue_ws_notification(
    db: Session,
    *,
    user_id: UUID,
    event_type: str,
    title: str,
    message: str,
    order_number: Optional[str] = None,
) -> None:
    queue = db.info.setdefault("_pending_notif_ws", [])
    queue.append(("user", str(user_id), event_type, {"title": title, "message": message, "order_number": order_number}))


def _safe_send_email(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    try:
        ok, reason = send_email(to_email, subject, body)
        if not ok:
            logger.warning("Email delivery failed/skipped to %s: %s", to_email, reason)
        return ok, reason
    except Exception as exc:
        logger.warning("Non-fatal email delivery failure to %s: %s", to_email, exc)
        return False, str(exc)


def _safe_send_sms(phone: str, msg: str, channel: str = "sms") -> tuple[bool, str]:
    try:
        ok, reason = send_sms_or_whatsapp(phone, msg, channel)
        if not ok:
            logger.warning("%s delivery failed/skipped to %s: %s", channel, phone, reason)
        return ok, reason
    except Exception as exc:
        logger.warning("Non-fatal %s delivery failure to %s: %s", channel, phone, exc)
        return False, str(exc)


def _safe_send_push(token: str, title: str, msg: str, data: Optional[dict] = None) -> tuple[bool, str]:
    try:
        ok, reason = send_expo_push(token, title, msg, data or {})
        if not ok:
            logger.warning("Expo push delivery failed/skipped: %s", reason)
        return ok, reason
    except Exception as exc:
        logger.warning("Non-fatal push delivery failure: %s", exc)
        return False, str(exc)


def _send_web_push_for_pref(
    pref: NotificationPreference,
    *,
    title: str,
    msg: str,
    url_path: str,
    data: Optional[dict] = None,
) -> tuple[bool, list[str]]:
    subs = [s for s in (pref.web_push_subscriptions or []) if isinstance(s, dict) and s.get("endpoint")]
    if not subs or not pref.push_enabled or not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        return True, []
    errors: list[str] = []
    kept: list[dict] = []
    any_ok = False
    for sub in subs:
        ok, reason = send_web_push(sub, title=title, body=msg, url_path=url_path, data=data)
        if ok:
            any_ok = True
            kept.append(sub)
        elif reason == "gone":
            # Drop expired 404/410 browser endpoint cleanly
            continue
        else:
            errors.append(reason)
            kept.append(sub)
    if len(kept) != len(subs):
        pref.web_push_subscriptions = kept
    return any_ok or not errors, errors


def _dispatch_role_web_push(
    db: Session,
    *,
    role_target: str,
    canteen_id: Optional[UUID],
    title: str,
    msg: str,
    url_path: str,
    data: Optional[dict] = None,
) -> None:
    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        return
    stmt = (
        select(NotificationPreference)
        .join(User, User.id == NotificationPreference.user_id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .outerjoin(StaffProfile, StaffProfile.user_id == User.id)
        .where(
            User.is_active.is_(True),
            Role.name == role_target,
            NotificationPreference.push_enabled.is_(True),
        )
    )
    if canteen_id:
        stmt = stmt.where(
            or_(StaffProfile.assigned_canteen_id == canteen_id, StaffProfile.assigned_canteen_id.is_(None))
        )
    prefs = db.scalars(stmt).all()
    for p in prefs:
        if p.web_push_subscriptions:
            _send_web_push_for_pref(p, title=title, msg=msg, url_path=url_path, data=data)


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
    dedup_key: Optional[str] = None,
    metadata_json: Optional[dict] = None,
) -> tuple[Notification, bool]:
    if dedup_key:
        existing = db.scalar(select(Notification).where(Notification.dedup_key == dedup_key))
        if existing:
            return existing, False

    n = Notification(
        user_id=user_id,
        role_target=role_target,
        canteen_id=canteen_id,
        order_id=order_id,
        dedup_key=dedup_key,
        channel=channel,
        title=title,
        message=message,
        event_type=event_type,
        delivery_status="sent",
        metadata_json=metadata_json or {},
    )
    db.add(n)
    if user_id:
        _queue_ws_notification(
            db,
            user_id=user_id,
            event_type=event_type,
            title=title,
            message=message,
            order_number=(metadata_json or {}).get("order_number"),
        )
    elif role_target:
        url_path = (
            "/kitchen"
            if role_target == "kitchen_staff"
            else "/inventory"
            if role_target == "inventory_manager"
            else "/pickup"
            if role_target == "pickup_staff"
            else "/token-board"
        )
        _dispatch_role_web_push(
            db,
            role_target=role_target,
            canteen_id=canteen_id,
            title=title,
            msg=message,
            url_path=url_path,
            data={"event_type": event_type, **(metadata_json or {})},
        )
    return n, True


def _dispatch_user_notifications(
    db: Session,
    *,
    order: Order,
    title: str,
    msg: str,
    event_type: str,
    send_external: bool = True,
    dedup_suffix: Optional[str] = None,
) -> None:
    suffix = f":{dedup_suffix}" if dedup_suffix else ""
    meta = {"order_number": order.order_number, "canteen_id": str(order.canteen_id)}

    if order.customer_id:
        pref = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == order.customer_id))
        cust_prof = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == order.customer_id))
        opt_in = True if cust_prof is None else cust_prof.notification_opt_in
        dedup = f"{event_type}:{order.id}:{order.customer_id}{suffix}"

        created = True
        notif: Optional[Notification] = None
        if not pref or pref.in_app_enabled:
            notif, created = _create_notification(
                db,
                user_id=order.customer_id,
                canteen_id=order.canteen_id,
                order_id=order.id,
                title=title,
                message=msg,
                event_type=event_type,
                dedup_key=dedup,
                metadata_json=meta,
            )
        else:
            existing = db.scalar(select(Notification.id).where(Notification.dedup_key == dedup))
            created = existing is None

        if not created or not opt_in or not send_external:
            return

        delivery_errors: dict[str, str] = {}
        user = db.get(User, order.customer_id)
        if user and user.email and (not pref or pref.email_enabled):
            ok, reason = _safe_send_email(user.email, title, msg)
            if not ok:
                delivery_errors["email"] = reason
        if user and user.phone and (not pref or pref.sms_enabled):
            ok, reason = _safe_send_sms(user.phone, msg, "sms")
            if not ok:
                delivery_errors["sms"] = reason
        if user and user.phone and pref and pref.whatsapp_enabled:
            ok, reason = _safe_send_sms(user.phone, msg, "whatsapp")
            if not ok:
                delivery_errors["whatsapp"] = reason
        if pref and pref.push_enabled and pref.expo_push_token:
            ok, reason = _safe_send_push(pref.expo_push_token, title, msg, {"order_number": order.order_number})
            if not ok:
                delivery_errors["expo_push"] = reason
        if pref and pref.push_enabled and pref.web_push_subscriptions:
            wp_ok, wp_errs = _send_web_push_for_pref(
                pref,
                title=title,
                msg=msg,
                url_path=f"/orders/{order.order_number}",
                data={"order_number": order.order_number, "event_type": event_type},
            )
            if not wp_ok and wp_errs:
                delivery_errors["web_push"] = ",".join(wp_errs[:3])
        if notif and delivery_errors:
            notif.metadata_json = {**meta, "delivery_errors": delivery_errors}
    elif send_external:
        guest_dedup = f"{event_type}:guest:{order.id}{suffix}"
        existing_guest = db.scalar(select(Notification.id).where(Notification.dedup_key == guest_dedup))
        if existing_guest:
            return
        notif, _ = _create_notification(
            db,
            canteen_id=order.canteen_id,
            order_id=order.id,
            channel="external_guest",
            title=title,
            message=msg,
            event_type=event_type,
            dedup_key=guest_dedup,
            metadata_json=meta,
        )
        delivery_errors: dict[str, str] = {}
        if order.guest_phone:
            ok, reason = _safe_send_sms(order.guest_phone, msg, "sms")
            if not ok:
                delivery_errors["sms"] = reason
        if getattr(order, "guest_email", None):
            ok, reason = _safe_send_email(order.guest_email, title, msg)
            if not ok:
                delivery_errors["email"] = reason
        if delivery_errors:
            notif.metadata_json = {**meta, "delivery_errors": delivery_errors}


def notify_order_confirmed(db: Session, order: Order, pickup_token: str) -> None:
    title = f"Order Confirmed • Token {pickup_token}"
    msg = f"Payment confirmed for {order.order_number}. Show token {pickup_token} at pickup."
    _dispatch_user_notifications(db, order=order, title=title, msg=msg, event_type="order_confirmed", send_external=True)
    for role_name in ("kitchen_staff", "canteen_manager"):
        _create_notification(
            db,
            role_target=role_name,
            canteen_id=order.canteen_id,
            order_id=order.id,
            title=f"New Paid Order • {pickup_token}",
            message=f"Order {order.order_number} confirmed and ready for acceptance.",
            event_type="kitchen_new_order",
            dedup_key=f"kitchen_new_order:{order.id}:{role_name}",
            metadata_json={"order_number": order.order_number, "token_code": pickup_token},
        )


def notify_order_ready(db: Session, order: Order) -> None:
    title = "Food Ready for Pickup!"
    msg = f"Order {order.order_number} is ready! Please proceed to your pickup counter with your QR code."
    _dispatch_user_notifications(db, order=order, title=title, msg=msg, event_type="order_ready", send_external=True)
    _create_notification(
        db,
        role_target="pickup_staff",
        canteen_id=order.canteen_id,
        order_id=order.id,
        title=f"Order Ready at Counter • {order.order_number}",
        message=f"Order {order.order_number} is ready for QR verification & handover.",
        event_type="pickup_ready",
        dedup_key=f"pickup_ready:{order.id}",
        metadata_json={"order_number": order.order_number},
    )


def notify_order_completed(db: Session, order: Order) -> None:
    title = "Order Collected"
    msg = f"Order {order.order_number} handover completed. Enjoy your meal!"
    _dispatch_user_notifications(db, order=order, title=title, msg=msg, event_type="order_completed", send_external=False)


def notify_customer_order_event(
    db: Session,
    order: Order,
    *,
    event_type: str,
    title: str,
    message: str,
    send_external: bool = False,
    dedup_suffix: Optional[str] = None,
) -> None:
    _dispatch_user_notifications(
        db,
        order=order,
        title=title,
        msg=message,
        event_type=event_type,
        send_external=send_external,
        dedup_suffix=dedup_suffix,
    )


def notify_inventory_stock_alert(
    db: Session,
    *,
    canteen_id: UUID,
    inventory_item_id: UUID,
    ingredient_name: str,
    current_qty: str,
    reorder_level: str,
    unit: str,
    blocked_foods: list[str],
) -> None:
    hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    blocked_note = f" Unavailable menu items: {', '.join(blocked_foods[:5])}." if blocked_foods else ""
    title = f"Low Stock Alert • {ingredient_name}"
    msg = f"{ingredient_name} dropped to {current_qty} {unit} (reorder level: {reorder_level} {unit}).{blocked_note}"
    for role_name in ("inventory_manager", "canteen_manager"):
        _create_notification(
            db,
            role_target=role_name,
            canteen_id=canteen_id,
            title=title,
            message=msg,
            event_type="inventory_alert",
            dedup_key=f"inv_alert:{inventory_item_id}:{current_qty}:{hour_bucket}:{role_name}",
            metadata_json={
                "inventory_item_id": str(inventory_item_id),
                "ingredient_name": ingredient_name,
                "blocked_foods": blocked_foods,
            },
        )


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


def mark_all_notifications_read(
    db: Session,
    user_id: UUID,
    roles: Optional[set[str]] = None,
    assigned_canteen_id: Optional[UUID] = None,
) -> int:
    now = datetime.now(timezone.utc)
    conds = [Notification.user_id == user_id]
    if roles:
        conds.append(Notification.role_target.in_(list(roles)))
    rows = db.scalars(select(Notification).where(or_(*conds), Notification.is_read.is_(False))).all()
    marked = 0
    for n in rows:
        if n.user_id is None and n.role_target and assigned_canteen_id and n.canteen_id and n.canteen_id != assigned_canteen_id:
            continue
        n.is_read = True
        n.read_at = now
        marked += 1
    db.commit()
    return marked


def register_web_push_subscription(db: Session, user_id: UUID, subscription: dict) -> NotificationPreference:
    pref = get_or_create_preferences(db, user_id)
    endpoint = str(subscription.get("endpoint") or "").strip()
    if not endpoint:
        raise HTTPException(status_code=400, detail="Web push endpoint is required")
    existing = [s for s in (pref.web_push_subscriptions or []) if isinstance(s, dict) and s.get("endpoint") != endpoint]
    existing.append(
        {
            "endpoint": endpoint,
            "keys": subscription.get("keys") or {},
            "device_name": subscription.get("device_name"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    pref.web_push_subscriptions = existing[-10:]
    pref.push_enabled = True
    db.commit()
    db.refresh(pref)
    return pref


def unregister_web_push_subscription(db: Session, user_id: UUID, endpoint: str) -> NotificationPreference:
    pref = get_or_create_preferences(db, user_id)
    pref.web_push_subscriptions = [
        s for s in (pref.web_push_subscriptions or []) if isinstance(s, dict) and s.get("endpoint") != endpoint.strip()
    ]
    db.commit()
    db.refresh(pref)
    return pref


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
