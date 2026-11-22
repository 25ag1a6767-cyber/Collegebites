from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.college import Canteen
from app.models.engagement import Notification
from app.models.auth import OTPVerification, RefreshToken
from app.services.audit_service import record_audit_log
from app.services.inventory_service import get_inventory_alerts
from app.services.order_service import release_expired_slot_reservations


def cleanup_expired_auth_artifacts(db: Session) -> dict[str, int]:
    """Remove expired OTP records, expired refresh tokens, and stale unpaid slot reservations."""
    now = datetime.now(timezone.utc)
    otp_res = db.execute(delete(OTPVerification).where(OTPVerification.expires_at < now))
    tok_res = db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now))
    released_slots = release_expired_slot_reservations(db)
    db.commit()
    return {
        "deleted_otps": int(otp_res.rowcount or 0),
        "deleted_refresh_tokens": int(tok_res.rowcount or 0),
        "released_expired_slots": int(released_slots),
    }


def scan_inventory_alerts(db: Session) -> dict[str, int]:
    """Create unread in-app low-stock & expiry alerts for active canteens without duplicates."""
    alerts_created = 0
    canteens = db.scalars(select(Canteen).where(Canteen.is_active.is_(True))).all()
    for canteen in canteens:
        alerts = get_inventory_alerts(db, canteen.id)
        low_cnt = len(alerts["low_stock"])
        exp_cnt = len(alerts["expiring_soon"])
        if low_cnt == 0 and exp_cnt == 0:
            continue
        existing = db.scalar(
            select(Notification).where(
                Notification.canteen_id == canteen.id,
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
                canteen_id=canteen.id,
                channel="in_app",
                title=f"Inventory Alert • {canteen.name}",
                message=f"Action required in {canteen.name}: {', '.join(parts)}.",
                event_type="inventory_alert",
                delivery_status="sent",
            )
        )
        alerts_created += 1
    db.commit()
    return {"alerts_created": alerts_created}


def run_scheduled_maintenance(
    db: Session,
    *,
    actor_user_id: Optional[UUID] = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Run all periodic cleanup and inventory alert scans atomically for HTTP cron or admin use."""
    cleanup_stats = cleanup_expired_auth_artifacts(db)
    alert_stats = scan_inventory_alerts(db)
    record_audit_log(
        db,
        action="system.maintenance_run",
        entity_type="system",
        entity_id="maintenance",
        actor_user_id=actor_user_id,
        details={"trigger": trigger, **cleanup_stats, **alert_stats},
    )
    db.commit()
    return {
        "status": "ok",
        "trigger": trigger,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        **cleanup_stats,
        **alert_stats,
    }
