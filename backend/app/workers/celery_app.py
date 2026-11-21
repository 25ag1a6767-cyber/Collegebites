from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

broker_url = settings.REDIS_URL if not settings.REDIS_URL.startswith("memory://") else "memory://"
celery_app = Celery("collegebites", broker=broker_url, backend=broker_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_acks_late=True,
    beat_schedule={
        "cleanup-expired-auth-artifacts-hourly": {
            "task": "app.workers.tasks.cleanup_expired_auth_artifacts_task",
            "schedule": crontab(minute=0),
        },
        "scan-inventory-alerts-every-15m": {
            "task": "app.workers.tasks.scan_inventory_alerts_task",
            "schedule": crontab(minute="*/15"),
        },
    },
)
