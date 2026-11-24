"""
Enterprise domain models extending CollegeBites without duplicating existing entities:
- Food Safety & Hygiene Compliance (Inspections, Equipment Temperature Monitoring, Cleaning, Incidents)
- Kitchen & Food Production Management (Plans, Batches, Ingredient Allocation, Quality Control)
- Traceability & Recall Management (End-to-End Trace Records, Recalls)
- Automated Reordering (Rules, Recommendations)
- Smart Queue Prediction Accuracy History
- AI Demand Forecasting (Models, Forecasts, Evaluations)
- AI Canteen Assistant (Conversations, Messages, Audit Logs)
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, QuantityNumeric, TimestampMixin, UUIDPrimaryKeyMixin


# =============================================================================
# PHASE 3: FOOD SAFETY & HYGIENE COMPLIANCE
# =============================================================================


class FoodSafetyChecklistTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_safety_checklist_templates"

    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, default="daily_hygiene"
    )  # daily_hygiene | kitchen | storage | staff_hygiene | pest_control | water_safety
    items_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # [{code, title, category, required}]
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class FoodSafetyInspection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_safety_inspections"
    __table_args__ = (Index("ix_fs_insp_canteen_date", "canteen_id", "inspected_at"),)

    inspection_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("food_safety_checklist_templates.id", ondelete="SET NULL"))
    inspector_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    inspected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    overall_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pass")  # pass | fail | partial
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    na_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    photo_urls: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    items: Mapped[list["FoodSafetyInspectionItem"]] = relationship(back_populates="inspection", cascade="all, delete-orphan")


class FoodSafetyInspectionItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_safety_inspection_items"

    inspection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_safety_inspections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_code: Mapped[str] = mapped_column(String(64), nullable=False)
    item_title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    result: Mapped[str] = mapped_column(String(24), nullable=False)  # pass | fail | not_applicable
    notes: Mapped[Optional[str]] = mapped_column(Text)
    photo_url: Mapped[Optional[str]] = mapped_column(String(500))

    inspection: Mapped["FoodSafetyInspection"] = relationship(back_populates="items")


class EquipmentTemperatureConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "equipment_temperature_configs"
    __table_args__ = (UniqueConstraint("canteen_id", "equipment_code", name="uq_equip_temp_canteen_code"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    equipment_name: Mapped[str] = mapped_column(String(140), nullable=False)
    equipment_code: Mapped[str] = mapped_column(String(48), nullable=False)
    equipment_type: Mapped[str] = mapped_column(
        String(48), nullable=False, default="refrigerator"
    )  # refrigerator | freezer | storage_unit | prep_equipment | holding_equipment
    location: Mapped[Optional[str]] = mapped_column(String(140))
    min_temp_c: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_temp_c: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    standard_reference: Mapped[Optional[str]] = mapped_column(String(200))  # Admin-configured policy / OEM spec
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    configured_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class EquipmentTemperatureLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "equipment_temperature_logs"
    __table_args__ = (Index("ix_temp_logs_canteen_time", "canteen_id", "recorded_at"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment_temperature_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recorded_temp_c: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    min_allowed_c: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_allowed_c: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    is_violation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    corrective_action: Mapped[Optional[str]] = mapped_column(Text)


class CleaningSchedule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "cleaning_schedules"

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    area_name: Mapped[str] = mapped_column(String(160), nullable=False)
    frequency: Mapped[str] = mapped_column(String(24), nullable=False, default="daily")  # daily | weekly | monthly
    instructions: Mapped[Optional[str]] = mapped_column(Text)
    assigned_staff_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CleaningTaskLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "cleaning_task_logs"
    __table_args__ = (Index("ix_cleaning_tasks_canteen_due", "canteen_id", "due_at", "status"),)

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cleaning_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_staff_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")  # pending | in_progress | completed
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    evidence_url: Mapped[Optional[str]] = mapped_column(String(500))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class FoodSafetyIncident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_safety_incidents"
    __table_args__ = (Index("ix_fs_incidents_canteen_status", "canteen_id", "status", "occurred_at"),)

    incident_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="medium")  # low | medium | high | critical
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")  # open | under_investigation | resolved | closed
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reported_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_to_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    evidence_urls: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    corrective_action: Mapped[Optional[str]] = mapped_column(Text)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# =============================================================================
# PHASES 4 & 5: PRODUCTION MANAGEMENT, TRACEABILITY & RECALLS
# =============================================================================


class ProductionPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "production_plans"
    __table_args__ = (Index("ix_prod_plan_canteen_date", "canteen_id", "plan_date"),)

    plan_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_session: Mapped[str] = mapped_column(String(32), nullable=False, default="all_day")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")  # draft | active | completed | cancelled
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProductionBatch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "production_batches"
    __table_args__ = (Index("ix_prod_batch_canteen_status", "canteen_id", "status", "created_at"),)

    batch_code: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(96), unique=True)
    production_plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("production_plans.id", ondelete="SET NULL"), index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    food_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("food_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    recipe_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="planned"
    )  # planned | ingredients_allocated | ready_for_preparation | preparing | prepared | quality_checked | completed | cancelled
    planned_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sold_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remaining_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    waste_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    allocation_strategy: Mapped[str] = mapped_column(String(16), nullable=False, default="FEFO")  # FEFO | FIFO
    assigned_staff_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    planned_prep_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    ingredient_allocations: Mapped[list["ProductionBatchIngredient"]] = relationship(
        back_populates="production_batch", cascade="all, delete-orphan"
    )
    quality_checks: Mapped[list["ProductionQualityCheck"]] = relationship(
        back_populates="production_batch", cascade="all, delete-orphan"
    )


class ProductionBatchIngredient(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "production_batch_ingredients"

    production_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False, index=True)
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False)
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_batches.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity_used: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    override_approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    override_reason: Mapped[Optional[str]] = mapped_column(String(255))

    production_batch: Mapped["ProductionBatch"] = relationship(back_populates="ingredient_allocations")


class ProductionQualityCheck(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "production_quality_checks"

    production_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    appearance_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preparation_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hygiene_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    temperature_c: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="passed")  # passed | failed | corrective_action_required
    notes: Mapped[Optional[str]] = mapped_column(Text)
    evidence_url: Mapped[Optional[str]] = mapped_column(String(500))
    corrective_action: Mapped[Optional[str]] = mapped_column(Text)
    checked_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    production_batch: Mapped["ProductionBatch"] = relationship(back_populates="quality_checks")


class TraceabilityRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "traceability_records"
    __table_args__ = (
        Index("ix_trace_stock_batch", "stock_batch_id"),
        Index("ix_trace_prod_batch", "production_batch_id"),
        Index("ix_trace_order", "order_id"),
    )

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"))
    goods_receipt_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("goods_receipts.id", ondelete="SET NULL"))
    stock_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("stock_batches.id", ondelete="SET NULL"))
    recipe_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"))
    production_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("production_batches.id", ondelete="SET NULL"))
    food_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("food_items.id", ondelete="SET NULL"))
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    trace_completeness: Mapped[str] = mapped_column(String(32), nullable=False, default="partial")  # complete | partial
    missing_links: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class RecallIncident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recall_incidents"

    recall_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="high")  # medium | high | critical
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="under_review"
    )  # under_review | active_recall | resolved | closed
    affected_stock_batch_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    affected_production_batch_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    affected_order_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    investigation_notes: Mapped[Optional[str]] = mapped_column(Text)
    corrective_actions: Mapped[Optional[str]] = mapped_column(Text)
    initiated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# =============================================================================
# PHASE 6: AUTOMATED REORDERING SYSTEM
# =============================================================================


class ReorderRule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reorder_rules"
    __table_args__ = (UniqueConstraint("inventory_item_id", name="uq_reorder_rule_inv_item"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True)
    preferred_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    min_stock_level: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    reorder_level: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("100.000"))
    safety_stock: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("25.000"))
    supplier_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    target_days_of_cover: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ReorderRecommendation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reorder_recommendations"
    __table_args__ = (Index("ix_reorder_rec_canteen_status", "canteen_id", "status", "created_at"),)

    recommendation_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), unique=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True)
    recommended_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_review"
    )  # pending_review | draft_po_created | dismissed | fulfilled
    current_stock: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    available_stock: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    reserved_stock: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    incoming_po_stock: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    avg_daily_consumption: Mapped[Optional[Decimal]] = mapped_column(QuantityNumeric)
    forecasted_demand_qty: Mapped[Optional[Decimal]] = mapped_column(QuantityNumeric)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    safety_stock: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    recommended_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    verified_unit_cost: Mapped[Optional[Decimal]] = mapped_column(Money)
    estimated_total_cost: Mapped[Optional[Decimal]] = mapped_column(Money)
    trigger_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="calculated")
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"))
    reviewed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)


# =============================================================================
# PHASE 7: SMART QUEUE PREDICTION ACCURACY HISTORY
# =============================================================================


class QueueEstimateHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "queue_estimate_history"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_queue_est_order"),
        Index("ix_queue_est_canteen_created", "canteen_id", "estimated_at"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    counter_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("counters.id", ondelete="SET NULL"))
    estimated_wait_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_prep_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_position_at_creation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_orders_at_creation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    on_duty_staff_at_creation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    estimated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_ready_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    actual_prep_minutes: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    actual_wait_minutes: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    absolute_error_minutes: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="estimated")


# =============================================================================
# PHASE 9: AI DEMAND FORECASTING
# =============================================================================


class ForecastModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "forecast_models"
    __table_args__ = (Index("ix_forecast_models_canteen_active", "canteen_id", "is_active", "trained_at"),)

    model_version: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    training_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    historical_days_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mae: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    rmse: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    mape: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    baseline_mae: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    baseline_rmse: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    comparison_metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    feature_columns: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trained_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DemandForecast(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "demand_forecasts"
    __table_args__ = (
        Index("ix_demand_fc_canteen_date", "canteen_id", "forecast_date"),
        Index("ix_demand_fc_model_item", "model_id", "food_item_id", "forecast_date"),
    )

    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forecast_models.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    food_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("food_categories.id", ondelete="SET NULL"))
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    predicted_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    lower_bound: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    upper_bound: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    historical_days_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="ai_predicted")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ForecastEvaluation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "forecast_evaluations"

    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forecast_models.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    evaluation_date: Mapped[date] = mapped_column(Date, nullable=False)
    mae: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    rmse: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    mape: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    evaluated_items_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text)


# =============================================================================
# PHASE 10: AI CANTEEN ASSISTANT
# =============================================================================


class AIAssistantConversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_assistant_conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Operations Assistant Session")

    messages: Mapped[list["AIAssistantMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class AIAssistantMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_assistant_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_assistant_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    data_source: Mapped[Optional[str]] = mapped_column(String(200))
    date_range: Mapped[Optional[str]] = mapped_column(String(120))
    data_classification: Mapped[Optional[str]] = mapped_column(String(48))  # actual | calculated | estimated | ai_predicted | unavailable | policy_restricted
    limitations: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    conversation: Mapped["AIAssistantConversation"] = relationship(back_populates="messages")


class AIAssistantAuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_assistant_audit_logs"
    __table_args__ = (Index("ix_ai_audit_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"))
    user_roles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_intents: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tools_invoked: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    data_classification: Mapped[str] = mapped_column(String(48), nullable=False, default="actual")
    blocked_action_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
