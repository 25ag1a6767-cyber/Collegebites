import asyncio
from collections import defaultdict
from typing import Any, Optional
from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket subscriptions by topic (order:{id}, kitchen:{canteen_id}, board:{canteen_id}, user:{id})."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, room: str, websocket: WebSocket) -> None:
        self._loop = asyncio.get_running_loop()
        await websocket.accept()
        self._rooms[room].add(websocket)

    def disconnect(self, room: str, websocket: WebSocket) -> None:
        if room in self._rooms:
            self._rooms[room].discard(websocket)
            if not self._rooms[room]:
                del self._rooms[room]

    async def broadcast(self, room: str, payload: dict[str, Any]) -> None:
        if room not in self._rooms:
            return
        dead: list[WebSocket] = []
        for ws in list(self._rooms[room]):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(room, ws)

    def schedule_broadcast(self, room: str, payload: dict[str, Any]) -> None:
        if room not in self._rooms:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(room, payload))
            return
        except RuntimeError:
            pass
        if self._loop and not self._loop.is_closed() and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(room, payload), self._loop)


ws_manager = ConnectionManager()


def emit_order_event_sync(canteen_id: str, order_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Safely schedule WebSocket broadcasts from sync or async FastAPI service contexts."""
    message = {"event": event_type, "order_id": order_id, "canteen_id": canteen_id, "data": payload}
    ws_manager.schedule_broadcast(f"order:{order_id}", message)
    ws_manager.schedule_broadcast(f"kitchen:{canteen_id}", message)
    ws_manager.schedule_broadcast(f"board:{canteen_id}", message)


def emit_user_notification_sync(user_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Push real-time notification events to a signed-in user's WebSocket room."""
    message = {"event": event_type, "user_id": user_id, "data": payload}
    ws_manager.schedule_broadcast(f"user:{user_id}", message)
