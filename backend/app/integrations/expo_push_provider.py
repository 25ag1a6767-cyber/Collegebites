import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("collegebites.push")
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send_expo_push(
    expo_push_token: str,
    title: str,
    body: str,
    data: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Send push notification through Expo Push Service when a valid ExponentPushToken is registered."""
    if not expo_push_token:
        return False, "no_token"
    if not (expo_push_token.startswith("ExponentPushToken[") or expo_push_token.startswith("ExpoPushToken[")):
        logger.info("Skipping non-Expo push token in dev mode: %s", expo_push_token)
        return True, "logged"

    try:
        resp = httpx.post(
            EXPO_PUSH_URL,
            json={"to": expo_push_token, "sound": "default", "title": title, "body": body, "data": data or {}},
            timeout=10.0,
        )
        resp.raise_for_status()
        return True, "sent_expo_push"
    except Exception as exc:
        logger.warning("Expo push dispatch failed for %s: %s", expo_push_token, exc)
        return False, "failed"
