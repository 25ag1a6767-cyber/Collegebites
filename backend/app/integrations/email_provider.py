import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("collegebites.email")


def send_email(to_email: str, subject: str, body_text: str) -> tuple[bool, str]:
    if not settings.SMTP_HOST or not to_email:
        logger.info("Email provider not configured; logged email to %s: %s", to_email, subject)
        return True, "logged"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(body_text)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        smtp.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)
    return True, "sent"
