from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.system import ActivityLog, AuditLog


def record_audit_log(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    actor_user_id: Optional[UUID] = None,
    actor_role: Optional[str] = None,
    ip_address: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
        details=details or {},
    )
    db.add(entry)
    return entry


def record_activity_log(
    db: Session,
    *,
    activity_type: str,
    description: str,
    user_id: Optional[UUID] = None,
    canteen_id: Optional[UUID] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> ActivityLog:
    entry = ActivityLog(
        user_id=user_id,
        canteen_id=canteen_id,
        activity_type=activity_type,
        description=description,
        metadata_json=metadata or {},
    )
    db.add(entry)
    return entry
