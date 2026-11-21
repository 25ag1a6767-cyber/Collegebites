from functools import lru_cache
from typing import Optional
import fakeredis
import redis

from app.core.config import settings


class RedisManager:
    """Provides a Redis client backed by real Redis or FakeRedis in memory:// mode."""

    def __init__(self, url: str):
        self.url = url
        self._client: Optional[redis.Redis] = None

    def get_client(self) -> redis.Redis:
        if self._client is not None:
            return self._client
        if not self.url or self.url.startswith("memory://"):
            self._client = fakeredis.FakeRedis(decode_responses=True)
        else:
            self._client = redis.from_url(self.url, decode_responses=True, socket_connect_timeout=2)
        return self._client

    def reset_for_tests(self) -> None:
        if self._client is not None:
            self._client.flushall()


@lru_cache
def get_redis_manager() -> RedisManager:
    return RedisManager(settings.REDIS_URL)


def get_redis() -> redis.Redis:
    return get_redis_manager().get_client()
