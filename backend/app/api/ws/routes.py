from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websockets import ws_manager

router = APIRouter(tags=["Real-time WebSockets"])


@router.websocket("/ws/orders/{order_id}")
async def ws_order(websocket: WebSocket, order_id: str):
    room = f"order:{order_id}"
    await ws_manager.connect(room, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(room, websocket)


@router.websocket("/ws/kitchen/{canteen_id}")
async def ws_kitchen(websocket: WebSocket, canteen_id: str):
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
    room = f"user:{user_id}"
    await ws_manager.connect(room, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(room, websocket)
