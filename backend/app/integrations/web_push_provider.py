import json
import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger("collegebites.webpush")


def send_web_push(
    subscription: dict[str, Any],
    *,
    title: str,
    body: str,
    url_path: str = "/orders",
    data: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Dispatch encrypted VAPID Web Push notification to a stored browser PushSubscription."""
    if not settings.VAPID_PUBLIC_KEY or not settings.VAPID_PRIVATE_KEY:
        return False, "vapid_not_configured"
    endpoint = str(subscription.get("endpoint") or "").strip()
    if not endpoint:
        return False, "missing_endpoint"

    try:
        from pywebpush import WebPushException, webpush
    except ImportError as exc:
        logger.warning("pywebpush not installed: %s", exc)
        return False, "pywebpush_missing"

    payload = json.dumps(
        {
            "title": title,
            "body": body,
            "url": url_path,
            "data": {"url": url_path, **(data or {})},
        }
    )
    try:
        webpush(
            subscription_info={
                "endpoint": endpoint,
                "keys": subscription.get("keys") or {},
            },
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT or "mailto:support@collegebites.edu"},
            ttl=300,
        )
        return True, "sent_web_push"
    except WebPushException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in (404, 410):
            logger.info("Pruning expired browser push subscription (%s)", status_code)
            return False, "gone"
        logger.warning("Web push delivery failed (%s): %s", status_code, exc)
        return False, f"http_{status_code or 'error'}"
    except Exception as exc:
        logger.warning("Non-fatal web push failure: %s", exc)
        return False, "failed"
