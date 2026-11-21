from datetime import datetime, time
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class FoodCategoryCreate(BaseModel):
    canteen_id: UUID
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=120, pattern="^[a-z0-9-]+$")
    description: Optional[str] = None
    display_order: int = 0


class FoodCategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    description: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class FoodCategoryOut(ORMModel):
    id: UUID
    canteen_id: UUID
    name: str
    slug: str
    description: Optional[str]
    display_order: int
    is_active: bool


class FoodVariantIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price_delta: Decimal = Field(default=Decimal("0.00"))
    absolute_price: Optional[Decimal] = Field(default=None, ge=0)
    is_default: bool = False
    is_available: bool = True


class FoodVariantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    price_delta: Optional[Decimal] = None
    absolute_price: Optional[Decimal] = Field(default=None, ge=0)
    is_default: Optional[bool] = None
    is_available: Optional[bool] = None


class FoodVariantOut(ORMModel):
    id: UUID
    name: str
    price_delta: Decimal
    absolute_price: Optional[Decimal]
    is_default: bool
    is_available: bool


class FoodAddonCreate(BaseModel):
    canteen_id: UUID
    name: str = Field(min_length=1, max_length=120)
    addon_type: str = Field(default="addon", pattern="^(addon|topping|side)$")
    price: Decimal = Field(ge=0)
    is_veg: bool = True
    is_available: bool = True


class FoodAddonUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    addon_type: Optional[str] = Field(default=None, pattern="^(addon|topping|side)$")
    price: Optional[Decimal] = Field(default=None, ge=0)
    is_veg: Optional[bool] = None
    is_available: Optional[bool] = None


class FoodAddonOut(ORMModel):
    id: UUID
    canteen_id: UUID
    name: str
    addon_type: str
    price: Decimal
    is_veg: bool
    is_available: bool
    max_quantity: int = 5


class FoodImageOut(ORMModel):
    id: UUID
    image_url: str
    alt_text: Optional[str]
    is_primary: bool
    display_order: int


class AllergenOut(ORMModel):
    id: UUID
    name: str
    description: Optional[str]


class FoodItemCreate(BaseModel):
    canteen_id: UUID
    category_id: UUID
    kitchen_id: Optional[UUID] = None
    counter_id: Optional[UUID] = None
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=160, pattern="^[a-z0-9-]+$")
    description: Optional[str] = None
    base_price: Decimal = Field(ge=0)
    tax_rate_percent: Optional[Decimal] = Field(default=None, ge=0, le=50)
    is_veg: bool = True
    is_featured: bool = False
    is_popular: bool = False
    is_todays_special: bool = False
    is_recommended: bool = False
    prep_time_minutes: int = Field(default=10, ge=1, le=180)
    portion_size: Optional[str] = None
    calories: Optional[int] = Field(default=None, ge=0)
    nutrition_info: Optional[dict[str, Any]] = None
    spice_levels: list[str] = ["Mild", "Medium", "Spicy"]
    sugar_levels: list[str] = []
    removable_ingredients: list[str] = []
    ingredients_text: Optional[str] = None
    image_url: Optional[str] = None
    variants: list[FoodVariantIn] = []
    addon_ids: list[UUID] = []
    allergen_names: list[str] = []


class FoodItemUpdate(BaseModel):
    category_id: Optional[UUID] = None
    kitchen_id: Optional[UUID] = None
    counter_id: Optional[UUID] = None
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = None
    base_price: Optional[Decimal] = Field(default=None, ge=0)
    tax_rate_percent: Optional[Decimal] = Field(default=None, ge=0, le=50)
    is_veg: Optional[bool] = None
    is_featured: Optional[bool] = None
    is_popular: Optional[bool] = None
    is_todays_special: Optional[bool] = None
    is_recommended: Optional[bool] = None
    prep_time_minutes: Optional[int] = Field(default=None, ge=1, le=180)
    portion_size: Optional[str] = None
    calories: Optional[int] = None
    nutrition_info: Optional[dict[str, Any]] = None
    spice_levels: Optional[list[str]] = None
    sugar_levels: Optional[list[str]] = None
    removable_ingredients: Optional[list[str]] = None
    ingredients_text: Optional[str] = None
    image_url: Optional[str] = None
    is_available: Optional[bool] = None
    is_active: Optional[bool] = None
    addon_ids: Optional[list[UUID]] = None
    allergen_names: Optional[list[str]] = None


class FoodItemOut(ORMModel):
    id: UUID
    canteen_id: UUID
    category_id: UUID
    category_name: Optional[str] = None
    kitchen_id: Optional[UUID]
    counter_id: Optional[UUID]
    name: str
    slug: str
    description: Optional[str]
    base_price: Decimal
    tax_rate_percent: Optional[Decimal]
    is_veg: bool
    is_featured: bool
    is_popular: bool
    is_todays_special: bool
    is_recommended: bool
    prep_time_minutes: int
    portion_size: Optional[str]
    calories: Optional[int]
    nutrition_info: Optional[dict[str, Any]]
    spice_levels: list[str]
    sugar_levels: list[str]
    removable_ingredients: list[str]
    ingredients_text: Optional[str]
    average_rating: Decimal
    rating_count: int
    popularity_score: int
    is_available: bool
    is_active: bool
    insufficient_ingredients: bool
    is_schedule_active_now: bool = True
    images: list[FoodImageOut] = []
    variants: list[FoodVariantOut] = []
    addons: list[FoodAddonOut] = []
    allergens: list[AllergenOut] = []


class MenuScheduleCreate(BaseModel):
    canteen_id: UUID
    name: str = Field(min_length=2, max_length=120)
    schedule_type: str = Field(default="all_day", pattern="^(breakfast|lunch|snacks|special|all_day)$")
    start_time: time
    end_time: time
    days_of_week: list[int] = [0, 1, 2, 3, 4, 5, 6]


class MenuScheduleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    schedule_type: Optional[str] = Field(default=None, pattern="^(breakfast|lunch|snacks|special|all_day)$")
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    days_of_week: Optional[list[int]] = None
    is_active: Optional[bool] = None


class MenuScheduleAssignItemsIn(BaseModel):
    food_item_ids: list[UUID]


class MenuScheduleOut(ORMModel):
    id: UUID
    canteen_id: UUID
    name: str
    schedule_type: str
    start_time: time
    end_time: time
    days_of_week: list[int]
    is_active: bool
    scheduled_item_ids: list[UUID] = []


class CustomerProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    phone: Optional[str] = Field(default=None, min_length=8, max_length=20)
    college_id_number: Optional[str] = None
    department: Optional[str] = None
    dietary_preference: Optional[str] = None
    default_canteen_id: Optional[UUID] = None
    notification_opt_in: Optional[bool] = None


class CustomerProfileOut(BaseModel):
    user_id: UUID
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    college_id_number: Optional[str]
    department: Optional[str]
    dietary_preference: Optional[str]
    default_canteen_id: Optional[UUID]
    favourite_item_ids: list[str]
    notification_opt_in: bool
    loyalty_points: int = 0
    loyalty_tier: str = "BRONZE"
    referral_code: Optional[str] = None
