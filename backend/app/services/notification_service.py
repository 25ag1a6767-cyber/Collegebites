import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import event, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import mask_mobile
from app.integrations.email_provider import send_email
from app.integrations.expo_push_provider import send_expo_push
from app.integrations.sms_provider import send_sms_or_whatsapp
from app.integrations.web_push_provider import send_web_push
from app.models.auth import CustomerProfile, Role, StaffProfile, User, UserRole
from app.models.engagement import Announcement, Notification, NotificationDelivery, NotificationPreference
from app.models.order import Order
from app.services.audit_service import record_audit_log
from app.websockets import emit_user_notification_sync

logger = logging.getLogger("collegebites.notifications")

VALID_PRIORITIES = {"low", "normal", "high", "critical"}
VALID_CATEGORIES = {
    "order",
    "payment",
    "inventory",
    "procurement",
    "production",
    "food_safety",
    "queue",
    "system",
    "announcement",
}


def _mask_email(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"{local[:1]}***@{domain}"
    return f"{local[:2]}***@{domain}"


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
    priority: str = "normal",
    category: str = "order",
    order_number: Optional[str] = None,
) -> None:
    queue = db.info.setdefault("_pending_notif_ws", [])
    queue.append(
        (
            "user",
            str(user_id),
            event_type,
            {
                "title": title,
                "message": message,
                "priority": priority,
                "category": category,
                "order_number": order_number,
            },
        )
    )


def _record_delivery(
    db: Session,
    *,
    notification: Notification,
    channel: str,
    recipient_masked: Optional[str],
    status: str,
    provider_name: str,
    provider_message_id: Optional[str] = None,
    last_error: Optional[str] = None,
) -> NotificationDelivery:
    now = datetime.now(timezone.utc)
    delivery = NotificationDelivery(
        notification_id=notification.id,
        channel=channel,
        recipient_masked=recipient_masked,
        status=status,
        provider_name=provider_name,
        provider_message_id=provider_message_id,
        attempt_count=1,
        last_error=last_error,
        sent_at=now if status in ("sent", "delivered") else None,
        delivered_at=now if status == "delivered" else None,
        next_retry_at=(now + timedelta(minutes=5)) if status == "failed" else None,
    )
    db.add(delivery)
    return delivery


def _safe_send_email(to_email: str, subject: str, body: str) -> tuple[str, str]:
    """Return strict delivery status ('sent' | 'pending' | 'failed') + detail."""
    try:
        ok, reason = send_email(to_email, subject, body)
        if not ok:
            logger.warning("Email delivery failed to %s: %s", _mask_email(to_email), reason)
            return "failed", reason
        if reason == "sent":
            return "sent", "smtp_accepted"
        return "pending", reason
    except Exception as exc:
        logger.warning("Non-fatal email delivery failure: %s", exc)
        return "failed", str(exc)


def _safe_send_sms(phone: str, msg: str, channel: str = "sms") -> tuple[str, str]:
    try:
        ok, reason = send_sms_or_whatsapp(phone, msg, channel)
        if not ok:
            logger.warning("%s delivery failed: %s", channel, reason)
            return "failed", reason
        if reason in ("logged", "pending"):
            return "pending", reason
        return "sent", reason
    except Exception as exc:
        logger.warning("Non-fatal %s delivery failure: %s", channel, exc)
        return "failed", str(exc)


def _safe_send_push(token: str, title: str, msg: str, data: Optional[dict] = None) -> tuple[str, str]:
    try:
        ok, reason = send_expo_push(token, title, msg, data or {})
        if not ok:
            return "failed", reason
        return "sent", reason
    except Exception as exc:
        return "failed", str(exc)


def _send_web_push_for_pref(
    pref: NotificationPreference,
    *,
    title: str,
    msg: str,
    url_path: str,
    data: Optional[dict] = None,
) -> tuple[str, list[str]]:
    subs = [s for s in (pref.web_push_subscriptions or []) if isinstance(s, dict) and s.get("endpoint")]
    if not subs or not pref.push_enabled or not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        return "pending", []
    errors: list[str] = []
    kept: list[dict] = []
    any_ok = False
    for sub in subs:
        ok, reason = send_web_push(sub, title=title, body=msg, url_path=url_path, data=data)
        if ok:
            any_ok = True
            kept.append(sub)
        elif reason == "gone":
            continue
        else:
            errors.append(reason)
            kept.append(sub)
    if len(kept) != len(subs):
        pref.web_push_subscriptions = kept
    if any_ok:
        return "sent", errors
    return ("failed" if errors else "pending"), errors


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
    for p in db.scalars(stmt).all():
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
    category: str = "order",
    priority: str = "normal",
    title: str,
    message: str,
    event_type: str,
    dedup_key: Optional[str] = None,
    event_id: Optional[str] = None,
    metadata_json: Optional[dict] = None,
) -> tuple[Notification, bool]:
    eff_event_id = event_id or dedup_key
    if dedup_key:
        existing = db.scalar(select(Notification).where(Notification.dedup_key == dedup_key))
        if existing:
            return existing, False
    elif eff_event_id:
        existing = db.scalar(select(Notification).where(Notification.event_id == eff_event_id))
        if existing:
            return existing, False

    safe_priority = priority if priority in VALID_PRIORITIES else "normal"
    safe_category = category if category in VALID_CATEGORIES else "order"
    now = datetime.now(timezone.utc)
    # In-app notifications stored in DB are immediately delivered; external-only start pending until provider confirms.
    initial_status = "delivered" if channel == "in_app" else "pending"

    n = Notification(
        user_id=user_id,
        role_target=role_target,
        canteen_id=canteen_id,
        order_id=order_id,
        dedup_key=dedup_key,
        event_id=eff_event_id,
        channel=channel,
        category=safe_category,
        priority=safe_priority,
        title=title,
        message=message,
        event_type=event_type,
        delivery_status=initial_status,
        delivered_at=now if initial_status == "delivered" else None,
        metadata_json=metadata_json or {},
    )
    db.add(n)
    db.flush()

    if channel == "in_app":
        _record_delivery(
            db,
            notification=n,
            channel="in_app",
            recipient_masked=f"role:{role_target}" if role_target else (f"user:{str(user_id)[:8]}" if user_id else "broadcast"),
            status="delivered",
            provider_name="collegebites_in_app",
        )

    if user_id:
        _queue_ws_notification(
            db,
            user_id=user_id,
            event_type=event_type,
            title=title,
            message=message,
            priority=safe_priority,
            category=safe_category,
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
            else "/food-safety"
            if role_target == "food_safety_inspector"
            else "/token-board"
        )
        _dispatch_role_web_push(
            db,
            role_target=role_target,
            canteen_id=canteen_id,
            title=title,
            msg=message,
            url_path=url_path,
            data={"event_type": event_type, "priority": safe_priority, **(metadata_json or {})},
        )
    return n, True


def create_role_notifications(
    db: Session,
    *,
    roles: list[str],
    canteen_id: Optional[UUID],
    event_type: str,
    category: str,
    priority: str,
    title: str,
    message: str,
    event_id_base: str,
    order_id: Optional[UUID] = None,
    metadata_json: Optional[dict] = None,
) -> list[Notification]:
    created_rows: list[Notification] = []
    for role_name in roles:
        dedup = f"{event_id_base}:{role_name}"
        n, created = _create_notification(
            db,
            role_target=role_name,
            canteen_id=canteen_id,
            order_id=order_id,
            category=category,
            priority=priority,
            title=title,
            message=message,
            event_type=event_type,
            dedup_key=dedup,
            event_id=dedup,
            metadata_json=metadata_json,
        )
        if created:
            created_rows.append(n)
    return created_rows


def _dispatch_user_notifications(
    db: Session,
    *,
    order: Order,
    title: str,
    msg: str,
    event_type: str,
    category: str = "order",
    priority: str = "normal",
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
                category=category,
                priority=priority,
                title=title,
                message=msg,
                event_type=event_type,
                dedup_key=dedup,
                metadata_json=meta,
            )
        else:
            existing = db.scalar(select(Notification.id).where(Notification.dedup_key == dedup))
            created = existing is None

        if not created or not opt_in or not send_external or notif is None:
            return

        delivery_errors: dict[str, str] = {}
        user = db.get(User, order.customer_id)
        if user and user.email and (not pref or pref.email_enabled):
            st, reason = _safe_send_email(user.email, title, msg)
            _record_delivery(
                db,
                notification=notif,
                channel="email",
                recipient_masked=_mask_email(user.email),
                status=st,
                provider_name="smtp",
                last_error=reason if st == "failed" else None,
            )
            if st == "failed":
                delivery_errors["email"] = reason
        if user and user.phone and (not pref or pref.sms_enabled):
            st, reason = _safe_send_sms(user.phone, msg, "sms")
            _record_delivery(
                db,
                notification=notif,
                channel="sms",
                recipient_masked=mask_mobile(user.phone),
                status=st,
                provider_name=settings.SMS_PROVIDER,
                last_error=reason if st == "failed" else None,
            )
            if st == "failed":
                delivery_errors["sms"] = reason
        if user and user.phone and pref and pref.whatsapp_enabled:
            st, reason = _safe_send_sms(user.phone, msg, "whatsapp")
            _record_delivery(
                db,
                notification=notif,
                channel="whatsapp",
                recipient_masked=mask_mobile(user.phone),
                status=st,
                provider_name=settings.WHATSAPP_PROVIDER,
                last_error=reason if st == "failed" else None,
            )
            if st == "failed":
                delivery_errors["whatsapp"] = reason
        if pref and pref.push_enabled and pref.expo_push_token:
            st, reason = _safe_send_push(pref.expo_push_token, title, msg, {"order_number": order.order_number})
            _record_delivery(
                db,
                notification=notif,
                channel="expo_push",
                recipient_masked="expo_device",
                status=st,
                provider_name="expo",
                last_error=reason if st == "failed" else None,
            )
            if st == "failed":
                delivery_errors["expo_push"] = reason
        if pref and pref.push_enabled and pref.web_push_subscriptions:
            st, wp_errs = _send_web_push_for_pref(
                pref,
                title=title,
                msg=msg,
                url_path=f"/orders/{order.order_number}",
                data={"order_number": order.order_number, "event_type": event_type},
            )
            _record_delivery(
                db,
                notification=notif,
                channel="web_push",
                recipient_masked="web_push_endpoint",
                status=st,
                provider_name="vapid_web_push",
                last_error=",".join(wp_errs[:3]) if wp_errs else None,
            )
            if st == "failed" and wp_errs:
                delivery_errors["web_push"] = ",".join(wp_errs[:3])
        if delivery_errors:
            notif.last_error = str(delivery_errors)[:500]
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
            category=category,
            priority=priority,
            title=title,
            message=msg,
            event_type=event_type,
            dedup_key=guest_dedup,
            metadata_json=meta,
        )
        delivery_errors: dict[str, str] = {}
        any_sent = False
        any_failed = False
        if order.guest_phone:
            st, reason = _safe_send_sms(order.guest_phone, msg, "sms")
            _record_delivery(
                db,
                notification=notif,
                channel="sms",
                recipient_masked=mask_mobile(order.guest_phone),
                status=st,
                provider_name=settings.SMS_PROVIDER,
                last_error=reason if st == "failed" else None,
            )
            any_sent = any_sent or st == "sent"
            any_failed = any_failed or st == "failed"
            if st == "failed":
                delivery_errors["sms"] = reason
        if getattr(order, "guest_email", None):
            st, reason = _safe_send_email(order.guest_email, title, msg)
            _record_delivery(
                db,
                notification=notif,
                channel="email",
                recipient_masked=_mask_email(order.guest_email),
                status=st,
                provider_name="smtp",
                last_error=reason if st == "failed" else None,
            )
            any_sent = any_sent or st == "sent"
            any_failed = any_failed or st == "failed"
            if st == "failed":
                delivery_errors["email"] = reason
        notif.delivery_status = "sent" if any_sent else ("failed" if any_failed else "pending")
        if delivery_errors:
            notif.last_error = str(delivery_errors)[:500]
            notif.metadata_json = {**meta, "delivery_errors": delivery_errors}


# =============================================================================
# DOMAIN EVENT NOTIFICATION TRIGGERS (ALL 20 ENTERPRISE EVENTS)
# =============================================================================


def notify_order_confirmed(db: Session, order: Order, pickup_token: str) -> None:
    title = f"Order Confirmed • Token {pickup_token}"
    msg = f"Payment confirmed for {order.order_number}. Show token {pickup_token} at pickup."
    _dispatch_user_notifications(
        db, order=order, title=title, msg=msg, event_type="order_confirmed", category="payment", priority="normal", send_external=True
    )
    create_role_notifications(
        db,
        roles=["kitchen_staff", "canteen_manager"],
        canteen_id=order.canteen_id,
        order_id=order.id,
        event_type="kitchen_new_order",
        category="order",
        priority="normal",
        title=f"New Paid Order • {pickup_token}",
        message=f"Order {order.order_number} confirmed and ready for acceptance.",
        event_id_base=f"kitchen_new_order:{order.id}",
        metadata_json={"order_number": order.order_number, "token_code": pickup_token},
    )


def notify_order_ready(db: Session, order: Order) -> None:
    title = "Food Ready for Pickup!"
    msg = f"Order {order.order_number} is ready! Please proceed to your pickup counter with your QR code."
    _dispatch_user_notifications(
        db, order=order, title=title, msg=msg, event_type="order_ready", category="order", priority="high", send_external=True
    )
    create_role_notifications(
        db,
        roles=["pickup_staff"],
        canteen_id=order.canteen_id,
        order_id=order.id,
        event_type="pickup_ready",
        category="order",
        priority="normal",
        title=f"Order Ready at Counter • {order.order_number}",
        message=f"Order {order.order_number} is ready for QR verification & handover.",
        event_id_base=f"pickup_ready:{order.id}",
        metadata_json={"order_number": order.order_number},
    )


def notify_order_completed(db: Session, order: Order) -> None:
    title = "Order Collected"
    msg = f"Order {order.order_number} handover completed. Enjoy your meal!"
    _dispatch_user_notifications(
        db, order=order, title=title, msg=msg, event_type="order_completed", category="order", priority="low", send_external=False
    )


def notify_payment_failed(db: Session, order: Order, reason: str) -> None:
    safe_reason = (reason or "Payment could not be verified")[:140]
    _dispatch_user_notifications(
        db,
        order=order,
        title="Payment Failed",
        msg=f"Payment for order {order.order_number} failed ({safe_reason}). You can retry online payment.",
        event_type="payment_failed",
        category="payment",
        priority="high",
        send_external=True,
    )


def notify_duplicate_payment_investigation(db: Session, order: Order, ref_code: str) -> None:
    masked_ref = f"{ref_code[:6]}***" if len(ref_code) > 6 else "***"
    create_role_notifications(
        db,
        roles=["college_admin", "canteen_manager"],
        canteen_id=order.canteen_id,
        order_id=order.id,
        event_type="duplicate_payment_investigation",
        category="payment",
        priority="critical",
        title=f"Duplicate Payment Investigation • {order.order_number}",
        message=f"Duplicate or late payment callback ({masked_ref}) detected on order {order.order_number}. Logged for finance office review under no-refund policy.",
        event_id_base=f"dup_pay_inv:{order.id}:{masked_ref}",
        metadata_json={"order_number": order.order_number},
    )


def notify_customer_order_event(
    db: Session,
    order: Order,
    *,
    event_type: str,
    title: str,
    message: str,
    category: str = "order",
    priority: str = "normal",
    send_external: bool = False,
    dedup_suffix: Optional[str] = None,
) -> None:
    _dispatch_user_notifications(
        db,
        order=order,
        title=title,
        msg=message,
        event_type=event_type,
        category=category,
        priority=priority,
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
    is_critical: bool = False,
) -> None:
    hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    blocked_note = f" Unavailable menu items: {', '.join(blocked_foods[:5])}." if blocked_foods else ""
    ev_type = "critical_stock_shortage" if is_critical else "low_inventory"
    priority = "critical" if is_critical else "high"
    title = f"{'CRITICAL Stock Shortage' if is_critical else 'Low Stock Alert'} • {ingredient_name}"
    msg = f"{ingredient_name} dropped to {current_qty} {unit} (reorder level: {reorder_level} {unit}).{blocked_note}"
    create_role_notifications(
        db,
        roles=["inventory_manager", "canteen_manager", "college_admin"],
        canteen_id=canteen_id,
        event_type=ev_type,
        category="inventory",
        priority=priority,
        title=title,
        message=msg,
        event_id_base=f"inv_alert:{ev_type}:{inventory_item_id}:{current_qty}:{hour_bucket}",
        metadata_json={
            "inventory_item_id": str(inventory_item_id),
            "ingredient_name": ingredient_name,
            "blocked_foods": blocked_foods,
        },
    )


def notify_inventory_expiry_alert(
    db: Session,
    *,
    canteen_id: UUID,
    batch_id: UUID,
    batch_number: str,
    ingredient_name: str,
    expiry_date_str: str,
    is_expired: bool,
) -> None:
    day_bucket = datetime.now(timezone.utc).strftime("%Y%m%d")
    ev_type = "expired_inventory" if is_expired else "expiring_ingredient"
    create_role_notifications(
        db,
        roles=["inventory_manager", "canteen_manager", "food_safety_inspector"],
        canteen_id=canteen_id,
        event_type=ev_type,
        category="food_safety" if is_expired else "inventory",
        priority="critical" if is_expired else "high",
        title=f"{'Expired Batch Blocked' if is_expired else 'Expiring Ingredient Alert'} • {ingredient_name}",
        message=f"Batch {batch_number} ({ingredient_name}) {'expired on' if is_expired else 'expires on'} {expiry_date_str}.",
        event_id_base=f"{ev_type}:{batch_id}:{day_bucket}",
        metadata_json={"batch_id": str(batch_id), "batch_number": batch_number, "expiry_date": expiry_date_str},
    )


def notify_procurement_event(
    db: Session,
    *,
    canteen_id: UUID,
    event_type: str,
    po_number: str,
    title: str,
    message: str,
    priority: str = "normal",
    roles: Optional[list[str]] = None,
) -> None:
    create_role_notifications(
        db,
        roles=roles or ["inventory_manager", "canteen_manager", "college_admin"],
        canteen_id=canteen_id,
        event_type=event_type,
        category="procurement",
        priority=priority,
        title=title,
        message=message,
        event_id_base=f"proc:{event_type}:{po_number}",
        metadata_json={"po_number": po_number},
    )


def notify_food_safety_event(
    db: Session,
    *,
    canteen_id: UUID,
    event_type: str,
    ref_id: str,
    title: str,
    message: str,
    priority: str = "high",
) -> None:
    create_role_notifications(
        db,
        roles=["food_safety_inspector", "canteen_manager", "college_admin", "kitchen_staff"],
        canteen_id=canteen_id,
        event_type=event_type,
        category="food_safety",
        priority=priority,
        title=title,
        message=message,
        event_id_base=f"fs:{event_type}:{ref_id}",
        metadata_json={"reference_id": ref_id},
    )


def notify_queue_congestion(
    db: Session,
    *,
    canteen_id: UUID,
    canteen_name: str,
    crowd_level: str,
    active_orders: int,
    est_wait_minutes: int,
) -> None:
    half_hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    create_role_notifications(
        db,
        roles=["canteen_manager", "kitchen_staff", "college_admin"],
        canteen_id=canteen_id,
        event_type="queue_congestion",
        category="queue",
        priority="critical" if crowd_level == "VERY_HIGH" else "high",
        title=f"Queue Congestion ({crowd_level}) • {canteen_name}",
        message=f"{canteen_name} currently has {active_orders} active orders (estimated wait ~{est_wait_minutes} min).",
        event_id_base=f"queue_cong:{canteen_id}:{crowd_level}:{half_hour_bucket}",
        metadata_json={"crowd_level": crowd_level, "active_orders": active_orders, "estimated_wait_minutes": est_wait_minutes},
    )


def notify_system_maintenance(
    db: Session,
    *,
    title: str,
    message: str,
    priority: str = "high",
    canteen_id: Optional[UUID] = None,
    actor_user_id: Optional[UUID] = None,
) -> list[Notification]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rows = create_role_notifications(
        db,
        roles=["college_admin", "canteen_manager", "kitchen_staff", "inventory_manager", "cashier", "pickup_staff", "food_safety_inspector", "customer"],
        canteen_id=canteen_id,
        event_type="system_maintenance",
        category="system",
        priority=priority,
        title=title,
        message=message,
        event_id_base=f"sys_maint:{ts}",
    )
    record_audit_log(
        db,
        action="notification.system_maintenance_broadcast",
        entity_type="notification",
        entity_id=f"sys_maint:{ts}",
        actor_user_id=actor_user_id,
        details={"title": title, "priority": priority, "targets": len(rows)},
    )
    db.commit()
    return rows


# =============================================================================
# QUERY, SEARCH, RETRY & AUDIT APIS
# =============================================================================


def _serialize_notification(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "user_id": str(n.user_id) if n.user_id else None,
        "role_target": n.role_target,
        "canteen_id": str(n.canteen_id) if n.canteen_id else None,
        "order_id": str(n.order_id) if n.order_id else None,
        "event_id": n.event_id or n.dedup_key,
        "channel": n.channel,
        "category": getattr(n, "category", "order") or "order",
        "priority": getattr(n, "priority", "normal") or "normal",
        "title": n.title,
        "message": n.message,
        "event_type": n.event_type,
        "delivery_status": n.delivery_status,
        "retry_count": n.retry_count,
        "last_error": getattr(n, "last_error", None),
        "delivered_at": n.delivered_at.isoformat() if getattr(n, "delivered_at", None) else None,
        "is_read": n.is_read,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "metadata_json": n.metadata_json or {},
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def list_my_notifications(
    db: Session,
    user_id: UUID,
    roles: set[str],
    assigned_canteen_id: Optional[UUID] = None,
    *,
    q: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    event_type: Optional[str] = None,
    delivery_status: Optional[str] = None,
    is_read: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Notification]:
    conds = [Notification.user_id == user_id]
    if roles:
        conds.append(Notification.role_target.in_(list(roles)))
    stmt = select(Notification).where(or_(*conds))
    if priority:
        stmt = stmt.where(Notification.priority == priority)
    if category:
        stmt = stmt.where(Notification.category == category)
    if event_type:
        stmt = stmt.where(Notification.event_type == event_type)
    if delivery_status:
        stmt = stmt.where(Notification.delivery_status == delivery_status)
    if is_read is not None:
        stmt = stmt.where(Notification.is_read.is_(is_read))
    if q and q.strip():
        pat = f"%{q.strip()}%"
        stmt = stmt.where(or_(Notification.title.ilike(pat), Notification.message.ilike(pat), Notification.event_type.ilike(pat)))

    rows = db.scalars(stmt.order_by(Notification.created_at.desc()).limit(max(150, limit + offset + 50))).all()
    filtered = []
    for n in rows:
        if n.user_id is None and n.role_target and assigned_canteen_id and n.canteen_id and n.canteen_id != assigned_canteen_id:
            continue
        filtered.append(n)
    return filtered[offset : offset + max(1, min(limit, 200))]


def get_unread_count(
    db: Session,
    user_id: UUID,
    roles: set[str],
    assigned_canteen_id: Optional[UUID] = None,
) -> int:
    rows = list_my_notifications(
        db, user_id, roles, assigned_canteen_id=assigned_canteen_id, is_read=False, limit=200
    )
    return len(rows)


def get_notification_history(
    db: Session,
    user_id: UUID,
    roles: set[str],
    assigned_canteen_id: Optional[UUID] = None,
    *,
    q: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    event_type: Optional[str] = None,
    delivery_status: Optional[str] = None,
    is_read: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    all_matched = list_my_notifications(
        db,
        user_id,
        roles,
        assigned_canteen_id=assigned_canteen_id,
        q=q,
        priority=priority,
        category=category,
        event_type=event_type,
        delivery_status=delivery_status,
        is_read=is_read,
        limit=200,
        offset=0,
    )
    unread = sum(1 for n in all_matched if not n.is_read)
    page = all_matched[offset : offset + max(1, min(limit, 100))]
    return {
        "total": len(all_matched),
        "unread_count": unread,
        "limit": limit,
        "offset": offset,
        "items": [_serialize_notification(n) for n in page],
    }


def list_notification_deliveries(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    channel: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = (
        select(NotificationDelivery, Notification)
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .order_by(NotificationDelivery.created_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    if canteen_id:
        stmt = stmt.where((Notification.canteen_id == canteen_id) | (Notification.canteen_id.is_(None)))
    if status_filter:
        stmt = stmt.where(NotificationDelivery.status == status_filter)
    if channel:
        stmt = stmt.where(NotificationDelivery.channel == channel)
    rows = db.execute(stmt).all()
    return [
        {
            "id": str(d.id),
            "notification_id": str(d.notification_id),
            "event_type": n.event_type,
            "category": n.category,
            "priority": n.priority,
            "title": n.title,
            "channel": d.channel,
            "recipient_masked": d.recipient_masked,
            "status": d.status,
            "provider_name": d.provider_name,
            "attempt_count": d.attempt_count,
            "last_error": d.last_error,
            "sent_at": d.sent_at.isoformat() if d.sent_at else None,
            "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d, n in rows
    ]


def retry_failed_notification(db: Session, notification_id: UUID, actor_user_id: UUID) -> dict[str, Any]:
    notif = db.get(Notification, notification_id)
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    deliveries = list(
        db.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == notif.id,
                NotificationDelivery.status.in_(("failed", "pending")),
            )
        ).all()
    )
    user = db.get(User, notif.user_id) if notif.user_id else None
    retried = 0
    succeeded = 0
    now = datetime.now(timezone.utc)

    for d in deliveries:
        if d.channel == "in_app":
            continue
        retried += 1
        d.attempt_count += 1
        if d.channel == "email" and user and user.email:
            st, reason = _safe_send_email(user.email, notif.title, notif.message)
        elif d.channel in ("sms", "whatsapp") and user and user.phone:
            st, reason = _safe_send_sms(user.phone, notif.message, d.channel)
        else:
            st, reason = "pending", "no_direct_provider_target"
        d.status = st
        d.last_error = reason if st == "failed" else None
        if st in ("sent", "delivered"):
            d.sent_at = now
            succeeded += 1
        elif st == "failed":
            d.next_retry_at = now + timedelta(minutes=5 * d.attempt_count)

    notif.retry_count += 1
    if succeeded > 0:
        notif.delivery_status = "sent"
        notif.last_error = None
    record_audit_log(
        db,
        action="notification.retried",
        entity_type="notification",
        entity_id=str(notif.id),
        actor_user_id=actor_user_id,
        details={"retried_channels": retried, "succeeded": succeeded, "retry_count": notif.retry_count},
    )
    db.commit()
    db.refresh(notif)
    return {
        "notification_id": str(notif.id),
        "retried_channels": retried,
        "succeeded_channels": succeeded,
        "delivery_status": notif.delivery_status,
        "retry_count": notif.retry_count,
    }


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
    out = []
    for a in rows:
        st = a.starts_at.replace(tzinfo=timezone.utc) if (a.starts_at and a.starts_at.tzinfo is None) else a.starts_at
        en = a.ends_at.replace(tzinfo=timezone.utc) if (a.ends_at and a.ends_at.tzinfo is None) else a.ends_at
        if (not st or st <= now) and (not en or en > now):
            out.append(a)
    return out


def create_announcement(db: Session, data: dict, actor_user_id: UUID) -> Announcement:
    ann = Announcement(**data, created_by_user_id=actor_user_id)
    db.add(ann)
    db.flush()
    priority = "critical" if ann.severity == "urgent" else ("high" if ann.severity == "warning" else "normal")
    create_role_notifications(
        db,
        roles=["customer", "canteen_manager", "kitchen_staff", "cashier", "pickup_staff", "inventory_manager", "food_safety_inspector"],
        canteen_id=ann.canteen_id,
        event_type="admin_announcement",
        category="announcement",
        priority=priority,
        title=f"Campus Notice • {ann.title}",
        message=ann.body,
        event_id_base=f"announcement:{ann.id}",
        metadata_json={"announcement_id": str(ann.id), "severity": ann.severity},
    )
    record_audit_log(
        db,
        action="announcement.created",
        entity_type="announcement",
        entity_id=str(ann.id),
        actor_user_id=actor_user_id,
        details={"title": ann.title, "severity": ann.severity},
    )
    db.commit()
    db.refresh(ann)
    return ann
