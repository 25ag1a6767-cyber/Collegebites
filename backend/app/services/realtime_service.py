from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from uuid import UUID

from fastapi import Request
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.cache import NS_BOARD, NS_QUEUE, cache_manager
from app.core.database import get_db
from app.core.security import sha256_hex
from app.core.time_utils import today_college
from app.models.engagement import Notification
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.payment import OrderQRCode, PickupToken
from app.schemas.operations import DigitalBoardResponse, OperationalTokenBoardResponse
from app.schemas.order import OrderOut
from app.services import notification_service, order_service, pickup_service, queue_service


def resolve_db_session(request: Request) -> tuple[Any, Session]:
    """Open a short-lived DB session respecting FastAPI dependency overrides (tests and prod)."""
    provider: Callable[[], Any] = request.app.dependency_overrides.get(get_db, get_db)
    gen = provider()
    db = next(gen)
    return gen, db


def close_db_session(gen: Any) -> None:
    try:
        gen.close()
    except Exception:
        pass


def compute_board_watermark(db: Session, canteen_id: Optional[UUID] = None) -> str:
    """Fast single-row aggregate fingerprint for public token board state (coalesced across concurrent clients)."""
    cache_ns = f"{NS_BOARD}:{canteen_id}" if canteen_id is not None else NS_BOARD
    cache_key = f"wm:{canteen_id or 'all'}"
    hit, cached = cache_manager.get_json(cache_ns, cache_key, l1_ttl=0.8)
    if hit and isinstance(cached, str):
        return cached
    today = today_college()
    stmt = (
        select(
            func.count(Order.id),
            func.max(Order.updated_at),
            func.max(Order.completed_at),
            func.coalesce(func.sum(case((Order.status == "PLACED", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == "ACCEPTED", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == "PREPARING", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == "READY", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == "COMPLETED", 1), else_=0)), 0),
            func.coalesce(func.sum(Order.delayed_minutes), 0),
        )
        .join(PickupToken, PickupToken.order_id == Order.id)
        .where(
            PickupToken.service_date == today,
            Order.status.in_(("PLACED", "ACCEPTED", "PREPARING", "READY", "COMPLETED")),
        )
    )
    if canteen_id is not None:
        stmt = stmt.where(Order.canteen_id == canteen_id)
    row = db.execute(stmt).one()
    raw = "|".join(
        [
            today.isoformat(),
            str(canteen_id or "all"),
            str(row[0] or 0),
            row[1].isoformat() if row[1] else "",
            row[2].isoformat() if row[2] else "",
            *(str(row[idx] or 0) for idx in range(3, 9)),
        ]
    )
    wm = sha256_hex(raw)[:16]
    cache_manager.set_json(cache_ns, cache_key, wm, ttl_seconds=2, l1_ttl=0.8)
    return wm


def fetch_board_snapshot(db: Session, canteen_id: Optional[UUID] = None) -> DigitalBoardResponse:
    return pickup_service.get_digital_token_board(db, canteen_id)


def compute_order_version(db: Session, order_id: UUID) -> Optional[str]:
    row = db.execute(
        select(
            Order.id,
            Order.canteen_id,
            Order.counter_id,
            Order.status,
            Order.payment_status,
            Order.is_priority,
            Order.delayed_minutes,
            Order.ready_at,
            Order.completed_at,
            Order.updated_at,
        ).where(Order.id == order_id)
    ).first()
    if not row:
        return None
    token_code = db.scalar(select(PickupToken.token_code).where(PickupToken.order_id == order_id))
    qr_revoked = db.scalar(select(OrderQRCode.revoked_at).where(OrderQRCode.order_id == order_id))
    hist_count = db.scalar(select(func.count(OrderStatusHistory.id)).where(OrderStatusHistory.order_id == order_id)) or 0
    queue_fp = ""
    if row[3] in queue_service.ACTIVE_QUEUE_WAITING_STATUSES:
        q_row = db.execute(
            select(
                func.count(Order.id),
                func.max(Order.updated_at),
                func.coalesce(func.sum(case((Order.is_priority.is_(True), 1), else_=0)), 0),
                func.coalesce(func.sum(Order.delayed_minutes), 0),
            ).where(
                Order.canteen_id == row[1],
                Order.status.in_(queue_service.ACTIVE_QUEUE_WAITING_STATUSES),
            )
        ).one()
        queue_fp = f"{q_row[0] or 0}:{q_row[1].isoformat() if q_row[1] else ''}:{q_row[2] or 0}:{q_row[3] or 0}"
    raw = "|".join(
        [
            str(row[0]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(bool(row[5])),
            str(row[6] or 0),
            row[7].isoformat() if row[7] else "",
            row[8].isoformat() if row[8] else "",
            row[9].isoformat() if row[9] else "",
            str(token_code or ""),
            qr_revoked.isoformat() if qr_revoked else "",
            str(hist_count),
            queue_fp,
        ]
    )
    return sha256_hex(raw)[:16]


def fetch_order_snapshot(db: Session, order_id: UUID) -> tuple[Optional[str], Optional[OrderOut]]:
    version = compute_order_version(db, order_id)
    if not version:
        return None, None
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order_id)
    )
    if not order:
        return None, None
    return version, order_service.serialize_order(db, order)


def compute_staff_orders_version(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    payment_status: Optional[str] = None,
    q: Optional[str] = None,
) -> str:
    cache_ns = f"{NS_BOARD}:{canteen_id}" if canteen_id is not None else NS_BOARD
    cache_key = f"staff_wm:{canteen_id or 'all'}:{status_filter or ''}:{payment_status or ''}:{(q or '').strip().lower()}"
    hit, cached = cache_manager.get_json(cache_ns, cache_key, l1_ttl=1.5)
    if hit and isinstance(cached, str):
        return cached
    since_window = datetime.now(timezone.utc) - timedelta(hours=36)
    active_statuses = ("PAYMENT_PENDING", "PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING", "READY")
    stmt = select(
        func.count(Order.id),
        func.max(Order.updated_at),
        func.max(Order.created_at),
        func.coalesce(func.sum(case((Order.status == "PAYMENT_PENDING", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Order.status == "PLACED", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Order.status == "ACCEPTED", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Order.status == "PREPARING", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Order.status == "READY", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Order.status == "COMPLETED", 1), else_=0)), 0),
        func.coalesce(func.sum(case((Order.status.in_(("CANCELLED", "REJECTED")), 1), else_=0)), 0),
        func.coalesce(func.sum(Order.delayed_minutes), 0),
        func.coalesce(func.sum(case((Order.is_priority.is_(True), 1), else_=0)), 0),
    ).where(or_(Order.created_at >= since_window, Order.status.in_(active_statuses)))
    if canteen_id is not None:
        stmt = stmt.where(Order.canteen_id == canteen_id)
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    if payment_status:
        stmt = stmt.where(Order.payment_status == payment_status)
    row = db.execute(stmt).one()
    # Scope OrderItem prep check strictly to active kitchen orders instead of full-table scan
    item_stmt = (
        select(func.count(OrderItem.id))
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.status.in_(("PLACED", "ACCEPTED", "PREPARING", "READY")),
            OrderItem.prep_status != "PENDING",
        )
    )
    if canteen_id is not None:
        item_stmt = item_stmt.where(Order.canteen_id == canteen_id)
    item_prep_ready = db.scalar(item_stmt) or 0
    raw = "|".join(
        [
            str(canteen_id or "all"),
            str(status_filter or ""),
            str(payment_status or ""),
            (q or "").strip().lower(),
            str(row[0] or 0),
            row[1].isoformat() if row[1] else "",
            row[2].isoformat() if row[2] else "",
            *(str(row[idx] or 0) for idx in range(3, 12)),
            str(item_prep_ready),
        ]
    )
    wm = sha256_hex(raw)[:16]
    cache_manager.set_json(cache_ns, cache_key, wm, ttl_seconds=3, l1_ttl=1.5)
    return wm


def fetch_token_board_snapshot(db: Session, canteen_id: Optional[UUID] = None) -> OperationalTokenBoardResponse:
    return pickup_service.get_operational_token_board(db, canteen_id)


def compute_queue_version(db: Session, canteen_id: UUID) -> str:
    cache_ns = f"{NS_QUEUE}:{canteen_id}"
    cache_key = f"qwm:{canteen_id}"
    hit, cached = cache_manager.get_json(cache_ns, cache_key, l1_ttl=1.5)
    if hit and isinstance(cached, str):
        return cached
    since_completed = datetime.now(timezone.utc) - timedelta(hours=24)
    row = db.execute(
        select(
            func.count(Order.id),
            func.max(Order.updated_at),
            func.max(Order.completed_at),
            func.coalesce(func.sum(case((Order.status == "PLACED", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == "ACCEPTED", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == "PREPARING", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == "READY", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.is_priority.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(Order.delayed_minutes), 0),
        ).where(
            Order.canteen_id == canteen_id,
            or_(
                Order.status.in_(("PLACED", "ACCEPTED", "PREPARING", "READY")),
                and_(Order.status == "COMPLETED", Order.completed_at >= since_completed),
            ),
        )
    ).one()
    raw = "|".join(
        [
            str(canteen_id),
            str(row[0] or 0),
            row[1].isoformat() if row[1] else "",
            row[2].isoformat() if row[2] else "",
            *(str(row[idx] or 0) for idx in range(3, 9)),
        ]
    )
    wm = sha256_hex(raw)[:16]
    cache_manager.set_json(cache_ns, cache_key, wm, ttl_seconds=3, l1_ttl=1.5)
    return wm


def fetch_queue_snapshot(db: Session, canteen_id: UUID) -> tuple[str, dict[str, Any]]:
    version = compute_queue_version(db, canteen_id)
    dash = queue_service.get_live_queue_dashboard(db, canteen_id)
    dash["version"] = version
    return version, dash


def compute_user_notifications_version(
    db: Session,
    *,
    user_id: UUID,
    roles: set[str],
    assigned_canteen_id: Optional[UUID] = None,
) -> str:
    return notification_service.compute_notifications_watermark(
        db, user_id, roles, assigned_canteen_id=assigned_canteen_id
    )


def fetch_user_notifications_snapshot(
    db: Session,
    *,
    user_id: UUID,
    roles: set[str],
    assigned_canteen_id: Optional[UUID] = None,
) -> tuple[str, dict[str, Any]]:
    rows = notification_service.list_my_notifications(
        db, user_id, roles, assigned_canteen_id=assigned_canteen_id, limit=100
    )
    serialized = [notification_service.serialize_notification_for_user(n, user_id) for n in rows]
    unread_cnt = sum(1 for r in serialized if not r["is_read"])
    latest_created = max((r["created_at"] or "" for r in serialized), default="")
    latest_updated = max((n.updated_at.isoformat() for n in rows if n.updated_at), default="")
    version = sha256_hex(f"{user_id}|{len(serialized)}|{unread_cnt}|{latest_created}|{latest_updated}")[:16]
    return version, {
        "version": version,
        "unread_count": unread_cnt,
        "notifications": serialized,
    }


def fetch_staff_orders_snapshot(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    payment_status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
) -> dict[str, Any]:
    stmt = (
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    if canteen_id is not None:
        stmt = stmt.where(Order.canteen_id == canteen_id)
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    if payment_status:
        stmt = stmt.where(Order.payment_status == payment_status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.outerjoin(PickupToken, PickupToken.order_id == Order.id).where(
            or_(
                Order.order_number.ilike(like),
                Order.guest_name.ilike(like),
                Order.guest_phone.ilike(like),
                PickupToken.token_code.ilike(like),
            )
        )
    orders = db.scalars(stmt).all()
    serialized = order_service.serialize_orders_batch(db, list(orders))
    board = pickup_service.get_digital_token_board(db, canteen_id)
    version = compute_staff_orders_version(
        db,
        canteen_id=canteen_id,
        status_filter=status_filter,
        payment_status=payment_status,
        q=q,
    )
    combined_version = sha256_hex(f"{version}|{board.version or ''}")[:16]
    return {
        "orders": [o.model_dump(mode="json") for o in serialized],
        "board": board.model_dump(mode="json"),
        "version": combined_version,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
