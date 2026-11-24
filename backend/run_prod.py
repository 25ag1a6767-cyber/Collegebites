"""
Production ASGI runner for CollegeBites FastAPI backend.

Computes safe Uvicorn worker count bounded by CPU cores and PostgreSQL connection
pool limits so multi-worker deployments scale linearly without exhausting DB connections.
"""

from __future__ import annotations

import os
import uvicorn

from app.core.config import settings


def compute_safe_worker_count() -> int:
    cpu_count = os.cpu_count() or 2
    requested = int(os.environ.get("UVICORN_WORKERS", settings.UVICORN_WORKERS or 4))
    max_db_conns = int(os.environ.get("PG_MAX_CONNECTIONS_BUDGET", "160"))
    per_worker_pool = max(1, settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW)
    db_bounded = max(1, max_db_conns // per_worker_pool)
    cpu_bounded = max(1, min(cpu_count, 8))
    return max(1, min(requested, cpu_bounded, db_bounded))


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    workers = compute_safe_worker_count()
    backlog = int(os.environ.get("UVICORN_BACKLOG", "2048"))
    limit_concurrency = int(os.environ.get("UVICORN_LIMIT_CONCURRENCY", "1200"))
    timeout_keep_alive = int(os.environ.get("UVICORN_TIMEOUT_KEEP_ALIVE", "15"))

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        workers=workers,
        backlog=backlog,
        limit_concurrency=limit_concurrency,
        timeout_keep_alive=timeout_keep_alive,
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=os.environ.get("UVICORN_ACCESS_LOG", "false").lower() == "true",
    )


if __name__ == "__main__":
    main()
