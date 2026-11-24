"""
Phase 10: Controlled, Role-Aware, Read-Only AI Canteen Assistant Service.
Non-Negotiable Safety & Anti-Hallucination Rules:
1. Role-restricted: ONLY authorized staff/admin/inspector roles; strictly scoped to assigned canteen.
2. Read-only: NEVER approves POs, modifies prices/menus/inventory/payments/production, sends announcements,
   issues refunds, or executes arbitrary SQL. Any write/mutation request is refused & audit-logged.
3. Zero Hallucination: ALL figures come strictly from parameterized approved service calls. When data
   is missing or insufficient, states clearly that data is unavailable.
4. Full Provenance: Every answer returns data_source, date_range, last_updated, data_classification,
   and limitations, and persists conversation + audit logs in PostgreSQL.
"""

import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.time_utils import today_college
from app.models.college import Canteen
from app.models.enterprise import AIAssistantAuditLog, AIAssistantConversation, AIAssistantMessage
from app.services import (
    food_safety_service,
    inventory_service,
    production_service,
    queue_service,
    reorder_service,
    report_service,
    traceability_service,
)

BLOCKED_ACTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(approve|confirm|place|submit|authorize)\b.{0,30}\b(po|purchase\s*order|reorder|procurement)\b", re.I), "Purchase order approval/submission"),
    (re.compile(r"\b(transfer|send|pay|disburse)\b.{0,25}\b(money|funds|vendor|supplier|payment)\b", re.I), "Financial payment / money transfer"),
    (re.compile(r"\b(refund|reverse|chargeback)\b", re.I), "Refund processing (prohibited under CollegeBites no-refund policy)"),
    (re.compile(r"\b(change|update|modify|set|edit|alter|raise|lower|delete|remove)\b.{0,30}\b(price|menu|food\s*item|stock|inventory|quantity|payment|financial|ledger|production\s*plan|batch|order)\b", re.I), "Direct operational or financial data modification"),
    (re.compile(r"\b(deduct|consume|add|adjust|dispose)\b.{0,25}\b(stock|inventory|batch)\b", re.I), "Direct inventory mutation"),
    (re.compile(r"\b(send|broadcast|publish|post)\b.{0,25}\b(announcement|notification|alert|email|sms|maintenance)\b", re.I), "Automated broadcast / announcement dispatch"),
    (re.compile(r"\b(confirm|mark)\b.{0,20}\b(payment|paid|delivered|completed)\b", re.I), "Payment or order confirmation"),
    (re.compile(r"\b(drop\s+table|delete\s+from|update\s+\w+\s+set|insert\s+into|truncate)\b", re.I), "Direct database modification"),
]


def _detect_blocked_action(question: str) -> Optional[str]:
    for pat, label in BLOCKED_ACTION_PATTERNS:
        if pat.search(question):
            return label
    return None


def _parse_date_window(question: str) -> tuple[str, date, date]:
    q = question.lower()
    today = today_college()
    if "yesterday" in q:
        y = today - timedelta(days=1)
        return "yesterday", y, y
    if "last 30" in q or "this month" in q or "monthly" in q or "30 days" in q:
        return "last_30_days", today - timedelta(days=29), today
    if "last 7" in q or "this week" in q or "weekly" in q or "7 days" in q:
        return "last_7_days", today - timedelta(days=6), today
    return "today", today, today


def _resolve_intents(question: str) -> list[str]:
    q = question.lower()
    intents: list[str] = []
    if any(k in q for k in ("forecast", "predict", "tomorrow", "expected demand", "next 7", "demand")):
        intents.append("demand_forecast")
    if any(k in q for k in ("reorder", "running low", "low stock", "shortage", "restock", "purchase", "inventory", "stock")):
        intents.append("inventory_alerts")
    if any(k in q for k in ("waste", "wastage", "spoil", "damaged", "unsold", "loss")):
        intents.append("wastage_report")
    if any(k in q for k in ("queue", "wait", "waiting", "crowd", "busy", "peak hour", "peak", "rush")):
        intents.append("queue_status")
    if any(k in q for k in ("hygiene", "safety", "temperature", "inspection", "cleaning", "incident", "compliance", "expir")):
        intents.append("food_safety_status")
    if any(k in q for k in ("recall", "trace", "traceability", "batch", "supplier", "vendor")):
        intents.append("batch_traceability")
    if any(k in q for k in ("production", "recipe", "prep", "cook", "kitchen batch")):
        intents.append("production_status")
    if any(k in q for k in ("top", "best", "most sold", "selling", "popular", "least ordered")):
        intents.append("top_items")
    if any(k in q for k in ("sale", "revenue", "income", "margin", "financial", "today", "order", "how much", "summary")):
        intents.append("sales_revenue")
    if not intents:
        intents.append("sales_revenue")
    return intents


def ask_assistant(
    db: Session,
    *,
    user_id: UUID,
    user_roles: set[str],
    canteen_id: UUID,
    question: str,
    conversation_id: Optional[UUID] = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    clean_q = (question or "").strip()
    if len(clean_q) < 2:
        raise HTTPException(status_code=400, detail="Question must be at least 2 characters")

    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")

    if conversation_id:
        conv = db.get(AIAssistantConversation, conversation_id)
        if not conv or conv.user_id != user_id:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conv = AIAssistantConversation(
            user_id=user_id,
            canteen_id=canteen_id,
            title=clean_q[:180],
        )
        db.add(conv)
        db.flush()

    db.add(AIAssistantMessage(conversation_id=conv.id, role="user", content=clean_q))

    now_iso = datetime.now(timezone.utc).isoformat()
    blocked_reason = _detect_blocked_action(clean_q)
    if blocked_reason:
        answer = (
            f"Action blocked by CollegeBites safety policy: I cannot perform '{blocked_reason}'. "
            "The AI Canteen Assistant is strictly read-only and cannot approve purchase orders, modify menus/prices/inventory, "
            "confirm payments, issue refunds, edit production plans, or send announcements. "
            "Please perform this action manually using your authorized CollegeBites console."
        )
        msg = AIAssistantMessage(
            conversation_id=conv.id,
            role="assistant",
            content=answer,
            data_source="CollegeBites Read-Only Governance Policy",
            date_range="N/A",
            data_classification="policy_restricted",
            limitations="AI Assistant is read-only and never executes operational, financial, or procurement mutations.",
            metadata_json={"blocked_action": blocked_reason},
        )
        db.add(msg)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        db.add(
            AIAssistantAuditLog(
                user_id=user_id,
                canteen_id=canteen_id,
                user_roles=sorted(user_roles),
                question=clean_q,
                resolved_intents=["blocked_write_attempt"],
                tools_invoked=[],
                data_classification="policy_restricted",
                blocked_action_attempted=True,
                response_ms=elapsed_ms,
            )
        )
        db.commit()
        db.refresh(msg)
        return {
            "conversation_id": str(conv.id),
            "message_id": str(msg.id),
            "answer": answer,
            "data_source": msg.data_source,
            "date_range": msg.date_range,
            "last_updated": now_iso,
            "data_classification": "policy_restricted",
            "limitations": msg.limitations,
            "tools_invoked": [],
            "blocked_action_attempted": True,
            "supporting_data": {"blocked_reason": blocked_reason},
        }

    intents = _resolve_intents(clean_q)
    preset, s_date, e_date = _parse_date_window(clean_q)
    date_range_str = f"{s_date.isoformat()} to {e_date.isoformat()} ({preset})"

    tools_invoked: list[str] = []
    sources: list[str] = []
    sections: list[str] = []
    limitations_list: list[str] = []
    supporting_data: dict[str, Any] = {}
    classifications: set[str] = set()

    # Role-based domain filtering (e.g., food_safety_inspector sees safety/traceability without financial internals if not manager/admin)
    is_finance_allowed = bool(user_roles & {"super_admin", "college_admin", "canteen_manager"})
    is_inventory_allowed = bool(user_roles & {"super_admin", "college_admin", "canteen_manager", "inventory_manager", "kitchen_staff"})

    report_cache: Optional[dict[str, Any]] = None

    def _get_report() -> dict[str, Any]:
        nonlocal report_cache
        if report_cache is None:
            tools_invoked.append("report_service.get_analytics_report")
            report_cache = report_service.get_analytics_report(
                db, canteen_id=canteen_id, preset=preset, start_date=s_date, end_date=e_date
            )
        return report_cache

    for intent in intents:
        if intent == "sales_revenue":
            if not is_finance_allowed:
                limitations_list.append("Financial revenue details require Canteen Manager or Admin role.")
                continue
            rep = _get_report()
            sources.append("Verified Orders & Payments DB")
            fin = rep.get("financial_analytics") or {}
            sales = rep.get("sales") or {}
            if rep.get("empty"):
                sections.append(f"Sales ({date_range_str}): No verified paid orders recorded for {canteen.name} in this period.")
                classifications.add("unavailable")
            else:
                classifications.add("actual")
                margin_str = (
                    f"Estimated gross margin: ₹{fin['estimated_gross_margin']} ({fin['estimated_gross_margin_percent']}%)"
                    if fin.get("estimated_gross_margin") is not None
                    else "Estimated gross margin unavailable (insufficient verified ingredient cost data; revenue is not profit)"
                )
                sections.append(
                    f"Sales for {canteen.name} ({date_range_str}): {sales['total_orders']} verified paid orders, "
                    f"Verified Net Revenue ₹{fin.get('verified_net_revenue', sales['net_sales'])}, "
                    f"Avg Order Value ₹{sales['average_order_value']}. {margin_str}."
                )
                if fin.get("estimated_gross_margin") is None:
                    limitations_list.append(fin.get("margin_note") or "Gross margin requires verified ingredient costs.")
            supporting_data["sales"] = {
                "total_orders": sales.get("total_orders", 0),
                "verified_net_revenue": fin.get("verified_net_revenue"),
                "verified_ingredient_cost": fin.get("verified_ingredient_cost"),
                "estimated_gross_margin": fin.get("estimated_gross_margin"),
            }

        elif intent == "top_items":
            rep = _get_report()
            sources.append("Verified OrderItems DB")
            top = (rep.get("sales") or {}).get("top_items") or []
            if not top:
                sections.append(f"Top Selling Items ({date_range_str}): No item sales data available for this range.")
                classifications.add("unavailable")
            else:
                classifications.add("actual")
                formatted = ", ".join(f"{it['item_name']} ({it['quantity_sold']} sold, ₹{it['revenue']:.2f})" for it in top[:5])
                sections.append(f"Top Selling Items ({date_range_str}): {formatted}.")
            supporting_data["top_items"] = top[:10]

        elif intent == "wastage_report":
            rep = _get_report()
            sources.append("Verified Wastage Records DB")
            inv_rep = rep.get("inventory") or {}
            tot_w = inv_rep.get("total_wastage_loss", "0.00")
            wb = inv_rep.get("wastage_breakdown") or {}
            classifications.add("actual")
            sections.append(
                f"Recorded Food & Ingredient Wastage ({date_range_str}): Total recorded loss ₹{tot_w} "
                f"(Expired: ₹{wb.get('expired', {}).get('loss_amount', '0.00')}, "
                f"Damaged: ₹{wb.get('damaged', {}).get('loss_amount', '0.00')}, "
                f"Unsold: ₹{wb.get('unsold', {}).get('loss_amount', '0.00')}, "
                f"Wastage: ₹{wb.get('wastage', {}).get('loss_amount', '0.00')})."
            )
            supporting_data["wastage"] = {"total_wastage_loss": tot_w, "breakdown": wb}

        elif intent == "inventory_alerts":
            if not is_inventory_allowed:
                limitations_list.append("Inventory details require Inventory/Kitchen/Manager/Admin role.")
                continue
            tools_invoked.extend(["inventory_service.get_inventory_dashboard", "reorder_service.list_reorder_recommendations"])
            sources.append("Live Inventory & Reorder Engine")
            dash = inventory_service.get_inventory_dashboard(db, canteen_id)
            recs = reorder_service.list_reorder_recommendations(db, canteen_id, status_filter="pending_review")
            low_items = dash.get("low_stock_items") or []
            classifications.add("actual")
            if not low_items and not recs:
                sections.append(
                    f"Inventory ({canteen.name}): {dash['total_inventory_items']} tracked items; no low-stock alerts or pending reorder recommendations right now."
                )
            else:
                low_str = ", ".join(f"{i['name']} ({i['current_quantity']}/{i['reorder_level']} {i['unit']})" for i in low_items[:6])
                sections.append(
                    f"Inventory Alerts ({canteen.name}): {dash['low_stock_alerts_count']} low-stock item(s) "
                    f"({low_str or 'none'}), {dash['expired_batches_count']} expired batch(es), "
                    f"{dash['expiring_soon_count']} expiring within 7 days, and {len(recs)} pending reorder recommendation(s)."
                )
            supporting_data["inventory"] = {
                "low_stock_count": dash["low_stock_alerts_count"],
                "low_stock_items": low_items[:10],
                "pending_reorder_recommendations": len(recs),
            }

        elif intent == "queue_status":
            tools_invoked.extend(["queue_service.get_live_queue_dashboard", "queue_service.get_queue_accuracy_metrics"])
            sources.append("Live Queue & Order Status Engine")
            q_dash = queue_service.get_live_queue_dashboard(db, canteen_id)
            acc = queue_service.get_queue_accuracy_metrics(db, canteen_id, days=30)
            classifications.add("estimated")
            wait_str = (
                f"Estimated wait: ~{q_dash['estimated_wait_minutes']} min (estimated)"
                if q_dash.get("waiting_time_available")
                else q_dash.get("waiting_time_message") or "Waiting time currently unavailable."
            )
            acc_str = (
                f"30-day prediction MAE: {acc['mae_minutes']} min ({acc['sample_count']} samples)."
                if acc.get("sample_count", 0) > 0
                else "Queue accuracy history has insufficient completed samples yet."
            )
            sections.append(
                f"Live Queue ({canteen.name}): Crowd {q_dash['crowd_level']}, {q_dash['active_order_count']} active orders, "
                f"{q_dash['on_duty_staff_count']} staff on duty. {wait_str}. {acc_str}"
            )
            limitations_list.append("Waiting times are live estimates based on active queue load and on-duty staff, not guaranteed delivery times.")
            supporting_data["queue"] = {
                "crowd_level": q_dash["crowd_level"],
                "active_order_count": q_dash["active_order_count"],
                "estimated_wait_minutes": q_dash["estimated_wait_minutes"],
                "waiting_time_available": q_dash["waiting_time_available"],
                "accuracy_mae_minutes": acc.get("mae_minutes"),
            }

        elif intent == "food_safety_status":
            tools_invoked.extend(["food_safety_service.get_food_safety_dashboard", "food_safety_service.get_expiry_monitoring"])
            sources.append("Food Safety & Hygiene Compliance DB")
            fs_dash = food_safety_service.get_food_safety_dashboard(db, canteen_id, days=30)
            classifications.add("actual")
            if fs_dash.get("empty"):
                sections.append(f"Food Safety ({canteen.name}, 30 days): {fs_dash['message']}")
                classifications.add("unavailable")
            else:
                pass_rate = (
                    f"{fs_dash['inspection_pass_rate_percent']}%"
                    if fs_dash.get("inspection_pass_rate_percent") is not None
                    else "N/A (no inspections)"
                )
                sections.append(
                    f"Food Safety ({canteen.name}, last 30 days): {fs_dash['completed_inspections_count']} inspection(s) "
                    f"(pass rate: {pass_rate}, failed: {fs_dash['failed_inspections_count']}), "
                    f"{fs_dash['temperature_violations_count']} temperature violation(s), "
                    f"{fs_dash['overdue_cleaning_tasks_count']} overdue cleaning task(s), "
                    f"{fs_dash['expired_batches_count']} expired batch(es), "
                    f"{fs_dash['open_incidents_count']} open incident(s)."
                )
            supporting_data["food_safety"] = fs_dash

        elif intent == "batch_traceability":
            tools_invoked.extend(["traceability_service.list_batches", "traceability_service.list_recalls"])
            sources.append("Batch Traceability & Recall Registry")
            batches = traceability_service.list_batches(db, canteen_id, include_empty=False)
            recalls = traceability_service.list_recalls(db, canteen_id)
            active_recalls = [r for r in recalls if r["status"] in ("under_review", "active_recall")]
            classifications.add("actual")
            sections.append(
                f"Batch Traceability ({canteen.name}): {len(batches)} active stock batch(es) tracked, "
                f"{len(active_recalls)} active/under-review recall incident(s)."
            )
            supporting_data["traceability"] = {
                "active_batches_count": len(batches),
                "active_recalls_count": len(active_recalls),
                "recalls": active_recalls[:5],
            }

        elif intent == "production_status":
            tools_invoked.extend(["production_service.get_production_planning_overview", "production_service.get_production_report"])
            sources.append("Kitchen Production & Recipe Engine")
            plan_ov = production_service.get_production_planning_overview(db, canteen_id)
            prod_rep = production_service.get_production_report(db, canteen_id, days=7)
            classifications.add("actual")
            sections.append(
                f"Kitchen Production ({canteen.name}, last 7 days): {prod_rep['total_batches']} batch(es) "
                f"({prod_rep['completed_batches']} completed), planned {prod_rep['total_planned_qty']}, "
                f"actual {prod_rep['total_actual_qty']}, recorded waste {prod_rep['total_waste_qty']}."
            )
            supporting_data["production"] = {"planning_items_count": len(plan_ov["items"]), "report": prod_rep}

        elif intent == "demand_forecast":
            from app.services import forecast_service

            tools_invoked.append("forecast_service.get_canteen_forecast_summary")
            sources.append("ML Demand Forecasting Pipeline (scikit-learn)")
            fc = forecast_service.get_canteen_forecast_summary(db, canteen_id)
            if fc.get("status") != "ok":
                classifications.add("unavailable")
                sections.append(f"AI Demand Forecast ({canteen.name}): {fc.get('message') or 'Insufficient historical data to generate a reliable forecast.'}")
                limitations_list.append("Forecasts require at least 7 distinct days of verified confirmed sales history.")
            else:
                classifications.add("ai_predicted")
                next_day = fc.get("next_day_forecasts") or []
                top_fc = ", ".join(
                    f"{it['food_item_name']} (~{it['predicted_quantity']} [{it['lower_bound']}–{it['upper_bound']}])"
                    for it in next_day[:5]
                )
                model_meta = fc.get("active_model") or {}
                sections.append(
                    f"AI Demand Forecast for {canteen.name} (Model {model_meta.get('model_version')}, {model_meta.get('algorithm')}, "
                    f"MAE {model_meta.get('mae')}): Next-day predicted demand — {top_fc or 'no active items'}. "
                    f"Potential recipe ingredient shortages detected: {len(fc.get('potential_shortages') or [])}."
                )
                limitations_list.append("Demand forecasts are AI predictions trained on historical verified orders and include uncertainty bands; actual campus demand may vary.")
            supporting_data["demand_forecast"] = fc

    if not sections:
        sections.append("No authorized data available to answer this query for your role and canteen scope.")
        classifications.add("unavailable")

    if "ai_predicted" in classifications:
        final_class = "ai_predicted"
    elif "estimated" in classifications:
        final_class = "estimated"
    elif "actual" in classifications:
        final_class = "actual"
    else:
        final_class = "unavailable"

    final_answer = "\n".join(sections)
    source_str = "; ".join(dict.fromkeys(sources)) or "CollegeBites Operational Database"
    limitation_str = (
        " ".join(dict.fromkeys(limitations_list))
        if limitations_list
        else "Read-only summary grounded strictly in verified CollegeBites database records."
    )

    msg = AIAssistantMessage(
        conversation_id=conv.id,
        role="assistant",
        content=final_answer,
        data_source=source_str[:200],
        date_range=date_range_str[:120],
        data_classification=final_class,
        limitations=limitation_str,
        metadata_json={"tools_invoked": tools_invoked, "intents": intents},
    )
    db.add(msg)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    db.add(
        AIAssistantAuditLog(
            user_id=user_id,
            canteen_id=canteen_id,
            user_roles=sorted(user_roles),
            question=clean_q,
            resolved_intents=intents,
            tools_invoked=tools_invoked,
            data_classification=final_class,
            blocked_action_attempted=False,
            response_ms=elapsed_ms,
        )
    )
    db.commit()
    db.refresh(msg)

    return {
        "conversation_id": str(conv.id),
        "message_id": str(msg.id),
        "answer": final_answer,
        "data_source": source_str,
        "date_range": date_range_str,
        "last_updated": now_iso,
        "data_classification": final_class,
        "limitations": limitation_str,
        "tools_invoked": tools_invoked,
        "blocked_action_attempted": False,
        "supporting_data": supporting_data,
    }


def list_conversations(db: Session, *, user_id: UUID, limit: int = 30) -> list[dict]:
    rows = db.scalars(
        select(AIAssistantConversation)
        .where(AIAssistantConversation.user_id == user_id)
        .order_by(AIAssistantConversation.updated_at.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return [
        {
            "id": str(c.id),
            "canteen_id": str(c.canteen_id) if c.canteen_id else None,
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in rows
    ]


def get_conversation_detail(db: Session, *, conversation_id: UUID, user_id: UUID) -> dict:
    conv = db.scalar(
        select(AIAssistantConversation)
        .options(selectinload(AIAssistantConversation.messages))
        .where(AIAssistantConversation.id == conversation_id, AIAssistantConversation.user_id == user_id)
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = sorted(conv.messages, key=lambda m: m.created_at or datetime.min.replace(tzinfo=timezone.utc))
    return {
        "id": str(conv.id),
        "canteen_id": str(conv.canteen_id) if conv.canteen_id else None,
        "title": conv.title,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "data_source": m.data_source,
                "date_range": m.date_range,
                "data_classification": m.data_classification,
                "limitations": m.limitations,
                "metadata_json": m.metadata_json or {},
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


def list_audit_logs(db: Session, *, canteen_id: Optional[UUID] = None, limit: int = 100) -> list[dict]:
    stmt = select(AIAssistantAuditLog)
    if canteen_id:
        stmt = stmt.where(AIAssistantAuditLog.canteen_id == canteen_id)
    rows = db.scalars(stmt.order_by(AIAssistantAuditLog.created_at.desc()).limit(max(1, min(limit, 300)))).all()
    return [
        {
            "id": str(r.id),
            "user_id": str(r.user_id),
            "canteen_id": str(r.canteen_id) if r.canteen_id else None,
            "user_roles": list(r.user_roles or []),
            "question": r.question,
            "resolved_intents": list(r.resolved_intents or []),
            "tools_invoked": list(r.tools_invoked or []),
            "data_classification": r.data_classification,
            "blocked_action_attempted": r.blocked_action_attempted,
            "response_ms": r.response_ms,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
