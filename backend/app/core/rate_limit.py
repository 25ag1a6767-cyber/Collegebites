from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Shared SlowAPI limiter instance imported by both FastAPI app lifespan and auth/sensitive route handlers
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    enabled=settings.RATE_LIMIT_ENABLED,
)
