from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.college import Canteen
from app.models.order import Order
from app.models.payment import PickupToken, QRVerificationEvent
from app.models.system import AuditLog, LoginAttempt, SecurityAlert, SystemEvent
from app.services.audit_service import record_audit_log

MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
IP_BRUTE_THRESHOLD = 6


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _find_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    ident = identifier.strip()
    return db.scalar(select(User).where(or_(User.email == ident.lower(), User.phone == ident)))


def create_security_alert(
    db: Session,
    *,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    canteen_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    order_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    dedupe_minutes: int = 30,
) -> SecurityAlert:
    now = datetime.now(timezone.utc)
    if dedupe_minutes > 0:
        since = now - timedelta(minutes=dedupe_minutes)
        stmt = select(SecurityAlert).where(
            SecurityAlert.alert_type == alert_type,
            SecurityAlert.status == "open",
            SecurityAlert.created_at >= since,
        )
        if user_id is not None:
            stmt = stmt.where(SecurityAlert.user_id == user_id)
        if order_id is not None:
            stmt = stmt.where(SecurityAlert.order_id == order_id)
        if user_id is None and order_id is None and ip_address:
            stmt = stmt.where(SecurityAlert.ip_address == ip_address)
        existing = db.scalar(stmt.order_by(SecurityAlert.created_at.desc()))
        if existing:
            meta = dict(existing.metadata_json or {})
            meta["occurrences"] = int(meta.get("occurrences", 1)) + 1
            meta["last_seen_at"] = now.isoformat()
            if metadata:
                meta["latest_event"] = metadata
            existing.metadata_json = meta
            if severity == "critical" or (severity == "high" and existing.severity == "medium"):
                existing.severity = severity
            return existing

    alert = SecurityAlert(
        alert_type=alert_type,
        severity=severity,
        status="open",
        canteen_id=canteen_id,
        user_id=user_id,
        order_id=order_id,
        ip_address=ip_address,
        title=title[:200],
        description=description,
        metadata_json={"occurrences": 1, **(metadata or {})},
    )
    db.add(alert)
    db.add(
        SystemEvent(
            event_source="security_monitor",
            severity=severity,
            event_code=alert_type,
            message=title[:255],
            payload={
                "canteen_id": str(canteen_id) if canteen_id else None,
                "user_id": str(user_id) if user_id else None,
                "order_id": str(order_id) if order_id else None,
                "ip_address": ip_address,
                **(metadata or {}),
            },
        )
    )
    return alert


def assert_login_allowed(
    db: Session,
    identifier: str,
    *,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    user = _find_user_by_identifier(db, identifier)
    if not user:
        return
    locked_until = _as_utc(user.locked_until)
    now = datetime.now(timezone.utc)
    if locked_until and locked_until > now:
        remaining_secs = int((locked_until - now).total_seconds())
        remaining_mins = max(1, (remaining_secs + 59) // 60)
        db.add(
            LoginAttempt(
                identifier=identifier.strip().lower()[:160],
                user_id=user.id,
                ip_address=ip_address,
                user_agent=(user_agent or "")[:255] or None,
                success=False,
                failure_reason="account_locked",
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account temporarily locked after repeated failed login attempts. Try again in {remaining_mins} minute(s) or ask an admin to unlock.",
        )
    if locked_until and locked_until <= now:
        user.locked_until = None
        user.failed_login_attempts = 0
        db.commit()


def record_login_failure(
    db: Session,
    identifier: str,
    *,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    reason: str = "Invalid credentials",
) -> None:
    now = datetime.now(timezone.utc)
    ident_norm = identifier.strip().lower()[:160]
    user = _find_user_by_identifier(db, identifier)

    db.add(
        LoginAttempt(
            identifier=ident_norm,
            user_id=user.id if user else None,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:255] or None,
            success=False,
            failure_reason=reason[:255],
        )
    )

    if user:
        # Reset stale failure streak if previous failure was >30m ago and not locked
        last_fail = _as_utc(user.last_failed_login_at)
        if last_fail and (now - last_fail) > timedelta(minutes=30):
            user.failed_login_attempts = 0
        user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
        user.last_failed_login_at = now
        if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            create_security_alert(
                db,
                alert_type="brute_force_attempt",
                severity="high",
                title=f"Account locked after {user.failed_login_attempts} failed logins",
                description=(
                    f"Account {user.email or user.phone} was temporarily locked for {LOCKOUT_MINUTES} minutes "
                    f"after {user.failed_login_attempts} consecutive failed authentication attempts."
                ),
                user_id=user.id,
                ip_address=ip_address,
                metadata={"identifier": ident_norm, "failed_attempts": user.failed_login_attempts},
            )
            record_audit_log(
                db,
                action="security.account_locked",
                entity_type="user",
                entity_id=str(user.id),
                actor_user_id=user.id,
                ip_address=ip_address,
                details={"failed_attempts": user.failed_login_attempts, "lockout_minutes": LOCKOUT_MINUTES},
            )

    if ip_address:
        since = now - timedelta(minutes=10)
        recent_ip_fails = db.scalar(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.success.is_(False),
                LoginAttempt.created_at >= since,
            )
        ) or 0
        if recent_ip_fails + 1 >= IP_BRUTE_THRESHOLD:
            create_security_alert(
                db,
                alert_type="brute_force_attempt",
                severity="high",
                title=f"Repeated failed logins detected from IP {ip_address}",
                description=f"{recent_ip_fails + 1} failed login attempts originated from IP {ip_address} within 10 minutes.",
                ip_address=ip_address,
                metadata={"identifier": ident_norm, "recent_ip_failures": int(recent_ip_fails) + 1},
            )

    db.commit()


def record_login_success(
    db: Session,
    user_id: UUID,
    identifier: str,
    *,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    user = db.get(User, user_id)
    prev_ip: Optional[str] = None
    if ip_address:
        prev_ip = db.scalar(
            select(LoginAttempt.ip_address)
            .where(LoginAttempt.user_id == user_id, LoginAttempt.success.is_(True), LoginAttempt.ip_address.is_not(None))
            .order_by(LoginAttempt.created_at.desc())
        )
    if user:
        user.failed_login_attempts = 0
        user.locked_until = None
    db.add(
        LoginAttempt(
            identifier=identifier.strip().lower()[:160],
            user_id=user_id,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:255] or None,
            success=True,
            failure_reason=None,
        )
    )
    if prev_ip and ip_address and prev_ip != ip_address:
        record_audit_log(
            db,
            action="user.login_new_ip",
            entity_type="user",
            entity_id=str(user_id),
            actor_user_id=user_id,
            ip_address=ip_address,
            details={"previous_ip": prev_ip, "new_ip": ip_address},
        )
    db.commit()


def unlock_user_account(
    db: Session,
    target_user_id: UUID,
    *,
    actor_user_id: UUID,
    ip_address: Optional[str] = None,
) -> User:
    user = db.get(User, target_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.failed_login_attempts = 0
    user.locked_until = None
    record_audit_log(
        db,
        action="security.user_unlocked",
        entity_type="user",
        entity_id=str(user.id),
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        details={"email": user.email},
    )
    db.commit()
    db.refresh(user)
    return user


def record_qr_fraud_if_applicable(
    db: Session,
    *,
    order: Optional[Order],
    canteen_id: Optional[UUID],
    staff_user_id: UUID,
    method: str,
    presented: Optional[str],
    result_code: str,
) -> None:
    masked = (presented[:12] + "...") if presented and len(presented) > 12 else presented
    eff_canteen = order.canteen_id if order else canteen_id
    if result_code == "ALREADY_COLLECTED":
        create_security_alert(
            db,
            alert_type="duplicate_handover_attempt",
            severity="high",
            title=f"Duplicate pickup attempt rejected ({order.order_number if order else masked or 'QR'})",
            description=(
                f"Staff {staff_user_id} scanned/submitted an already-collected order "
                f"({order.order_number if order else masked}). Duplicate handover blocked."
            ),
            canteen_id=eff_canteen,
            order_id=order.id if order else None,
            metadata={"method": method, "presented": masked, "staff_user_id": str(staff_user_id), "result_code": result_code},
            dedupe_minutes=5,
        )
    elif result_code == "INVALID_QR" and method == "qr_scan":
        create_security_alert(
            db,
            alert_type="qr_tamper_attempt",
            severity="medium",
            title="Invalid or tampered QR code scanned at pickup",
            description=f"Signed QR verification failed for presented token ({masked or 'empty'}) at counter.",
            canteen_id=eff_canteen,
            order_id=order.id if order else None,
            metadata={"method": method, "presented": masked, "staff_user_id": str(staff_user_id), "result_code": result_code},
            dedupe_minutes=10,
        )


def list_security_dashboard(db: Session, *, canteen_id: Optional[UUID] = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    alert_base = select(SecurityAlert)
    qr_base = select(QRVerificationEvent)
    if canteen_id is not None:
        alert_base = alert_base.where(SecurityAlert.canteen_id == canteen_id)
        qr_base = qr_base.where(QRVerificationEvent.canteen_id == canteen_id)

    open_alerts = db.scalar(
        select(func.count(SecurityAlert.id)).where(
            SecurityAlert.status == "open",
            *([SecurityAlert.canteen_id == canteen_id] if canteen_id is not None else []),
        )
    ) or 0
    high_critical_alerts = db.scalar(
        select(func.count(SecurityAlert.id)).where(
            SecurityAlert.status == "open",
            SecurityAlert.severity.in_(("high", "critical")),
            *([SecurityAlert.canteen_id == canteen_id] if canteen_id is not None else []),
        )
    ) or 0

    failed_logins_24h = (
        0
        if canteen_id is not None
        else (
            db.scalar(
                select(func.count(LoginAttempt.id)).where(
                    LoginAttempt.success.is_(False),
                    LoginAttempt.created_at >= since_24h,
                )
            )
            or 0
        )
    )
    successful_logins_24h = (
        0
        if canteen_id is not None
        else (
            db.scalar(
                select(func.count(LoginAttempt.id)).where(
                    LoginAttempt.success.is_(True),
                    LoginAttempt.created_at >= since_24h,
                )
            )
            or 0
        )
    )
    invalid_qr_24h = db.scalar(
        select(func.count(QRVerificationEvent.id)).where(
            QRVerificationEvent.is_valid.is_(False),
            QRVerificationEvent.created_at >= since_24h,
            *([QRVerificationEvent.canteen_id == canteen_id] if canteen_id is not None else []),
        )
    ) or 0
    duplicate_handover_24h = db.scalar(
        select(func.count(QRVerificationEvent.id)).where(
            QRVerificationEvent.result_code == "ALREADY_COLLECTED",
            QRVerificationEvent.created_at >= since_24h,
            *([QRVerificationEvent.canteen_id == canteen_id] if canteen_id is not None else []),
        )
    ) or 0
    webhook_failures_24h = (
        0
        if canteen_id is not None
        else (
            db.scalar(
                select(func.count(SecurityAlert.id)).where(
                    SecurityAlert.alert_type == "webhook_signature_invalid",
                    SecurityAlert.created_at >= since_24h,
                )
            )
            or 0
        )
    )

    locked_users = []
    if canteen_id is None:
        rows = db.scalars(
            select(User)
            .where(User.locked_until.is_not(None), User.locked_until > now)
            .order_by(User.locked_until.desc())
        ).all()
        locked_users = [
            {
                "id": str(u.id),
                "email": u.email,
                "phone": u.phone,
                "full_name": u.full_name,
                "failed_login_attempts": u.failed_login_attempts,
                "locked_until": u.locked_until.isoformat() if u.locked_until else None,
            }
            for u in rows
        ]

    return {
        "open_alerts": int(open_alerts),
        "high_critical_alerts": int(high_critical_alerts),
        "failed_logins_24h": int(failed_logins_24h),
        "successful_logins_24h": int(successful_logins_24h),
        "invalid_qr_24h": int(invalid_qr_24h),
        "duplicate_handover_24h": int(duplicate_handover_24h),
        "webhook_failures_24h": int(webhook_failures_24h),
        "locked_accounts_count": len(locked_users),
        "locked_accounts": locked_users,
    }


def list_security_alerts(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    severity: Optional[str] = None,
    alert_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = select(SecurityAlert).order_by(SecurityAlert.created_at.desc()).offset(offset).limit(limit)
    if canteen_id is not None:
        stmt = stmt.where(SecurityAlert.canteen_id == canteen_id)
    if status_filter:
        stmt = stmt.where(SecurityAlert.status == status_filter)
    if severity:
        stmt = stmt.where(SecurityAlert.severity == severity)
    if alert_type:
        stmt = stmt.where(SecurityAlert.alert_type == alert_type)
    rows = db.scalars(stmt).all()
    canteen_ids = {r.canteen_id for r in rows if r.canteen_id}
    cmap = (
        {c.id: c.name for c in db.scalars(select(Canteen).where(Canteen.id.in_(canteen_ids))).all()}
        if canteen_ids
        else {}
    )
    return [
        {
            "id": str(r.id),
            "alert_type": r.alert_type,
            "severity": r.severity,
            "status": r.status,
            "canteen_id": str(r.canteen_id) if r.canteen_id else None,
            "canteen_name": cmap.get(r.canteen_id) if r.canteen_id else None,
            "user_id": str(r.user_id) if r.user_id else None,
            "order_id": str(r.order_id) if r.order_id else None,
            "ip_address": r.ip_address,
            "title": r.title,
            "description": r.description,
            "metadata": r.metadata_json or {},
            "resolved_by_user_id": str(r.resolved_by_user_id) if r.resolved_by_user_id else None,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            "resolution_notes": r.resolution_notes,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


def resolve_security_alert(
    db: Session,
    alert_id: UUID,
    *,
    status_value: str,
    notes: Optional[str],
    actor_user_id: UUID,
    scoped_canteen_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
) -> dict[str, Any]:
    if status_value not in ("acknowledged", "resolved", "dismissed"):
        raise HTTPException(status_code=400, detail="Status must be acknowledged, resolved, or dismissed")
    alert = db.get(SecurityAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Security alert not found")
    if scoped_canteen_id is not None and alert.canteen_id != scoped_canteen_id:
        raise HTTPException(status_code=403, detail="Not authorized to resolve alerts outside assigned canteen")

    now = datetime.now(timezone.utc)
    alert.status = status_value
    alert.resolved_by_user_id = actor_user_id
    alert.resolved_at = now
    alert.resolution_notes = (notes or "").strip() or None
    record_audit_log(
        db,
        action="security.alert_updated",
        entity_type="security_alert",
        entity_id=str(alert.id),
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        details={"status": status_value, "notes": alert.resolution_notes},
    )
    db.commit()
    return list_security_alerts(db, limit=1, canteen_id=alert.canteen_id)[0] if False else {
        "id": str(alert.id),
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "status": alert.status,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "resolution_notes": alert.resolution_notes,
    }


def list_login_attempts(
    db: Session,
    *,
    identifier: Optional[str] = None,
    success: Optional[bool] = None,
    ip_address: Optional[str] = None,
    limit: int = 60,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = select(LoginAttempt).order_by(LoginAttempt.created_at.desc()).offset(offset).limit(limit)
    if identifier:
        stmt = stmt.where(LoginAttempt.identifier.ilike(f"%{identifier.strip()}%"))
    if success is not None:
        stmt = stmt.where(LoginAttempt.success.is_(success))
    if ip_address:
        stmt = stmt.where(LoginAttempt.ip_address.ilike(f"%{ip_address.strip()}%"))
    rows = db.scalars(stmt).all()
    return [
        {
            "id": str(r.id),
            "identifier": r.identifier,
            "user_id": str(r.user_id) if r.user_id else None,
            "ip_address": r.ip_address,
            "user_agent": r.user_agent,
            "success": r.success,
            "failure_reason": r.failure_reason,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


def list_qr_verification_events(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    is_valid: Optional[bool] = None,
    result_code: Optional[str] = None,
    limit: int = 60,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = select(QRVerificationEvent).order_by(QRVerificationEvent.created_at.desc()).offset(offset).limit(limit)
    if canteen_id is not None:
        stmt = stmt.where(QRVerificationEvent.canteen_id == canteen_id)
    if is_valid is not None:
        stmt = stmt.where(QRVerificationEvent.is_valid.is_(is_valid))
    if result_code:
        stmt = stmt.where(QRVerificationEvent.result_code == result_code)
    rows = db.scalars(stmt).all()
    order_ids = {r.order_id for r in rows if r.order_id}
    omap = (
        {o.id: o.order_number for o in db.scalars(select(Order).where(Order.id.in_(order_ids))).all()}
        if order_ids
        else {}
    )
    tok_ids = {r.pickup_token_id for r in rows if r.pickup_token_id}
    tmap = (
        {t.id: t.token_code for t in db.scalars(select(PickupToken).where(PickupToken.id.in_(tok_ids))).all()}
        if tok_ids
        else {}
    )
    staff_ids = {r.staff_user_id for r in rows if r.staff_user_id}
    umap = (
        {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(staff_ids))).all()}
        if staff_ids
        else {}
    )
    return [
        {
            "id": str(r.id),
            "order_id": str(r.order_id) if r.order_id else None,
            "order_number": omap.get(r.order_id) if r.order_id else None,
            "pickup_token_code": tmap.get(r.pickup_token_id) if r.pickup_token_id else None,
            "staff_name": umap.get(r.staff_user_id) if r.staff_user_id else None,
            "canteen_id": str(r.canteen_id) if r.canteen_id else None,
            "verification_method": r.verification_method,
            "presented_code_masked": r.presented_code_masked,
            "result_code": r.result_code,
            "is_valid": r.is_valid,
            "details": r.details,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


def search_audit_logs(
    db: Session,
    *,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    ip_address: Optional[str] = None,
    search: Optional[str] = None,
    actor_user_id: Optional[UUID] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 60,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action.strip()}%"))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type.strip())
    if ip_address:
        stmt = stmt.where(AuditLog.ip_address.ilike(f"%{ip_address.strip()}%"))
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(or_(AuditLog.action.ilike(q), AuditLog.entity_id.ilike(q), AuditLog.entity_type.ilike(q)))
    if start_date:
        try:
            s_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            stmt = stmt.where(AuditLog.created_at >= s_dt)
        except ValueError:
            pass
    if end_date:
        try:
            e_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
            stmt = stmt.where(AuditLog.created_at < e_dt)
        except ValueError:
            pass

    rows = db.scalars(stmt).all()
    actor_ids = {r.actor_user_id for r in rows if r.actor_user_id}
    umap = (
        {u.id: (u.email or u.full_name) for u in db.scalars(select(User).where(User.id.in_(actor_ids))).all()}
        if actor_ids
        else {}
    )
    return [
        {
            "id": str(r.id),
            "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
            "actor_label": umap.get(r.actor_user_id) if r.actor_user_id else "system",
            "actor_role": r.actor_role,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "ip_address": r.ip_address,
            "details": r.details or {},
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
