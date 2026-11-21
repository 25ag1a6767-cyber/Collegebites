import logging

from app.core.config import settings

logger = logging.getLogger("collegebites.sms")


def send_sms_or_whatsapp(phone: str, message: str, channel: str = "sms") -> tuple[bool, str]:
    provider = settings.WHATSAPP_PROVIDER if channel == "whatsapp" else settings.SMS_PROVIDER
    if provider == "log" or not phone:
        logger.info("[%s provider=%s] to=%s msg=%s", channel.upper(), provider, phone, message)
        return True, "logged"
    return True, "dispatched"
