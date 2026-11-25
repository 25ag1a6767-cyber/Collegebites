from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.college import Canteen
from app.models.engagement import Notification
from app.models.auth import PasswordResetToken, RefreshToken, SessionRecord
from app.models.meal_plan import StudentMealSubscription
from app.services.audit_service import record_audit_log
from app.services.inventory_service import get_inventory_alerts
from app.services.order_service import release_expired_slot_reservations


def cleanup_expired_auth_artifacts(db: Session) -> dict[str, int]:
    """Remove expired password reset tokens, refresh tokens, sessions, stale unpaid slot reservations, and expire past-due meal plans."""
    now = datetime.now(timezone.utc)
    reset_res = db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < now))
    tok_res = db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now))
    sess_res = db.execute(delete(SessionRecord).where(SessionRecord.expires_at < now))
    meal_res = db.execute(
        update(StudentMealSubscription)
        .where(
            StudentMealSubscription.status == "active",
            StudentMealSubscription.expires_at.is_not(None),
            StudentMealSubscription.expires_at <= now,
        )
        .values(status="expired")
    )
    released_slots = release_expired_slot_reservations(db)
    db.commit()
    return {
        "deleted_password_reset_tokens": int(reset_res.rowcount or 0),
        "deleted_refresh_tokens": int(tok_res.rowcount or 0),
        "deleted_sessions": int(sess_res.rowcount or 0),
        "released_expired_slots": int(released_slots),
        "expired_meal_subscriptions": int(meal_res.rowcount or 0),
    }


def scan_inventory_alerts(db: Session) -> dict[str, int]:
    """Create unread in-app low-stock & expiry alerts for active canteens through Notification Center without duplicates."""
    from app.services.notification_service import create_role_notifications

    alerts_created = 0
    canteens = db.scalars(select(Canteen).where(Canteen.is_active.is_(True))).all()
    day_bucket = datetime.now(timezone.utc).strftime("%Y%m%d")
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
        created = create_role_notifications(
            db,
            roles=["inventory_manager", "canteen_manager"],
            canteen_id=canteen.id,
            event_type="inventory_alert",
            category="inventory",
            priority="high",
            title=f"Inventory Alert • {canteen.name}",
            message=f"Action required in {canteen.name}: {', '.join(parts)}.",
            event_id_base=f"inv_scan:{canteen.id}:{day_bucket}",
        )
        if created:
            alerts_created += 1
    db.commit()
    return {"alerts_created": alerts_created}


def run_scheduled_maintenance(
    db: Session,
    *,
    actor_user_id: Optional[UUID] = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Run periodic cleanup, inventory alert scan, overdue cleaning alerts, and automated financial reconciliation."""
    cleanup_stats = cleanup_expired_auth_artifacts(db)
    alert_stats = scan_inventory_alerts(db)
    from app.services import backup_service, food_safety_service, reconciliation_service

    overdue_cleaning_notified = 0
    for canteen in db.scalars(select(Canteen).where(Canteen.is_active.is_(True))).all():
        res_clean = food_safety_service.notify_overdue_cleaning_tasks(db, canteen.id)
        overdue_cleaning_notified += int(
            res_clean.get("reminders_dispatched", res_clean.get("notified_overdue_tasks", 0))
        )

    reconcil_stats = reconciliation_service.run_auto_reconciliation(
        db,
        trigger=trigger,
        actor_user_id=actor_user_id,
    )
    from app.services.receipt_service import process_retryable_network_print_jobs

    print_recovery_stats = process_retryable_network_print_jobs(db)
    backup_stats = backup_service.run_scheduled_backup_if_due(db, trigger="cron")
    record_audit_log(
        db,
        action="system.maintenance_run",
        entity_type="system",
        entity_id="maintenance",
        actor_user_id=actor_user_id,
        details={
            "trigger": trigger,
            **cleanup_stats,
            **alert_stats,
            "overdue_cleaning_notified": overdue_cleaning_notified,
            "reconciled_checked": reconcil_stats["total_checked"],
            "reconciled_discrepancies": reconcil_stats["discrepancy_count"],
            "print_jobs_recovered": print_recovery_stats.get("completed", 0),
            "backup_ran": backup_stats.get("ran", False),
        },
    )
    db.commit()
    return {
        "status": "ok",
        "trigger": trigger,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        **cleanup_stats,
        **alert_stats,
        "overdue_cleaning_notified": overdue_cleaning_notified,
        "reconciled_checked": reconcil_stats["total_checked"],
        "reconciled_discrepancies": reconcil_stats["discrepancy_count"],
        "print_recovery": print_recovery_stats,
        "backup_status": backup_stats,
    }
