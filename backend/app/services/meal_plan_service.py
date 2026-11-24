import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import today_college
from app.integrations.razorpay_client import razorpay_gateway
from app.integrations.stripe_client import stripe_gateway
from app.models.auth import User
from app.models.college import Canteen
from app.models.meal_plan import MealPlan, MealPlanRedemption, StudentMealSubscription
from app.models.menu import FoodCategory, FoodItem
from app.services.audit_service import record_audit_log


def _quantize(val: Decimal) -> Decimal:
    return Decimal(str(val)).quantize(Decimal("0.01"))


def _serialize_meal_plan(
    plan: MealPlan,
    *,
    canteen_map: Optional[dict[UUID, str]] = None,
    cat_map: Optional[dict[str, str]] = None,
    food_map: Optional[dict[str, str]] = None,
) -> dict:
    cat_ids = [str(cid) for cid in (plan.eligible_category_ids or [])]
    item_ids = [str(fid) for fid in (plan.eligible_food_item_ids or [])]
    price = _quantize(plan.price)
    tax_rate = Decimal("0.00")
    tax_amt = Decimal("0.00")
    total_price = price
    return {
        "id": str(plan.id),
        "canteen_id": str(plan.canteen_id) if plan.canteen_id else None,
        "canteen_name": (canteen_map or {}).get(plan.canteen_id) if plan.canteen_id else "All Canteens",
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "plan_type": plan.plan_type,
        "price": str(price),
        "tax_rate_percent": str(tax_rate),
        "tax_amount": str(tax_amt),
        "total_price": str(total_price),
        "validity_days": plan.validity_days,
        "total_meals": plan.total_meals,
        "eligible_category_ids": cat_ids,
        "eligible_category_names": [(cat_map or {}).get(cid, cid) for cid in cat_ids],
        "eligible_food_item_ids": item_ids,
        "eligible_food_item_names": [(food_map or {}).get(fid, fid) for fid in item_ids],
        "start_date": plan.start_date.isoformat() if plan.start_date else None,
        "expiry_date": plan.expiry_date.isoformat() if plan.expiry_date else None,
        "is_active": plan.is_active,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


def list_meal_plans(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    include_inactive: bool = False,
) -> list[dict]:
    stmt = select(MealPlan)
    if canteen_id:
        stmt = stmt.where((MealPlan.canteen_id == canteen_id) | (MealPlan.canteen_id.is_(None)))
    if not include_inactive:
        stmt = stmt.where(MealPlan.is_active.is_(True))
    plans = list(db.scalars(stmt.order_by(MealPlan.created_at.desc())).all())
    if not plans:
        return []
    cids = {p.canteen_id for p in plans if p.canteen_id}
    canteen_map = (
        {c.id: c.name for c in db.scalars(select(Canteen).where(Canteen.id.in_(cids))).all()}
        if cids
        else {}
    )
    cat_map = {str(c.id): c.name for c in db.scalars(select(FoodCategory)).all()}
    food_map = {str(f.id): f.name for f in db.scalars(select(FoodItem)).all()}
    return [
        _serialize_meal_plan(p, canteen_map=canteen_map, cat_map=cat_map, food_map=food_map)
        for p in plans
    ]


def create_meal_plan(db: Session, data: dict, actor_user_id: UUID) -> dict:
    code = (data.get("code") or "").strip().upper() or f"MP-{uuid4().hex[:6].upper()}"
    dup = db.scalar(select(MealPlan).where(MealPlan.code == code))
    if dup:
        raise HTTPException(status_code=409, detail="Meal plan code already exists")
    if data.get("canteen_id") and not db.get(Canteen, data["canteen_id"]):
        raise HTTPException(status_code=404, detail="Canteen not found")

    plan = MealPlan(
        canteen_id=data.get("canteen_id"),
        code=code,
        name=data["name"].strip(),
        description=(data.get("description") or "").strip() or None,
        plan_type=(data.get("plan_type") or "monthly").strip().lower(),
        price=_quantize(Decimal(str(data["price"]))),
        tax_rate_percent=Decimal("0.00"),
        validity_days=int(data["validity_days"]),
        total_meals=int(data["total_meals"]),
        eligible_category_ids=[str(x) for x in (data.get("eligible_category_ids") or [])],
        eligible_food_item_ids=[str(x) for x in (data.get("eligible_food_item_ids") or [])],
        start_date=data.get("start_date"),
        expiry_date=data.get("expiry_date"),
        is_active=bool(data.get("is_active", True)),
        created_by_user_id=actor_user_id,
    )
    db.add(plan)
    record_audit_log(
        db,
        action="meal_plan.created",
        entity_type="meal_plan",
        entity_id=plan.code,
        actor_user_id=actor_user_id,
        details={"name": plan.name, "total_meals": plan.total_meals, "price": str(plan.price)},
    )
    db.commit()
    db.refresh(plan)
    return _serialize_meal_plan(plan)


def update_meal_plan(db: Session, plan_id: UUID, data: dict, actor_user_id: UUID) -> dict:
    plan = db.get(MealPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    for k, v in data.items():
        if v is None:
            continue
        if k == "price":
            setattr(plan, k, _quantize(Decimal(str(v))))
        elif k == "tax_rate_percent":
            setattr(plan, k, Decimal("0.00"))
        elif k in ("eligible_category_ids", "eligible_food_item_ids"):
            setattr(plan, k, [str(x) for x in v])
        else:
            setattr(plan, k, v)
    record_audit_log(
        db,
        action="meal_plan.updated",
        entity_type="meal_plan",
        entity_id=plan.code,
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(plan)
    return _serialize_meal_plan(plan)


def _serialize_subscription(
    db: Session,
    sub: StudentMealSubscription,
    *,
    plan: Optional[MealPlan] = None,
    student: Optional[User] = None,
    include_redemptions: bool = True,
) -> dict:
    now = datetime.now(timezone.utc)
    exp_dt = sub.expires_at
    if exp_dt is not None and exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    if sub.status == "active" and exp_dt and exp_dt <= now:
        sub.status = "expired"
        db.commit()

    plan_obj = plan or db.get(MealPlan, sub.meal_plan_id)
    user_obj = student or db.get(User, sub.student_user_id)
    redemptions: list[dict] = []
    if include_redemptions:
        rows = db.scalars(
            select(MealPlanRedemption)
            .where(MealPlanRedemption.subscription_id == sub.id)
            .order_by(MealPlanRedemption.redeemed_at.desc())
        ).all()
        staff_ids = {r.redeemed_by_staff_id for r in rows if r.redeemed_by_staff_id}
        staff_map = (
            {u.id: (u.full_name or u.email) for u in db.scalars(select(User).where(User.id.in_(staff_ids))).all()}
            if staff_ids
            else {}
        )
        redemptions = [
            {
                "id": str(r.id),
                "redemption_number": r.redemption_number,
                "canteen_id": str(r.canteen_id),
                "food_item_id": str(r.food_item_id) if r.food_item_id else None,
                "meal_item_name": r.meal_item_name,
                "meals_deducted": r.meals_deducted,
                "remaining_meals_after": r.remaining_meals_after,
                "redeemed_by_staff_id": str(r.redeemed_by_staff_id) if r.redeemed_by_staff_id else None,
                "redeemed_by_staff_name": staff_map.get(r.redeemed_by_staff_id) if r.redeemed_by_staff_id else "Canteen Staff",
                "redeemed_at": r.redeemed_at.isoformat() if r.redeemed_at else None,
                "notes": r.notes,
            }
            for r in rows
        ]

    return {
        "id": str(sub.id),
        "subscription_number": sub.subscription_number,
        "student_user_id": str(sub.student_user_id),
        "student_name": (user_obj.full_name or user_obj.email) if user_obj else "Student",
        "student_email": user_obj.email if user_obj else None,
        "meal_plan_id": str(sub.meal_plan_id),
        "meal_plan_name": plan_obj.name if plan_obj else "Meal Plan",
        "meal_plan_code": plan_obj.code if plan_obj else None,
        "plan_type": plan_obj.plan_type if plan_obj else "monthly",
        "canteen_id": str(sub.canteen_id) if sub.canteen_id else None,
        "total_meals": sub.total_meals,
        "remaining_meals": sub.remaining_meals,
        "used_meals": max(0, sub.total_meals - sub.remaining_meals),
        "subtotal_amount": str(_quantize(sub.subtotal_amount)),
        "tax_amount": str(_quantize(sub.tax_amount)),
        "total_amount": str(_quantize(sub.total_amount)),
        "payment_method": sub.payment_method,
        "payment_status": sub.payment_status,
        "provider_order_id": sub.provider_order_id,
        "provider_payment_id": sub.provider_payment_id,
        "payment_reference": sub.payment_reference,
        "razorpay_order_id": sub.provider_order_id if sub.payment_method == "razorpay" else None,
        "razorpay_key_id": razorpay_gateway.public_key_id if sub.payment_method == "razorpay" else None,
        "stripe_payment_intent_id": sub.provider_order_id if sub.payment_method == "stripe" else None,
        "status": sub.status,
        "valid_from": sub.valid_from.isoformat() if sub.valid_from else None,
        "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
        "redemption_code": sub.redemption_code if sub.payment_status == "CONFIRMED" else None,
        "redemption_qr_payload": sub.redemption_qr_payload if sub.payment_status == "CONFIRMED" else None,
        "confirmed_at": sub.confirmed_at.isoformat() if sub.confirmed_at else None,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        "redemptions": redemptions,
    }


def subscribe_to_meal_plan(
    db: Session,
    *,
    plan_id: UUID,
    student_user_id: UUID,
    payment_method: str = "razorpay",
) -> dict:
    plan = db.get(MealPlan, plan_id)
    if not plan or not plan.is_active:
        raise HTTPException(status_code=404, detail="Selected meal plan is unavailable or inactive")

    today = today_college()
    if plan.start_date and today < plan.start_date:
        raise HTTPException(status_code=400, detail="Meal plan enrollment has not started yet")
    if plan.expiry_date and today > plan.expiry_date:
        raise HTTPException(status_code=400, detail="Meal plan enrollment window has expired")

    method = (payment_method or "razorpay").strip().lower()
    if method not in ("razorpay", "stripe"):
        raise HTTPException(status_code=400, detail="Only online verified payments (Razorpay or Stripe) are supported for meal plans")

    subtotal = _quantize(plan.price)
    tax_amount = Decimal("0.00")
    total_amount = subtotal

    now = datetime.now(timezone.utc)
    sub_number = f"MPS-{now.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
    redemption_code = f"CBMP-{secrets.token_hex(4).upper()}"
    qr_payload = f"COLLEGEBITES:MEALPLAN:{sub_number}:{redemption_code}"

    provider_order_id = None
    if method == "razorpay":
        rzp = razorpay_gateway.create_order(
            amount_inr=total_amount,
            receipt_ref=sub_number,
            notes={"subscription_number": sub_number, "meal_plan": plan.code},
        )
        provider_order_id = rzp["id"]
    elif method == "stripe":
        pi = stripe_gateway.create_payment_intent(
            amount_inr=total_amount,
            order_number=sub_number,
            idempotency_key=f"cb-mp-{sub_number}",
            metadata={"subscription_number": sub_number, "meal_plan": plan.code},
        )
        provider_order_id = pi["id"]

    sub = StudentMealSubscription(
        subscription_number=sub_number,
        student_user_id=student_user_id,
        meal_plan_id=plan.id,
        canteen_id=plan.canteen_id,
        total_meals=plan.total_meals,
        remaining_meals=plan.total_meals,
        subtotal_amount=subtotal,
        tax_amount=tax_amount,
        total_amount=total_amount,
        payment_method=method,
        payment_status="PENDING",
        provider_order_id=provider_order_id,
        status="pending_payment",
        redemption_code=redemption_code,
        redemption_qr_payload=qr_payload,
    )
    db.add(sub)
    record_audit_log(
        db,
        action="meal_plan.subscription_created",
        entity_type="student_meal_subscription",
        entity_id=sub_number,
        actor_user_id=student_user_id,
        details={"meal_plan_id": str(plan.id), "total_amount": str(total_amount)},
    )
    db.commit()
    db.refresh(sub)
    return _serialize_subscription(db, sub, plan=plan, include_redemptions=False)


def verify_meal_plan_payment(
    db: Session,
    *,
    subscription_id: UUID,
    actor_user_id: UUID,
    razorpay_order_id: Optional[str] = None,
    razorpay_payment_id: Optional[str] = None,
    razorpay_signature: Optional[str] = None,
    stripe_payment_intent_id: Optional[str] = None,
) -> dict:
    sub = db.scalar(
        select(StudentMealSubscription).where(StudentMealSubscription.id == subscription_id).with_for_update()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Meal plan subscription not found")
    if sub.student_user_id != actor_user_id:
        user = db.get(User, actor_user_id)
        if not user:
            raise HTTPException(status_code=403, detail="Not authorized to verify this subscription")

    if sub.payment_status == "CONFIRMED" and sub.status in ("active", "exhausted"):
        return _serialize_subscription(db, sub)

    plan = db.get(MealPlan, sub.meal_plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Meal plan not found")

    provider_payment_id: Optional[str] = None
    if sub.payment_method == "razorpay":
        ord_id = razorpay_order_id or sub.provider_order_id
        if not ord_id or not razorpay_payment_id or not razorpay_signature:
            raise HTTPException(status_code=400, detail="Razorpay order_id, payment_id, and signature are required")
        if ord_id != sub.provider_order_id:
            raise HTTPException(status_code=400, detail="Razorpay order_id mismatch")
        if not razorpay_gateway.verify_payment_signature(
            razorpay_order_id=ord_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
        ):
            sub.payment_status = "FAILED"
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid Razorpay payment signature")
        provider_payment_id = razorpay_payment_id
    elif sub.payment_method == "stripe":
        pi_id = stripe_payment_intent_id or sub.provider_order_id
        if not pi_id or pi_id != sub.provider_order_id:
            raise HTTPException(status_code=400, detail="Stripe payment_intent_id mismatch")
        pi_data = stripe_gateway.retrieve_payment_intent(pi_id)
        if pi_data.get("status") != "succeeded":
            raise HTTPException(status_code=400, detail="Stripe payment intent has not succeeded")
        provider_payment_id = pi_id

    if provider_payment_id:
        dup = db.scalar(
            select(StudentMealSubscription).where(
                StudentMealSubscription.provider_payment_id == provider_payment_id,
                StudentMealSubscription.id != sub.id,
            )
        )
        if dup:
            raise HTTPException(status_code=409, detail="Payment reference already used for another subscription")

    now = datetime.now(timezone.utc)
    sub.payment_status = "CONFIRMED"
    sub.provider_payment_id = provider_payment_id
    sub.payment_reference = provider_payment_id
    sub.status = "active"
    sub.valid_from = now
    sub.expires_at = now + timedelta(days=max(1, plan.validity_days))
    sub.confirmed_at = now

    try:
        from app.services.invoice_service import ensure_invoice_for_meal_subscription

        ensure_invoice_for_meal_subscription(db, sub, plan=plan)
    except ImportError:
        pass

    record_audit_log(
        db,
        action="meal_plan.payment_confirmed",
        entity_type="student_meal_subscription",
        entity_id=sub.subscription_number,
        actor_user_id=actor_user_id,
        details={"payment_reference": provider_payment_id, "total_meals": sub.total_meals},
    )
    db.commit()
    db.refresh(sub)
    return _serialize_subscription(db, sub, plan=plan)


def list_student_subscriptions(db: Session, student_user_id: UUID) -> list[dict]:
    subs = list(
        db.scalars(
            select(StudentMealSubscription)
            .where(StudentMealSubscription.student_user_id == student_user_id)
            .order_by(StudentMealSubscription.created_at.desc())
        ).all()
    )
    return [_serialize_subscription(db, s) for s in subs]


def list_all_subscriptions(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
) -> list[dict]:
    stmt = select(StudentMealSubscription)
    if canteen_id:
        stmt = stmt.where(
            (StudentMealSubscription.canteen_id == canteen_id) | (StudentMealSubscription.canteen_id.is_(None))
        )
    if status_filter and status_filter != "all":
        stmt = stmt.where(StudentMealSubscription.status == status_filter)
    subs = list(db.scalars(stmt.order_by(StudentMealSubscription.created_at.desc()).limit(200)).all())
    return [_serialize_subscription(db, s) for s in subs]


def _resolve_subscription_for_redemption(
    db: Session,
    *,
    redemption_code: Optional[str] = None,
    qr_payload: Optional[str] = None,
    subscription_id: Optional[UUID] = None,
    for_update: bool = False,
) -> StudentMealSubscription:
    stmt = select(StudentMealSubscription)
    if for_update:
        stmt = stmt.with_for_update()

    if subscription_id:
        stmt = stmt.where(StudentMealSubscription.id == subscription_id)
    elif qr_payload and qr_payload.strip():
        raw = qr_payload.strip()
        if raw.startswith("COLLEGEBITES:MEALPLAN:"):
            parts = raw.split(":")
            code_part = parts[-1] if len(parts) >= 4 else raw
            stmt = stmt.where(StudentMealSubscription.redemption_code == code_part)
        else:
            stmt = stmt.where(
                (StudentMealSubscription.redemption_qr_payload == raw)
                | (StudentMealSubscription.redemption_code == raw)
                | (StudentMealSubscription.subscription_number == raw)
            )
    elif redemption_code and redemption_code.strip():
        code = redemption_code.strip()
        stmt = stmt.where(
            (StudentMealSubscription.redemption_code == code)
            | (StudentMealSubscription.subscription_number == code)
        )
    else:
        raise HTTPException(status_code=400, detail="Provide redemption_code, qr_payload, or subscription_id")

    sub = db.scalar(stmt)
    if not sub:
        raise HTTPException(status_code=404, detail="Meal plan subscription or redemption code not found")
    return sub


def _validate_subscription_and_item_eligibility(
    db: Session,
    *,
    sub: StudentMealSubscription,
    plan: MealPlan,
    canteen_id: UUID,
    food_item_id: Optional[UUID],
    meals_to_deduct: int,
) -> Optional[FoodItem]:
    now = datetime.now(timezone.utc)
    if sub.payment_status != "CONFIRMED":
        raise HTTPException(status_code=400, detail="Meal plan subscription payment is not verified/confirmed")
    exp_dt = sub.expires_at
    if exp_dt is not None and exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    if exp_dt and exp_dt <= now:
        sub.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="Meal plan subscription has expired")
    if sub.status == "expired":
        raise HTTPException(status_code=400, detail="Meal plan subscription has expired")
    if sub.status != "active":
        raise HTTPException(status_code=400, detail=f"Meal plan subscription is currently {sub.status}")
    if sub.canteen_id and sub.canteen_id != canteen_id:
        raise HTTPException(status_code=400, detail="Meal plan is restricted to a different canteen")
    if meals_to_deduct <= 0:
        raise HTTPException(status_code=400, detail="Meals to deduct must be at least 1")
    if sub.remaining_meals < meals_to_deduct:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient meal balance: {sub.remaining_meals} remaining, requested {meals_to_deduct}",
        )

    food: Optional[FoodItem] = None
    if food_item_id:
        food = db.get(FoodItem, food_item_id)
        if not food or food.canteen_id != canteen_id:
            raise HTTPException(status_code=404, detail="Selected meal food item not found in this canteen")
        allowed_items = {str(x) for x in (plan.eligible_food_item_ids or [])}
        allowed_cats = {str(x) for x in (plan.eligible_category_ids or [])}
        if allowed_items and str(food.id) not in allowed_items:
            raise HTTPException(status_code=400, detail=f"'{food.name}' is not eligible under meal plan '{plan.name}'")
        if allowed_cats and str(food.category_id) not in allowed_cats:
            raise HTTPException(
                status_code=400,
                detail=f"Category for '{food.name}' is not eligible under meal plan '{plan.name}'",
            )
    elif (plan.eligible_food_item_ids or plan.eligible_category_ids):
        # If plan restricts specific items/categories and food_item_id was provided, checked above
        pass
    return food


def verify_meal_plan_eligibility(
    db: Session,
    *,
    canteen_id: UUID,
    redemption_code: Optional[str] = None,
    qr_payload: Optional[str] = None,
    subscription_id: Optional[UUID] = None,
    food_item_id: Optional[UUID] = None,
    meals_to_deduct: int = 1,
) -> dict:
    sub = _resolve_subscription_for_redemption(
        db,
        redemption_code=redemption_code,
        qr_payload=qr_payload,
        subscription_id=subscription_id,
        for_update=False,
    )
    plan = db.get(MealPlan, sub.meal_plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    food = _validate_subscription_and_item_eligibility(
        db,
        sub=sub,
        plan=plan,
        canteen_id=canteen_id,
        food_item_id=food_item_id,
        meals_to_deduct=meals_to_deduct,
    )
    return {
        "eligible": True,
        "subscription": _serialize_subscription(db, sub, plan=plan),
        "selected_food_item": {"id": str(food.id), "name": food.name} if food else None,
    }


def redeem_meal_plan(
    db: Session,
    *,
    canteen_id: UUID,
    staff_user_id: UUID,
    redemption_code: Optional[str] = None,
    qr_payload: Optional[str] = None,
    subscription_id: Optional[UUID] = None,
    food_item_id: Optional[UUID] = None,
    meal_item_name: Optional[str] = None,
    meals_to_deduct: int = 1,
    idempotency_key: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    if idempotency_key:
        existing = db.scalar(
            select(MealPlanRedemption).where(MealPlanRedemption.idempotency_key == idempotency_key)
        )
        if existing:
            sub_ex = db.get(StudentMealSubscription, existing.subscription_id)
            return {
                "idempotent_replay": True,
                "redemption_number": existing.redemption_number,
                "meals_deducted": existing.meals_deducted,
                "remaining_meals_after": existing.remaining_meals_after,
                "subscription": _serialize_subscription(db, sub_ex),
            }

    sub = _resolve_subscription_for_redemption(
        db,
        redemption_code=redemption_code,
        qr_payload=qr_payload,
        subscription_id=subscription_id,
        for_update=True,
    )
    plan = db.get(MealPlan, sub.meal_plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Meal plan not found")

    food = _validate_subscription_and_item_eligibility(
        db,
        sub=sub,
        plan=plan,
        canteen_id=canteen_id,
        food_item_id=food_item_id,
        meals_to_deduct=meals_to_deduct,
    )

    now = datetime.now(timezone.utc)
    sub.remaining_meals -= meals_to_deduct
    if sub.remaining_meals <= 0:
        sub.remaining_meals = 0
        sub.status = "exhausted"

    eff_meal_name = (meal_item_name or (food.name if food else f"{plan.name} Standard Meal")).strip()
    red = MealPlanRedemption(
        redemption_number=f"MPR-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:5].upper()}",
        idempotency_key=idempotency_key,
        subscription_id=sub.id,
        student_user_id=sub.student_user_id,
        canteen_id=canteen_id,
        food_item_id=food.id if food else None,
        meal_item_name=eff_meal_name,
        meals_deducted=meals_to_deduct,
        remaining_meals_after=sub.remaining_meals,
        redeemed_by_staff_id=staff_user_id,
        redeemed_at=now,
        notes=notes,
    )
    db.add(red)
    record_audit_log(
        db,
        action="meal_plan.redeemed",
        entity_type="student_meal_subscription",
        entity_id=sub.subscription_number,
        actor_user_id=staff_user_id,
        details={
            "redemption_number": red.redemption_number,
            "meal_item_name": eff_meal_name,
            "meals_deducted": meals_to_deduct,
            "remaining_meals_after": sub.remaining_meals,
        },
    )
    db.commit()
    db.refresh(sub)
    return {
        "idempotent_replay": False,
        "redemption_id": str(red.id),
        "redemption_number": red.redemption_number,
        "meal_item_name": red.meal_item_name,
        "meals_deducted": red.meals_deducted,
        "remaining_meals_after": red.remaining_meals_after,
        "redeemed_at": red.redeemed_at.isoformat(),
        "subscription": _serialize_subscription(db, sub, plan=plan),
    }
