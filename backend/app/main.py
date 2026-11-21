import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.websockets import ws_manager

setup_logging()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    enabled=settings.RATE_LIMIT_ENABLED,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ws_manager.set_loop(asyncio.get_running_loop())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="CollegeBites API",
        version="1.0.0",
        description="Complete Smart College Canteen Management, Food Ordering, Payment, QR Token & Operations Platform",
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.API_PREFIX)

    @app.get("/health", tags=["Health"])
    def health():
        return {"status": "ok", "service": settings.APP_NAME, "environment": settings.ENVIRONMENT}

    return app


app = create_app()
