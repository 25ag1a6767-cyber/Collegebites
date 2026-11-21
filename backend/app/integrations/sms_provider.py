import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("collegebites.sms")


def send_sms_or_whatsapp(phone: str, message: str, channel: str = "sms") -> tuple[bool, str]:
    """Dispatch SMS or WhatsApp via Twilio REST API, webhook, or dev log (no fake delivery in prod)."""
    provider = (settings.WHATSAPP_PROVIDER if channel == "whatsapp" else settings.SMS_PROVIDER or "").strip().lower()
    if not phone:
        return False, "missing_phone"

    if provider in ("", "log", "none", "disabled"):
        if settings.is_production or provider in ("", "none", "disabled"):
            logger.warning("[%s] provider=%r not configured; not dispatched to %s", channel.upper(), provider, phone)
            return False, "sms_provider_not_configured"
        logger.info("[%s provider=%s] to=%s msg=%s", channel.upper(), provider, phone, message)
        return True, "logged"

    if provider == "twilio":
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN):
            if settings.is_production:
                return False, "twilio_credentials_missing"
            logger.warning("Twilio selected without credentials; falling back to log for %s", phone)
            return True, "logged"
        from_num = settings.TWILIO_WHATSAPP_FROM if channel == "whatsapp" else settings.TWILIO_FROM_NUMBER
        to_val = f"whatsapp:{phone}" if channel == "whatsapp" and not phone.startswith("whatsapp:") else phone
        from_val = (
            f"whatsapp:{from_num}"
            if channel == "whatsapp" and from_num and not from_num.startswith("whatsapp:")
            else from_num
        )
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
        try:
            resp = httpx.post(
                url,
                auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                data={"From": from_val, "To": to_val, "Body": message},
                timeout=10.0,
            )
            resp.raise_for_status()
            return True, "dispatched_twilio"
        except httpx.HTTPError as exc:
            logger.error("Twilio %s dispatch failed for %s: %s", channel, phone, exc)
            return False, str(exc)

    if provider == "webhook":
        if not settings.SMS_WEBHOOK_URL:
            if settings.is_production:
                return False, "sms_webhook_missing"
            logger.warning("Webhook SMS selected without SMS_WEBHOOK_URL; logged for %s", phone)
            return True, "logged"
        payload: dict[str, Any] = {"channel": channel, "to": phone, "message": message}
        try:
            resp = httpx.post(settings.SMS_WEBHOOK_URL, json=payload, timeout=10.0)
            resp.raise_for_status()
            return True, "dispatched_webhook"
        except httpx.HTTPError as exc:
            logger.error("Webhook SMS dispatch failed for %s: %s", phone, exc)
            return False, str(exc)

    if settings.is_production:
        logger.error("[%s] unsupported provider=%r in production", channel.upper(), provider)
        return False, f"unsupported_sms_provider:{provider}"
    logger.info("[%s custom-provider=%s] to=%s msg=%s", channel.upper(), provider, phone, message)
    return True, "logged"
