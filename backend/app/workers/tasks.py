from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.integrations.email_provider import send_email
from app.integrations.sms_provider import send_sms_or_whatsapp
from app.models.auth import OTPVerification, RefreshToken
from app.models.college import Canteen
from app.models.engagement import Notification
from app.services.inventory_service import get_inventory_alerts
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
    """Remove expired OTP records and expired refresh tokens."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        otp_res = db.execute(delete(OTPVerification).where(OTPVerification.expires_at < now))
        tok_res = db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now))
        db.commit()
        return {"deleted_otps": otp_res.rowcount or 0, "deleted_refresh_tokens": tok_res.rowcount or 0}


@celery_app.task
def scan_inventory_alerts_task() -> dict:
    """Create unread in-app low-stock & expiry alerts for inventory/canteen managers without spamming duplicates."""
    alerts_created = 0
    with SessionLocal() as db:
        canteens = db.scalars(select(Canteen).where(Canteen.is_active.is_(True))).all()
        for c in canteens:
            alerts = get_inventory_alerts(db, c.id)
            low_cnt = len(alerts["low_stock"])
            exp_cnt = len(alerts["expiring_soon"])
            if low_cnt == 0 and exp_cnt == 0:
                continue
            existing = db.scalar(
                select(Notification).where(
                    Notification.canteen_id == c.id,
                    Notification.event_type == "inventory_alert",
                    Notification.is_read.is_(False),
                )
            )
            if existing:
                continue
            parts = []
            if low_cnt:
                parts.append(f"{low_cnt} low-stock ingredient(s)")
            if exp_cnt:
                parts.append(f"{exp_cnt} batch(es) expiring soon")
            db.add(
                Notification(
                    role_target="inventory_manager",
                    canteen_id=c.id,
                    channel="in_app",
                    title=f"Inventory Alert • {c.name}",
                    message=f"Action required in {c.name}: {', '.join(parts)}.",
                    event_type="inventory_alert",
                    delivery_status="sent",
                )
            )
            alerts_created += 1
        db.commit()
    return {"alerts_created": alerts_created}
