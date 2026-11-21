from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    get_current_principal,
    require_roles,
)
from app.models.promotion import Coupon, LoyaltyAccount, LoyaltyTransaction, Promotion
from app.services.audit_service import record_audit_log

router = APIRouter(prefix="/promotions", tags=["Coupons, Offers & Loyalty"])


class CouponCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=2, max_length=160)
    description: Optional[str] = None
    canteen_id: Optional[UUID] = None
    discount_type: str = Field(default="percentage", pattern="^(percentage|fixed|category|food_item)$")
    discount_value: Decimal = Field(gt=0)
    target_category_id: Optional[UUID] = None
    target_food_item_id: Optional[UUID] = None
    min_order_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    max_discount_amount: Optional[Decimal] = Field(default=None, ge=0)
    first_order_only: bool = False
    usage_limit_total: Optional[int] = Field(default=None, ge=1)
    usage_limit_per_user: int = Field(default=1, ge=1)
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class PromotionCreateIn(BaseModel):
    canteen_id: Optional[UUID] = None
    title: str = Field(min_length=2, max_length=160)
    subtitle: Optional[str] = None
    badge_text: Optional[str] = None
    promo_type: str = Field(default="banner", pattern="^(banner|flash_offer|combo)$")
    coupon_code: Optional[str] = None


@router.get("")
def list_active_promotions(canteen_id: Optional[UUID] = Query(default=None), db: Session = Depends(get_db)):
    stmt = select(Promotion).where(Promotion.is_active.is_(True)).order_by(Promotion.created_at.desc())
    rows = db.scalars(stmt).all()
    if canteen_id:
        rows = [r for r in rows if r.canteen_id is None or r.canteen_id == canteen_id]
    return rows


@router.post("", status_code=status.HTTP_201_CREATED)
def create_promotion(
    payload: PromotionCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    promo = Promotion(**payload.model_dump())
    db.add(promo)
    db.commit()
    db.refresh(promo)
    return promo


@router.get("/coupons")
def list_coupons(
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    stmt = select(Coupon).order_by(Coupon.created_at.desc())
    if active_only:
        stmt = stmt.where(Coupon.is_active.is_(True))
    return list(db.scalars(stmt).all())


@router.post("/coupons", status_code=status.HTTP_201_CREATED)
def create_coupon(
    payload: CouponCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    data = payload.model_dump()
    data["code"] = data["code"].strip().upper()
    dup = db.scalar(select(Coupon).where(Coupon.code == data["code"]))
    if dup:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Coupon code already exists")
    coupon = Coupon(**data)
    db.add(coupon)
    record_audit_log(db, action="coupon.created", entity_type="coupon", entity_id=coupon.code, actor_user_id=principal.user.id)
    db.commit()
    db.refresh(coupon)
    return coupon


@router.get("/loyalty/me")
def my_loyalty(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    acct = db.scalar(select(LoyaltyAccount).where(LoyaltyAccount.user_id == principal.user.id))
    if not acct:
        return {"points_balance": 0, "tier_level": "BRONZE", "transactions": []}
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
    from fastapi import HTTPException

    my_acct = db.scalar(select(LoyaltyAccount).where(LoyaltyAccount.user_id == principal.user.id))
    if not my_acct:
        raise HTTPException(status_code=404, detail="Loyalty account not found")
    if my_acct.referred_by_user_id is not None:
        raise HTTPException(status_code=409, detail="Referral already applied")
    referrer = db.scalar(select(LoyaltyAccount).where(LoyaltyAccount.referral_code == referral_code.strip().upper()))
    if not referrer or referrer.user_id == principal.user.id:
        raise HTTPException(status_code=400, detail="Invalid referral code")

    my_acct.referred_by_user_id = referrer.user_id
    my_acct.points_balance += 50
    my_acct.lifetime_points += 50
    referrer.points_balance += 50
    referrer.lifetime_points += 50
    db.add_all([
        LoyaltyTransaction(loyalty_account_id=my_acct.id, points_delta=50, transaction_type="referral_bonus", description=f"Applied referral {referrer.referral_code}"),
        LoyaltyTransaction(loyalty_account_id=referrer.id, points_delta=50, transaction_type="referral_bonus", description="Referral reward"),
    ])
    db.commit()
    return {"message": "Referral bonus credited (+50 pts each)", "points_balance": my_acct.points_balance}
