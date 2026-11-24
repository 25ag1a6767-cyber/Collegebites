from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Pure ASGI middleware attaching security headers and unified correlation ID with zero body buffering."""

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

        # Reuse the canonical request_id established by RequestObservabilityMiddleware when present
        state_rid = (scope.get("state") or {}).get("request_id")
        request_id: bytes | None = state_rid.encode("ascii") if isinstance(state_rid, str) and state_rid else None
        if request_id is None:
            for key, value in scope.get("headers") or ():
                if key.lower() == b"x-request-id" and value:
                    request_id = value
                    break
        if request_id is None:
            request_id = uuid4().hex[:16].encode("ascii")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                if not any(k.lower() == b"x-request-id" for k, _ in headers):
                    headers.append((b"x-request-id", request_id))
                headers.extend(self._STATIC_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
