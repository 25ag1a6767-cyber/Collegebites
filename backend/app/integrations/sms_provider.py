import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("collegebites.sms")


def send_sms_or_whatsapp(phone: str, message: str, channel: str = "sms") -> tuple[bool, str]:
    """Dispatch SMS or WhatsApp via Twilio REST API, generic webhook, or structured dev log."""
    provider = settings.WHATSAPP_PROVIDER if channel == "whatsapp" else settings.SMS_PROVIDER
    if provider == "log" or not phone:
        logger.info("[%s provider=%s] to=%s msg=%s", channel.upper(), provider, phone, message)
        return True, "logged"

    if provider == "twilio":
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN):
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
        resp = httpx.post(
            url,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            data={"From": from_val, "To": to_val, "Body": message},
            timeout=10.0,
        )
        resp.raise_for_status()
        return True, "dispatched_twilio"

    if provider == "webhook":
        if not settings.SMS_WEBHOOK_URL:
            logger.warning("Webhook SMS selected without SMS_WEBHOOK_URL; logged for %s", phone)
            return True, "logged"
        payload: dict[str, Any] = {"channel": channel, "to": phone, "message": message}
        resp = httpx.post(settings.SMS_WEBHOOK_URL, json=payload, timeout=10.0)
        resp.raise_for_status()
        return True, "dispatched_webhook"

    logger.info("[%s custom-provider=%s] to=%s msg=%s", channel.upper(), provider, phone, message)
    return True, "logged"
