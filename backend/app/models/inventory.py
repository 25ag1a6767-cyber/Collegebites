import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, QuantityNumeric, TimestampMixin, UUIDPrimaryKeyMixin


class Supplier(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_person: Mapped[Optional[str]] = mapped_column(String(120))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    email: Mapped[Optional[str]] = mapped_column(String(160))
    address: Mapped[Optional[str]] = mapped_column(Text)
    gst_number: Mapped[Optional[str]] = mapped_column(String(32))
    business_details: Mapped[Optional[str]] = mapped_column(Text)
    supplied_products: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(80))
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class InventoryItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("canteen_id", "ingredient_id", name="uq_inventory_canteen_ingredient"),
        Index("ix_inventory_canteen_arch_qty", "canteen_id", "is_archived", "current_quantity"),
    )

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    current_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    reserved_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    reorder_level: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("100.000"))
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="grams")
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="General")
    description: Mapped[Optional[str]] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(String(500))
    storage_location: Mapped[Optional[str]] = mapped_column(String(120))
    preferred_supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL")
    )
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    archived_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class StockBatch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "stock_batches"
    __table_args__ = (
        Index("ix_stock_batches_expiry", "inventory_item_id", "expiry_date"),
        Index("ix_stock_batches_quality", "inventory_item_id", "quality_status"),
    )

    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"), index=True)
    goods_receipt_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("goods_receipts.id", ondelete="SET NULL"), index=True)
    batch_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    initial_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    allocated_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    consumed_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    rejected_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    wasted_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    manufacturing_date: Mapped[Optional[date]] = mapped_column(Date)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    storage_location: Mapped[Optional[str]] = mapped_column(String(120))
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False, default="approved")  # pending | approved | rejected | blocked | recalled
    block_reason: Mapped[Optional[str]] = mapped_column(String(255))
    supporting_documents: Mapped[Optional[list]] = mapped_column(JSON, default=list)


class StockMovement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_item", "inventory_item_id", "created_at"),
    )

    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("stock_batches.id", ondelete="SET NULL"))
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)  # purchase | order_deduct | adjustment | wastage | transfer_in | transfer_out
    quantity_delta: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(48))  # order | purchase_order | adjustment | wastage | transfer
    reference_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[Optional[str]] = mapped_column(String(255))


class PurchaseOrder(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("ix_po_supplier_status", "supplier_id", "status"),
        Index("ix_po_canteen_status_created", "canteen_id", "status", "created_at"),
    )

    po_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ordered")  # draft | pending_approval | approved | ordered | partially_received | partial | received | cancelled
    subtotal_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    total_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    ordered_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expected_delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class PurchaseOrderItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "purchase_order_items"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingredient_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=True)
    item_name: Mapped[Optional[str]] = mapped_column(String(140))
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="units")
    quantity_ordered: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    quantity_damaged: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    quantity_rejected: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    quantity_missing: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    tax_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)


class GoodsReceipt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "goods_receipts"

    grn_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canteen_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(96), unique=True)
    delivery_challan_ref: Mapped[Optional[str]] = mapped_column(String(96))
    received_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class GoodsReceiptItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "goods_receipt_items"

    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    po_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_items.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("ingredients.id", ondelete="SET NULL")
    )
    item_name: Mapped[str] = mapped_column(String(140), nullable=False)
    quantity_delivered: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    quantity_accepted: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    quantity_damaged: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    quantity_rejected: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    quantity_missing: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class VendorPayment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "vendor_payments"
    __table_args__ = (
        Index("ix_vendor_payments_po_status", "purchase_order_id", "status"),
        Index("ix_vendor_payments_supplier_status", "supplier_id", "status"),
    )

    payment_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("canteens.id", ondelete="SET NULL"), index=True
    )
    purchase_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="SET NULL"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False, default="bank_transfer")
    payment_reference: Mapped[Optional[str]] = mapped_column(String(128))
    document_url: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_verification", index=True
    )  # pending_verification | verified | cancelled
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class StockAdjustment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "stock_adjustments"

    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity_delta: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    adjusted_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class WastageRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "wastage_records"

    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("canteens.id", ondelete="CASCADE"), nullable=True, index=True
    )
    inventory_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    food_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("food_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("stock_batches.id", ondelete="SET NULL"))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="ingredient")  # ingredient | prepared_food
    quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    loss_type: Mapped[str] = mapped_column(String(32), nullable=False, default="wastage")  # damaged | expired | wastage | unsold
    reason: Mapped[str] = mapped_column(String(255), nullable=False)  # expired | spoiled | spilled | prep_waste | damaged | unsold_food
    waste_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    estimated_loss: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    responsible_staff_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DailyFoodPrepLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "daily_food_prep_logs"
    __table_args__ = (
        UniqueConstraint(
            "canteen_id",
            "food_item_id",
            "prep_date",
            "meal_session",
            name="uq_daily_food_prep_item_session",
        ),
    )

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    food_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False, index=True)
    prep_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    meal_session: Mapped[str] = mapped_column(String(32), nullable=False, default="all_day")  # breakfast | lunch | evening | dinner | all_day
    prepared_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsold_wasted_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    waste_reason: Mapped[Optional[str]] = mapped_column(String(255))
    responsible_staff_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[Optional[str]] = mapped_column(String(255))


class StockTransfer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "stock_transfers"

    from_canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="RESTRICT"), nullable=False)
    to_canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="RESTRICT"), nullable=False)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    transferred_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[Optional[str]] = mapped_column(String(255))


class InventoryAuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "inventory_audit_logs"
    __table_args__ = (Index("ix_inv_audit_canteen_item", "canteen_id", "inventory_item_id", "created_at"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    inventory_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(48), nullable=False)  # created | edited | archived | restored | stock_changed | purchase_price_updated | selling_price_requested | selling_price_approved | selling_price_rejected
    field_name: Mapped[Optional[str]] = mapped_column(String(64))
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    changed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PriceChangeRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "price_change_requests"
    __table_args__ = (Index("ix_price_change_canteen_status", "canteen_id", "status", "created_at"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    inventory_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL"), index=True
    )
    food_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("food_items.id", ondelete="CASCADE"), index=True
    )
    price_kind: Mapped[str] = mapped_column(String(32), nullable=False)  # purchase_cost | selling_price
    old_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    new_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_approval"
    )  # applied | pending_approval | approved | rejected
    requested_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    review_notes: Mapped[Optional[str]] = mapped_column(String(300))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
