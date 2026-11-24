from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import _find_route_handler, _should_exempt
from slowapi.util import get_remote_address
from starlette.types import ASGIApp, Receive, Scope, Send
import anyio
import logging

from app.core.config import settings
from app.core.security import decode_token

logger = logging.getLogger("collegebites.rate_limit")


def campus_rate_limit_key(request: Request) -> str:
    """
    Campus-NAT-aware rate-limit bucket key:
    - Authenticated students/staff get per-user buckets (`user:<sub_id>`) so shared
      college Wi-Fi NAT gateways do not throttle unrelated students.
    - Guest checkout/browse sessions get per-guest-session buckets (`guest:<sid>`).
    - Anonymous/unauthenticated callers fall back to forwarded client IP.
    """
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header[7:].strip()
        if raw_token:
            try:
                payload = decode_token(raw_token)
                sub = payload.get("sub")
                if sub and payload.get("type") == "access":
                    return f"user:{sub}"
            except Exception:
                pass

    guest_sid = (request.headers.get("x-guest-session-id") or "").strip()
    if guest_sid and len(guest_sid) >= 6:
        return f"guest:{guest_sid[:64]}"

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first_ip = forwarded.split(",")[0].strip()
        if first_ip:
            return f"ip:{first_ip}"
    return f"ip:{get_remote_address(request)}"


def _resolve_storage_uri() -> str:
    url = (settings.REDIS_URL or "").strip()
    if url.startswith(("redis://", "rediss://")):
        return url
    return "memory://"


def _resolve_storage_options() -> dict:
    uri = _resolve_storage_uri()
    if uri.startswith(("redis://", "rediss://")):
        return {"socket_connect_timeout": 0.4, "socket_timeout": 0.4, "max_connections": 64}
    return {}


# Shared SlowAPI limiter instance imported by FastAPI app lifespan and route handlers
limiter = Limiter(
    key_func=campus_rate_limit_key,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    enabled=settings.RATE_LIMIT_ENABLED,
    storage_uri=_resolve_storage_uri(),
    storage_options=_resolve_storage_options(),
    in_memory_fallback_enabled=True,
    in_memory_fallback=[settings.RATE_LIMIT_DEFAULT],
    swallow_errors=True,
)

# Dedicated in-memory fallback limiter used instantaneously while Redis circuit breaker is open
_fallback_limiter = Limiter(
    key_func=campus_rate_limit_key,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    enabled=settings.RATE_LIMIT_ENABLED,
    storage_uri="memory://",
    swallow_errors=True,
)


class PureASGIRateLimitMiddleware:
    """
    Pure ASGI SlowAPI rate-limiting middleware (replaces Starlette BaseHTTPMiddleware-based
    SlowAPIMiddleware). Offloads Redis storage checks off the AsyncIO event loop, honors the
    Redis circuit breaker for <1ms outage failover, and eliminates BaseHTTPMiddleware overhead.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        fastapi_app = scope.get("app")
        app_limiter: Limiter | None = getattr(getattr(fastapi_app, "state", None), "limiter", None)
        if not app_limiter or not app_limiter.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if path in ("/health", "/health/ready"):
            await self.app(scope, receive, send)
            return

        handler = _find_route_handler(fastapi_app.routes, scope)
        if _should_exempt(app_limiter, handler):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        from app.core.cache import cache_manager

        active_limiter = _fallback_limiter if cache_manager._redis_circuit_open() else app_limiter

        def _check() -> RateLimitExceeded | None:
            try:
                active_limiter._check_request_limit(request, handler, True)
                return None
            except RateLimitExceeded as exc:
                return exc
            except Exception as exc:
                if active_limiter is app_limiter:
                    cache_manager._trip_redis_circuit()
                    try:
                        _fallback_limiter._check_request_limit(request, handler, True)
                        return None
                    except RateLimitExceeded as exc2:
                        return exc2
                    except Exception:
                        return None
                if app_limiter._swallow_errors:
                    logger.debug("Rate limit storage error swallowed: %s", exc)
                    return None
                raise

        exceeded = await anyio.to_thread.run_sync(_check)
        if exceeded is not None:
            resp = JSONResponse(
                status_code=429,
                content={"error": f"Rate limit exceeded: {exceeded.detail}"},
            )
            await resp(scope, receive, send)
            return

        await self.app(scope, receive, send)
