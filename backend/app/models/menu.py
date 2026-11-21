import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Money, QuantityNumeric, TimestampMixin, UUIDPrimaryKeyMixin


class FoodCategory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_categories"
    __table_args__ = (UniqueConstraint("canteen_id", "slug", name="uq_food_categories_canteen_slug"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    items: Mapped[list["FoodItem"]] = relationship(back_populates="category")


class FoodItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_items"
    __table_args__ = (
        UniqueConstraint("canteen_id", "slug", name="uq_food_items_canteen_slug"),
        Index("ix_food_items_canteen_active", "canteen_id", "is_active", "is_available"),
    )

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kitchen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("kitchens.id", ondelete="SET NULL"))
    counter_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("counters.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    base_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_rate_percent: Mapped[Optional[Decimal]] = mapped_column(Money)
    is_veg: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_popular: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_todays_special: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prep_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    portion_size: Mapped[Optional[str]] = mapped_column(String(64))
    calories: Mapped[Optional[int]] = mapped_column(Integer)
    nutrition_info: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    spice_levels: Mapped[list] = mapped_column(JSON, nullable=False, default=lambda: ["Mild", "Medium", "Spicy"])
    sugar_levels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    removable_ingredients: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ingredients_text: Mapped[Optional[str]] = mapped_column(Text)
    average_rating: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    popularity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    insufficient_ingredients: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    category: Mapped["FoodCategory"] = relationship(back_populates="items")
    images: Mapped[list["FoodImage"]] = relationship(back_populates="food_item", cascade="all, delete-orphan")
    variants: Mapped[list["FoodVariant"]] = relationship(back_populates="food_item", cascade="all, delete-orphan")
    addon_links: Mapped[list["FoodItemAddon"]] = relationship(back_populates="food_item", cascade="all, delete-orphan")
    allergen_links: Mapped[list["FoodItemAllergen"]] = relationship(back_populates="food_item", cascade="all, delete-orphan")


class FoodImage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_images"

    food_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    alt_text: Mapped[Optional[str]] = mapped_column(String(160))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    food_item: Mapped["FoodItem"] = relationship(back_populates="images")


class FoodVariant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_variants"

    food_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # Regular, Large, Half, Full
    price_delta: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    absolute_price: Mapped[Optional[Decimal]] = mapped_column(Money)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    food_item: Mapped["FoodItem"] = relationship(back_populates="variants")


class FoodAddon(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_addons"

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    addon_type: Mapped[str] = mapped_column(String(48), nullable=False, default="addon")  # addon | topping | side
    price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    is_veg: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FoodItemAddon(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_item_addons"
    __table_args__ = (UniqueConstraint("food_item_id", "addon_id", name="uq_food_item_addons_pair"),)

    food_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    addon_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_addons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    max_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    food_item: Mapped["FoodItem"] = relationship(back_populates="addon_links")
    addon: Mapped["FoodAddon"] = relationship()


class Ingredient(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ingredients"
    __table_args__ = (UniqueConstraint("canteen_id", "sku", name="uq_ingredients_canteen_sku"),)

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="grams")  # grams, ml, pcs
    is_allergen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Recipe(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recipes"

    food_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    yield_portions: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(back_populates="recipe", cascade="all, delete-orphan")


class RecipeIngredient(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (UniqueConstraint("recipe_id", "ingredient_id", name="uq_recipe_ingredient_pair"),)

    recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingredients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity_required: Mapped[Decimal] = mapped_column(QuantityNumeric, nullable=False)

    recipe: Mapped["Recipe"] = relationship(back_populates="ingredients")
    ingredient: Mapped["Ingredient"] = relationship()


class Allergen(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "allergens"

    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))


class FoodItemAllergen(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "food_item_allergens"
    __table_args__ = (UniqueConstraint("food_item_id", "allergen_id", name="uq_food_item_allergen_pair"),)

    food_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    allergen_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("allergens.id", ondelete="CASCADE"), nullable=False, index=True
    )

    food_item: Mapped["FoodItem"] = relationship(back_populates="allergen_links")
    allergen: Mapped["Allergen"] = relationship()


class MenuSchedule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "menu_schedules"

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)  # Breakfast, Lunch, Snacks, Specials
    schedule_type: Mapped[str] = mapped_column(String(32), nullable=False, default="all_day")
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    days_of_week: Mapped[list] = mapped_column(JSON, nullable=False, default=lambda: [0, 1, 2, 3, 4, 5, 6])
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class MenuAvailability(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "menu_availability"
    __table_args__ = (UniqueConstraint("food_item_id", "menu_schedule_id", name="uq_menu_avail_item_sched"),)

    food_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("food_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    menu_schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("menu_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    override_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
