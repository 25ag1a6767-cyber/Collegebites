import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.websockets import ws_manager

setup_logging()


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
    def health(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return {
            "status": "ok",
            "service": settings.APP_NAME,
            "environment": settings.ENVIRONMENT,
            "server_time": datetime.now(timezone.utc).isoformat(),
        }

    return app


app = create_app()
