from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.college import Canteen
from app.models.menu import FoodAddon, FoodItem, FoodItemAddon, FoodVariant
from app.models.order import Cart, CartItem, CartItemCustomization, Order
from app.models.promotion import Coupon, CouponRedemption
from app.schemas.order import (
    CartApplyCouponIn,
    CartCustomizationOut,
    CartItemAddIn,
    CartItemOut,
    CartItemUpdateIn,
    CartSummaryOut,
)
from app.services.college_service import compute_canteen_live_status


def _quantize(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"))


def get_active_cart(
    db: Session,
    canteen_id: UUID,
    user_id: Optional[UUID] = None,
    guest_session_id: Optional[str] = None,
    create_if_missing: bool = False,
) -> Optional[Cart]:
    if not user_id and not guest_session_id:
        raise HTTPException(status_code=400, detail="Either user session or X-Guest-Session-ID header is required")

    stmt = (
        select(Cart)
        .options(selectinload(Cart.items).selectinload(CartItem.customizations))
        .where(Cart.canteen_id == canteen_id, Cart.status == "active")
    )
    if user_id:
        stmt = stmt.where(Cart.user_id == user_id)
    else:
        stmt = stmt.where(Cart.guest_session_id == guest_session_id, Cart.user_id.is_(None))
    cart = db.scalar(stmt)
    if not cart and create_if_missing:
        cart = Cart(
            user_id=user_id,
            guest_session_id=guest_session_id if not user_id else None,
            canteen_id=canteen_id,
            status="active",
        )
        db.add(cart)
        db.flush()
    return cart


def evaluate_coupon(
    db: Session,
    coupon_code: str,
    canteen_id: UUID,
    subtotal: Decimal,
    items_with_categories: list[tuple[UUID, UUID, Decimal]],
    user_id: Optional[UUID],
    guest_phone: Optional[str] = None,
) -> tuple[bool, Decimal, Optional[str], Optional[Coupon]]:
    code = coupon_code.strip().upper()
    coupon = db.scalar(select(Coupon).where(Coupon.code == code, Coupon.is_active.is_(True)))
    if not coupon:
        return False, Decimal("0.00"), "Invalid or inactive coupon code", None

    now = datetime.now(timezone.utc)
    if coupon.starts_at and coupon.starts_at > now:
        return False, Decimal("0.00"), "Coupon is not active yet", None
    if coupon.expires_at and coupon.expires_at <= now:
        return False, Decimal("0.00"), "Coupon has expired", None
    if coupon.canteen_id and coupon.canteen_id != canteen_id:
        return False, Decimal("0.00"), "Coupon is not valid at this canteen", None
    if subtotal < coupon.min_order_amount:
        return False, Decimal("0.00"), f"Minimum order ₹{coupon.min_order_amount:.2f} required", None
    if coupon.usage_limit_total is not None and coupon.times_used >= coupon.usage_limit_total:
        return False, Decimal("0.00"), "Coupon total redemption limit reached", None

    if user_id:
        user_used = db.scalar(
            select(func.count(CouponRedemption.id)).where(
                CouponRedemption.coupon_id == coupon.id,
                CouponRedemption.user_id == user_id,
            )
        ) or 0
        if user_used >= coupon.usage_limit_per_user:
            return False, Decimal("0.00"), "You have already reached the usage limit for this coupon", None
        if coupon.first_order_only:
            prior_orders = db.scalar(
                select(func.count(Order.id)).where(
                    Order.customer_id == user_id, Order.payment_status == "CONFIRMED"
                )
            ) or 0
            if prior_orders > 0:
                return False, Decimal("0.00"), "Coupon is valid on first order only", None
    elif guest_phone:
        guest_used = db.scalar(
            select(func.count(CouponRedemption.id)).where(
                CouponRedemption.coupon_id == coupon.id,
                CouponRedemption.guest_phone == guest_phone,
            )
        ) or 0
        if guest_used >= coupon.usage_limit_per_user:
            return False, Decimal("0.00"), "Coupon usage limit reached for this phone", None

    eligible_amount = subtotal
    if coupon.discount_type == "category" and coupon.target_category_id:
        eligible_amount = sum(
            (line_sub for _fid, cat_id, line_sub in items_with_categories if cat_id == coupon.target_category_id),
            Decimal("0.00"),
        )
        if eligible_amount <= Decimal("0.00"):
            return False, Decimal("0.00"), "Coupon applies to a different category", None
    elif coupon.discount_type == "food_item" and coupon.target_food_item_id:
        eligible_amount = sum(
            (line_sub for fid, _cat_id, line_sub in items_with_categories if fid == coupon.target_food_item_id),
            Decimal("0.00"),
        )
        if eligible_amount <= Decimal("0.00"):
            return False, Decimal("0.00"), "Required food item is not in cart", None

    if coupon.discount_type in ("percentage", "category", "food_item"):
        discount = _quantize((eligible_amount * coupon.discount_value) / Decimal("100"))
    else:
        discount = _quantize(coupon.discount_value)

    if coupon.max_discount_amount is not None:
        discount = min(discount, coupon.max_discount_amount)
    discount = min(discount, subtotal)
    return True, discount, f"Applied {coupon.code}", coupon


def calculate_cart_summary(
    db: Session,
    canteen_id: UUID,
    user_id: Optional[UUID] = None,
    guest_session_id: Optional[str] = None,
) -> CartSummaryOut:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")

    is_open, crowd, eta, active_count = compute_canteen_live_status(db, canteen)
    has_capacity = not (canteen.auto_throttle_enabled and active_count >= canteen.max_concurrent_orders)
    validation_errors: list[str] = []
    if not is_open:
        validation_errors.append("Selected canteen is currently closed or paused.")
    if not has_capacity:
        validation_errors.append("Canteen is currently at maximum concurrent order capacity.")

    cart = get_active_cart(db, canteen_id, user_id=user_id, guest_session_id=guest_session_id, create_if_missing=False)
    if not cart:
        return CartSummaryOut(
            cart_id=None,
            canteen_id=canteen.id,
            canteen_name=canteen.name,
            coupon_code=None,
            items=[],
            subtotal_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("0.00"),
            is_canteen_open=is_open,
            has_capacity=has_capacity,
            estimated_prep_minutes=eta,
            validation_errors=validation_errors,
        )

    items_out: list[CartItemOut] = []
    subtotal = Decimal("0.00")
    items_for_coupon: list[tuple[UUID, UUID, Decimal]] = []

    for ci in cart.items:
        food = db.get(FoodItem, ci.food_item_id)
        if not food or not food.is_active or food.canteen_id != canteen.id:
            validation_errors.append("One or more items in your cart are no longer active.")
            continue
        if not food.is_available or food.insufficient_ingredients:
            validation_errors.append(f"{food.name} is currently unavailable.")

        unit_price = food.base_price
        variant_name = None
        if ci.variant_id:
            var = db.get(FoodVariant, ci.variant_id)
            if not var or var.food_item_id != food.id or not var.is_available:
                validation_errors.append(f"Selected variant for {food.name} is unavailable.")
            else:
                variant_name = var.name
                unit_price = var.absolute_price if var.absolute_price is not None else (food.base_price + var.price_delta)
        unit_price = _quantize(unit_price)

        addon_per_unit = Decimal("0.00")
        cust_outs: list[CartCustomizationOut] = []
        for cust in ci.customizations:
            if cust.customization_type == "addon" and cust.addon_id:
                addon = db.get(FoodAddon, cust.addon_id)
                if addon and addon.is_available:
                    line_addon_total = _quantize(addon.price * cust.quantity)
                    addon_per_unit += line_addon_total
                    cust_outs.append(
                        CartCustomizationOut(
                            customization_type="addon",
                            addon_id=addon.id,
                            option_name=addon.name,
                            option_value=f"x{cust.quantity}",
                            quantity=cust.quantity,
                            unit_price=addon.price,
                            total_price=line_addon_total,
                        )
                    )
            else:
                cust_outs.append(
                    CartCustomizationOut(
                        customization_type=cust.customization_type,
                        addon_id=None,
                        option_name=cust.option_name,
                        option_value=cust.option_value,
                        quantity=cust.quantity,
                        unit_price=Decimal("0.00"),
                        total_price=Decimal("0.00"),
                    )
                )

        line_sub = _quantize((unit_price + addon_per_unit) * ci.quantity)
        subtotal += line_sub
        items_for_coupon.append((food.id, food.category_id, line_sub))
        items_out.append(
            CartItemOut(
                id=ci.id,
                food_item_id=food.id,
                item_name=food.name,
                variant_id=ci.variant_id,
                variant_name=variant_name,
                quantity=ci.quantity,
                unit_price=unit_price,
                addon_total_per_unit=addon_per_unit,
                line_subtotal=line_sub,
                special_instructions=ci.special_instructions,
                customizations=cust_outs,
            )
        )

    discount = Decimal("0.00")
    coupon_valid = True
    coupon_msg = None
    if cart.coupon_code and items_out:
        coupon_valid, discount, coupon_msg, _ = evaluate_coupon(
            db, cart.coupon_code, canteen.id, subtotal, items_for_coupon, user_id=user_id
        )

    taxable = max(Decimal("0.00"), subtotal - discount)
    tax = _quantize((taxable * canteen.tax_rate_percent) / Decimal("100"))
    total = _quantize(taxable + tax)

    return CartSummaryOut(
        cart_id=cart.id,
        canteen_id=canteen.id,
        canteen_name=canteen.name,
        coupon_code=cart.coupon_code,
        coupon_valid=coupon_valid,
        coupon_message=coupon_msg,
        items=items_out,
        subtotal_amount=_quantize(subtotal),
        discount_amount=_quantize(discount),
        tax_amount=tax,
        total_amount=total,
        is_canteen_open=is_open,
        has_capacity=has_capacity,
        estimated_prep_minutes=eta,
        validation_errors=validation_errors,
    )


def add_item_to_cart(
    db: Session,
    payload: CartItemAddIn,
    user_id: Optional[UUID] = None,
    guest_session_id: Optional[str] = None,
) -> CartSummaryOut:
    food = db.get(FoodItem, payload.food_item_id)
    if not food or food.canteen_id != payload.canteen_id or not food.is_active:
        raise HTTPException(status_code=404, detail="Food item not found in selected canteen")
    if not food.is_available or food.insufficient_ingredients:
        raise HTTPException(status_code=400, detail=f"{food.name} is currently unavailable")

    if payload.variant_id:
        var = db.get(FoodVariant, payload.variant_id)
        if not var or var.food_item_id != food.id or not var.is_available:
            raise HTTPException(status_code=400, detail="Invalid or unavailable variant selected")

    cart = get_active_cart(db, payload.canteen_id, user_id=user_id, guest_session_id=guest_session_id, create_if_missing=True)
    ci = CartItem(
        cart_id=cart.id,
        food_item_id=food.id,
        variant_id=payload.variant_id,
        quantity=payload.quantity,
        special_instructions=payload.special_instructions,
    )
    db.add(ci)
    db.flush()

    if payload.spice_level:
        db.add(CartItemCustomization(cart_item_id=ci.id, customization_type="spice", option_name="Spice Level", option_value=payload.spice_level))
    if payload.sugar_level:
        db.add(CartItemCustomization(cart_item_id=ci.id, customization_type="sugar", option_name="Sugar Level", option_value=payload.sugar_level))
    for rem in payload.removed_ingredients:
        db.add(CartItemCustomization(cart_item_id=ci.id, customization_type="remove_ingredient", option_name="Remove", option_value=rem))

    for ad in payload.addons:
        link = db.scalar(select(FoodItemAddon).where(FoodItemAddon.food_item_id == food.id, FoodItemAddon.addon_id == ad.addon_id))
        addon = db.get(FoodAddon, ad.addon_id)
        if not link or not addon or not addon.is_available:
            raise HTTPException(status_code=400, detail="Invalid or unavailable add-on selected")
        if ad.quantity > link.max_quantity:
            raise HTTPException(status_code=400, detail=f"Maximum {link.max_quantity} allowed for {addon.name}")
        db.add(
            CartItemCustomization(
                cart_item_id=ci.id,
                customization_type="addon",
                addon_id=addon.id,
                option_name=addon.name,
                option_value=f"x{ad.quantity}",
                quantity=ad.quantity,
            )
        )

    db.commit()
    db.expire_all()
    return calculate_cart_summary(db, payload.canteen_id, user_id=user_id, guest_session_id=guest_session_id)


def update_cart_item(
    db: Session,
    cart_item_id: UUID,
    payload: CartItemUpdateIn,
    user_id: Optional[UUID] = None,
    guest_session_id: Optional[str] = None,
) -> CartSummaryOut:
    ci = db.get(CartItem, cart_item_id)
    if not ci:
        raise HTTPException(status_code=404, detail="Cart item not found")
    cart = db.get(Cart, ci.cart_id)
    if not cart or (user_id and cart.user_id != user_id) or (not user_id and cart.guest_session_id != guest_session_id):
        raise HTTPException(status_code=403, detail="Not authorized for this cart")

    if payload.quantity == 0:
        canteen_id = cart.canteen_id
        db.delete(ci)
        db.commit()
        db.expire_all()
        return calculate_cart_summary(db, canteen_id, user_id=user_id, guest_session_id=guest_session_id)

    if payload.quantity is not None:
        ci.quantity = payload.quantity
    if payload.variant_id is not None:
        ci.variant_id = payload.variant_id
    if payload.special_instructions is not None:
        ci.special_instructions = payload.special_instructions

    if any(
        x is not None
        for x in (payload.spice_level, payload.sugar_level, payload.removed_ingredients, payload.addons)
    ):
        for old in list(ci.customizations):
            db.delete(old)
        db.flush()
        if payload.spice_level:
            db.add(CartItemCustomization(cart_item_id=ci.id, customization_type="spice", option_name="Spice Level", option_value=payload.spice_level))
        if payload.sugar_level:
            db.add(CartItemCustomization(cart_item_id=ci.id, customization_type="sugar", option_name="Sugar Level", option_value=payload.sugar_level))
        for rem in (payload.removed_ingredients or []):
            db.add(CartItemCustomization(cart_item_id=ci.id, customization_type="remove_ingredient", option_name="Remove", option_value=rem))
        for ad in (payload.addons or []):
            addon = db.get(FoodAddon, ad.addon_id)
            if addon and addon.is_available:
                db.add(
                    CartItemCustomization(
                        cart_item_id=ci.id,
                        customization_type="addon",
                        addon_id=addon.id,
                        option_name=addon.name,
                        option_value=f"x{ad.quantity}",
                        quantity=ad.quantity,
                    )
                )

    db.commit()
    db.expire_all()
    return calculate_cart_summary(db, cart.canteen_id, user_id=user_id, guest_session_id=guest_session_id)


def apply_coupon_to_cart(
    db: Session,
    payload: CartApplyCouponIn,
    user_id: Optional[UUID] = None,
    guest_session_id: Optional[str] = None,
) -> CartSummaryOut:
    cart = get_active_cart(db, payload.canteen_id, user_id=user_id, guest_session_id=guest_session_id, create_if_missing=True)
    cart.coupon_code = payload.coupon_code.strip().upper() if payload.coupon_code else None
    db.commit()
    db.expire_all()
    return calculate_cart_summary(db, payload.canteen_id, user_id=user_id, guest_session_id=guest_session_id)
