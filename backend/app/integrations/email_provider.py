from html import escape
import logging
from pathlib import Path
import smtplib
from email.message import EmailMessage

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
          CollegeBites Smart Campus Canteen &bull; Strict Online Payments &bull; Verified QR Pickup
        </td>
      </tr>
    </table>
  </body>
</html>"""


def send_email(to_email: str, subject: str, body_text: str) -> tuple[bool, str]:
    """Send a branded CollegeBites email via configured SMTP (SSL port 465 or STARTTLS port 587)."""
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
        return True, "sent"
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("SMTP delivery failed for %s: %s", to_email, exc)
        return False, str(exc)
