from functools import lru_cache
import logging
from typing import Callable, Optional, TypeVar

import fakeredis
import redis

from app.core.config import settings

logger = logging.getLogger("collegebites.redis")
_T = TypeVar("_T")


class RedisManager:
    """Provides a Redis client backed by real Redis or FakeRedis in memory:// / dev-fallback mode."""

    def __init__(self, url: str):
        self.url = url
        self._client: Optional[redis.Redis] = None

    def get_client(self) -> redis.Redis:
        if self._client is not None:
            return self._client
        if not self.url or self.url.startswith("memory://"):
            self._client = fakeredis.FakeRedis(decode_responses=True)
        else:
            client = redis.from_url(
                self.url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            if not settings.is_production:
                try:
                    client.ping()
                except redis.exceptions.RedisError:
                    logger.warning("Redis unavailable at %s in development; falling back to FakeRedis", self.url)
                    client = fakeredis.FakeRedis(decode_responses=True)
            self._client = client
        return self._client

    def reset_for_tests(self) -> None:
        if self._client is not None:
            self._client.flushall()


@lru_cache
def get_redis_manager() -> RedisManager:
    return RedisManager(settings.REDIS_URL)


def get_redis() -> redis.Redis:
    return get_redis_manager().get_client()


def safe_redis(op: Callable[[redis.Redis], _T], default: Optional[_T] = None) -> Optional[_T]:
    """Execute a non-authoritative Redis cache/counter op without failing requests if Redis is offline."""
    try:
        return op(get_redis())
    except redis.exceptions.RedisError as exc:
        logger.warning("Redis cache operation skipped: %s", exc)
        return default
