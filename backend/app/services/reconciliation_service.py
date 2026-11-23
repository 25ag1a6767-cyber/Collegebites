from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.integrations.razorpay_client import razorpay_gateway
from app.integrations.stripe_client import stripe_gateway
from app.models.college import Canteen
from app.models.order import Order
from app.models.payment import (
    Payment,
    PaymentReconciliation,
    PaymentTransaction,
    PaymentWebhookEvent,
    ReconciliationRun,
)
from app.services import security_service
from app.services.audit_service import record_audit_log


def _upsert_reconciliation(
    db: Session,
    *,
    payment: Payment,
    order: Order,
    batch_id: UUID,
    settled_amount: Decimal,
    status: str,
    discrepancy_type: str,
    gateway_fee: Decimal = Decimal("0.00"),
    tax_on_fee: Decimal = Decimal("0.00"),
    gateway_settlement_id: Optional[str] = None,
    notes: Optional[str] = None,
    actor_user_id: Optional[UUID] = None,
) -> PaymentReconciliation:
    now = datetime.now(timezone.utc)
    expected = (order.total_amount if payment.status == "CONFIRMED" else payment.amount).quantize(Decimal("0.01"))
    discrepancy = (expected - settled_amount).quantize(Decimal("0.01")) if status in ("matched", "discrepancy") else Decimal("0.00")

    rec = db.scalar(select(PaymentReconciliation).where(PaymentReconciliation.payment_id == payment.id))
    if rec:
        # Never auto-overwrite manually resolved matches unless amount changed
        rec.batch_id = batch_id
        rec.gateway_provider = payment.provider
        rec.gateway_reference = payment.payment_reference or payment.provider_order_id
        if gateway_settlement_id:
            rec.gateway_settlement_id = gateway_settlement_id
        rec.expected_amount = expected
        rec.settled_amount = settled_amount
        rec.discrepancy_amount = discrepancy
        rec.gateway_fee = gateway_fee
        rec.tax_on_fee = tax_on_fee
        rec.status = status
        rec.reconciliation_source = "auto_gateway"
        rec.discrepancy_type = discrepancy_type
        rec.reconciled_at = now
        if actor_user_id:
            rec.reconciled_by_user_id = actor_user_id
        if notes:
            rec.notes = notes
        return rec

    rec = PaymentReconciliation(
        payment_id=payment.id,
        order_id=order.id,
        batch_id=batch_id,
        gateway_provider=payment.provider,
        gateway_settlement_id=gateway_settlement_id,
        gateway_reference=payment.payment_reference or payment.provider_order_id,
        expected_amount=expected,
        settled_amount=settled_amount,
        discrepancy_amount=discrepancy,
        gateway_fee=gateway_fee,
        tax_on_fee=tax_on_fee,
        status=status,
        reconciliation_source="auto_gateway",
        discrepancy_type=discrepancy_type,
        reconciled_at=now,
        reconciled_by_user_id=actor_user_id,
        notes=notes,
    )
    db.add(rec)
    return rec


def run_auto_reconciliation(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    trigger: str = "manual",
    actor_user_id: Optional[UUID] = None,
    fetch_gateway: bool = False,
    ip_address: Optional[str] = None,
) -> dict[str, Any]:
    """
    Compare Orders, Payments, PaymentTransactions, Webhooks (and optional live gateway API fetches)
    to classify matched payments, pending stale payments, failed transactions, and discrepancies.
    Strictly adheres to NO REFUNDS policy (never modifies historical paid totals or triggers refunds).
    """
    now = datetime.now(timezone.utc)
    run = ReconciliationRun(
        trigger=trigger,
        canteen_id=canteen_id,
        started_at=now,
        run_by_user_id=actor_user_id,
    )
    db.add(run)
    db.flush()

    stmt = (
        select(Payment, Order)
        .join(Order, Order.id == Payment.order_id)
        .order_by(Payment.created_at.desc())
        .limit(1000)
    )
    if canteen_id is not None:
        stmt = stmt.where(Order.canteen_id == canteen_id)

    rows = db.execute(stmt).all()
    payment_ids = [p.id for p, _ in rows]
    tx_rows = (
        db.scalars(
            select(PaymentTransaction)
            .where(PaymentTransaction.payment_id.in_(payment_ids))
            .order_by(PaymentTransaction.created_at.desc())
        ).all()
        if payment_ids
        else []
    )
    tx_by_payment: dict[UUID, list[PaymentTransaction]] = {}
    for tx in tx_rows:
        tx_by_payment.setdefault(tx.payment_id, []).append(tx)

    matched = 0
    discrepancy = 0
    pending = 0
    failed = 0
    verified_total = Decimal("0.00")
    flagged_discrepancies: list[dict[str, Any]] = []

    for payment, order in rows:
        txs = tx_by_payment.get(payment.id, [])
        fee = Decimal("0.00")
        tax = Decimal("0.00")
        settlement_id = None
        settled_amount = Decimal("0.00")

        disc_txs = [t for t in txs if t.status == "DISCREPANCY"]
        late_conflicts = [t for t in txs if t.status == "CONFLICT" or t.transaction_type == "late_capture_conflict"]

        # 1. Explicit transaction discrepancy (e.g., underpaid webhook or currency mismatch)
        if disc_txs:
            discrepancy += 1
            settled_val = disc_txs[0].amount
            _upsert_reconciliation(
                db,
                payment=payment,
                order=order,
                batch_id=run.id,
                settled_amount=settled_val,
                status="discrepancy",
                discrepancy_type="amount_mismatch",
                notes=f"Gateway discrepancy logged: paid ₹{settled_val} vs order ₹{order.total_amount}",
                actor_user_id=actor_user_id,
            )
            flagged_discrepancies.append({"order_number": order.order_number, "type": "amount_mismatch"})
            continue

        # 2. Order confirmed vs Payment missing confirmation
        if order.payment_status == "CONFIRMED" and payment.status != "CONFIRMED":
            discrepancy += 1
            _upsert_reconciliation(
                db,
                payment=payment,
                order=order,
                batch_id=run.id,
                settled_amount=Decimal("0.00"),
                status="discrepancy",
                discrepancy_type="missing_payment",
                notes="Order marked confirmed but payment record is not CONFIRMED",
                actor_user_id=actor_user_id,
            )
            flagged_discrepancies.append({"order_number": order.order_number, "type": "missing_payment"})
            continue

        # 3. Failed payment
        if payment.status == "FAILED":
            failed += 1
            _upsert_reconciliation(
                db,
                payment=payment,
                order=order,
                batch_id=run.id,
                settled_amount=Decimal("0.00"),
                status="failed",
                discrepancy_type="failed",
                notes=payment.failure_reason or "Payment failed at gateway",
                actor_user_id=actor_user_id,
            )
            continue

        # 4. Pending payment (flag stale > 30m)
        if payment.status == "PENDING":
            pending += 1
            created = payment.created_at.replace(tzinfo=timezone.utc) if payment.created_at.tzinfo is None else payment.created_at
            is_stale = (now - created) > timedelta(minutes=30)
            _upsert_reconciliation(
                db,
                payment=payment,
                order=order,
                batch_id=run.id,
                settled_amount=Decimal("0.00"),
                status="pending",
                discrepancy_type="pending_stale" if is_stale else "none",
                notes="Awaiting gateway confirmation (>30m stale)" if is_stale else "Pending live checkout",
                actor_user_id=actor_user_id,
            )
            continue

        # 5. Confirmed payment validation against order total, transactions, and optional live gateway
        capture_tx = next((t for t in txs if t.status == "CONFIRMED"), None)
        settled_amount = capture_tx.amount if capture_tx else payment.amount

        if fetch_gateway:
            if payment.provider == "razorpay" and razorpay_gateway.use_live_api and payment.provider_payment_id:
                gw_pay = razorpay_gateway.fetch_payment(payment.provider_payment_id)
                if gw_pay and gw_pay.get("amount") is not None:
                    settled_amount = (Decimal(int(gw_pay["amount"])) / Decimal("100")).quantize(Decimal("0.01"))
                    fee = (Decimal(int(gw_pay.get("fee") or 0)) / Decimal("100")).quantize(Decimal("0.01"))
                    tax = (Decimal(int(gw_pay.get("tax") or 0)) / Decimal("100")).quantize(Decimal("0.01"))
                    settlement_id = gw_pay.get("acquirer_data", {}).get("rrn") or gw_pay.get("settlement_id")
            elif payment.provider == "stripe" and stripe_gateway.use_live_api and payment.provider_payment_id:
                gw_pi = stripe_gateway.fetch_payment_intent_safe(payment.provider_payment_id)
                if gw_pi and gw_pi.get("amount_received") is not None:
                    settled_amount = (Decimal(int(gw_pi["amount_received"])) / Decimal("100")).quantize(Decimal("0.01"))

        if disc_txs or (settled_amount - order.total_amount).quantize(Decimal("0.01")) != Decimal("0.00"):
            discrepancy += 1
            _upsert_reconciliation(
                db,
                payment=payment,
                order=order,
                batch_id=run.id,
                settled_amount=settled_amount,
                status="discrepancy",
                discrepancy_type="amount_mismatch",
                gateway_fee=fee,
                tax_on_fee=tax,
                gateway_settlement_id=settlement_id,
                notes=f"Settled ₹{settled_amount} vs Order ₹{order.total_amount}",
                actor_user_id=actor_user_id,
            )
            flagged_discrepancies.append({"order_number": order.order_number, "type": "amount_mismatch"})
            security_service.create_security_alert(
                db,
                alert_type="reconciliation_discrepancy",
                severity="high",
                title=f"Reconciliation amount mismatch on {order.order_number}",
                description=f"Order expected ₹{order.total_amount} but gateway/capture recorded ₹{settled_amount}. Review manually (no-refund ledger policy).",
                canteen_id=order.canteen_id,
                order_id=order.id,
                metadata={"payment_id": str(payment.id), "settled": str(settled_amount), "expected": str(order.total_amount)},
            )
        elif order.status in ("CANCELLED", "REJECTED", "PAYMENT_FAILED") or late_conflicts:
            discrepancy += 1
            _upsert_reconciliation(
                db,
                payment=payment,
                order=order,
                batch_id=run.id,
                settled_amount=settled_amount,
                status="discrepancy",
                discrepancy_type="duplicate_callback",
                gateway_fee=fee,
                tax_on_fee=tax,
                gateway_settlement_id=settlement_id,
                notes=f"Confirmed capture on {order.status} order (retained per no-refund policy)",
                actor_user_id=actor_user_id,
            )
            flagged_discrepancies.append({"order_number": order.order_number, "type": "duplicate_callback"})
        else:
            matched += 1
            verified_total += settled_amount
            _upsert_reconciliation(
                db,
                payment=payment,
                order=order,
                batch_id=run.id,
                settled_amount=settled_amount,
                status="matched",
                discrepancy_type="none",
                gateway_fee=fee,
                tax_on_fee=tax,
                gateway_settlement_id=settlement_id,
                notes="Auto-verified against gateway & order ledger",
                actor_user_id=actor_user_id,
            )

    # Check orphan webhook capture callbacks (where no Payment row matched any provider_order_id)
    orphan_webhooks = 0
    if canteen_id is None:
        wh_rows = db.scalars(
            select(PaymentWebhookEvent)
            .where(
                PaymentWebhookEvent.signature_verified.is_(True),
                PaymentWebhookEvent.event_type.in_(("payment.captured", "order.paid", "payment_intent.succeeded", "checkout.session.completed")),
            )
            .order_by(PaymentWebhookEvent.created_at.desc())
            .limit(200)
        ).all()
        known_refs = {p.provider_order_id for p, _ in rows if p.provider_order_id} | {
            p.provider_payment_id for p, _ in rows if p.provider_payment_id
        }
        for wh in wh_rows:
            pl = wh.payload or {}
            ref_id = None
            if wh.provider == "razorpay":
                ent = pl.get("payload", {}).get("payment", {}).get("entity", {})
                ref_id = ent.get("order_id") or ent.get("id")
            else:
                obj = pl.get("data", {}).get("object", {})
                ref_id = obj.get("id") or obj.get("payment_intent")
            if ref_id and ref_id not in known_refs:
                orphan_webhooks += 1

    run.completed_at = datetime.now(timezone.utc)
    run.total_checked = len(rows)
    run.matched_count = matched
    run.discrepancy_count = discrepancy
    run.pending_count = pending
    run.failed_count = failed
    run.total_verified_amount = verified_total.quantize(Decimal("0.01"))
    run.summary_json = {
        "orphan_webhooks": orphan_webhooks,
        "discrepancies": flagged_discrepancies[:25],
    }

    record_audit_log(
        db,
        action="payment.reconciliation_run",
        entity_type="reconciliation_run",
        entity_id=str(run.id),
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        details={
            "trigger": trigger,
            "total_checked": run.total_checked,
            "matched": matched,
            "discrepancy": discrepancy,
            "pending": pending,
            "failed": failed,
        },
    )
    db.commit()
    return {
        "run_id": str(run.id),
        "trigger": run.trigger,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "total_checked": run.total_checked,
        "matched_count": run.matched_count,
        "discrepancy_count": run.discrepancy_count,
        "pending_count": run.pending_count,
        "failed_count": run.failed_count,
        "total_verified_amount": float(run.total_verified_amount),
        "orphan_webhooks": orphan_webhooks,
        "flagged_discrepancies": flagged_discrepancies[:25],
    }


def get_reconciliation_dashboard(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    days: int = 30,
) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    base = (
        select(Payment, Order, PaymentReconciliation)
        .join(Order, Order.id == Payment.order_id)
        .outerjoin(PaymentReconciliation, PaymentReconciliation.payment_id == Payment.id)
        .where(Payment.created_at >= since)
    )
    if canteen_id is not None:
        base = base.where(Order.canteen_id == canteen_id)

    rows = db.execute(base.order_by(Payment.created_at.desc())).all()
    total_attempts = len(rows)
    confirmed_count = 0
    failed_count = 0
    pending_count = 0
    matched_count = 0
    discrepancy_count = 0
    verified_amount = Decimal("0.00")
    discrepancy_amount = Decimal("0.00")

    gateway_breakdown: dict[str, dict[str, Any]] = {}
    daily_totals: dict[str, dict[str, Any]] = {}

    for payment, order, rec in rows:
        day_key = payment.created_at.date().isoformat()
        d_bucket = daily_totals.setdefault(day_key, {"date": day_key, "confirmed_amount": 0.0, "attempts": 0, "discrepancies": 0})
        d_bucket["attempts"] += 1

        gw = gateway_breakdown.setdefault(
            payment.provider,
            {"provider": payment.provider, "total": 0, "confirmed": 0, "failed": 0, "pending": 0, "amount_inr": 0.0},
        )
        gw["total"] += 1

        if payment.status == "CONFIRMED":
            confirmed_count += 1
            verified_amount += payment.amount
            gw["confirmed"] += 1
            gw["amount_inr"] += float(payment.amount)
            d_bucket["confirmed_amount"] += float(payment.amount)
        elif payment.status == "FAILED":
            failed_count += 1
            gw["failed"] += 1
        else:
            pending_count += 1
            gw["pending"] += 1

        if rec:
            if rec.status == "matched":
                matched_count += 1
            elif rec.status == "discrepancy":
                discrepancy_count += 1
                discrepancy_amount += abs(rec.discrepancy_amount or Decimal("0.00"))
                d_bucket["discrepancies"] += 1

    invalid_webhooks = 0
    if canteen_id is None:
        invalid_webhooks = db.scalar(
            select(func.count(PaymentWebhookEvent.id)).where(
                PaymentWebhookEvent.signature_verified.is_(False),
                PaymentWebhookEvent.created_at >= since,
            )
        ) or 0

    runs_stmt = select(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).limit(10)
    if canteen_id is not None:
        runs_stmt = runs_stmt.where(ReconciliationRun.canteen_id == canteen_id)
    recent_runs = db.scalars(runs_stmt).all()

    return {
        "window_days": days,
        "total_attempts": total_attempts,
        "confirmed_count": confirmed_count,
        "failed_count": failed_count,
        "pending_count": pending_count,
        "matched_count": matched_count,
        "discrepancy_count": discrepancy_count,
        "verified_collections_inr": round(float(verified_amount), 2),
        "discrepancy_total_inr": round(float(discrepancy_amount), 2),
        "invalid_webhooks_count": int(invalid_webhooks),
        "gateway_breakdown": list(gateway_breakdown.values()),
        "daily_summary": [daily_totals[k] for k in sorted(daily_totals.keys())[-14:]],
        "recent_runs": [
            {
                "id": str(r.id),
                "trigger": r.trigger,
                "total_checked": r.total_checked,
                "matched_count": r.matched_count,
                "discrepancy_count": r.discrepancy_count,
                "pending_count": r.pending_count,
                "failed_count": r.failed_count,
                "total_verified_amount": float(r.total_verified_amount),
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in recent_runs
        ],
    }


def list_reconciliation_ledger(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    gateway: Optional[str] = None,
    payment_status: Optional[str] = None,
    reconciliation_status: Optional[str] = None,
    discrepancy_type: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = (
        select(Payment, Order, PaymentReconciliation, Canteen.name)
        .join(Order, Order.id == Payment.order_id)
        .join(Canteen, Canteen.id == Order.canteen_id)
        .outerjoin(PaymentReconciliation, PaymentReconciliation.payment_id == Payment.id)
        .order_by(Payment.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if canteen_id is not None:
        stmt = stmt.where(Order.canteen_id == canteen_id)
    if gateway:
        stmt = stmt.where(Payment.provider == gateway.strip())
    if payment_status:
        stmt = stmt.where(Payment.status == payment_status.strip())
    if reconciliation_status:
        if reconciliation_status == "unreconciled":
            stmt = stmt.where(PaymentReconciliation.id.is_(None))
        else:
            stmt = stmt.where(PaymentReconciliation.status == reconciliation_status.strip())
    if discrepancy_type:
        stmt = stmt.where(PaymentReconciliation.discrepancy_type == discrepancy_type.strip())
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Order.order_number.ilike(q),
                Payment.payment_reference.ilike(q),
                Payment.provider_order_id.ilike(q),
                Payment.provider_payment_id.ilike(q),
            )
        )
    if start_date:
        try:
            s_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            stmt = stmt.where(Payment.created_at >= s_dt)
        except ValueError:
            pass
    if end_date:
        try:
            e_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
            stmt = stmt.where(Payment.created_at < e_dt)
        except ValueError:
            pass

    rows = db.execute(stmt).all()
    out: list[dict[str, Any]] = []
    for p, o, rec, cname in rows:
        out.append(
            {
                "payment_id": str(p.id),
                "order_id": str(o.id),
                "order_number": o.order_number,
                "order_status": o.status,
                "canteen_id": str(o.canteen_id),
                "canteen_name": cname,
                "provider": p.provider,
                "method": p.method,
                "provider_order_id": p.provider_order_id,
                "provider_payment_id": p.provider_payment_id,
                "payment_reference": p.payment_reference,
                "payment_status": p.status,
                "expected_amount": float(rec.expected_amount if rec else p.amount),
                "settled_amount": float(rec.settled_amount) if rec else (float(p.amount) if p.status == "CONFIRMED" else 0.0),
                "discrepancy_amount": float(rec.discrepancy_amount) if rec else 0.0,
                "gateway_fee": float(rec.gateway_fee) if rec else 0.0,
                "reconciliation_status": rec.status if rec else "unreconciled",
                "reconciliation_source": rec.reconciliation_source if rec else None,
                "discrepancy_type": rec.discrepancy_type if rec else "none",
                "gateway_settlement_id": rec.gateway_settlement_id if rec else None,
                "notes": rec.notes if rec else p.failure_reason,
                "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
                "reconciled_at": rec.reconciled_at.isoformat() if rec and rec.reconciled_at else None,
                "created_at": p.created_at.isoformat(),
            }
        )
    return out


def list_webhook_events(
    db: Session,
    *,
    provider: Optional[str] = None,
    signature_verified: Optional[bool] = None,
    limit: int = 60,
) -> list[dict[str, Any]]:
    stmt = select(PaymentWebhookEvent).order_by(PaymentWebhookEvent.created_at.desc()).limit(limit)
    if provider:
        stmt = stmt.where(PaymentWebhookEvent.provider == provider)
    if signature_verified is not None:
        stmt = stmt.where(PaymentWebhookEvent.signature_verified.is_(signature_verified))
    rows = db.scalars(stmt).all()
    return [
        {
            "id": str(w.id),
            "provider": w.provider,
            "event_id": w.event_id,
            "event_type": w.event_type,
            "signature_verified": w.signature_verified,
            "processed": w.processed,
            "processing_error": w.processing_error,
            "processed_at": w.processed_at.isoformat() if w.processed_at else None,
            "created_at": w.created_at.isoformat(),
        }
        for w in rows
    ]


def list_payment_transactions(db: Session, payment_id: UUID) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(PaymentTransaction)
        .where(PaymentTransaction.payment_id == payment_id)
        .order_by(PaymentTransaction.created_at.asc())
    ).all()
    return [
        {
            "id": str(t.id),
            "transaction_type": t.transaction_type,
            "amount": float(t.amount),
            "status": t.status,
            "external_reference": t.external_reference,
            "raw_summary": t.raw_summary or {},
            "created_at": t.created_at.isoformat(),
        }
        for t in rows
    ]


def export_reconciliation_csv(db: Session, **filters: Any) -> str:
    rows = list_reconciliation_ledger(db, limit=500, **filters)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Order Number",
            "Canteen",
            "Order Status",
            "Gateway",
            "Method",
            "Payment Status",
            "Gateway Ref",
            "Expected (INR)",
            "Settled (INR)",
            "Discrepancy (INR)",
            "Reconciliation Status",
            "Discrepancy Type",
            "Settlement ID",
            "Confirmed At",
            "Reconciled At",
            "Notes",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r["order_number"],
                r["canteen_name"],
                r["order_status"],
                r["provider"],
                r["method"] or "",
                r["payment_status"],
                r["payment_reference"] or r["provider_order_id"] or "",
                f"{r['expected_amount']:.2f}",
                f"{r['settled_amount']:.2f}",
                f"{r['discrepancy_amount']:.2f}",
                r["reconciliation_status"],
                r["discrepancy_type"],
                r["gateway_settlement_id"] or "",
                r["confirmed_at"] or "",
                r["reconciled_at"] or "",
                r["notes"] or "",
            ]
        )
    return buf.getvalue()


def export_reconciliation_xlsx(db: Session, **filters: Any) -> bytes:
    canteen_id = filters.get("canteen_id")
    dash = get_reconciliation_dashboard(db, canteen_id=canteen_id, days=30)
    rows = list_reconciliation_ledger(db, limit=500, **filters)

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "Summary"
    ws_sum.append(["CollegeBites Financial Reconciliation Report (No-Refund Policy)"])
    ws_sum["A1"].font = Font(bold=True, size=13)
    ws_sum.append(["Generated At (UTC)", datetime.now(timezone.utc).isoformat()])
    ws_sum.append(["Total Attempts", dash["total_attempts"]])
    ws_sum.append(["Confirmed Payments", dash["confirmed_count"]])
    ws_sum.append(["Failed Payments", dash["failed_count"]])
    ws_sum.append(["Pending Payments", dash["pending_count"]])
    ws_sum.append(["Matched Reconciliations", dash["matched_count"]])
    ws_sum.append(["Flagged Discrepancies", dash["discrepancy_count"]])
    ws_sum.append(["Verified Collections (INR)", dash["verified_collections_inr"]])
    ws_sum.append(["Discrepancy Total (INR)", dash["discrepancy_total_inr"]])

    ws_led = wb.create_sheet("Ledger")
    headers = [
        "Order Number",
        "Canteen",
        "Gateway",
        "Method",
        "Payment Status",
        "Reference",
        "Expected INR",
        "Settled INR",
        "Discrepancy INR",
        "Reconciliation Status",
        "Discrepancy Type",
        "Confirmed At",
        "Notes",
    ]
    ws_led.append(headers)
    for cell in ws_led[1]:
        cell.font = Font(bold=True)
    for r in rows:
        ws_led.append(
            [
                r["order_number"],
                r["canteen_name"],
                r["provider"],
                r["method"] or "",
                r["payment_status"],
                r["payment_reference"] or r["provider_order_id"] or "",
                r["expected_amount"],
                r["settled_amount"],
                r["discrepancy_amount"],
                r["reconciliation_status"],
                r["discrepancy_type"],
                r["confirmed_at"] or "",
                r["notes"] or "",
            ]
        )

    ws_disc = wb.create_sheet("Discrepancies")
    ws_disc.append(["Order Number", "Gateway", "Expected INR", "Settled INR", "Discrepancy Type", "Notes"])
    for cell in ws_disc[1]:
        cell.font = Font(bold=True)
    for r in rows:
        if r["reconciliation_status"] == "discrepancy":
            ws_disc.append(
                [
                    r["order_number"],
                    r["provider"],
                    r["expected_amount"],
                    r["settled_amount"],
                    r["discrepancy_type"],
                    r["notes"] or "",
                ]
            )

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
