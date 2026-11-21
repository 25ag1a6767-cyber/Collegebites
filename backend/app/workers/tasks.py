from app.integrations.email_provider import send_email
from app.integrations.sms_provider import send_sms_or_whatsapp
from app.workers.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=15)
def dispatch_notification_task(self, channel: str, target: str, subject: str, body: str) -> dict:
    try:
        if channel == "email":
            ok, status = send_email(target, subject, body)
        elif channel in ("sms", "whatsapp"):
            ok, status = send_sms_or_whatsapp(target, body, channel=channel)
        else:
            ok, status = True, "in_app"
        return {"ok": ok, "status": status}
    except Exception as exc:
        raise self.retry(exc=exc)
