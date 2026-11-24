import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import anyio
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.router import api_router
from app.core.cache import cache_manager
from app.core.config import settings
from app.core.database import SessionLocal, dispose_engine, get_pool_stats
from app.core.logging import request_id_ctx, setup_logging
from app.core.rate_limit import PureASGIRateLimitMiddleware, limiter
from app.core.redis_client import get_redis
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.websockets import ws_manager

setup_logging()
perf_logger = logging.getLogger("collegebites.perf")


class RequestObservabilityMiddleware:
    """Pure ASGI correlation ID, timing, slow-request logging, and timeout guard (zero BaseHTTPMiddleware overhead)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        path = scope.get("path") or ""
        method = scope.get("method") or "GET"
        is_stream = "/realtime/" in path or path.endswith("/stream")
        incoming_rid = None
        for k, v in scope.get("headers") or ():
            if k.lower() == b"x-request-id":
                raw = v.decode("ascii", errors="ignore").strip()
                if raw and len(raw) <= 64:
                    incoming_rid = raw
                break
        request_id = incoming_rid or uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = request_id
        rid_token = request_id_ctx.set(request_id)
        response_started = False
        status_code = 200

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message.get("status", 200))
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                headers = [
                    (k, v)
                    for k, v in (message.get("headers") or [])
                    if k.lower() not in (b"x-request-id", b"x-response-time-ms")
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                headers.append((b"x-response-time-ms", f"{elapsed_ms:.2f}".encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            if is_stream or settings.REQUEST_TIMEOUT_SECONDS <= 0:
                await self.app(scope, receive, send_wrapper)
            else:
                await asyncio.wait_for(
                    self.app(scope, receive, send_wrapper),
                    timeout=settings.REQUEST_TIMEOUT_SECONDS,
                )
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            perf_logger.error("Request timed out [req=%s] after %.1fms: %s %s", request_id, elapsed_ms, method, path)
            if not response_started:
                resp = JSONResponse(
                    status_code=504,
                    content={
                        "detail": "Request timed out while processing. Please retry shortly.",
                        "request_id": request_id,
                    },
                    headers={"X-Request-ID": request_id},
                )
                await resp(scope, receive, send)
            return
        finally:
            request_id_ctx.reset(rid_token)

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if elapsed_ms >= 500.0 and not is_stream:
            perf_logger.warning(
                "Slow request [req=%s] %.1fms %s %s -> %s",
                request_id,
                elapsed_ms,
                method,
                path,
                status_code,
            )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ws_manager.set_loop(asyncio.get_running_loop())
    try:
        limiter_tok = anyio.to_thread.current_default_thread_limiter()
        limiter_tok.total_tokens = max(40, int(settings.ANYIO_THREADPOOL_TOKENS))
    except Exception:
        pass
    yield
    dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CollegeBites API",
        version="1.0.0",
        description="Complete Smart College Canteen Management, Food Ordering, Payment, QR Token & Operations Platform",
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(PureASGIRateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestObservabilityMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.API_PREFIX)

    @app.get("/health", tags=["Health"])
    def health(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return {
            "status": "ok",
            "service": settings.APP_NAME,
            "environment": settings.ENVIRONMENT,
            "server_time": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/health/ready", tags=["Health"])
    def health_ready(response: Response):
        response.headers["Cache-Control"] = "no-store"
        db_ok = True
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        redis_ok = True
        try:
            get_redis().ping()
        except Exception:
            redis_ok = False
        status_code = 200 if db_ok else 503
        payload = {
            "status": "ready" if db_ok else "degraded",
            "database": "connected" if db_ok else "error",
            "redis": "connected" if redis_ok else "fallback",
            "db_pool": get_pool_stats(),
            "cache": cache_manager.get_stats(),
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
        if status_code != 200:
            return JSONResponse(status_code=status_code, content=payload)
        return payload

    return app


app = create_app()
