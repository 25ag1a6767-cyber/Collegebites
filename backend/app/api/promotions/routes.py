from datetime import datetime, timezone
from decimal import Decimal
import secrets
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_current_principal,
    require_roles,
    scoped_canteen_for_principal,
)
from app.models.promotion import LoyaltyAccount, LoyaltyTransaction, Promotion
from app.services.audit_service import record_audit_log
from app.services.auth_service import recompute_loyalty_tier

router = APIRouter(prefix="/promotions", tags=["Offers, Banners & Loyalty"])


class PromotionCreateIn(BaseModel):
    canteen_id: Optional[UUID] = None
    title: str = Field(min_length=2, max_length=160)
    subtitle: Optional[str] = None
    badge_text: Optional[str] = None
    promo_type: str = Field(default="banner", pattern="^(banner|flash_offer|combo)$")
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


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
    data = payload.model_dump()
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
