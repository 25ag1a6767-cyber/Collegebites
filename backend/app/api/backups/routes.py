from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    client_ip_from_request,
    require_roles,
)
from app.services import backup_service

router = APIRouter(prefix="/backups", tags=["Backup & Disaster Recovery"])


class BackupCreateIn(BaseModel):
    trigger_type: str = Field(default="manual", pattern="^(manual|scheduled)$")


class BackupRestoreIn(BaseModel):
    dry_run: bool = True
    confirmation_phrase: Optional[str] = Field(default=None, max_length=120)


class BackupSettingsUpdateIn(BaseModel):
    auto_backup_enabled: Optional[bool] = None
    frequency_hours: Optional[int] = Field(default=None, ge=1, le=168)
    retention_days: Optional[int] = Field(default=None, ge=1, le=365)
    max_backups: Optional[int] = Field(default=None, ge=2, le=200)


@router.get("/dashboard")
def backup_dashboard(
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return backup_service.get_backup_dashboard(db)


@router.get("")
def list_backups(
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return backup_service.list_backups(db)


@router.post("")
def create_backup(
    payload: BackupCreateIn,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return backup_service.create_backup(
        db,
        trigger_type=payload.trigger_type,
        actor_user_id=principal.user.id,
        ip_address=client_ip_from_request(request),
    )


@router.post("/{backup_id}/verify")
def verify_backup(
    backup_id: UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return backup_service.verify_backup_integrity(
        db,
        backup_id,
        actor_user_id=principal.user.id,
        ip_address=client_ip_from_request(request),
    )


@router.post("/{backup_id}/restore")
def restore_backup(
    backup_id: UUID,
    payload: BackupRestoreIn,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return backup_service.restore_backup(
        db,
        backup_id,
        dry_run=payload.dry_run,
        confirmation_phrase=payload.confirmation_phrase,
        actor_user_id=principal.user.id,
        ip_address=client_ip_from_request(request),
    )


@router.get("/{backup_id}/download")
def download_encrypted_backup(
    backup_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    code, checksum, payload_enc = backup_service.get_encrypted_backup_blob(db, backup_id)
    return Response(
        content=payload_enc,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{code}.cbk.enc"',
            "X-Backup-Checksum-SHA256": checksum,
        },
    )


@router.put("/settings")
def update_backup_settings(
    payload: BackupSettingsUpdateIn,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return backup_service.update_backup_settings(
        db,
        auto_backup_enabled=payload.auto_backup_enabled,
        frequency_hours=payload.frequency_hours,
        retention_days=payload.retention_days,
        max_backups=payload.max_backups,
        actor_user_id=principal.user.id,
        ip_address=client_ip_from_request(request),
    )


@router.get("/recovery-logs")
def list_recovery_logs(
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)),
    db: Session = Depends(get_db),
):
    return backup_service.list_recovery_logs(db)
