import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
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
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class InventoryItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "inventory_items"
    __table_args__ = (UniqueConstraint("canteen_id", "ingredient_id", name="uq_inventory_canteen_ingredient"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    current_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    reserved_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    reorder_level: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("100.000"))
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="grams")
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))


class StockBatch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "stock_batches"
    __table_args__ = (Index("ix_stock_batches_expiry", "inventory_item_id", "expiry_date"),)

    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    batch_number: Mapped[str] = mapped_column(String(64), nullable=False)
    initial_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)


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

    po_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ordered")  # draft | ordered | received | cancelled
    total_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    ordered_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class PurchaseOrderItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "purchase_order_items"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False)
    quantity_ordered: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False, default=Decimal("0.000"))
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)


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

    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("stock_batches.id", ondelete="SET NULL"))
    quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)  # expired | spoiled | spilled | prep_waste
    estimated_loss: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class StockTransfer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "stock_transfers"

    from_canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="RESTRICT"), nullable=False)
    to_canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="RESTRICT"), nullable=False)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    transferred_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[Optional[str]] = mapped_column(String(255))
