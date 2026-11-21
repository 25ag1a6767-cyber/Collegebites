import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("collegebites.email")


def send_email(to_email: str, subject: str, body_text: str) -> tuple[bool, str]:
    """Send an email via configured SMTP (SSL port 465 or STARTTLS port 587)."""
    if not to_email:
        return False, "missing_recipient"
    host = (settings.SMTP_HOST or "").strip()
    if not host:
        if settings.is_production:
            logger.error("SMTP_HOST is not configured in production; cannot deliver email to %s", to_email)
            return False, "smtp_not_configured"
        logger.info("Email provider not configured; logged email to %s: %s", to_email, subject)
        return True, "logged"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.effective_smtp_from
    msg["To"] = to_email
    msg.set_content(body_text)

    smtp_user = settings.effective_smtp_user
    use_ssl = bool(settings.SMTP_SECURE or settings.SMTP_PORT == 465)
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, settings.SMTP_PORT, timeout=12) as smtp:
                if smtp_user and settings.SMTP_PASSWORD:
                    smtp.login(smtp_user, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, settings.SMTP_PORT, timeout=12) as smtp:
                smtp.ehlo()
                try:
                    smtp.starttls()
                    smtp.ehlo()
                except smtplib.SMTPNotSupportedError:
                    pass
                if smtp_user and settings.SMTP_PASSWORD:
                    smtp.login(smtp_user, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        return True, "sent"
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("SMTP delivery failed for %s: %s", to_email, exc)
        return False, str(exc)
