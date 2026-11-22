from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import UUID

from fastapi import Request
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.security import sha256_hex
from app.core.time_utils import today_college
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.payment import OrderQRCode, PickupToken
from app.schemas.operations import DigitalBoardResponse
from app.schemas.order import OrderOut
from app.services import order_service, pickup_service


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
    """Fast single-row aggregate fingerprint for public token board state."""
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
    return sha256_hex(raw)[:16]


def fetch_board_snapshot(db: Session, canteen_id: Optional[UUID] = None) -> DigitalBoardResponse:
    return pickup_service.get_digital_token_board(db, canteen_id)


def compute_order_version(db: Session, order_id: UUID) -> Optional[str]:
    row = db.execute(
        select(
            Order.id,
            Order.status,
            Order.payment_status,
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
    raw = "|".join(
        [
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3] or 0),
            row[4].isoformat() if row[4] else "",
            row[5].isoformat() if row[5] else "",
            row[6].isoformat() if row[6] else "",
            str(token_code or ""),
            qr_revoked.isoformat() if qr_revoked else "",
            str(hist_count),
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
    )
    if canteen_id is not None:
        stmt = stmt.where(Order.canteen_id == canteen_id)
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    if payment_status:
        stmt = stmt.where(Order.payment_status == payment_status)
    row = db.execute(stmt).one()
    raw = "|".join(
        [
            str(canteen_id or "all"),
            str(status_filter or ""),
            str(payment_status or ""),
            (q or "").strip().lower(),
            str(row[0] or 0),
            row[1].isoformat() if row[1] else "",
            row[2].isoformat() if row[2] else "",
            *(str(row[idx] or 0) for idx in range(3, 11)),
        ]
    )
    return sha256_hex(raw)[:16]


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
