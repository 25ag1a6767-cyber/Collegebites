from __future__ import annotations

import base64
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any, Optional
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, Time, Uuid, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Base
from app.models.system import BackupRecord, BackupSetting, RecoveryLog
from app.services import security_service
from app.services.audit_service import record_audit_log

CONFIRM_RESTORE_PHRASE = "CONFIRM PRODUCTION RESTORE"

# Strictly exclude ephemeral credential/token tables and the backup vault itself from snapshot bundles
EXCLUDED_BACKUP_TABLES: set[str] = {
    "sessions",
    "refresh_tokens",
    "otp_verifications",
    "backup_records",
    "backup_settings",
    "recovery_logs",
}


def _ordered_backup_tables() -> list[str]:
    return [t.name for t in Base.metadata.sorted_tables if t.name not in EXCLUDED_BACKUP_TABLES]

SENSITIVE_DICT_SUBSTRINGS = ("secret", "password", "private_key", "token_hash", "razorpay_signature", "client_secret")
REDACTED_COLUMNS: dict[str, set[str]] = {
    "users": {"password_hash"},
    "orders": {"guest_access_token_hash"},
}


def _derive_fernet() -> Fernet:
    raw_secret = (settings.BACKUP_ENCRYPTION_KEY or "").strip() or f"cb-dr-vault:{settings.SECRET_KEY}"
    digest = hashlib.sha256(raw_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _scrub_json_value(val: Any) -> Any:
    if isinstance(val, dict):
        cleaned: dict[str, Any] = {}
        for k, v in val.items():
            kl = str(k).lower()
            if any(sub in kl for sub in SENSITIVE_DICT_SUBSTRINGS):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = _scrub_json_value(v)
        return cleaned
    if isinstance(val, list):
        return [_scrub_json_value(item) for item in val]
    return val


def _serialize_cell(table_name: str, col_name: str, val: Any) -> Any:
    if col_name in REDACTED_COLUMNS.get(table_name, set()):
        return None
    if val is None:
        return None
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, Decimal):
        return str(val)
    if isinstance(val, (datetime, date, time)):
        return val.isoformat()
    if isinstance(val, (dict, list)):
        return _scrub_json_value(val)
    return val


def _deserialize_cell(col: Any, val: Any) -> Any:
    if val is None:
        return None
    col_type = col.type
    if isinstance(col_type, Uuid) or "UUID" in col_type.__class__.__name__.upper():
        return UUID(str(val))
    if isinstance(col_type, DateTime):
        dt = datetime.fromisoformat(str(val))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    if isinstance(col_type, Date) and not isinstance(col_type, DateTime):
        return date.fromisoformat(str(val))
    if isinstance(col_type, Time):
        return time.fromisoformat(str(val))
    if isinstance(col_type, Numeric):
        return Decimal(str(val))
    return val


def get_or_create_backup_settings(db: Session) -> BackupSetting:
    row = db.scalar(select(BackupSetting).where(BackupSetting.singleton_key == "default"))
    if not row:
        now = datetime.now(timezone.utc)
        row = BackupSetting(
            singleton_key="default",
            auto_backup_enabled=True,
            frequency_hours=24,
            retention_days=30,
            max_backups=30,
            storage_backend="database_encrypted",
            next_scheduled_at=now + timedelta(hours=24),
        )
        db.add(row)
        db.flush()
    return row


def update_backup_settings(
    db: Session,
    *,
    auto_backup_enabled: Optional[bool] = None,
    frequency_hours: Optional[int] = None,
    retention_days: Optional[int] = None,
    max_backups: Optional[int] = None,
    actor_user_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
) -> dict[str, Any]:
    cfg = get_or_create_backup_settings(db)
    if auto_backup_enabled is not None:
        cfg.auto_backup_enabled = auto_backup_enabled
    if frequency_hours is not None:
        cfg.frequency_hours = max(1, min(int(frequency_hours), 168))
    if retention_days is not None:
        cfg.retention_days = max(1, min(int(retention_days), 365))
    if max_backups is not None:
        cfg.max_backups = max(2, min(int(max_backups), 200))
    cfg.updated_by_user_id = actor_user_id
    base_ts = cfg.last_backup_at or datetime.now(timezone.utc)
    if base_ts.tzinfo is None:
        base_ts = base_ts.replace(tzinfo=timezone.utc)
    cfg.next_scheduled_at = base_ts + timedelta(hours=cfg.frequency_hours)
    record_audit_log(
        db,
        action="backup.settings_updated",
        entity_type="backup_setting",
        entity_id="default",
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        details={
            "auto_backup_enabled": cfg.auto_backup_enabled,
            "frequency_hours": cfg.frequency_hours,
            "retention_days": cfg.retention_days,
            "max_backups": cfg.max_backups,
        },
    )
    db.commit()
    return _serialize_settings(cfg)


def _serialize_settings(cfg: BackupSetting) -> dict[str, Any]:
    return {
        "auto_backup_enabled": cfg.auto_backup_enabled,
        "frequency_hours": cfg.frequency_hours,
        "retention_days": cfg.retention_days,
        "max_backups": cfg.max_backups,
        "storage_backend": cfg.storage_backend,
        "last_backup_at": cfg.last_backup_at.isoformat() if cfg.last_backup_at else None,
        "next_scheduled_at": cfg.next_scheduled_at.isoformat() if cfg.next_scheduled_at else None,
    }


def _serialize_backup_record(rec: BackupRecord) -> dict[str, Any]:
    return {
        "id": str(rec.id),
        "backup_code": rec.backup_code,
        "trigger_type": rec.trigger_type,
        "storage_backend": rec.storage_backend,
        "file_path": rec.file_path,
        "size_bytes": rec.size_bytes,
        "checksum_sha256": rec.checksum_sha256,
        "encryption_algo": rec.encryption_algo,
        "is_encrypted": rec.is_encrypted,
        "status": rec.status,
        "integrity_verified": rec.integrity_verified,
        "verified_at": rec.verified_at.isoformat() if rec.verified_at else None,
        "row_counts": rec.row_counts_json or {},
        "total_rows": sum(int(v) for v in (rec.row_counts_json or {}).values()),
        "error_message": rec.error_message,
        "created_at": rec.created_at.isoformat(),
    }


def apply_retention_policy(db: Session, cfg: BackupSetting) -> int:
    """Prune stale completed/verified backups outside retention policy while always retaining >= 1 valid snapshot."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=cfg.retention_days)
    all_valid = list(
        db.scalars(
            select(BackupRecord)
            .where(BackupRecord.status.in_(("completed", "verified", "restored")))
            .order_by(BackupRecord.created_at.desc())
        ).all()
    )
    if len(all_valid) <= 1:
        return 0

    deleted = 0
    for idx, rec in enumerate(all_valid):
        if idx == 0:
            continue  # Never purge newest valid backup
        created = rec.created_at.replace(tzinfo=timezone.utc) if rec.created_at.tzinfo is None else rec.created_at
        over_count = idx >= cfg.max_backups
        expired = created < cutoff
        if over_count or expired:
            db.delete(rec)
            deleted += 1
    return deleted


def create_backup(
    db: Session,
    *,
    trigger_type: str = "manual",
    actor_user_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
    simulate_failure: bool = False,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    backup_code = f"CB-BKP-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3).upper()}"
    cfg = get_or_create_backup_settings(db)

    try:
        if simulate_failure:
            raise RuntimeError("Simulated storage write failure during backup snapshot")

        snapshot_tables: dict[str, list[dict[str, Any]]] = {}
        row_counts: dict[str, int] = {}

        for table_name in _ordered_backup_tables():
            tbl = Base.metadata.tables.get(table_name)
            if tbl is None:
                continue
            result = db.execute(select(tbl)).mappings().all()
            col_names = [c.name for c in tbl.columns]
            rows_out = [
                {cname: _serialize_cell(table_name, cname, r[cname]) for cname in col_names}
                for r in result
            ]
            snapshot_tables[table_name] = rows_out
            row_counts[table_name] = len(rows_out)

        bundle = {
            "format_version": "1.0",
            "backup_code": backup_code,
            "created_at": now.isoformat(),
            "environment": settings.ENVIRONMENT,
            "redacted_fields": sorted(c for cols in REDACTED_COLUMNS.values() for c in cols),
            "tables": snapshot_tables,
        }
        raw_json = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        compressed = gzip.compress(raw_json, compresslevel=6)
        checksum = hashlib.sha256(compressed).hexdigest()
        encrypted_token = _derive_fernet().encrypt(compressed).decode("ascii")

        # Best-effort mirror to writable temp backup folder (safe in serverless read-only deployments)
        file_ref = f"encrypted://db-vault/{backup_code}.cbk.enc"
        try:
            backup_dir = Path(tempfile.gettempdir()) / "collegebites_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            disk_path = backup_dir / f"{backup_code}.cbk.enc"
            disk_path.write_text(encrypted_token, encoding="utf-8")
            file_ref = str(disk_path)
        except OSError:
            pass

        rec = BackupRecord(
            backup_code=backup_code,
            trigger_type=trigger_type,
            storage_backend="database_encrypted",
            file_path=file_ref,
            size_bytes=len(encrypted_token.encode("ascii")),
            checksum_sha256=checksum,
            encryption_algo="fernet-aes128-hmac-sha256",
            is_encrypted=True,
            status="verified",
            integrity_verified=True,
            verified_at=now,
            row_counts_json=row_counts,
            payload_encrypted=encrypted_token,
            created_by_user_id=actor_user_id,
        )
        db.add(rec)
        db.flush()

        cfg.last_backup_at = now
        cfg.next_scheduled_at = now + timedelta(hours=cfg.frequency_hours)
        pruned = apply_retention_policy(db, cfg)

        record_audit_log(
            db,
            action="backup.created",
            entity_type="backup_record",
            entity_id=backup_code,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            details={"trigger": trigger_type, "size_bytes": rec.size_bytes, "checksum": checksum, "pruned": pruned},
        )
        db.commit()
        db.refresh(rec)
        return _serialize_backup_record(rec)

    except Exception as exc:
        err_rec = BackupRecord(
            backup_code=backup_code,
            trigger_type=trigger_type,
            storage_backend="database_encrypted",
            size_bytes=0,
            checksum_sha256="FAILED",
            is_encrypted=True,
            status="failed",
            integrity_verified=False,
            row_counts_json={},
            error_message=str(exc)[:1000],
            created_by_user_id=actor_user_id,
        )
        db.add(err_rec)
        security_service.create_security_alert(
            db,
            alert_type="backup_failed",
            severity="critical",
            title=f"Database backup failed ({backup_code})",
            description=f"Automated/manual backup execution failed: {exc}",
            metadata={"backup_code": backup_code, "trigger": trigger_type},
            dedupe_minutes=5,
        )
        db.commit()
        raise HTTPException(status_code=500, detail=f"Backup failed: {exc}") from exc


def _decrypt_and_validate_bundle(db: Session, rec: BackupRecord) -> dict[str, Any]:
    token_str = rec.payload_encrypted
    if not token_str and rec.file_path and os.path.exists(rec.file_path):
        token_str = Path(rec.file_path).read_text(encoding="utf-8")
    if not token_str:
        raise ValueError("Encrypted backup payload is missing")

    try:
        compressed = _derive_fernet().decrypt(token_str.encode("ascii"))
    except InvalidToken as exc:
        raise ValueError("Backup decryption failed (key mismatch or corrupted cipher payload)") from exc

    actual_checksum = hashlib.sha256(compressed).hexdigest()
    if actual_checksum != rec.checksum_sha256:
        raise ValueError(f"Checksum mismatch: expected {rec.checksum_sha256}, computed {actual_checksum}")

    raw_json = gzip.decompress(compressed)
    bundle = json.loads(raw_json.decode("utf-8"))
    if not isinstance(bundle, dict) or "tables" not in bundle or not isinstance(bundle["tables"], dict):
        raise ValueError("Malformed backup manifest structure")
    return bundle


def verify_backup_integrity(
    db: Session,
    backup_id: UUID,
    *,
    actor_user_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
) -> dict[str, Any]:
    rec = db.get(BackupRecord, backup_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Backup record not found")

    try:
        bundle = _decrypt_and_validate_bundle(db, rec)
        tables = bundle["tables"]
        # Ensure zero sensitive credentials escaped into user records
        for u_row in tables.get("users", []):
            if u_row.get("password_hash") is not None:
                raise ValueError("Sensitive user credential detected inside backup archive")
        now = datetime.now(timezone.utc)
        rec.integrity_verified = True
        rec.verified_at = now
        if rec.status == "completed":
            rec.status = "verified"
        record_audit_log(
            db,
            action="backup.verified",
            entity_type="backup_record",
            entity_id=rec.backup_code,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            details={"checksum": rec.checksum_sha256, "tables_count": len(tables)},
        )
        db.commit()
        return {
            "verified": True,
            "backup_id": str(rec.id),
            "backup_code": rec.backup_code,
            "checksum_sha256": rec.checksum_sha256,
            "tables_count": len(tables),
            "total_rows": sum(len(rows) for rows in tables.values()),
            "verified_at": rec.verified_at.isoformat() if rec.verified_at else None,
        }
    except Exception as exc:
        rec.integrity_verified = False
        security_service.create_security_alert(
            db,
            alert_type="backup_integrity_failed",
            severity="critical",
            title=f"Backup integrity verification failed ({rec.backup_code})",
            description=f"Checksum/decryption validation failed for backup {rec.backup_code}: {exc}",
            metadata={"backup_id": str(rec.id), "backup_code": rec.backup_code},
            dedupe_minutes=5,
        )
        db.commit()
        raise HTTPException(status_code=400, detail=f"Backup integrity check failed: {exc}") from exc


def restore_backup(
    db: Session,
    backup_id: UUID,
    *,
    dry_run: bool = True,
    confirmation_phrase: Optional[str] = None,
    target_engine: Optional[Engine] = None,
    target_schema: Optional[str] = None,
    actor_user_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
) -> dict[str, Any]:
    rec = db.get(BackupRecord, backup_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Backup record not found")

    started_at = datetime.now(timezone.utc)
    if not dry_run and target_engine is None and (confirmation_phrase or "").strip() != CONFIRM_RESTORE_PHRASE:
        raise HTTPException(
            status_code=400,
            detail=f'Live restore requires explicit confirmation phrase "{CONFIRM_RESTORE_PHRASE}". Run dry-run first.',
        )

    log = RecoveryLog(
        backup_id=rec.id,
        target_env=target_schema or ("dry_run_sandbox" if dry_run else "production_database"),
        dry_run=dry_run,
        status="running",
        started_at=started_at,
        authorized_by_user_id=actor_user_id,
    )
    db.add(log)
    db.flush()

    try:
        bundle = _decrypt_and_validate_bundle(db, rec)
        tables_data: dict[str, list[dict[str, Any]]] = bundle["tables"]

        # Validate schema compatibility for all non-empty tables before touching any destination DB
        restored_counts: dict[str, int] = {}
        ordered_present = [t.name for t in Base.metadata.sorted_tables if t.name in tables_data]
        for tbl_name in ordered_present:
            tbl = Base.metadata.tables[tbl_name]
            valid_cols = {c.name for c in tbl.columns}
            for r in tables_data[tbl_name]:
                unknown = set(r.keys()) - valid_cols
                if unknown:
                    raise ValueError(f"Schema mismatch in table {tbl_name}: unknown columns {sorted(unknown)}")
            restored_counts[tbl_name] = len(tables_data[tbl_name])

        if dry_run and target_engine is None:
            log.status = "completed"
            log.verification_passed = True
            log.restored_tables_json = restored_counts
            log.completed_at = datetime.now(timezone.utc)
            record_audit_log(
                db,
                action="backup.dry_run_tested",
                entity_type="backup_record",
                entity_id=rec.backup_code,
                actor_user_id=actor_user_id,
                ip_address=ip_address,
                details={"tables": len(ordered_present), "rows": sum(restored_counts.values())},
            )
            db.commit()
            return {
                "dry_run": True,
                "status": "completed",
                "verification_passed": True,
                "backup_code": rec.backup_code,
                "tables_restored": len(ordered_present),
                "total_rows": sum(restored_counts.values()),
                "row_counts": restored_counts,
            }

        # Execute transactional restore either against isolated drill target_engine/schema or live db engine
        dest_engine = target_engine or db.get_bind()
        if target_engine is None:
            # Take automatic pre-restore safety snapshot before altering live tables
            create_backup(db, trigger_type="pre_restore", actor_user_id=actor_user_id, ip_address=ip_address)

        with dest_engine.begin() as conn:
            if target_schema:
                conn.execute(text(f'SET LOCAL search_path TO "{target_schema}"'))

            # Delete children before parents
            for tbl in reversed(Base.metadata.sorted_tables):
                if tbl.name in ordered_present:
                    conn.execute(tbl.delete())

            # Re-insert parents before children
            for tbl in Base.metadata.sorted_tables:
                if tbl.name not in ordered_present:
                    continue
                raw_rows = tables_data[tbl.name]
                if not raw_rows:
                    continue
                cols_by_name = {c.name: c for c in tbl.columns}
                parsed_rows = [
                    {
                        cname: _deserialize_cell(cols_by_name[cname], val)
                        for cname, val in r.items()
                        if cname in cols_by_name
                    }
                    for r in raw_rows
                ]
                conn.execute(tbl.insert(), parsed_rows)

        log.status = "completed"
        log.verification_passed = True
        log.restored_tables_json = restored_counts
        log.completed_at = datetime.now(timezone.utc)
        if not dry_run and target_engine is None:
            rec.status = "restored"

        record_audit_log(
            db,
            action="backup.restored",
            entity_type="backup_record",
            entity_id=rec.backup_code,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            details={"dry_run": dry_run, "target_env": log.target_env, "total_rows": sum(restored_counts.values())},
        )
        db.commit()
        return {
            "dry_run": dry_run,
            "status": "completed",
            "verification_passed": True,
            "backup_code": rec.backup_code,
            "target_env": log.target_env,
            "tables_restored": len(ordered_present),
            "total_rows": sum(restored_counts.values()),
            "row_counts": restored_counts,
        }

    except HTTPException:
        raise
    except Exception as exc:
        log.status = "failed"
        log.verification_passed = False
        log.error_message = str(exc)[:1000]
        log.completed_at = datetime.now(timezone.utc)
        security_service.create_security_alert(
            db,
            alert_type="restore_failed",
            severity="critical",
            title=f"Disaster recovery restore failed ({rec.backup_code})",
            description=f"Restore attempt into {log.target_env} failed cleanly without corruption: {exc}",
            metadata={"backup_code": rec.backup_code, "dry_run": dry_run},
            dedupe_minutes=5,
        )
        db.commit()
        raise HTTPException(status_code=400, detail=f"Restore failed: {exc}") from exc


def run_scheduled_backup_if_due(db: Session, *, trigger: str = "cron") -> dict[str, Any]:
    cfg = get_or_create_backup_settings(db)
    db.flush()
    if not cfg.auto_backup_enabled:
        return {"ran": False, "reason": "auto_backup_disabled"}
    now = datetime.now(timezone.utc)
    next_at = cfg.next_scheduled_at
    if next_at and next_at.tzinfo is None:
        next_at = next_at.replace(tzinfo=timezone.utc)
    if cfg.last_backup_at is not None and next_at and next_at > now:
        return {"ran": False, "reason": "not_due_yet", "next_scheduled_at": next_at.isoformat()}
    created = create_backup(db, trigger_type=trigger)
    return {"ran": True, "backup_code": created["backup_code"], "size_bytes": created["size_bytes"]}


def list_backups(db: Session, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.scalars(select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(limit)).all()
    return [_serialize_backup_record(r) for r in rows]


def list_recovery_logs(db: Session, *, limit: int = 40) -> list[dict[str, Any]]:
    rows = db.scalars(select(RecoveryLog).order_by(RecoveryLog.created_at.desc()).limit(limit)).all()
    b_ids = {r.backup_id for r in rows}
    bmap = (
        {b.id: b.backup_code for b in db.scalars(select(BackupRecord).where(BackupRecord.id.in_(b_ids))).all()}
        if b_ids
        else {}
    )
    return [
        {
            "id": str(r.id),
            "backup_id": str(r.backup_id),
            "backup_code": bmap.get(r.backup_id),
            "target_env": r.target_env,
            "dry_run": r.dry_run,
            "status": r.status,
            "verification_passed": r.verification_passed,
            "tables_count": len(r.restored_tables_json or {}),
            "total_rows": sum(int(v) for v in (r.restored_tables_json or {}).values()),
            "error_message": r.error_message,
            "started_at": r.started_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]


def get_backup_dashboard(db: Session) -> dict[str, Any]:
    cfg = get_or_create_backup_settings(db)
    db.commit()
    backups = list_backups(db, limit=30)
    logs = list_recovery_logs(db, limit=20)
    verified = [b for b in backups if b["integrity_verified"]]
    failed = [b for b in backups if b["status"] == "failed"]
    return {
        "settings": _serialize_settings(cfg),
        "total_backups": len(backups),
        "verified_backups": len(verified),
        "failed_backups": len(failed),
        "latest_verified": verified[0] if verified else None,
        "backups": backups,
        "recovery_logs": logs,
    }


def get_encrypted_backup_blob(db: Session, backup_id: UUID) -> tuple[str, str, str]:
    rec = db.get(BackupRecord, backup_id)
    if not rec or not rec.payload_encrypted:
        raise HTTPException(status_code=404, detail="Encrypted backup payload not found")
    return rec.backup_code, rec.checksum_sha256, rec.payload_encrypted
