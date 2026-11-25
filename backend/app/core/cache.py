from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional, TypeVar
from uuid import UUID

import redis

try:
    import orjson as _orjson
except Exception:  # pragma: no cover
    _orjson = None

from app.core.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger("collegebites.cache")
_T = TypeVar("_T")

# Cache namespace constants
NS_COLLEGE = "college"
NS_CANTEENS = "canteens"
NS_MENU = "menu"
NS_BOARD = "board"
NS_QUEUE = "queue"
NS_REPORTS = "reports"
NS_AUTH = "auth"
NS_CAMPUS_INTEL = "campus_intel"
NS_COMMAND_CENTER = "command_center"
NS_ANNOUNCEMENTS = "announcements"


class _BoundedL1Cache:
    """Thread-safe bounded LRU+TTL in-process L1 micro-cache."""

    def __init__(self, max_entries: int = 1024) -> None:
        self._max_entries = max(64, max_entries)
        self._lock = threading.RLock()
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> tuple[bool, Any]:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False, None
            expires_at, val = entry
            if expires_at <= now:
                self._store.pop(key, None)
                return False, None
            self._store.move_to_end(key)
            return True, val

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        expires_at = time.monotonic() + ttl_seconds
        with self._lock:
            self._store[key] = (expires_at, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def delete_prefix(self, prefix: str) -> None:
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                self._store.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)


class CacheManager:
    """
    Production two-tier cache (bounded L1 in-process + L2 Redis JSON) with atomic
    namespace version counters for O(1) multi-worker invalidation and graceful fallback.

    Rules enforced:
    - Never caches payment verification or authoritative financial transaction state.
    - Never caches private user-specific data under public keys.
    - Degrades silently to DB queries if Redis is unreachable.
    """

    def __init__(self) -> None:
        self._l1 = _BoundedL1Cache(max_entries=settings.CACHE_L1_MAX_ENTRIES)
        self._ver_l1 = _BoundedL1Cache(max_entries=4096)
        self._lock = threading.Lock()
        self._redis_circuit_open_until: float = 0.0
        self._stats = {
            "l1_hits": 0,
            "l2_hits": 0,
            "misses": 0,
            "sets": 0,
            "invalidations": 0,
            "redis_errors": 0,
        }

    def _redis_circuit_open(self) -> bool:
        return time.monotonic() < self._redis_circuit_open_until

    def _trip_redis_circuit(self) -> None:
        self._redis_circuit_open_until = time.monotonic() + 8.0
        try:
            client = get_redis()
            pool = getattr(client, "connection_pool", None)
            if pool is not None:
                pool.disconnect()
        except Exception:
            pass

    def _close_redis_circuit(self) -> None:
        self._redis_circuit_open_until = 0.0

    def _inc(self, metric: str) -> None:
        with self._lock:
            self._stats[metric] += 1

    def _is_enabled(self) -> bool:
        return bool(settings.CACHE_ENABLED)

    def _use_external_redis(self) -> bool:
        url = (settings.REDIS_URL or "").strip()
        return bool(url and not url.startswith("memory://"))

    def _get_namespace_version(self, namespace: str) -> str:
        ver_key = f"cb:ver:{namespace}"
        # Default missing version key to "0" so the very first Redis INCR (which yields 1)
        # ALWAYS transitions to a strictly distinct key ("v0" -> "v1" -> "v2"...).
        if self._use_external_redis():
            ok, cached_ver = self._ver_l1.get(ver_key)
            if ok:
                return str(cached_ver)
            if self._redis_circuit_open():
                return "0"
            try:
                raw = get_redis().get(ver_key)
                self._close_redis_circuit()
                ver = str(raw) if raw is not None else "0"
                self._ver_l1.set(ver_key, ver, ttl_seconds=0.5)
                return ver
            except redis.exceptions.RedisError:
                self._inc("redis_errors")
                self._trip_redis_circuit()
                return "0"
        else:
            ok, cached_ver = self._ver_l1.get(ver_key)
            if ok:
                return str(cached_ver)
            try:
                raw = get_redis().get(ver_key)
                ver = str(raw) if raw is not None else "0"
                self._ver_l1.set(ver_key, ver, ttl_seconds=60.0)
                return ver
            except redis.exceptions.RedisError:
                return "0"

    def _full_key(self, namespace: str, key: str) -> str:
        ver = self._get_namespace_version(namespace)
        return f"cb:c:{namespace}:v{ver}:{key}"

    def get_json(self, namespace: str, key: str, *, l1_ttl: Optional[float] = None) -> tuple[bool, Any]:
        if not self._is_enabled():
            return False, None
        full_key = self._full_key(namespace, key)
        hit, val = self._l1.get(full_key)
        if hit:
            self._inc("l1_hits")
            return True, val

        if not self._redis_circuit_open():
            try:
                raw = get_redis().get(full_key)
                self._close_redis_circuit()
                if raw is not None:
                    parsed = _orjson.loads(raw) if _orjson is not None else json.loads(raw)
                    eff_l1 = min(
                        float(l1_ttl if l1_ttl is not None else settings.CACHE_L1_MAX_TTL_SECONDS),
                        float(settings.CACHE_L1_MAX_TTL_SECONDS),
                    )
                    if eff_l1 > 0:
                        self._l1.set(full_key, parsed, ttl_seconds=eff_l1)
                    self._inc("l2_hits")
                    return True, parsed
            except (redis.exceptions.RedisError, ValueError, TypeError) as exc:
                self._inc("redis_errors")
                if isinstance(exc, redis.exceptions.RedisError):
                    self._trip_redis_circuit()
                logger.debug("Redis cache get skipped for %s: %s", full_key, exc)

        self._inc("misses")
        return False, None

    def set_json(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        ttl_seconds: int = 30,
        l1_ttl: Optional[float] = None,
    ) -> None:
        if not self._is_enabled() or ttl_seconds <= 0:
            return
        full_key = self._full_key(namespace, key)
        eff_l1 = min(
            float(l1_ttl if l1_ttl is not None else min(ttl_seconds, settings.CACHE_L1_MAX_TTL_SECONDS)),
            float(ttl_seconds),
            float(settings.CACHE_L1_MAX_TTL_SECONDS),
        )
        if eff_l1 > 0:
            self._l1.set(full_key, value, ttl_seconds=eff_l1)
        if not self._redis_circuit_open():
            try:
                if _orjson is not None:
                    payload = _orjson.dumps(value, option=_orjson.OPT_NON_STR_KEYS, default=str).decode("utf-8")
                else:
                    payload = json.dumps(value, default=str, separators=(",", ":"))
                get_redis().setex(full_key, int(max(1, ttl_seconds)), payload)
                self._close_redis_circuit()
                self._inc("sets")
            except (redis.exceptions.RedisError, TypeError, ValueError) as exc:
                self._inc("redis_errors")
                if isinstance(exc, redis.exceptions.RedisError):
                    self._trip_redis_circuit()
                logger.debug("Redis cache set skipped for %s: %s", full_key, exc)

    def get_or_set_json(
        self,
        namespace: str,
        key: str,
        loader: Callable[[], Any],
        *,
        ttl_seconds: int = 30,
        l1_ttl: Optional[float] = None,
    ) -> Any:
        hit, val = self.get_json(namespace, key, l1_ttl=l1_ttl)
        if hit:
            return val
        fresh = loader()
        self.set_json(namespace, key, fresh, ttl_seconds=ttl_seconds, l1_ttl=l1_ttl)
        return fresh

    def delete_key(self, namespace: str, key: str) -> None:
        full_key = self._full_key(namespace, key)
        self._l1.delete(full_key)
        try:
            get_redis().delete(full_key)
        except redis.exceptions.RedisError:
            self._inc("redis_errors")

    def invalidate_namespace(self, namespace: str) -> None:
        """Atomically bump namespace version so all workers & filter variants invalidate in O(1)."""
        ver_key = f"cb:ver:{namespace}"
        self._l1.delete_prefix(f"cb:c:{namespace}:")
        self._ver_l1.delete(ver_key)
        self._inc("invalidations")
        if not self._redis_circuit_open():
            try:
                new_ver = get_redis().incr(ver_key)
                self._close_redis_circuit()
                self._ver_l1.set(ver_key, str(new_ver), ttl_seconds=0.5 if self._use_external_redis() else 60.0)
            except redis.exceptions.RedisError as exc:
                self._inc("redis_errors")
                self._trip_redis_circuit()
                logger.debug("Redis version bump skipped for %s: %s", namespace, exc)

    def reset_all(self) -> None:
        """Clear all L1 caches (used by test fixtures)."""
        self._l1.clear()
        self._ver_l1.clear()
        self._redis_circuit_open_until = 0.0

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            snap = dict(self._stats)
        total = snap["l1_hits"] + snap["l2_hits"] + snap["misses"]
        hit_rate = round(((snap["l1_hits"] + snap["l2_hits"]) / total) * 100.0, 2) if total > 0 else 0.0
        return {
            **snap,
            "enabled": self._is_enabled(),
            "external_redis": self._use_external_redis(),
            "l1_entries": self._l1.size(),
            "hit_rate_percent": hit_rate,
        }


cache_manager = CacheManager()


def _ns_scoped(base: str, scope_id: Optional[UUID | str] = None) -> str:
    return f"{base}:{scope_id}" if scope_id is not None else base


def invalidate_college_settings() -> None:
    cache_manager.invalidate_namespace(NS_COLLEGE)
    cache_manager.invalidate_namespace(NS_CANTEENS)


def invalidate_canteens(canteen_id: Optional[UUID | str] = None) -> None:
    cache_manager.invalidate_namespace(NS_CANTEENS)
    if canteen_id is not None:
        cache_manager.invalidate_namespace(_ns_scoped(NS_CANTEENS, canteen_id))


def invalidate_menu(canteen_id: Optional[UUID | str] = None) -> None:
    cache_manager.invalidate_namespace(NS_MENU)
    cache_manager.invalidate_namespace(NS_CAMPUS_INTEL)
    cache_manager.invalidate_namespace(NS_COMMAND_CENTER)
    if canteen_id is not None:
        cache_manager.invalidate_namespace(_ns_scoped(NS_MENU, canteen_id))
        cache_manager.invalidate_namespace(_ns_scoped(NS_CAMPUS_INTEL, canteen_id))
        cache_manager.invalidate_namespace(_ns_scoped(NS_COMMAND_CENTER, canteen_id))


def invalidate_board_and_queue(canteen_id: Optional[UUID | str] = None) -> None:
    cache_manager.invalidate_namespace(NS_BOARD)
    cache_manager.invalidate_namespace(NS_QUEUE)
    cache_manager.invalidate_namespace(NS_CANTEENS)
    cache_manager.invalidate_namespace(NS_CAMPUS_INTEL)
    cache_manager.invalidate_namespace(NS_COMMAND_CENTER)
    if canteen_id is not None:
        cache_manager.invalidate_namespace(_ns_scoped(NS_BOARD, canteen_id))
        cache_manager.invalidate_namespace(_ns_scoped(NS_QUEUE, canteen_id))
        cache_manager.invalidate_namespace(_ns_scoped(NS_CANTEENS, canteen_id))
        cache_manager.invalidate_namespace(_ns_scoped(NS_CAMPUS_INTEL, canteen_id))
        cache_manager.invalidate_namespace(_ns_scoped(NS_COMMAND_CENTER, canteen_id))


def invalidate_campus_intel(canteen_id: Optional[UUID | str] = None) -> None:
    cache_manager.invalidate_namespace(NS_CAMPUS_INTEL)
    cache_manager.invalidate_namespace(NS_COMMAND_CENTER)
    if canteen_id is not None:
        cache_manager.invalidate_namespace(_ns_scoped(NS_CAMPUS_INTEL, canteen_id))
        cache_manager.invalidate_namespace(_ns_scoped(NS_COMMAND_CENTER, canteen_id))


def invalidate_command_center(canteen_id: Optional[UUID | str] = None) -> None:
    cache_manager.invalidate_namespace(NS_COMMAND_CENTER)
    if canteen_id is not None:
        cache_manager.invalidate_namespace(_ns_scoped(NS_COMMAND_CENTER, canteen_id))


def invalidate_announcements() -> None:
    cache_manager.invalidate_namespace(NS_ANNOUNCEMENTS)


def invalidate_reports(canteen_id: Optional[UUID | str] = None) -> None:
    cache_manager.invalidate_namespace(NS_REPORTS)
    if canteen_id is not None:
        cache_manager.invalidate_namespace(_ns_scoped(NS_REPORTS, canteen_id))


def invalidate_auth_user(user_id: UUID | str) -> None:
    cache_manager.invalidate_namespace(_ns_scoped(NS_AUTH, f"u:{user_id}"))


def invalidate_auth_session(session_id: UUID | str) -> None:
    cache_manager.invalidate_namespace(_ns_scoped(NS_AUTH, f"s:{session_id}"))
