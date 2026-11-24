import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Pure ASGI middleware attaching security headers and correlation ID with zero body buffering."""

    _STATIC_HEADERS: tuple[tuple[bytes, bytes], ...] = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"SAMEORIGIN"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"camera=(self), microphone=(), geolocation=()"),
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id: bytes | None = None
        for key, value in scope.get("headers") or ():
            if key == b"x-request-id" and value:
                request_id = value
                break
        if request_id is None:
            request_id = str(uuid4()).encode("ascii")

        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                elapsed_ms = f"{round((time.perf_counter() - started) * 1000, 2)}".encode("ascii")
                headers.append((b"x-request-id", request_id))
                headers.append((b"x-process-time-ms", elapsed_ms))
                headers.extend(self._STATIC_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
