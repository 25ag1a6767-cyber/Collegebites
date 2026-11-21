import csv
import io
import re
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.college import Canteen
from app.models.menu import (
    Allergen,
    FoodAddon,
    FoodCategory,
    FoodImage,
    FoodItem,
    FoodItemAddon,
    FoodItemAllergen,
    FoodVariant,
    MenuSchedule,
)
from app.schemas.menu import (
    AllergenOut,
    FoodAddonCreate,
    FoodAddonOut,
    FoodCategoryCreate,
    FoodCategoryUpdate,
    FoodItemCreate,
    FoodItemOut,
    FoodItemUpdate,
    MenuScheduleCreate,
)
from app.services.audit_service import record_audit_log


def serialize_food_item(db: Session, item: FoodItem) -> FoodItemOut:
    category = db.get(FoodCategory, item.category_id)
    addons: list[FoodAddonOut] = []
    for link in item.addon_links:
        addon = db.get(FoodAddon, link.addon_id)
        if addon:
            addons.append(
                FoodAddonOut(
                    id=addon.id,
                    canteen_id=addon.canteen_id,
                    name=addon.name,
                    addon_type=addon.addon_type,
                    price=addon.price,
                    is_veg=addon.is_veg,
                    is_available=addon.is_available,
                    max_quantity=link.max_quantity,
                )
            )
    allergens: list[AllergenOut] = []
    for alink in item.allergen_links:
        alg = db.get(Allergen, alink.allergen_id)
        if alg:
            allergens.append(AllergenOut.model_validate(alg))

    return FoodItemOut(
        id=item.id,
        canteen_id=item.canteen_id,
        category_id=item.category_id,
        category_name=category.name if category else None,
        kitchen_id=item.kitchen_id,
        counter_id=item.counter_id,
        name=item.name,
        slug=item.slug,
        description=item.description,
        base_price=item.base_price,
        tax_rate_percent=item.tax_rate_percent,
        is_veg=item.is_veg,
        is_featured=item.is_featured,
        is_popular=item.is_popular,
        is_todays_special=item.is_todays_special,
        is_recommended=item.is_recommended,
        prep_time_minutes=item.prep_time_minutes,
        portion_size=item.portion_size,
        calories=item.calories,
        nutrition_info=item.nutrition_info,
        spice_levels=item.spice_levels or [],
        sugar_levels=item.sugar_levels or [],
        removable_ingredients=item.removable_ingredients or [],
        ingredients_text=item.ingredients_text,
        average_rating=item.average_rating,
        rating_count=item.rating_count,
        popularity_score=item.popularity_score,
        is_available=item.is_available,
        is_active=item.is_active,
        insufficient_ingredients=item.insufficient_ingredients,
        images=sorted(item.images, key=lambda x: (not x.is_primary, x.display_order)),
        variants=item.variants,
        addons=addons,
        allergens=allergens,
    )


def list_categories(db: Session, canteen_id: UUID, include_inactive: bool = False) -> list[FoodCategory]:
    stmt = select(FoodCategory).where(FoodCategory.canteen_id == canteen_id).order_by(FoodCategory.display_order, FoodCategory.name)
    if not include_inactive:
        stmt = stmt.where(FoodCategory.is_active.is_(True))
    return list(db.scalars(stmt).all())


def create_category(db: Session, payload: FoodCategoryCreate, actor_user_id: UUID) -> FoodCategory:
    if not db.get(Canteen, payload.canteen_id):
        raise HTTPException(status_code=404, detail="Canteen not found")
    dup = db.scalar(
        select(FoodCategory).where(FoodCategory.canteen_id == payload.canteen_id, FoodCategory.slug == payload.slug)
    )
    if dup:
        raise HTTPException(status_code=409, detail="Category slug already exists in this canteen")
    cat = FoodCategory(**payload.model_dump())
    db.add(cat)
    record_audit_log(db, action="category.created", entity_type="food_category", entity_id=payload.slug, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(cat)
    return cat


def update_category(db: Session, category_id: UUID, payload: FoodCategoryUpdate, actor_user_id: UUID) -> FoodCategory:
    cat = db.get(FoodCategory, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(cat, k, v)
    record_audit_log(db, action="category.updated", entity_type="food_category", entity_id=str(cat.id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(cat)
    return cat


def list_food_items(
    db: Session,
    canteen_id: UUID,
    *,
    q: Optional[str] = None,
    category_id: Optional[UUID] = None,
    is_veg: Optional[bool] = None,
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
    featured: Optional[bool] = None,
    popular: Optional[bool] = None,
    todays_special: Optional[bool] = None,
    recommended: Optional[bool] = None,
    available_only: bool = False,
    include_inactive: bool = False,
    sort_by: str = "popularity",
) -> list[FoodItemOut]:
    stmt = (
        select(FoodItem)
        .options(
            selectinload(FoodItem.images),
            selectinload(FoodItem.variants),
            selectinload(FoodItem.addon_links),
            selectinload(FoodItem.allergen_links),
        )
        .where(FoodItem.canteen_id == canteen_id)
    )
    if not include_inactive:
        stmt = stmt.where(FoodItem.is_active.is_(True))
    if available_only:
        stmt = stmt.where(FoodItem.is_available.is_(True), FoodItem.insufficient_ingredients.is_(False))
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(FoodItem.name.ilike(pattern), FoodItem.description.ilike(pattern), FoodItem.ingredients_text.ilike(pattern)))
    if category_id:
        stmt = stmt.where(FoodItem.category_id == category_id)
    if is_veg is not None:
        stmt = stmt.where(FoodItem.is_veg.is_(is_veg))
    if min_price is not None:
        stmt = stmt.where(FoodItem.base_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(FoodItem.base_price <= max_price)
    if featured is not None:
        stmt = stmt.where(FoodItem.is_featured.is_(featured))
    if popular is not None:
        stmt = stmt.where(FoodItem.is_popular.is_(popular))
    if todays_special is not None:
        stmt = stmt.where(FoodItem.is_todays_special.is_(todays_special))
    if recommended is not None:
        stmt = stmt.where(FoodItem.is_recommended.is_(recommended))

    if sort_by == "price_asc":
        stmt = stmt.order_by(FoodItem.base_price.asc(), FoodItem.name.asc())
    elif sort_by == "price_desc":
        stmt = stmt.order_by(FoodItem.base_price.desc(), FoodItem.name.asc())
    elif sort_by == "rating":
        stmt = stmt.order_by(FoodItem.average_rating.desc(), FoodItem.rating_count.desc())
    else:
        stmt = stmt.order_by(FoodItem.popularity_score.desc(), FoodItem.name.asc())

    items = db.scalars(stmt).all()
    return [serialize_food_item(db, item) for item in items]


def get_food_item(db: Session, item_id: UUID) -> FoodItemOut:
    item = db.scalar(
        select(FoodItem)
        .options(
            selectinload(FoodItem.images),
            selectinload(FoodItem.variants),
            selectinload(FoodItem.addon_links),
            selectinload(FoodItem.allergen_links),
        )
        .where(FoodItem.id == item_id)
    )
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    return serialize_food_item(db, item)


def create_food_item(db: Session, payload: FoodItemCreate, actor_user_id: UUID) -> FoodItemOut:
    if not db.get(Canteen, payload.canteen_id):
        raise HTTPException(status_code=404, detail="Canteen not found")
    cat = db.get(FoodCategory, payload.category_id)
    if not cat or cat.canteen_id != payload.canteen_id:
        raise HTTPException(status_code=400, detail="Invalid category for this canteen")
    dup = db.scalar(select(FoodItem).where(FoodItem.canteen_id == payload.canteen_id, FoodItem.slug == payload.slug))
    if dup:
        raise HTTPException(status_code=409, detail="Food item slug already exists in this canteen")

    data = payload.model_dump(exclude={"image_url", "variants", "addon_ids", "allergen_names"})
    item = FoodItem(**data)
    db.add(item)
    db.flush()

    if payload.image_url:
        db.add(FoodImage(food_item_id=item.id, image_url=payload.image_url, alt_text=item.name, is_primary=True))

    if payload.variants:
        for v in payload.variants:
            db.add(FoodVariant(food_item_id=item.id, **v.model_dump()))
    else:
        db.add(FoodVariant(food_item_id=item.id, name="Regular", price_delta=Decimal("0.00"), is_default=True))

    for addon_id in payload.addon_ids:
        addon = db.get(FoodAddon, addon_id)
        if addon:
            db.add(FoodItemAddon(food_item_id=item.id, addon_id=addon.id))

    for alg_name in payload.allergen_names:
        alg = db.scalar(select(Allergen).where(Allergen.name.ilike(alg_name.strip())))
        if not alg:
            alg = Allergen(name=alg_name.strip())
            db.add(alg)
            db.flush()
        db.add(FoodItemAllergen(food_item_id=item.id, allergen_id=alg.id))

    record_audit_log(
        db,
        action="food_item.created",
        entity_type="food_item",
        entity_id=str(item.id),
        actor_user_id=actor_user_id,
        details={"name": item.name, "base_price": str(item.base_price)},
    )
    db.commit()
    return get_food_item(db, item.id)


def update_food_item(db: Session, item_id: UUID, payload: FoodItemUpdate, actor_user_id: UUID) -> FoodItemOut:
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")

    updates = payload.model_dump(exclude_unset=True, exclude={"image_url", "addon_ids"})
    for k, v in updates.items():
        setattr(item, k, v)

    if payload.image_url is not None:
        existing_primary = db.scalar(
            select(FoodImage).where(FoodImage.food_item_id == item.id, FoodImage.is_primary.is_(True))
        )
        if existing_primary:
            existing_primary.image_url = payload.image_url
        else:
            db.add(FoodImage(food_item_id=item.id, image_url=payload.image_url, alt_text=item.name, is_primary=True))

    if payload.addon_ids is not None:
        old_links = db.scalars(select(FoodItemAddon).where(FoodItemAddon.food_item_id == item.id)).all()
        for link in old_links:
            db.delete(link)
        db.flush()
        for addon_id in payload.addon_ids:
            if db.get(FoodAddon, addon_id):
                db.add(FoodItemAddon(food_item_id=item.id, addon_id=addon_id))

    record_audit_log(
        db,
        action="food_item.updated",
        entity_type="food_item",
        entity_id=str(item.id),
        actor_user_id=actor_user_id,
        details=payload.model_dump(exclude_unset=True, mode="json"),
    )
    db.commit()
    return get_food_item(db, item.id)


def create_addon(db: Session, payload: FoodAddonCreate, actor_user_id: UUID) -> FoodAddon:
    addon = FoodAddon(**payload.model_dump())
    db.add(addon)
    record_audit_log(db, action="addon.created", entity_type="food_addon", entity_id=payload.name, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(addon)
    return addon


def list_addons(db: Session, canteen_id: UUID) -> list[FoodAddon]:
    return list(db.scalars(select(FoodAddon).where(FoodAddon.canteen_id == canteen_id).order_by(FoodAddon.name)).all())


def list_schedules(db: Session, canteen_id: UUID) -> list[MenuSchedule]:
    return list(db.scalars(select(MenuSchedule).where(MenuSchedule.canteen_id == canteen_id).order_by(MenuSchedule.start_time)).all())


def create_schedule(db: Session, payload: MenuScheduleCreate, actor_user_id: UUID) -> MenuSchedule:
    sched = MenuSchedule(**payload.model_dump())
    db.add(sched)
    record_audit_log(db, action="menu_schedule.created", entity_type="menu_schedule", entity_id=payload.name, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(sched)
    return sched


def export_menu_csv(db: Session, canteen_id: UUID) -> str:
    items = list_food_items(db, canteen_id, include_inactive=True)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "slug", "category", "base_price", "is_veg", "prep_time_minutes", "portion_size", "is_available", "is_active", "description"])
    for it in items:
        writer.writerow([
            it.name,
            it.slug,
            it.category_name or "General",
            f"{it.base_price:.2f}",
            "true" if it.is_veg else "false",
            it.prep_time_minutes,
            it.portion_size or "",
            "true" if it.is_available else "false",
            "true" if it.is_active else "false",
            it.description or "",
        ])
    return buf.getvalue()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def import_menu_csv(db: Session, canteen_id: UUID, csv_text: str, actor_user_id: UUID) -> dict:
    if not db.get(Canteen, canteen_id):
        raise HTTPException(status_code=404, detail="Canteen not found")

    reader = csv.DictReader(io.StringIO(csv_text))
    created_count = 0
    updated_count = 0

    for row in reader:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        cat_name = (row.get("category") or "General").strip()
        cat_slug = _slugify(cat_name)
        cat = db.scalar(select(FoodCategory).where(FoodCategory.canteen_id == canteen_id, FoodCategory.slug == cat_slug))
        if not cat:
            cat = FoodCategory(canteen_id=canteen_id, name=cat_name, slug=cat_slug)
            db.add(cat)
            db.flush()

        item_slug = _slugify((row.get("slug") or name).strip())
        base_price = Decimal(str(row.get("base_price") or "0.00")).quantize(Decimal("0.01"))
        is_veg = str(row.get("is_veg") or "true").lower() in ("true", "1", "yes", "veg")
        prep_time = int(row.get("prep_time_minutes") or 10)
        is_avail = str(row.get("is_available") or "true").lower() in ("true", "1", "yes")
        is_active = str(row.get("is_active") or "true").lower() in ("true", "1", "yes")

        existing = db.scalar(select(FoodItem).where(FoodItem.canteen_id == canteen_id, FoodItem.slug == item_slug))
        if existing:
            existing.name = name
            existing.category_id = cat.id
            existing.base_price = base_price
            existing.is_veg = is_veg
            existing.prep_time_minutes = prep_time
            existing.is_available = is_avail
            existing.is_active = is_active
            existing.portion_size = row.get("portion_size") or existing.portion_size
            existing.description = row.get("description") or existing.description
            updated_count += 1
        else:
            item = FoodItem(
                canteen_id=canteen_id,
                category_id=cat.id,
                name=name,
                slug=item_slug,
                base_price=base_price,
                is_veg=is_veg,
                prep_time_minutes=prep_time,
                portion_size=row.get("portion_size") or None,
                description=row.get("description") or None,
                is_available=is_avail,
                is_active=is_active,
            )
            db.add(item)
            db.flush()
            db.add(FoodVariant(food_item_id=item.id, name="Regular", price_delta=Decimal("0.00"), is_default=True))
            created_count += 1

    record_audit_log(
        db,
        action="menu.csv_imported",
        entity_type="canteen",
        entity_id=str(canteen_id),
        actor_user_id=actor_user_id,
        details={"created": created_count, "updated": updated_count},
    )
    db.commit()
    return {"created": created_count, "updated": updated_count}
