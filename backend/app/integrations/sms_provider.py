import logging
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("collegebites.sms")


def send_sms_or_whatsapp(phone: str, message: str, channel: str = "sms") -> tuple[bool, str]:
    """Dispatch non-OTP SMS or WhatsApp notifications (never logs message body)."""
    provider = (settings.WHATSAPP_PROVIDER if channel == "whatsapp" else settings.SMS_PROVIDER or "").strip().lower()
    if not phone:
        return False, "missing_phone"

    if provider in ("", "log", "none", "disabled"):
        return False, "sms_provider_not_configured"

    if provider == "twilio":
        from_num = settings.TWILIO_WHATSAPP_FROM if channel == "whatsapp" else settings.TWILIO_FROM_NUMBER
        if not (settings.TWILIO_ACCOUNT_SID.strip() and settings.TWILIO_AUTH_TOKEN.strip() and from_num.strip()):
            return False, "twilio_credentials_missing"
        to_val = f"whatsapp:{phone}" if channel == "whatsapp" and not phone.startswith("whatsapp:") else phone
        from_val = (
            f"whatsapp:{from_num}"
            if channel == "whatsapp" and from_num and not from_num.startswith("whatsapp:")
            else from_num
        )
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID.strip()}/Messages.json"
        try:
            resp = httpx.post(
                url,
                auth=(settings.TWILIO_ACCOUNT_SID.strip(), settings.TWILIO_AUTH_TOKEN.strip()),
                data={"From": from_val, "To": to_val, "Body": message},
                timeout=10.0,
            )
            resp.raise_for_status()
            return True, "dispatched_twilio"
        except httpx.HTTPError as exc:
            logger.error("Twilio %s dispatch failed: %s", channel, type(exc).__name__)
            return False, f"twilio_error:{type(exc).__name__}"

    if provider == "webhook":
        if not settings.SMS_WEBHOOK_URL.strip():
            return False, "sms_webhook_missing"
        payload: dict[str, Any] = {"channel": channel, "to": phone, "message": message}
        try:
            resp = httpx.post(settings.SMS_WEBHOOK_URL.strip(), json=payload, timeout=10.0)
            resp.raise_for_status()
            return True, "dispatched_webhook"
        except httpx.HTTPError as exc:
            logger.error("Webhook %s dispatch failed: %s", channel, type(exc).__name__)
            return False, f"webhook_error:{type(exc).__name__}"

    return False, f"unsupported_sms_provider:{provider}"
