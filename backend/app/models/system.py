import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TimestampMixin, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor_role: Mapped[Optional[str]] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    details: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


class ActivityLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "activity_logs"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"))
    activity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


class DailySalesSummary(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "daily_sales_summaries"
    __table_args__ = (UniqueConstraint("canteen_id", "summary_date", name="uq_daily_sales_canteen_date"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    summary_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_sales: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    tax_collected: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    net_sales: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    breakdown_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


class SystemEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "system_events"

    event_source: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="info")
    event_code: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


class LoginAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_ident_time", "identifier", "created_at"),
        Index("ix_login_attempts_ip_success_time", "ip_address", "success", "created_at"),
    )

    identifier: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255))


class SecurityAlert(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "security_alerts"
    __table_args__ = (
        Index("ix_security_alerts_type_status", "alert_type", "status"),
    )

    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    resolved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)


class BackupRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "backup_records"

    backup_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="database_encrypted")
    file_path: Mapped[Optional[str]] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum_sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    encryption_algo: Mapped[str] = mapped_column(String(64), nullable=False, default="fernet-aes128-hmac-sha256")
    is_encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed", index=True)
    integrity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    row_counts_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    payload_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class BackupSetting(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "backup_settings"

    singleton_key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, default="default")
    auto_backup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    frequency_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_backups: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="database_encrypted")
    last_backup_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class RecoveryLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recovery_logs"

    backup_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("backup_records.id", ondelete="CASCADE"), nullable=False, index=True)
    target_env: Mapped[str] = mapped_column(String(64), nullable=False, default="dry_run_sandbox")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    restored_tables_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    verification_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    authorized_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
