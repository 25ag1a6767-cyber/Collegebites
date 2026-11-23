from app.core.database import SessionLocal
from app.integrations.email_provider import send_email
from app.integrations.sms_provider import send_sms_or_whatsapp
from app.services.maintenance_service import (
    cleanup_expired_auth_artifacts,
    run_scheduled_maintenance,
    scan_inventory_alerts,
)
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


@celery_app.task
def cleanup_expired_auth_artifacts_task() -> dict:
    """Remove expired OTP records, expired refresh tokens, and stale unpaid slot reservations."""
    with SessionLocal() as db:
        return cleanup_expired_auth_artifacts(db)


@celery_app.task
def scan_inventory_alerts_task() -> dict:
    """Create unread in-app low-stock & expiry alerts for inventory/canteen managers without spamming duplicates."""
    with SessionLocal() as db:
        return scan_inventory_alerts(db)


@celery_app.task
def scheduled_backup_and_reconcile_task() -> dict:
    """Run automated financial reconciliation and encrypted database backup when due."""
    with SessionLocal() as db:
        return run_scheduled_maintenance(db, trigger="celery_schedule")
