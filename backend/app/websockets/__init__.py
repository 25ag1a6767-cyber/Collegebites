from collections import defaultdict
from typing import Any
from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket subscriptions by topic (order:{id}, kitchen:{canteen_id}, board:{canteen_id})."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, room: str, websocket: WebSocket) -> None:
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


ws_manager = ConnectionManager()


def emit_order_event_sync(canteen_id: str, order_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Safely schedule WebSocket broadcasts from synchronous FastAPI/service contexts when an event loop exists."""
    import asyncio

    message = {"event": event_type, "order_id": order_id, "canteen_id": canteen_id, "data": payload}
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(ws_manager.broadcast(f"order:{order_id}", message))
        loop.create_task(ws_manager.broadcast(f"kitchen:{canteen_id}", message))
        loop.create_task(ws_manager.broadcast(f"board:{canteen_id}", message))
    except RuntimeError:
        # No active async loop (e.g., synchronous pytest TestClient or CLI); skip WS push cleanly
        pass
