from datetime import datetime, timezone
from decimal import Decimal
import secrets
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_current_principal,
    get_optional_principal,
    require_roles,
    scoped_canteen_for_principal,
)
from app.models.menu import FoodCategory, FoodItem
from app.models.order import Order
from app.models.promotion import Coupon, CouponRedemption, LoyaltyAccount, LoyaltyTransaction, Promotion
from app.services.audit_service import record_audit_log
from app.services.auth_service import recompute_loyalty_tier
from app.services.cart_service import evaluate_coupon_discount

router = APIRouter(prefix="/promotions", tags=["Offers, Banners & Loyalty"])

PROMO_ADMIN_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)


class PromotionCreateIn(BaseModel):
    canteen_id: Optional[UUID] = None
    title: str = Field(min_length=2, max_length=160)
    subtitle: Optional[str] = None
    badge_text: Optional[str] = None
    promo_type: str = Field(default="banner", pattern="^(banner|flash_offer|combo)$")
    coupon_code: Optional[str] = Field(default=None, max_length=48)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class CouponCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=48)
    title: str = Field(min_length=2, max_length=160)
    description: Optional[str] = None
    canteen_id: Optional[UUID] = None
    discount_type: str = Field(pattern="^(percentage|fixed)$")
    discount_value: Decimal = Field(gt=0)
    target_category_id: Optional[UUID] = None
    target_food_item_id: Optional[UUID] = None
    min_order_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    max_discount_amount: Optional[Decimal] = Field(default=None, gt=0)
    first_order_only: bool = False
    usage_limit_total: Optional[int] = Field(default=None, ge=1)
    usage_limit_per_user: int = Field(default=1, ge=1)
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True


class CouponUpdateIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = None
    discount_type: Optional[str] = Field(default=None, pattern="^(percentage|fixed)$")
    discount_value: Optional[Decimal] = Field(default=None, gt=0)
    target_category_id: Optional[UUID] = None
    target_food_item_id: Optional[UUID] = None
    min_order_amount: Optional[Decimal] = Field(default=None, ge=0)
    max_discount_amount: Optional[Decimal] = Field(default=None, gt=0)
    first_order_only: Optional[bool] = None
    usage_limit_total: Optional[int] = Field(default=None, ge=1)
    usage_limit_per_user: Optional[int] = Field(default=None, ge=1)
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: Optional[bool] = None


class CouponValidateIn(BaseModel):
    canteen_id: UUID
    coupon_code: str = Field(min_length=2, max_length=48)
    subtotal_amount: Decimal = Field(ge=0)
    items: list[dict] = []


@router.get("")
def list_active_promotions(canteen_id: Optional[UUID] = Query(default=None), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    stmt = select(Promotion).where(Promotion.is_active.is_(True)).order_by(Promotion.created_at.desc())
    rows = db.scalars(stmt).all()
    rows = [
        r
        for r in rows
        if (not r.starts_at or r.starts_at <= now) and (not r.ends_at or r.ends_at > now)
    ]
    if canteen_id:
        rows = [r for r in rows if r.canteen_id is None or r.canteen_id == canteen_id]
    return rows


@router.post("", status_code=status.HTTP_201_CREATED)
def create_promotion(
    payload: PromotionCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    if payload.coupon_code and payload.coupon_code.strip():
        raise HTTPException(
            status_code=400,
            detail="Discounts and promotional coupon codes are disabled.",
        )
    data = payload.model_dump()
    data["coupon_code"] = None
    if ROLE_CANTEEN_MANAGER in principal.roles and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        data["canteen_id"] = scoped_canteen_for_principal(principal, payload.canteen_id)
    promo = Promotion(**data)
    db.add(promo)
    db.commit()
    db.refresh(promo)
    return promo


@router.delete("/{promo_id}")
def deactivate_promotion(
    promo_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    promo = db.get(Promotion, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promotion not found")
    enforce_canteen_scope(principal, promo.canteen_id)
    promo.is_active = False
    db.commit()
    return {"status": "deactivated", "id": str(promo_id)}


@router.get("/loyalty/me")
def my_loyalty(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    acct = db.scalar(select(LoyaltyAccount).where(LoyaltyAccount.user_id == principal.user.id))
    if not acct:
        return {"points_balance": 0, "lifetime_points": 0, "tier_level": "BRONZE", "referral_code": None, "transactions": []}
    txns = list(
        db.scalars(
            select(LoyaltyTransaction)
            .where(LoyaltyTransaction.loyalty_account_id == acct.id)
            .order_by(LoyaltyTransaction.created_at.desc())
            .limit(30)
        ).all()
    )
    return {
        "points_balance": acct.points_balance,
        "lifetime_points": acct.lifetime_points,
        "tier_level": acct.tier_level,
        "referral_code": acct.referral_code,
        "transactions": txns,
    }


@router.post("/loyalty/apply-referral")
def apply_referral(
    referral_code: str = Query(min_length=4),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    my_acct = db.scalar(select(LoyaltyAccount).where(LoyaltyAccount.user_id == principal.user.id).with_for_update())
    if not my_acct:
        my_acct = LoyaltyAccount(user_id=principal.user.id, referral_code=f"CB{secrets.token_hex(4).upper()}")
        db.add(my_acct)
        db.flush()
    if my_acct.referred_by_user_id is not None:
        raise HTTPException(status_code=409, detail="Referral already applied")
    referrer = db.scalar(
        select(LoyaltyAccount).where(LoyaltyAccount.referral_code == referral_code.strip().upper()).with_for_update()
    )
    if not referrer or referrer.user_id == principal.user.id:
        raise HTTPException(status_code=400, detail="Invalid referral code")

    my_acct.referred_by_user_id = referrer.user_id
    my_acct.points_balance += 50
    my_acct.lifetime_points += 50
    recompute_loyalty_tier(my_acct)
    referrer.points_balance += 50
    referrer.lifetime_points += 50
    recompute_loyalty_tier(referrer)
    db.add_all([
        LoyaltyTransaction(loyalty_account_id=my_acct.id, points_delta=50, transaction_type="referral_bonus", description=f"Applied referral {referrer.referral_code}"),
        LoyaltyTransaction(loyalty_account_id=referrer.id, points_delta=50, transaction_type="referral_bonus", description="Referral reward"),
    ])
    db.commit()
    return {"message": "Referral bonus credited (+50 pts each)", "points_balance": my_acct.points_balance}


def _serialize_coupon(
    c: Coupon,
    *,
    cat_map: Optional[dict[UUID, str]] = None,
    food_map: Optional[dict[UUID, str]] = None,
) -> dict:
    return {
        "id": str(c.id),
        "code": c.code,
        "title": c.title,
        "description": c.description,
        "canteen_id": str(c.canteen_id) if c.canteen_id else None,
        "discount_type": c.discount_type,
        "discount_value": str(c.discount_value),
        "target_category_id": str(c.target_category_id) if c.target_category_id else None,
        "target_category_name": (cat_map or {}).get(c.target_category_id) if c.target_category_id else None,
        "target_food_item_id": str(c.target_food_item_id) if c.target_food_item_id else None,
        "target_food_item_name": (food_map or {}).get(c.target_food_item_id) if c.target_food_item_id else None,
        "min_order_amount": str(c.min_order_amount),
        "max_discount_amount": str(c.max_discount_amount) if c.max_discount_amount is not None else None,
        "first_order_only": c.first_order_only,
        "usage_limit_total": c.usage_limit_total,
        "usage_limit_per_user": c.usage_limit_per_user,
        "times_used": c.times_used,
        "starts_at": c.starts_at.isoformat() if c.starts_at else None,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("/coupons")
def list_coupons(
    canteen_id: Optional[UUID] = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    # Discounts & promotional coupons are disabled globally; never expose active coupons.
    if not include_inactive:
        return []
    stmt = select(Coupon).where(Coupon.is_active.is_(False)).order_by(Coupon.created_at.desc())
    rows = list(db.scalars(stmt).all())
    if canteen_id:
        rows = [r for r in rows if r.canteen_id is None or r.canteen_id == canteen_id]
    cat_map = {c.id: c.name for c in db.scalars(select(FoodCategory)).all()}
    food_map = {f.id: f.name for f in db.scalars(select(FoodItem)).all()}
    return [_serialize_coupon(c, cat_map=cat_map, food_map=food_map) for c in rows]


@router.post("/coupons", status_code=status.HTTP_201_CREATED)
def create_coupon(
    payload: CouponCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROMO_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=400,
        detail="Discounts and promotional coupon campaigns are disabled. Items are billed at exact listed prices.",
    )


@router.patch("/coupons/{coupon_id}")
def update_coupon(
    coupon_id: UUID,
    payload: CouponUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROMO_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    coupon = db.get(Coupon, coupon_id)
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")
    if coupon.canteen_id:
        enforce_canteen_scope(principal, coupon.canteen_id)
    updates = payload.model_dump(exclude_unset=True)
    # Only allow deactivating legacy records; reject activating or modifying discounts.
    if updates.get("is_active") is not False or any(k != "is_active" for k in updates):
        raise HTTPException(
            status_code=400,
            detail="Discounts and promotional coupon campaigns are disabled and cannot be activated or edited.",
        )
    coupon.is_active = False
    record_audit_log(
        db,
        action="coupon.deactivated",
        entity_type="coupon",
        entity_id=coupon.code,
        actor_user_id=principal.user.id,
    )
    db.commit()
    db.refresh(coupon)
    return _serialize_coupon(coupon)


@router.post("/coupons/validate")
def validate_coupon_endpoint(
    payload: CouponValidateIn,
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=400,
        detail="Discounts and promotional coupon codes are disabled. All items are billed at exact listed prices.",
    )


@router.get("/campaigns/report")
def get_campaigns_performance_report(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*PROMO_ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    eff_cid = scoped_canteen_for_principal(principal, canteen_id)
    stmt = select(Coupon).order_by(Coupon.created_at.desc())
    if eff_cid:
        stmt = stmt.where((Coupon.canteen_id == eff_cid) | (Coupon.canteen_id.is_(None)))
    coupons = list(db.scalars(stmt).all())

    redemptions = db.execute(
        select(
            CouponRedemption.coupon_id,
            func.count(CouponRedemption.id),
            func.coalesce(func.sum(CouponRedemption.discount_applied), 0),
            func.coalesce(func.sum(Order.total_amount), 0),
        )
        .join(Order, Order.id == CouponRedemption.order_id)
        .where(Order.status.not_in(["CANCELLED", "REJECTED", "PAYMENT_FAILED"]))
        .group_by(CouponRedemption.coupon_id)
    ).all()
    stats_map = {
        cid: {
            "redemptions_count": int(cnt or 0),
            "total_discount_given": Decimal(str(disc or 0)).quantize(Decimal("0.01")),
            "attributed_order_revenue": Decimal(str(rev or 0)).quantize(Decimal("0.01")),
        }
        for cid, cnt, disc, rev in redemptions
    }

    total_redemptions = sum(s["redemptions_count"] for s in stats_map.values())
    total_discount = sum((s["total_discount_given"] for s in stats_map.values()), Decimal("0.00")).quantize(Decimal("0.01"))
    total_revenue = sum((s["attributed_order_revenue"] for s in stats_map.values()), Decimal("0.00")).quantize(Decimal("0.01"))

    return {
        "total_campaigns": len(coupons),
        "active_campaigns": sum(1 for c in coupons if c.is_active),
        "total_redemptions": total_redemptions,
        "total_discount_given": str(total_discount),
        "attributed_order_revenue": str(total_revenue),
        "campaigns": [
            {
                **_serialize_coupon(c),
                "redemptions_count": stats_map.get(c.id, {}).get("redemptions_count", c.times_used),
                "total_discount_given": str(stats_map.get(c.id, {}).get("total_discount_given", Decimal("0.00"))),
                "attributed_order_revenue": str(stats_map.get(c.id, {}).get("attributed_order_revenue", Decimal("0.00"))),
            }
            for c in coupons
        ],
    }
