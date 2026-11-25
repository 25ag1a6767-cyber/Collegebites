from html import escape
import logging
from pathlib import Path
import smtplib
from email.message import EmailMessage
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("collegebites.email")
_LOGO_ASSET_PATH = Path(__file__).resolve().parent.parent / "assets" / "collegebites-logo.png"


def _build_branded_html_email(subject: str, body_text: str, logo_cid: str | None) -> str:
    body_html = "<br />".join(escape(line) for line in body_text.strip().splitlines())
    logo_block = (
        f'<img src="cid:{logo_cid}" alt="CollegeBites" width="44" height="44" '
        'style="display:block;border-radius:10px;border:1px solid #fdedce;background:#fdf8f0;" />'
        if logo_cid
        else ""
    )
    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#fdf8f0;font-family:Arial,Helvetica,sans-serif;color:#1e293b;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e7d7c9;border-radius:16px;overflow:hidden;">
      <tr>
        <td style="background:#76010d;padding:18px 22px;color:#ffffff;">
          <table role="presentation" cellspacing="0" cellpadding="0">
            <tr>
              <td style="padding-right:12px;vertical-align:middle;">{logo_block}</td>
              <td style="vertical-align:middle;">
                <div style="font-size:18px;font-weight:800;letter-spacing:-0.2px;color:#ffffff;">CollegeBites</div>
                <div style="font-size:12px;color:#fdedce;">{escape(subject)}</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="padding:22px;font-size:14px;line-height:1.6;color:#1e293b;">
          {body_html}
        </td>
      </tr>
      <tr>
        <td style="padding:14px 22px;background:#fdf8f0;border-top:1px solid #f1e3d3;font-size:11px;color:#5d010a;">
          CollegeBites Smart Campus Canteen &bull; Razorpay Verified Payments &bull; Live QR Pickup
        </td>
      </tr>
    </table>
  </body>
</html>"""


def resolve_email_provider() -> Optional[str]:
    """Return the active configured transactional email provider (`smtp` | `resend` | `sendgrid`) or None."""
    explicit = (settings.EMAIL_PROVIDER or "").strip().lower()
    if explicit:
        if explicit == "resend":
            return "resend" if settings.RESEND_API_KEY.strip() else None
        if explicit == "sendgrid":
            return "sendgrid" if settings.SENDGRID_API_KEY.strip() else None
        if explicit == "smtp":
            return "smtp" if (settings.SMTP_HOST or "").strip() else None
        return None

    if settings.RESEND_API_KEY.strip():
        return "resend"
    if settings.SENDGRID_API_KEY.strip():
        return "sendgrid"
    if (settings.SMTP_HOST or "").strip():
        return "smtp"
    return None


def _dispatch_via_smtp(to_email: str, subject: str, body_text: str) -> tuple[bool, str]:
    host = (settings.SMTP_HOST or "").strip()
    if not host:
        return False, "smtp_not_configured"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.effective_smtp_from
    msg["To"] = to_email
    msg.set_content(body_text)

    logo_bytes = _LOGO_ASSET_PATH.read_bytes() if _LOGO_ASSET_PATH.is_file() else None
    logo_cid = "collegebites-logo" if logo_bytes else None
    html_body = _build_branded_html_email(subject, body_text, logo_cid)
    msg.add_alternative(html_body, subtype="html")
    if logo_bytes and logo_cid:
        html_part = msg.get_payload()[1]
        html_part.add_related(
            logo_bytes,
            maintype="image",
            subtype="png",
            cid=f"<{logo_cid}>",
            filename="collegebites-logo.png",
        )

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
        return True, "smtp"
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("SMTP delivery failed (subject=%s): %s", subject, type(exc).__name__)
        return False, f"smtp_error:{type(exc).__name__}"


def _dispatch_via_resend(to_email: str, subject: str, body_text: str) -> tuple[bool, str]:
    api_key = settings.RESEND_API_KEY.strip()
    if not api_key:
        return False, "resend_not_configured"
    html_body = _build_branded_html_email(subject, body_text, None)
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": settings.effective_smtp_from,
                "to": [to_email],
                "subject": subject,
                "text": body_text,
                "html": html_body,
            },
            timeout=12.0,
        )
        resp.raise_for_status()
        return True, "resend"
    except httpx.HTTPError as exc:
        logger.error("Resend email delivery failed (subject=%s): %s", subject, type(exc).__name__)
        return False, f"resend_error:{type(exc).__name__}"


def _dispatch_via_sendgrid(to_email: str, subject: str, body_text: str) -> tuple[bool, str]:
    api_key = settings.SENDGRID_API_KEY.strip()
    if not api_key:
        return False, "sendgrid_not_configured"
    html_body = _build_branded_html_email(subject, body_text, None)
    try:
        resp = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": settings.effective_smtp_from, "name": "CollegeBites"},
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": body_text},
                    {"type": "text/html", "value": html_body},
                ],
            },
            timeout=12.0,
        )
        resp.raise_for_status()
        return True, "sendgrid"
    except httpx.HTTPError as exc:
        logger.error("SendGrid email delivery failed (subject=%s): %s", subject, type(exc).__name__)
        return False, f"sendgrid_error:{type(exc).__name__}"


def send_password_reset_email(to_email: str, reset_url: str, expiry_minutes: int) -> tuple[bool, str]:
    """Deliver a secure single-use non-OTP password reset link via the configured transactional email provider."""
    subject = "CollegeBites — Password Reset Request"
    body_text = (
        "A password reset was requested for your CollegeBites account.\n\n"
        f"Reset link (valid for {expiry_minutes} minutes, single use):\n{reset_url}\n\n"
        "If you did not request this reset, you can safely ignore this email — your password will remain unchanged."
    )
    return send_email(to_email, subject, body_text)


def send_email(to_email: str, subject: str, body_text: str) -> tuple[bool, str]:
    """Send transactional notifications & account recovery links via configured email provider."""
    if not to_email:
        return False, "missing_recipient"
    provider = resolve_email_provider()
    if provider == "resend":
        ok, detail = _dispatch_via_resend(to_email, subject, body_text)
        return (True, "sent") if ok else (False, detail)
    if provider == "sendgrid":
        ok, detail = _dispatch_via_sendgrid(to_email, subject, body_text)
        return (True, "sent") if ok else (False, detail)
    if provider == "smtp":
        ok, detail = _dispatch_via_smtp(to_email, subject, body_text)
        return (True, "sent") if ok else (False, detail)

    if settings.is_production:
        logger.error("No email provider configured in production; cannot deliver email (%s)", subject)
        return False, "email_provider_not_configured"
    return False, "email_provider_not_configured"
