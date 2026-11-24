from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_current_principal,
    require_roles,
)
from app.services import meal_plan_service

router = APIRouter(prefix="/meal-plans", tags=["Student Meal Plans"])

ADMIN_MEAL_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
REDEEM_STAFF_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER, ROLE_PICKUP_STAFF)


class MealPlanCreateIn(BaseModel):
    canteen_id: Optional[UUID] = None
    code: Optional[str] = Field(default=None, max_length=48)
    name: str = Field(min_length=2, max_length=140)
    description: Optional[str] = None
    plan_type: str = Field(default="monthly", pattern="^(daily|weekly|monthly|custom)$")
    price: Decimal = Field(gt=0)
    tax_rate_percent: Decimal = Field(default=Decimal("0.00"), ge=0, le=100)
    validity_days: int = Field(ge=1, le=365)
    total_meals: int = Field(ge=1, le=1000)
    eligible_category_ids: Optional[list[UUID]] = None
    eligible_food_item_ids: Optional[list[UUID]] = None
    start_date: Optional[date] = None
    expiry_date: Optional[date] = None
    is_active: bool = True


class MealPlanUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=140)
    description: Optional[str] = None
    plan_type: Optional[str] = Field(default=None, pattern="^(daily|weekly|monthly|custom)$")
    price: Optional[Decimal] = Field(default=None, gt=0)
    tax_rate_percent: Optional[Decimal] = Field(default=None, ge=0, le=100)
    validity_days: Optional[int] = Field(default=None, ge=1, le=365)
    total_meals: Optional[int] = Field(default=None, ge=1, le=1000)
    eligible_category_ids: Optional[list[UUID]] = None
    eligible_food_item_ids: Optional[list[UUID]] = None
    start_date: Optional[date] = None
    expiry_date: Optional[date] = None
    is_active: Optional[bool] = None


class MealPlanSubscribeIn(BaseModel):
    payment_method: str = Field(default="razorpay", pattern="^razorpay$")


class MealPlanVerifyPaymentIn(BaseModel):
    razorpay_order_id: Optional[str] = None
    razorpay_payment_id: Optional[str] = None
    razorpay_signature: Optional[str] = None


class MealPlanRedeemIn(BaseModel):
    canteen_id: UUID
    redemption_code: Optional[str] = None
    qr_payload: Optional[str] = None
    subscription_id: Optional[UUID] = None
    food_item_id: Optional[UUID] = None
    meal_item_name: Optional[str] = Field(default=None, max_length=140)
    meals_to_deduct: int = Field(default=1, ge=1, le=20)
    idempotency_key: Optional[str] = Field(default=None, max_length=96)
    notes: Optional[str] = Field(default=None, max_length=255)


@router.get("")
def list_meal_plans(
    canteen_id: Optional[UUID] = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return meal_plan_service.list_meal_plans(db, canteen_id=canteen_id, include_inactive=include_inactive)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_meal_plan(
    payload: MealPlanCreateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*ADMIN_MEAL_ROLES)),
    db: Session = Depends(get_db),
):
    if payload.canteen_id:
        enforce_canteen_scope(principal, payload.canteen_id)
    return meal_plan_service.create_meal_plan(db, payload.model_dump(), principal.user.id)


@router.patch("/{plan_id}")
def update_meal_plan(
    plan_id: UUID,
    payload: MealPlanUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*ADMIN_MEAL_ROLES)),
    db: Session = Depends(get_db),
):
    return meal_plan_service.update_meal_plan(db, plan_id, payload.model_dump(exclude_unset=True), principal.user.id)


@router.post("/{plan_id}/subscribe", status_code=status.HTTP_201_CREATED)
def subscribe_meal_plan(
    plan_id: UUID,
    payload: MealPlanSubscribeIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return meal_plan_service.subscribe_to_meal_plan(
        db,
        plan_id=plan_id,
        student_user_id=principal.user.id,
        payment_method=payload.payment_method,
    )


@router.post("/subscriptions/{subscription_id}/verify-payment")
def verify_subscription_payment(
    subscription_id: UUID,
    payload: MealPlanVerifyPaymentIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return meal_plan_service.verify_meal_plan_payment(
        db,
        subscription_id=subscription_id,
        actor_user_id=principal.user.id,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    )


@router.get("/my-subscriptions")
def get_my_subscriptions(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return meal_plan_service.list_student_subscriptions(db, principal.user.id)


@router.get("/subscriptions")
def list_all_subscriptions(
    canteen_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REDEEM_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    elif principal.assigned_canteen_id and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        canteen_id = principal.assigned_canteen_id
    return meal_plan_service.list_all_subscriptions(db, canteen_id=canteen_id, status_filter=status_filter)


@router.post("/verify-eligibility")
def verify_eligibility(
    payload: MealPlanRedeemIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*REDEEM_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return meal_plan_service.verify_meal_plan_eligibility(
        db,
        canteen_id=payload.canteen_id,
        redemption_code=payload.redemption_code,
        qr_payload=payload.qr_payload,
        subscription_id=payload.subscription_id,
        food_item_id=payload.food_item_id,
        meals_to_deduct=payload.meals_to_deduct,
    )


@router.post("/redeem")
def redeem_meal(
    payload: MealPlanRedeemIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*REDEEM_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return meal_plan_service.redeem_meal_plan(
        db,
        canteen_id=payload.canteen_id,
        staff_user_id=principal.user.id,
        redemption_code=payload.redemption_code,
        qr_payload=payload.qr_payload,
        subscription_id=payload.subscription_id,
        food_item_id=payload.food_item_id,
        meal_item_name=payload.meal_item_name,
        meals_to_deduct=payload.meals_to_deduct,
        idempotency_key=payload.idempotency_key,
        notes=payload.notes,
    )
