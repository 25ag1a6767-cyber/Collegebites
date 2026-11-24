import logging
import os
import time
from collections.abc import Generator
from typing import Any, Callable, TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from app.core.config import settings

logger = logging.getLogger("collegebites.database")
_T = TypeVar("_T")


def normalize_database_url(raw_url: str) -> str:
    """Normalize standard postgres:// or postgresql:// URLs to SQLAlchemy psycopg v3 driver."""
    url = (raw_url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def is_serverless_runtime() -> bool:
    return bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def is_pgbouncer_pooled_url(url: str) -> bool:
    low = (url or "").lower()
    return "-pooler." in low or "pgbouncer=true" in low or ":6543/" in low


def _build_engine_kwargs(url: str) -> dict[str, Any]:
    if url.startswith("sqlite"):
        return {
            "connect_args": {"check_same_thread": False, "timeout": 30},
            "pool_pre_ping": True,
        }

    connect_args: dict[str, Any] = {
        "connect_timeout": settings.DB_CONNECT_TIMEOUT,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }
    if is_pgbouncer_pooled_url(url):
        # Neon PgBouncer / transaction-pooled endpoints require prepared statements disabled
        # and reject startup `options` flags.
        connect_args["prepare_threshold"] = None
    elif settings.DB_STATEMENT_TIMEOUT_MS > 0:
        connect_args["options"] = f"-c statement_timeout={int(settings.DB_STATEMENT_TIMEOUT_MS)}"

    if is_serverless_runtime():
        if settings.DB_SERVERLESS_NULLPOOL:
            return {
                "poolclass": NullPool,
                "pool_pre_ping": True,
                "connect_args": connect_args,
            }
        # Small bounded QueuePool per warm serverless/Fluid Compute instance avoids
        # per-request TCP+TLS handshakes while capping total concurrent DB sessions.
        return {
            "poolclass": QueuePool,
            "pool_size": max(1, settings.DB_SERVERLESS_POOL_SIZE),
            "max_overflow": max(1, settings.DB_SERVERLESS_MAX_OVERFLOW),
            "pool_timeout": min(10, settings.DB_POOL_TIMEOUT),
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_use_lifo": True,
            "connect_args": connect_args,
        }

    return {
        "poolclass": QueuePool,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_pre_ping": True,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_use_lifo": True,
        "connect_args": connect_args,
    }


EFFECTIVE_DATABASE_URL = normalize_database_url(settings.DATABASE_URL)
engine = create_engine(EFFECTIVE_DATABASE_URL, **_build_engine_kwargs(EFFECTIVE_DATABASE_URL))


if EFFECTIVE_DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite_pragmas(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA cache_size=-32000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a transactional SQLAlchemy session per request, guaranteeing rollback & pool release."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()


def run_with_db_retry(
    operation: Callable[[], _T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.05,
) -> _T:
    """Retry transient DB connectivity drops or deadlock/serialization conflicts safely."""
    last_exc: Exception | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            return operation()
        except (OperationalError, DBAPIError) as exc:
            last_exc = exc
            msg = str(exc).lower()
            transient = (
                getattr(exc, "connection_invalidated", False)
                or "deadlock" in msg
                or "could not serialize" in msg
                or "database is locked" in msg
                or "connection reset" in msg
                or "server closed the connection" in msg
                or "ssl connection has been closed" in msg
            )
            if not transient or attempt >= max_attempts:
                raise
            delay = base_delay_seconds * (2 ** (attempt - 1))
            logger.warning("Transient DB error on attempt %d/%d (%s); retrying in %.3fs", attempt, max_attempts, exc.__class__.__name__, delay)
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def get_pool_stats() -> dict[str, Any]:
    """Return live SQLAlchemy connection pool diagnostics for health & SRE monitoring."""
    pool = engine.pool
    stats: dict[str, Any] = {
        "dialect": engine.dialect.name,
        "pool_class": pool.__class__.__name__,
        "serverless_mode": is_serverless_runtime(),
        "pgbouncer_detected": is_pgbouncer_pooled_url(EFFECTIVE_DATABASE_URL),
    }
    for attr in ("size", "checkedin", "checkedout", "overflow"):
        fn = getattr(pool, attr, None)
        if callable(fn):
            try:
                stats[attr] = int(fn())
            except Exception:
                pass
    return stats


def dispose_engine() -> None:
    """Cleanly release all idle pooled database connections on graceful shutdown."""
    try:
        engine.dispose()
    except Exception as exc:
        logger.warning("Error disposing SQLAlchemy engine: %s", exc)
