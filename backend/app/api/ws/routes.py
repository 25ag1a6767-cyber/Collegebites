from typing import Optional
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

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
    load_user_roles_and_permissions,
)
from app.core.security import decode_token, sha256_hex
from app.models.auth import SessionRecord, User
from app.models.order import Order
from app.websockets import ws_manager

router = APIRouter(tags=["Real-time WebSockets"])

STAFF_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
    ROLE_PICKUP_STAFF,
)


def _authenticate_jwt_from_ws(websocket: WebSocket) -> Optional[AuthenticatedPrincipal]:
    token = (websocket.query_params.get("token") or "").strip()
    if not token:
        return None
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        user_id = UUID(payload["sub"])
        session_id = UUID(payload["sid"])
    except Exception:
        return None

    provider = websocket.app.dependency_overrides.get(get_db, get_db)
    gen = provider()
    db = next(gen)
    try:
        sess = db.get(SessionRecord, session_id)
        if not sess or sess.revoked_at is not None:
            return None
        user = db.get(User, user_id)
        if not user or not user.is_active:
            return None
        roles, perms, assigned_canteen_id = load_user_roles_and_permissions(db, user.id)
        return AuthenticatedPrincipal(
            user=user,
            session_id=session_id,
            roles=roles,
            permissions=perms,
            assigned_canteen_id=assigned_canteen_id,
        )
    finally:
        gen.close()


def _authorize_order_ws(websocket: WebSocket, order_id: str) -> bool:
    try:
        oid = UUID(order_id)
    except ValueError:
        return False

    guest_token = (websocket.query_params.get("guest_token") or "").strip()
    principal = _authenticate_jwt_from_ws(websocket)

    provider = websocket.app.dependency_overrides.get(get_db, get_db)
    gen = provider()
    db = next(gen)
    try:
        order = db.get(Order, oid)
        if not order:
            return False
        if guest_token and order.guest_access_token_hash and sha256_hex(guest_token) == order.guest_access_token_hash:
            return True
        if not principal:
            return False
        if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
            return True
        if order.customer_id and order.customer_id == principal.user.id:
            return True
        if principal.has_role(*STAFF_ROLES) and principal.assigned_canteen_id == order.canteen_id:
            return True
        return False
    finally:
        gen.close()


@router.websocket("/ws/orders/{order_id}")
async def ws_order(websocket: WebSocket, order_id: str):
    if not _authorize_order_ws(websocket, order_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    room = f"order:{order_id}"
    await ws_manager.connect(room, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(room, websocket)


@router.websocket("/ws/kitchen/{canteen_id}")
async def ws_kitchen(websocket: WebSocket, canteen_id: str):
    try:
        cid = UUID(canteen_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    principal = _authenticate_jwt_from_ws(websocket)
    if not principal or not principal.has_role(*STAFF_ROLES):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) and principal.assigned_canteen_id != cid:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    room = f"kitchen:{canteen_id}"
    await ws_manager.connect(room, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(room, websocket)


@router.websocket("/ws/board/{canteen_id}")
async def ws_board(websocket: WebSocket, canteen_id: str):
    room = f"board:{canteen_id}"
    await ws_manager.connect(room, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(room, websocket)


@router.websocket("/ws/notifications/{user_id}")
async def ws_notifications(websocket: WebSocket, user_id: str):
    try:
        uid = UUID(user_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    principal = _authenticate_jwt_from_ws(websocket)
    if not principal or (
        principal.user.id != uid and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    room = f"user:{user_id}"
    await ws_manager.connect(room, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(room, websocket)
