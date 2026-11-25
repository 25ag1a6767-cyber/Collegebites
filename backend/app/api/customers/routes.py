from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.permissions import AuthenticatedPrincipal, get_current_principal
from app.models.auth import CustomerProfile, SessionRecord, User
from app.models.menu import FoodItem
from app.models.promotion import LoyaltyAccount
from app.schemas.common import MessageResponse
from app.schemas.menu import CustomerProfileOut, CustomerProfileUpdate, FoodItemOut
from app.services import menu_service
from app.services.audit_service import record_audit_log

router = APIRouter(prefix="/customers", tags=["Customer Profile & Favourites"])


def _build_profile_out(db: Session, principal: AuthenticatedPrincipal) -> CustomerProfileOut:
    user = principal.user
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    if not profile:
        profile = CustomerProfile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    loyalty = db.scalar(select(LoyaltyAccount).where(LoyaltyAccount.user_id == user.id))
    return CustomerProfileOut(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        college_id_number=profile.college_id_number,
        department=profile.department,
        dietary_preference=profile.dietary_preference,
        default_canteen_id=profile.default_canteen_id,
        favourite_item_ids=[str(x) for x in (profile.favourite_item_ids or [])],
        notification_opt_in=profile.notification_opt_in,
        loyalty_points=loyalty.points_balance if loyalty else 0,
        loyalty_tier=loyalty.tier_level if loyalty else "BRONZE",
        referral_code=loyalty.referral_code if loyalty else None,
    )


@router.get("/profile", response_model=CustomerProfileOut)
def get_profile(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return _build_profile_out(db, principal)


@router.patch("/profile", response_model=CustomerProfileOut)
def update_profile(
    payload: CustomerProfileUpdate,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    user = principal.user
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    if not profile:
        profile = CustomerProfile(user_id=user.id)
        db.add(profile)
        db.flush()

    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.phone is not None:
        clean_phone = payload.phone.strip()
        if clean_phone and clean_phone != user.phone:
            dup = db.scalar(select(User).where(User.phone == clean_phone, User.id != user.id))
            if dup:
                raise HTTPException(status_code=409, detail="Mobile number already registered to another user")
            user.phone = clean_phone
    for field in ("college_id_number", "department", "dietary_preference", "default_canteen_id", "notification_opt_in"):
        val = getattr(payload, field)
        if val is not None:
            setattr(profile, field, val)
    db.commit()
    return _build_profile_out(db, principal)


@router.get("/favourites", response_model=list[FoodItemOut])
def list_favourites(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == principal.user.id))
    fav_ids = list(profile.favourite_item_ids or []) if profile else []
    uuids: list[UUID] = []
    for raw_id in fav_ids:
        try:
            uuids.append(UUID(str(raw_id)))
        except Exception:
            continue
    if not uuids:
        return []
    rows = db.scalars(
        select(FoodItem)
        .options(
            selectinload(FoodItem.images),
            selectinload(FoodItem.variants),
            selectinload(FoodItem.addon_links),
            selectinload(FoodItem.allergen_links),
        )
        .where(FoodItem.id.in_(uuids), FoodItem.is_active.is_(True))
    ).all()
    by_id = {r.id: r for r in rows}
    ordered = [by_id[uid] for uid in uuids if uid in by_id]
    if not ordered:
        return []
    from app.models.college import KitchenStation
    from app.models.menu import Allergen, FoodAddon, FoodCategory

    cat_ids = list({i.category_id for i in ordered})
    addon_ids = list({lnk.addon_id for i in ordered for lnk in i.addon_links})
    allergen_ids = list({alnk.allergen_id for i in ordered for alnk in i.allergen_links})
    station_ids = list({i.station_id for i in ordered if i.station_id})
    cat_map = {c.id: c for c in db.scalars(select(FoodCategory).where(FoodCategory.id.in_(cat_ids))).all()} if cat_ids else {}
    addon_map = {a.id: a for a in db.scalars(select(FoodAddon).where(FoodAddon.id.in_(addon_ids))).all()} if addon_ids else {}
    alg_map = {a.id: a for a in db.scalars(select(Allergen).where(Allergen.id.in_(allergen_ids))).all()} if allergen_ids else {}
    station_map = {s.id: s for s in db.scalars(select(KitchenStation).where(KitchenStation.id.in_(station_ids))).all()} if station_ids else {}
    sched_map = menu_service.compute_schedule_availability_map(
        db, [i.id for i in ordered], food_items_map={i.id: i for i in ordered}
    )
    return [
        menu_service.serialize_food_item(
            db,
            item,
            category_map=cat_map,
            addon_map=addon_map,
            allergen_map=alg_map,
            schedule_active_map=sched_map,
            station_map=station_map,
        )
        for item in ordered
    ]


@router.delete("/me", response_model=MessageResponse)
def deactivate_my_account(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Deactivate own customer account cleanly while preserving immutable payment & order ledgers."""
    if not principal.has_role("customer"):
        raise HTTPException(status_code=403, detail="Staff/admin accounts must be deactivated by an administrator")
    user = principal.user
    now = datetime.now(timezone.utc)
    user.is_active = False
    for sess in db.scalars(
        select(SessionRecord).where(SessionRecord.user_id == user.id, SessionRecord.revoked_at.is_(None))
    ).all():
        sess.revoked_at = now
    record_audit_log(
        db,
        action="customer.deactivated_self",
        entity_type="user",
        entity_id=str(user.id),
        actor_user_id=user.id,
    )
    db.commit()
    return MessageResponse(message="Account deactivated successfully. Historical receipts remain archived per policy.")


@router.post("/favourites/{food_item_id}", response_model=CustomerProfileOut)
def add_favourite(
    food_item_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    if not db.get(FoodItem, food_item_id):
        raise HTTPException(status_code=404, detail="Food item not found")
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == principal.user.id))
    if not profile:
        profile = CustomerProfile(user_id=principal.user.id, favourite_item_ids=[])
        db.add(profile)
        db.flush()
    favs = list(profile.favourite_item_ids or [])
    key = str(food_item_id)
    if key not in favs:
        favs.append(key)
        profile.favourite_item_ids = favs
        db.commit()
    return _build_profile_out(db, principal)


@router.delete("/favourites/{food_item_id}", response_model=CustomerProfileOut)
def remove_favourite(
    food_item_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == principal.user.id))
    if profile and profile.favourite_item_ids:
        key = str(food_item_id)
        profile.favourite_item_ids = [x for x in profile.favourite_item_ids if x != key]
        db.commit()
    return _build_profile_out(db, principal)
