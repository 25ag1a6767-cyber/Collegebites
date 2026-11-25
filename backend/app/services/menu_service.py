import csv
import io
import re
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.cache import NS_MENU, cache_manager, invalidate_menu
from app.core.time_utils import get_college_tz, now_college
from app.models.auth import User
from app.models.college import Canteen, CollegeSettings, Kitchen, KitchenStation
from app.models.order import CartItem, OrderItem
from app.models.menu import (
    Allergen,
    FoodAddon,
    FoodCategory,
    FoodImage,
    FoodItem,
    FoodItemAddon,
    FoodItemAllergen,
    FoodVariant,
    MenuAvailability,
    MenuRestoreApproval,
    MenuSchedule,
)
from app.schemas.menu import (
    AllergenOut,
    FoodAddonCreate,
    FoodAddonOut,
    FoodAddonUpdate,
    FoodCategoryCreate,
    FoodCategoryUpdate,
    FoodItemAddonCreate,
    FoodItemCreate,
    FoodItemOut,
    FoodItemUpdate,
    FoodVariantIn,
    FoodVariantUpdate,
    MenuScheduleCreate,
    MenuScheduleOut,
    MenuScheduleUpdate,
)
from app.services.audit_service import record_audit_log


def _time_in_window(cur_time: time, start_time: time, end_time: time) -> bool:
    if start_time <= end_time:
        return start_time <= cur_time <= end_time
    # Overnight window (e.g. 22:00 to 02:00)
    return cur_time >= start_time or cur_time <= end_time


def _item_date_time_ok(item: Optional[FoodItem], check_dt: datetime) -> bool:
    if item is None:
        return True
    cur_date = check_dt.date()
    cur_time = check_dt.time()
    if getattr(item, "valid_from", None) and cur_date < item.valid_from:
        return False
    if getattr(item, "valid_until", None) and cur_date > item.valid_until:
        return False
    avail_from = getattr(item, "available_from_time", None)
    avail_until = getattr(item, "available_until_time", None)
    if avail_from and avail_until:
        if not _time_in_window(cur_time, avail_from, avail_until):
            return False
    elif avail_from and cur_time < avail_from:
        return False
    elif avail_until and cur_time > avail_until:
        return False
    return True


def compute_schedule_availability_map(
    db: Session,
    food_item_ids: list[UUID],
    *,
    target_dt: Optional[datetime] = None,
    food_items_map: Optional[dict[UUID, FoodItem]] = None,
) -> dict[UUID, bool]:
    """Return {food_item_id: is_schedule_and_window_active}. Evaluates item windows and MenuSchedule rules."""
    if not food_item_ids:
        return {}

    from app.services.college_service import get_college_config_snapshot

    tz_name = get_college_config_snapshot(db).get("college_timezone")
    if target_dt is not None:
        tz = get_college_tz(tz_name)
        now_dt = target_dt.astimezone(tz) if target_dt.tzinfo else target_dt.replace(tzinfo=tz)
    else:
        now_dt = now_college(tz_name)
    cur_time = now_dt.time()
    cur_date = now_dt.date()
    cur_date_iso = cur_date.isoformat()
    weekday = now_dt.weekday()

    if food_items_map is None:
        food_items_map = {
            f.id: f for f in db.scalars(select(FoodItem).where(FoodItem.id.in_(food_item_ids))).all()
        }

    links = db.scalars(
        select(MenuAvailability).where(MenuAvailability.food_item_id.in_(food_item_ids))
    ).all()
    scheds: dict[UUID, MenuSchedule] = {}
    if links:
        sched_ids = {l.menu_schedule_id for l in links}
        scheds = {
            s.id: s for s in db.scalars(select(MenuSchedule).where(MenuSchedule.id.in_(list(sched_ids)))).all()
        }

    links_by_item: dict[UUID, list[MenuAvailability]] = {}
    for l in links:
        if l.menu_schedule_id in scheds:
            links_by_item.setdefault(l.food_item_id, []).append(l)

    out: dict[UUID, bool] = {}
    for fid in food_item_ids:
        if not _item_date_time_ok(food_items_map.get(fid), now_dt):
            out[fid] = False
            continue

        item_links = links_by_item.get(fid)
        if not item_links:
            out[fid] = True
            continue
        active_now = False
        for l in item_links:
            if not l.is_available:
                continue
            if l.override_until and l.override_until <= now_dt:
                continue
            sched = scheds.get(l.menu_schedule_id)
            if not sched or not sched.is_active:
                continue
            if getattr(sched, "valid_from", None) and cur_date < sched.valid_from:
                continue
            if getattr(sched, "valid_until", None) and cur_date > sched.valid_until:
                continue
            sp_dates = getattr(sched, "special_dates", None) or []
            if sp_dates:
                if cur_date_iso not in sp_dates:
                    continue
            elif weekday not in (sched.days_of_week or []):
                continue
            if _time_in_window(cur_time, sched.start_time, sched.end_time):
                active_now = True
                break
        out[fid] = active_now
    return out


def serialize_food_item(
    db: Session,
    item: FoodItem,
    *,
    category_map: Optional[dict[UUID, FoodCategory]] = None,
    addon_map: Optional[dict[UUID, FoodAddon]] = None,
    allergen_map: Optional[dict[UUID, Allergen]] = None,
    schedule_active_map: Optional[dict[UUID, bool]] = None,
    station_map: Optional[dict[UUID, KitchenStation]] = None,
) -> FoodItemOut:
    category = category_map.get(item.category_id) if category_map is not None else db.get(FoodCategory, item.category_id)
    addons: list[FoodAddonOut] = []
    for link in item.addon_links:
        addon = addon_map.get(link.addon_id) if addon_map is not None else db.get(FoodAddon, link.addon_id)
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
        alg = allergen_map.get(alink.allergen_id) if allergen_map is not None else db.get(Allergen, alink.allergen_id)
        if alg:
            allergens.append(AllergenOut.model_validate(alg))

    if schedule_active_map is not None:
        sched_ok = schedule_active_map.get(item.id, True)
    else:
        sched_ok = compute_schedule_availability_map(db, [item.id]).get(item.id, True)

    if item.station_id:
        station = station_map.get(item.station_id) if station_map is not None else db.get(KitchenStation, item.station_id)
    else:
        station = None
    cat_active = bool(category.is_active) if category else True
    pending_restore = bool(getattr(item, "pending_restore_approval", False))
    avail_to_order = bool(item.is_active and cat_active and item.is_available and not item.insufficient_ingredients and sched_ok)

    return FoodItemOut(
        id=item.id,
        canteen_id=item.canteen_id,
        category_id=item.category_id,
        category_name=category.name if category else None,
        kitchen_id=item.kitchen_id,
        station_id=item.station_id,
        station_name=station.name if station else None,
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
        nutrition_verified=bool(getattr(item, "nutrition_verified", False)),
        nutrition_disclaimer=(
            "Verified nutrition & allergen information"
            if bool(getattr(item, "nutrition_verified", False))
            else "Nutrition and allergen information is unverified or unavailable; please consult canteen staff for severe allergies."
        ),
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
        pending_restore_approval=pending_restore,
        category_is_active=cat_active,
        is_schedule_active_now=sched_ok,
        is_available_to_order=avail_to_order,
        available_from_time=getattr(item, "available_from_time", None),
        available_until_time=getattr(item, "available_until_time", None),
        valid_from=getattr(item, "valid_from", None),
        valid_until=getattr(item, "valid_until", None),
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


def list_categories_cached(db: Session, canteen_id: UUID, include_inactive: bool = False) -> list[dict]:
    from app.schemas.menu import FoodCategoryOut

    cache_ns = f"{NS_MENU}:{canteen_id}"
    cache_key = f"cats:inc={int(bool(include_inactive))}"
    hit, cached = cache_manager.get_json(cache_ns, cache_key, l1_ttl=3.0)
    if hit and isinstance(cached, list):
        return cached
    canteen = db.get(Canteen, canteen_id)
    if not canteen or (not include_inactive and not canteen.is_active):
        raise HTTPException(status_code=404, detail="Canteen not found")
    rows = list_categories(db, canteen_id, include_inactive=include_inactive)
    out = [FoodCategoryOut.model_validate(c).model_dump(mode="json") for c in rows]
    cache_manager.set_json(cache_ns, cache_key, out, ttl_seconds=60, l1_ttl=3.0)
    return out


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
    invalidate_menu(payload.canteen_id)
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
    invalidate_menu(cat.canteen_id)
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
    cache_ns = f"{NS_MENU}:{canteen_id}"
    q_norm = (q or "").strip().lower()
    cache_key = (
        f"items:q={q_norm}|cat={category_id}|veg={is_veg}|min={min_price}|max={max_price}|"
        f"feat={featured}|pop={popular}|spec={todays_special}|rec={recommended}|"
        f"avail={int(bool(available_only))}|inc={int(bool(include_inactive))}|sort={sort_by}"
    )
    hit, cached = cache_manager.get_json(cache_ns, cache_key, l1_ttl=2.0)
    if hit and isinstance(cached, list):
        return [FoodItemOut.model_validate(x) for x in cached]

    canteen = db.get(Canteen, canteen_id)
    if not canteen or (not include_inactive and not canteen.is_active):
        raise HTTPException(status_code=404, detail="Canteen not found")

    stmt = (
        select(FoodItem)
        .join(FoodCategory, FoodCategory.id == FoodItem.category_id)
        .options(
            selectinload(FoodItem.images),
            selectinload(FoodItem.variants),
            selectinload(FoodItem.addon_links),
            selectinload(FoodItem.allergen_links),
        )
        .where(FoodItem.canteen_id == canteen_id)
    )
    if not include_inactive:
        stmt = stmt.where(FoodItem.is_active.is_(True), FoodCategory.is_active.is_(True))
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
    if not items:
        cache_manager.set_json(cache_ns, cache_key, [], ttl_seconds=10 if q_norm else 20, l1_ttl=2.0)
        return []
    cat_ids = list({i.category_id for i in items})
    addon_ids = list({lnk.addon_id for i in items for lnk in i.addon_links})
    allergen_ids = list({alnk.allergen_id for i in items for alnk in i.allergen_links})
    station_ids = list({i.station_id for i in items if i.station_id})
    cat_map = {c.id: c for c in db.scalars(select(FoodCategory).where(FoodCategory.id.in_(cat_ids))).all()} if cat_ids else {}
    addon_map = {a.id: a for a in db.scalars(select(FoodAddon).where(FoodAddon.id.in_(addon_ids))).all()} if addon_ids else {}
    alg_map = {a.id: a for a in db.scalars(select(Allergen).where(Allergen.id.in_(allergen_ids))).all()} if allergen_ids else {}
    station_map = {s.id: s for s in db.scalars(select(KitchenStation).where(KitchenStation.id.in_(station_ids))).all()} if station_ids else {}
    sched_map = compute_schedule_availability_map(
        db,
        [i.id for i in items],
        food_items_map={i.id: i for i in items},
    )

    serialized = [
        serialize_food_item(
            db,
            item,
            category_map=cat_map,
            addon_map=addon_map,
            allergen_map=alg_map,
            schedule_active_map=sched_map,
            station_map=station_map,
        )
        for item in items
    ]
    if available_only:
        serialized = [s for s in serialized if s.is_schedule_active_now]
    cache_manager.set_json(
        cache_ns,
        cache_key,
        [s.model_dump(mode="json") for s in serialized],
        ttl_seconds=10 if q_norm else 20,
        l1_ttl=2.0,
    )
    return serialized


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


def _validate_station_for_canteen(db: Session, canteen_id: UUID, station_id: Optional[UUID]) -> None:
    if not station_id:
        return
    station = db.scalar(
        select(KitchenStation)
        .join(Kitchen, Kitchen.id == KitchenStation.kitchen_id)
        .where(KitchenStation.id == station_id, Kitchen.canteen_id == canteen_id)
    )
    if not station:
        raise HTTPException(status_code=400, detail="Invalid kitchen station for this canteen")


def create_food_item(db: Session, payload: FoodItemCreate, actor_user_id: UUID) -> FoodItemOut:
    if not db.get(Canteen, payload.canteen_id):
        raise HTTPException(status_code=404, detail="Canteen not found")
    cat = db.get(FoodCategory, payload.category_id)
    if not cat or cat.canteen_id != payload.canteen_id:
        raise HTTPException(status_code=400, detail="Invalid category for this canteen")
    _validate_station_for_canteen(db, payload.canteen_id, payload.station_id)
    dup = db.scalar(select(FoodItem).where(FoodItem.canteen_id == payload.canteen_id, FoodItem.slug == payload.slug))
    if dup:
        raise HTTPException(status_code=409, detail="Food item slug already exists in this canteen")

    data = payload.model_dump(exclude={"image_url", "variants", "addon_ids", "allergen_names"})
    data["tax_rate_percent"] = Decimal("0.00")
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
        if addon and addon.canteen_id == item.canteen_id:
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
    invalidate_menu(item.canteen_id)
    return get_food_item(db, item.id)


def update_food_item(db: Session, item_id: UUID, payload: FoodItemUpdate, actor_user_id: UUID) -> FoodItemOut:
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")

    if payload.category_id is not None:
        cat = db.get(FoodCategory, payload.category_id)
        if not cat or cat.canteen_id != item.canteen_id:
            raise HTTPException(status_code=400, detail="Invalid category for this canteen")
    if payload.station_id is not None:
        _validate_station_for_canteen(db, item.canteen_id, payload.station_id)
    slug_val = getattr(payload, "slug", None)
    if slug_val is not None and slug_val != item.slug:
        dup = db.scalar(select(FoodItem).where(FoodItem.canteen_id == item.canteen_id, FoodItem.slug == slug_val))
        if dup and dup.id != item.id:
            raise HTTPException(status_code=409, detail="Food item slug already exists in this canteen")

    updates = payload.model_dump(exclude_unset=True, exclude={"image_url", "addon_ids", "allergen_names"})
    if "tax_rate_percent" in updates:
        updates["tax_rate_percent"] = Decimal("0.00")
    for k, v in updates.items():
        setattr(item, k, v)
    if payload.is_available is True and not item.insufficient_ingredients:
        item.pending_restore_approval = False
        pending_reqs = db.scalars(
            select(MenuRestoreApproval).where(
                MenuRestoreApproval.food_item_id == item.id,
                MenuRestoreApproval.status == "pending_approval",
            )
        ).all()
        now_utc = datetime.now(timezone.utc)
        for req in pending_reqs:
            req.status = "approved"
            req.reviewed_by_user_id = actor_user_id
            req.reviewed_at = now_utc
            req.review_notes = "Approved via menu item update"

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
            addon = db.get(FoodAddon, addon_id)
            if addon and addon.canteen_id == item.canteen_id:
                db.add(FoodItemAddon(food_item_id=item.id, addon_id=addon_id))

    if payload.allergen_names is not None:
        for old_al in db.scalars(select(FoodItemAllergen).where(FoodItemAllergen.food_item_id == item.id)).all():
            db.delete(old_al)
        db.flush()
        for alg_name in payload.allergen_names:
            clean = alg_name.strip()
            if not clean:
                continue
            alg = db.scalar(select(Allergen).where(Allergen.name.ilike(clean)))
            if not alg:
                alg = Allergen(name=clean)
                db.add(alg)
                db.flush()
            db.add(FoodItemAllergen(food_item_id=item.id, allergen_id=alg.id))

    record_audit_log(
        db,
        action="food_item.updated",
        entity_type="food_item",
        entity_id=str(item.id),
        actor_user_id=actor_user_id,
        details=payload.model_dump(exclude_unset=True, mode="json"),
    )
    db.commit()
    invalidate_menu(item.canteen_id)
    return get_food_item(db, item.id)


def delete_food_item(db: Session, item_id: UUID, actor_user_id: UUID) -> dict:
    """Delete an un-ordered food item permanently, or archive it when past order records exist."""
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")

    order_ref_count = int(
        db.scalar(select(func.count(OrderItem.id)).where(OrderItem.food_item_id == item.id)) or 0
    )
    if order_ref_count > 0:
        item.is_active = False
        item.is_available = False
        db.execute(delete(CartItem).where(CartItem.food_item_id == item.id))
        record_audit_log(
            db,
            action="food_item.archived",
            entity_type="food_item",
            entity_id=str(item.id),
            actor_user_id=actor_user_id,
            details={"name": item.name, "order_ref_count": order_ref_count},
        )
        db.commit()
        invalidate_menu(item.canteen_id)
        return {
            "status": "archived",
            "id": str(item_id),
            "name": item.name,
            "message": f"'{item.name}' has {order_ref_count} historical order line(s) and was deactivated from the menu.",
        }

    item_name = item.name
    item_canteen_id = item.canteen_id
    db.execute(delete(CartItem).where(CartItem.food_item_id == item.id))
    db.delete(item)
    record_audit_log(
        db,
        action="food_item.deleted",
        entity_type="food_item",
        entity_id=str(item_id),
        actor_user_id=actor_user_id,
        details={"name": item_name},
    )
    db.commit()
    invalidate_menu(item_canteen_id)
    return {
        "status": "deleted",
        "id": str(item_id),
        "name": item_name,
        "message": f"'{item_name}' permanently deleted from the menu.",
    }


def set_food_item_primary_image(db: Session, item_id: UUID, image_url: str, actor_user_id: UUID) -> FoodItemOut:
    """Replace or set the primary image for a food item and record an audit entry."""
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    existing_primary = db.scalar(
        select(FoodImage).where(FoodImage.food_item_id == item.id, FoodImage.is_primary.is_(True))
    )
    if existing_primary:
        existing_primary.image_url = image_url
    else:
        db.add(FoodImage(food_item_id=item.id, image_url=image_url, alt_text=item.name, is_primary=True))
    record_audit_log(
        db,
        action="food_item.image_uploaded",
        entity_type="food_item",
        entity_id=str(item.id),
        actor_user_id=actor_user_id,
        details={"is_data_uri": image_url.startswith("data:")},
    )
    db.commit()
    invalidate_menu(item.canteen_id)
    return get_food_item(db, item.id)


def create_addon(db: Session, payload: FoodAddonCreate, actor_user_id: UUID) -> FoodAddon:
    addon = FoodAddon(**payload.model_dump())
    db.add(addon)
    record_audit_log(db, action="addon.created", entity_type="food_addon", entity_id=payload.name, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(addon)
    invalidate_menu(addon.canteen_id)
    return addon


def update_addon(db: Session, addon: FoodAddon, payload: FoodAddonUpdate, actor_user_id: UUID) -> FoodAddon:
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(addon, k, v)
    record_audit_log(db, action="addon.updated", entity_type="food_addon", entity_id=str(addon.id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(addon)
    invalidate_menu(addon.canteen_id)
    return addon


def list_addons(db: Session, canteen_id: UUID) -> list[FoodAddon]:
    return list(db.scalars(select(FoodAddon).where(FoodAddon.canteen_id == canteen_id).order_by(FoodAddon.name)).all())


def add_addon_to_food_item(db: Session, item_id: UUID, payload: FoodItemAddonCreate, actor_user_id: UUID) -> FoodAddon:
    """Create or reuse a canteen add-on and link it to the specified food item."""
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")

    clean_name = payload.name.strip()
    addon = db.scalar(
        select(FoodAddon).where(
            FoodAddon.canteen_id == item.canteen_id,
            func.lower(FoodAddon.name) == clean_name.lower(),
            FoodAddon.price == payload.price,
        )
    )
    if not addon:
        addon = FoodAddon(
            canteen_id=item.canteen_id,
            name=clean_name,
            addon_type=payload.addon_type,
            price=payload.price,
            is_veg=payload.is_veg,
            is_available=payload.is_available,
        )
        db.add(addon)
        db.flush()

    existing_link = db.scalar(
        select(FoodItemAddon).where(FoodItemAddon.food_item_id == item.id, FoodItemAddon.addon_id == addon.id)
    )
    if existing_link:
        existing_link.max_quantity = payload.max_quantity
    else:
        db.add(FoodItemAddon(food_item_id=item.id, addon_id=addon.id, max_quantity=payload.max_quantity))

    record_audit_log(
        db,
        action="food_item.addon_linked",
        entity_type="food_item",
        entity_id=str(item.id),
        actor_user_id=actor_user_id,
        details={"addon_id": str(addon.id), "addon_name": addon.name, "price": str(addon.price)},
    )
    db.commit()
    db.refresh(addon)
    invalidate_menu(item.canteen_id)
    return addon


def unlink_addon_from_food_item(db: Session, item_id: UUID, addon_id: UUID, actor_user_id: UUID) -> dict:
    """Unlink an add-on from a food item cleanly."""
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    link = db.scalar(
        select(FoodItemAddon).where(FoodItemAddon.food_item_id == item.id, FoodItemAddon.addon_id == addon_id)
    )
    if not link:
        raise HTTPException(status_code=404, detail="Add-on link not found on this food item")
    db.delete(link)
    record_audit_log(
        db,
        action="food_item.addon_unlinked",
        entity_type="food_item",
        entity_id=str(item.id),
        actor_user_id=actor_user_id,
        details={"addon_id": str(addon_id)},
    )
    db.commit()
    invalidate_menu(item.canteen_id)
    return {"status": "removed", "item_id": str(item_id), "addon_id": str(addon_id)}


def _serialize_schedule(db: Session, sched: MenuSchedule) -> MenuScheduleOut:
    item_ids = list(
        db.scalars(
            select(MenuAvailability.food_item_id).where(
                MenuAvailability.menu_schedule_id == sched.id, MenuAvailability.is_available.is_(True)
            )
        ).all()
    )
    return MenuScheduleOut(
        id=sched.id,
        canteen_id=sched.canteen_id,
        name=sched.name,
        schedule_type=sched.schedule_type,
        start_time=sched.start_time,
        end_time=sched.end_time,
        days_of_week=sched.days_of_week or [],
        valid_from=getattr(sched, "valid_from", None),
        valid_until=getattr(sched, "valid_until", None),
        special_dates=getattr(sched, "special_dates", None) or [],
        is_special_event=bool(getattr(sched, "is_special_event", False)),
        event_name=getattr(sched, "event_name", None),
        is_active=sched.is_active,
        scheduled_item_ids=item_ids,
    )


def list_restore_approvals(
    db: Session,
    canteen_id: UUID,
    *,
    status_filter: Optional[str] = None,
) -> list[dict]:
    stmt = (
        select(MenuRestoreApproval, FoodItem.name, FoodItem.insufficient_ingredients, FoodItem.is_available)
        .join(FoodItem, FoodItem.id == MenuRestoreApproval.food_item_id)
        .where(MenuRestoreApproval.canteen_id == canteen_id)
        .order_by(MenuRestoreApproval.created_at.desc())
    )
    if status_filter and status_filter != "all":
        stmt = stmt.where(MenuRestoreApproval.status == status_filter)
    rows = db.execute(stmt.limit(100)).all()
    reviewer_ids = {req.reviewed_by_user_id for req, _, _, _ in rows if req.reviewed_by_user_id}
    user_map = (
        {u.id: (u.full_name or u.email or str(u.id)) for u in db.scalars(select(User).where(User.id.in_(reviewer_ids))).all()}
        if reviewer_ids
        else {}
    )
    return [
        {
            "id": str(req.id),
            "canteen_id": str(req.canteen_id),
            "food_item_id": str(req.food_item_id),
            "food_item_name": food_name,
            "insufficient_ingredients": bool(insufficient),
            "item_is_available": bool(is_avail),
            "status": req.status,
            "reason": req.reason,
            "review_notes": req.review_notes,
            "reviewed_by_name": user_map.get(req.reviewed_by_user_id) if req.reviewed_by_user_id else None,
            "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
            "created_at": req.created_at.isoformat() if req.created_at else None,
        }
        for req, food_name, insufficient, is_avail in rows
    ]


def review_restore_approval(
    db: Session,
    request_id: UUID,
    *,
    decision: str,
    review_notes: Optional[str],
    actor_user_id: UUID,
) -> dict:
    from datetime import timezone
    from app.websockets import emit_order_event_sync

    req = db.get(MenuRestoreApproval, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Menu restore approval request not found")
    if req.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Request has already been {req.status}")

    food = db.get(FoodItem, req.food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")

    if decision == "approve":
        if food.insufficient_ingredients:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot restore {food.name}: linked recipe ingredients are still insufficient",
            )
        food.is_available = True
        food.pending_restore_approval = False
        req.status = "approved"
    else:
        food.is_available = False
        food.pending_restore_approval = False
        req.status = "rejected"

    req.reviewed_by_user_id = actor_user_id
    req.reviewed_at = datetime.now(timezone.utc)
    req.review_notes = review_notes

    record_audit_log(
        db,
        action=f"menu.restore_{req.status}",
        entity_type="food_item",
        entity_id=str(food.id),
        actor_user_id=actor_user_id,
        details={"request_id": str(req.id), "decision": decision, "review_notes": review_notes},
    )
    db.commit()
    invalidate_menu(food.canteen_id)
    emit_order_event_sync(
        str(food.canteen_id),
        "inventory",
        "menu.availability_changed",
        {"canteen_id": str(food.canteen_id), "food_item_id": str(food.id), "is_available": food.is_available},
    )
    return {
        "id": str(req.id),
        "food_item_id": str(food.id),
        "food_item_name": food.name,
        "status": req.status,
        "is_available": food.is_available,
        "pending_restore_approval": food.pending_restore_approval,
    }


def list_schedules(db: Session, canteen_id: UUID) -> list[MenuScheduleOut]:
    rows = db.scalars(select(MenuSchedule).where(MenuSchedule.canteen_id == canteen_id).order_by(MenuSchedule.start_time)).all()
    return [_serialize_schedule(db, s) for s in rows]


def create_schedule(db: Session, payload: MenuScheduleCreate, actor_user_id: UUID) -> MenuScheduleOut:
    sched = MenuSchedule(**payload.model_dump())
    db.add(sched)
    record_audit_log(db, action="menu_schedule.created", entity_type="menu_schedule", entity_id=payload.name, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(sched)
    invalidate_menu(sched.canteen_id)
    return _serialize_schedule(db, sched)


def update_schedule(db: Session, sched: MenuSchedule, payload: MenuScheduleUpdate, actor_user_id: UUID) -> MenuScheduleOut:
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(sched, k, v)
    record_audit_log(db, action="menu_schedule.updated", entity_type="menu_schedule", entity_id=str(sched.id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(sched)
    invalidate_menu(sched.canteen_id)
    return _serialize_schedule(db, sched)


def assign_schedule_items(
    db: Session, sched: MenuSchedule, food_item_ids: list[UUID], actor_user_id: UUID
) -> MenuScheduleOut:
    old = db.scalars(select(MenuAvailability).where(MenuAvailability.menu_schedule_id == sched.id)).all()
    for row in old:
        db.delete(row)
    db.flush()
    for fid in set(food_item_ids):
        item = db.get(FoodItem, fid)
        if item and item.canteen_id == sched.canteen_id:
            db.add(MenuAvailability(food_item_id=fid, menu_schedule_id=sched.id, is_available=True))
    record_audit_log(
        db,
        action="menu_schedule.items_assigned",
        entity_type="menu_schedule",
        entity_id=str(sched.id),
        actor_user_id=actor_user_id,
        details={"count": len(set(food_item_ids))},
    )
    db.commit()
    invalidate_menu(sched.canteen_id)
    return _serialize_schedule(db, sched)


def export_menu_csv(db: Session, canteen_id: UUID) -> str:
    items = list_food_items(db, canteen_id, include_inactive=True)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "name",
        "slug",
        "category",
        "base_price",
        "tax_rate_percent",
        "is_veg",
        "prep_time_minutes",
        "portion_size",
        "calories",
        "is_featured",
        "is_popular",
        "is_todays_special",
        "is_recommended",
        "is_available",
        "is_active",
        "description",
    ])
    for it in items:
        writer.writerow([
            it.name,
            it.slug,
            it.category_name or "General",
            f"{it.base_price:.2f}",
            f"{it.tax_rate_percent:.2f}" if it.tax_rate_percent is not None else "",
            "true" if it.is_veg else "false",
            it.prep_time_minutes,
            it.portion_size or "",
            it.calories if it.calories is not None else "",
            "true" if it.is_featured else "false",
            "true" if it.is_popular else "false",
            "true" if it.is_todays_special else "false",
            "true" if it.is_recommended else "false",
            "true" if it.is_available else "false",
            "true" if it.is_active else "false",
            it.description or "",
        ])
    return buf.getvalue()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:150]
    return slug or "item"


def import_menu_csv(db: Session, canteen_id: UUID, csv_text: str, actor_user_id: UUID) -> dict:
    if not db.get(Canteen, canteen_id):
        raise HTTPException(status_code=404, detail="Canteen not found")

    reader = csv.DictReader(io.StringIO(csv_text))
    created_count = 0
    updated_count = 0
    errors: list[dict] = []

    for row_num, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        try:
            cat_name = (row.get("category") or "General").strip()
            cat_slug = _slugify(cat_name)[:115]
            cat = db.scalar(select(FoodCategory).where(FoodCategory.canteen_id == canteen_id, FoodCategory.slug == cat_slug))
            if not cat:
                cat = FoodCategory(canteen_id=canteen_id, name=cat_name[:120], slug=cat_slug)
                db.add(cat)
                db.flush()

            item_slug = _slugify((row.get("slug") or name).strip())
            base_price = Decimal(str(row.get("base_price") or "0.00")).quantize(Decimal("0.01"))
            if base_price < 0:
                raise ValueError("base_price must be non-negative")
            tax_raw = (row.get("tax_rate_percent") or "").strip()
            tax_rate = Decimal(tax_raw).quantize(Decimal("0.01")) if tax_raw else None
            prep_time = max(1, int(row.get("prep_time_minutes") or 10))
            cal_raw = (row.get("calories") or "").strip()
            calories = int(cal_raw) if cal_raw else None
            is_veg = str(row.get("is_veg") or "true").lower() in ("true", "1", "yes", "veg")
            is_avail = str(row.get("is_available") or "true").lower() in ("true", "1", "yes")
            is_active = str(row.get("is_active") or "true").lower() in ("true", "1", "yes")
            is_feat = str(row.get("is_featured") or "false").lower() in ("true", "1", "yes")
            is_pop = str(row.get("is_popular") or "false").lower() in ("true", "1", "yes")
            is_spec = str(row.get("is_todays_special") or "false").lower() in ("true", "1", "yes")
            is_rec = str(row.get("is_recommended") or "false").lower() in ("true", "1", "yes")

            existing = db.scalar(select(FoodItem).where(FoodItem.canteen_id == canteen_id, FoodItem.slug == item_slug))
            if existing:
                existing.name = name[:160]
                existing.category_id = cat.id
                existing.base_price = base_price
                existing.tax_rate_percent = tax_rate
                existing.is_veg = is_veg
                existing.prep_time_minutes = prep_time
                existing.calories = calories
                existing.is_featured = is_feat
                existing.is_popular = is_pop
                existing.is_todays_special = is_spec
                existing.is_recommended = is_rec
                existing.is_available = is_avail
                existing.is_active = is_active
                existing.portion_size = row.get("portion_size") or existing.portion_size
                existing.description = row.get("description") or existing.description
                updated_count += 1
            else:
                item = FoodItem(
                    canteen_id=canteen_id,
                    category_id=cat.id,
                    name=name[:160],
                    slug=item_slug,
                    base_price=base_price,
                    tax_rate_percent=tax_rate,
                    is_veg=is_veg,
                    prep_time_minutes=prep_time,
                    calories=calories,
                    is_featured=is_feat,
                    is_popular=is_pop,
                    is_todays_special=is_spec,
                    is_recommended=is_rec,
                    portion_size=row.get("portion_size") or None,
                    description=row.get("description") or None,
                    is_available=is_avail,
                    is_active=is_active,
                )
                db.add(item)
                db.flush()
                db.add(FoodVariant(food_item_id=item.id, name="Regular", price_delta=Decimal("0.00"), is_default=True))
                created_count += 1
        except Exception as exc:
            errors.append({"row": row_num, "name": name, "error": str(exc)})

    record_audit_log(
        db,
        action="menu.csv_imported",
        entity_type="canteen",
        entity_id=str(canteen_id),
        actor_user_id=actor_user_id,
        details={"created": created_count, "updated": updated_count, "errors": len(errors)},
    )
    db.commit()
    invalidate_menu(canteen_id)
    return {"created": created_count, "updated": updated_count, "errors": errors}
