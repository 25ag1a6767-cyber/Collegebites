from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from fastapi import Request, Response

try:
    import orjson as _orjson
except Exception:  # pragma: no cover
    _orjson = None


def set_private_no_store(response: Response) -> None:
    """Explicitly prevent CDN, proxy, or browser caching of sensitive or user-specific responses."""
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


def set_public_cache(
    response: Response,
    *,
    s_maxage: int,
    swr: int = 0,
    max_age: int = 0,
    vary: Optional[str] = None,
) -> None:
    """
    Configure Vercel Edge CDN & shared-cache headers for strictly public, non-PII responses.
    Never call this on authenticated, personalized, cart, order, or payment mutation endpoints.
    """
    parts = ["public", f"max-age={max(0, int(max_age))}", f"s-maxage={max(1, int(s_maxage))}"]
    if swr > 0:
        parts.append(f"stale-while-revalidate={int(swr)}")
    cc_value = ", ".join(parts)
    response.headers["Cache-Control"] = cc_value

    cdn_parts = ["public", f"s-maxage={max(1, int(s_maxage))}"]
    if swr > 0:
        cdn_parts.append(f"stale-while-revalidate={int(swr)}")
    response.headers["CDN-Cache-Control"] = ", ".join(cdn_parts)
    if vary:
        response.headers["Vary"] = vary


def compute_weak_etag(payload_or_seed: Any) -> str:
    """Build a deterministic weak ETag from a precomputed version string or JSON-serializable payload."""
    if isinstance(payload_or_seed, str):
        raw = payload_or_seed.encode("utf-8")
    elif _orjson is not None:
        raw = _orjson.dumps(payload_or_seed, default=str, option=_orjson.OPT_SORT_KEYS)
    else:
        raw = json.dumps(payload_or_seed, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f'W/"{digest}"'


def apply_etag_and_check_304(
    request: Optional[Request],
    response: Response,
    etag_seed: Any,
    *,
    s_maxage: int,
    swr: int = 0,
    max_age: int = 0,
    vary: Optional[str] = None,
) -> Optional[Response]:
    """
    Attach public Cache-Control + weak ETag headers.
    Returns a 304 Not Modified Response if the client's If-None-Match matches, else None.
    """
    set_public_cache(response, s_maxage=s_maxage, swr=swr, max_age=max_age, vary=vary)
    etag = compute_weak_etag(etag_seed)
    response.headers["ETag"] = etag
    if request is not None:
        inm = (request.headers.get("if-none-match") or "").strip()
        if inm:
            candidates = [c.strip() for c in inm.split(",")]
            if "*" in candidates or etag in candidates or etag.removeprefix("W/") in [
                c.removeprefix("W/") for c in candidates
            ]:
                hdrs = {
                    "ETag": etag,
                    "Cache-Control": response.headers["Cache-Control"],
                    "CDN-Cache-Control": response.headers["CDN-Cache-Control"],
                }
                if vary:
                    hdrs["Vary"] = vary
                return Response(status_code=304, headers=hdrs)
    return None
