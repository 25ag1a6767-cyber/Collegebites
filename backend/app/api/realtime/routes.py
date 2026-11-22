from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_optional_principal,
    require_roles,
)
from app.core.security import sha256_hex
from app.models.college import Canteen
from app.models.order import Order
from app.services import realtime_service
from app.websockets import ws_manager

router = APIRouter(prefix="/realtime", tags=["Real-time SSE Streams"])

STAFF_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
    ROLE_PICKUP_STAFF,
)

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _default_stream_window(max_seconds: Optional[float]) -> float:
    if max_seconds is not None:
        return max(0.5, min(float(max_seconds), 55.0))
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return 25.0
    return 45.0


def _format_sse(event: str, data: dict, event_id: Optional[str] = None, retry_ms: Optional[int] = None) -> str:
    lines: list[str] = []
    if retry_ms is not None:
        lines.append(f"retry: {retry_ms}")
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, default=str)}")
    return "\n".join(lines) + "\n\n"


def _authorize_order_for_stream(
    db: Session,
    order_id_or_number: str,
    principal: Optional[AuthenticatedPrincipal],
    guest_token: Optional[str],
) -> Order:
    stmt = None
    try:
        uid = UUID(order_id_or_number)
        stmt = select(Order).where(Order.id == uid)
    except ValueError:
        stmt = select(Order).where(Order.order_number == order_id_or_number)
    order = db.scalar(stmt)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if principal and principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return order
    if principal and order.customer_id and order.customer_id == principal.user.id:
        return order
    if principal and principal.has_role(*STAFF_ROLES):
        enforce_canteen_scope(principal, order.canteen_id)
        return order
    if guest_token and order.guest_access_token_hash and sha256_hex(guest_token.strip()) == order.guest_access_token_hash:
        return order
    if principal:
        raise HTTPException(status_code=403, detail="Not authorized to stream this order")
    raise HTTPException(status_code=401, detail="Authentication or valid guest token required")


@router.get("/board/stream")
async def stream_digital_board(
    request: Request,
    canteen_id: Optional[UUID] = Query(default=None),
    last_version: Optional[str] = Query(default=None),
    once: bool = Query(default=False),
    max_seconds: Optional[float] = Query(default=None, ge=0.2, le=55.0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream for real-time public Token Board synchronization across all instances."""
    if canteen_id is not None and not db.get(Canteen, canteen_id):
        raise HTTPException(status_code=404, detail="Canteen not found")

    topic = f"board:{canteen_id}" if canteen_id is not None else "board:all"
    window_secs = _default_stream_window(max_seconds)
    seen_version = (last_version or last_event_id or "").strip() or None

    async def event_generator():
        nonlocal seen_version
        queue = ws_manager.subscribe(topic)
        started_at = time.monotonic()
        last_ping = started_at
        last_watermark: Optional[str] = None
        first_cycle = True

        try:
            yield "retry: 1500\n\n"
            while True:
                if await request.is_disconnected():
                    break

                woken_by_event = False
                if not first_cycle:
                    remaining = window_secs - (time.monotonic() - started_at)
                    if remaining <= 0:
                        yield _format_sse("stream.reconnect", {"reason": "cycle", "version": seen_version})
                        break
                    wait_for = min(0.9, remaining)
                    try:
                        await asyncio.wait_for(queue.get(), timeout=wait_for)
                        while not queue.empty():
                            try:
                                queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        woken_by_event = True
                    except asyncio.TimeoutError:
                        pass

                gen, sess = realtime_service.resolve_db_session(request)
                try:
                    watermark = realtime_service.compute_board_watermark(sess, canteen_id)
                    if first_cycle or woken_by_event or watermark != last_watermark:
                        last_watermark = watermark
                        snapshot = realtime_service.fetch_board_snapshot(sess, canteen_id)
                        snap_version = snapshot.version or watermark
                        if first_cycle or snap_version != seen_version:
                            seen_version = snap_version
                            yield _format_sse(
                                "board.snapshot",
                                snapshot.model_dump(mode="json"),
                                event_id=snap_version,
                            )
                finally:
                    realtime_service.close_db_session(gen)

                first_cycle = False
                if once:
                    break

                now = time.monotonic()
                if now - last_ping >= 12.0:
                    last_ping = now
                    yield ": keepalive\n\n"
                if now - started_at >= window_secs:
                    yield _format_sse("stream.reconnect", {"reason": "cycle", "version": seen_version})
                    break
        finally:
            ws_manager.unsubscribe(topic, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/orders/{order_id_or_number}/stream")
async def stream_order_updates(
    order_id_or_number: str,
    request: Request,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    last_version: Optional[str] = Query(default=None),
    once: bool = Query(default=False),
    max_seconds: Optional[float] = Query(default=None, ge=0.2, le=55.0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream for real-time customer & staff single-order status tracking."""
    order = _authorize_order_for_stream(db, order_id_or_number, principal, guest_token or x_guest_token)
    order_id = order.id
    topic = f"order:{order_id}"
    window_secs = _default_stream_window(max_seconds)
    seen_version = (last_version or last_event_id or "").strip() or None

    async def event_generator():
        nonlocal seen_version
        queue = ws_manager.subscribe(topic)
        started_at = time.monotonic()
        last_ping = started_at
        last_computed: Optional[str] = None
        first_cycle = True

        try:
            yield "retry: 1500\n\n"
            while True:
                if await request.is_disconnected():
                    break

                woken_by_event = False
                if not first_cycle:
                    remaining = window_secs - (time.monotonic() - started_at)
                    if remaining <= 0:
                        yield _format_sse("stream.reconnect", {"reason": "cycle", "version": seen_version})
                        break
                    try:
                        await asyncio.wait_for(queue.get(), timeout=min(0.9, remaining))
                        while not queue.empty():
                            try:
                                queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        woken_by_event = True
                    except asyncio.TimeoutError:
                        pass

                gen, sess = realtime_service.resolve_db_session(request)
                try:
                    ver = realtime_service.compute_order_version(sess, order_id)
                    if ver and (first_cycle or woken_by_event or ver != last_computed):
                        last_computed = ver
                        if first_cycle or ver != seen_version:
                            snap_ver, order_out = realtime_service.fetch_order_snapshot(sess, order_id)
                            if snap_ver and order_out:
                                seen_version = snap_ver
                                yield _format_sse(
                                    "order.snapshot",
                                    {"version": snap_ver, "order": order_out.model_dump(mode="json")},
                                    event_id=snap_ver,
                                )
                finally:
                    realtime_service.close_db_session(gen)

                first_cycle = False
                if once:
                    break

                now = time.monotonic()
                if now - last_ping >= 12.0:
                    last_ping = now
                    yield ": keepalive\n\n"
                if now - started_at >= window_secs:
                    yield _format_sse("stream.reconnect", {"reason": "cycle", "version": seen_version})
                    break
        finally:
            ws_manager.unsubscribe(topic, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/staff/orders/stream")
async def stream_staff_orders(
    request: Request,
    canteen_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    payment_status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    last_version: Optional[str] = Query(default=None),
    once: bool = Query(default=False),
    max_seconds: Optional[float] = Query(default=None, ge=0.2, le=55.0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_ROLES)),
):
    """Server-Sent Events stream for Canteen Manager, Kitchen Display, Pickup, and Admin consoles."""
    scoped_canteen = canteen_id
    if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        enforce_canteen_scope(principal, canteen_id or principal.assigned_canteen_id)
        scoped_canteen = canteen_id or principal.assigned_canteen_id

    topic = f"kitchen:{scoped_canteen}" if scoped_canteen is not None else "staff:orders"
    window_secs = _default_stream_window(max_seconds)
    seen_version = (last_version or last_event_id or "").strip() or None

    async def event_generator():
        nonlocal seen_version
        queue = ws_manager.subscribe(topic)
        started_at = time.monotonic()
        last_ping = started_at
        last_watermark: Optional[str] = None
        first_cycle = True

        try:
            yield "retry: 1500\n\n"
            while True:
                if await request.is_disconnected():
                    break

                woken_by_event = False
                if not first_cycle:
                    remaining = window_secs - (time.monotonic() - started_at)
                    if remaining <= 0:
                        yield _format_sse("stream.reconnect", {"reason": "cycle", "version": seen_version})
                        break
                    try:
                        await asyncio.wait_for(queue.get(), timeout=min(0.9, remaining))
                        while not queue.empty():
                            try:
                                queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        woken_by_event = True
                    except asyncio.TimeoutError:
                        pass

                gen, sess = realtime_service.resolve_db_session(request)
                try:
                    ver = realtime_service.compute_staff_orders_version(
                        sess,
                        canteen_id=scoped_canteen,
                        status_filter=status_filter,
                        payment_status=payment_status,
                        q=q,
                    )
                    board_wm = realtime_service.compute_board_watermark(sess, scoped_canteen)
                    combined_wm = sha256_hex(f"{ver}|{board_wm}")[:16]
                    if first_cycle or woken_by_event or combined_wm != last_watermark:
                        last_watermark = combined_wm
                        if first_cycle or combined_wm != seen_version:
                            snap = realtime_service.fetch_staff_orders_snapshot(
                                sess,
                                canteen_id=scoped_canteen,
                                status_filter=status_filter,
                                payment_status=payment_status,
                                q=q,
                                limit=limit,
                            )
                            seen_version = combined_wm
                            snap["version"] = combined_wm
                            yield _format_sse("orders.snapshot", snap, event_id=combined_wm)
                finally:
                    realtime_service.close_db_session(gen)

                first_cycle = False
                if once:
                    break

                now = time.monotonic()
                if now - last_ping >= 12.0:
                    last_ping = now
                    yield ": keepalive\n\n"
                if now - started_at >= window_secs:
                    yield _format_sse("stream.reconnect", {"reason": "cycle", "version": seen_version})
                    break
        finally:
            ws_manager.unsubscribe(topic, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)
