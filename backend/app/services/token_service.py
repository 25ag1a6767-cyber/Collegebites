from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_signed_qr_token
from app.core.time_utils import today_college
from app.models.college import Canteen
from app.models.order import Order
from app.models.payment import OrderQRCode, OrderTokenSequence, PickupToken
from app.models.promotion import LoyaltyAccount, LoyaltyTransaction


def generate_token_and_qr_for_confirmed_order(db: Session, order: Order) -> tuple[PickupToken, OrderQRCode]:
    """
    Atomically generate a unique human-readable pickup token and signed QR authorization
    ONLY after backend payment verification has succeeded.
    Prevents duplicate tokens on retries or duplicate webhook deliveries.
    """
    existing_token = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id))
    existing_qr = db.scalar(select(OrderQRCode).where(OrderQRCode.order_id == order.id))
    if existing_token and existing_qr:
        return existing_token, existing_qr

    canteen = db.get(Canteen, order.canteen_id)
    prefix = (canteen.token_prefix if canteen and canteen.token_prefix else "A").upper()
    service_day = today_college()

    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(
            pg_insert(OrderTokenSequence)
            .values(canteen_id=order.canteen_id, service_date=service_day, prefix=prefix, last_sequence=0)
            .on_conflict_do_nothing(constraint="uq_token_seq_canteen_date_prefix")
        )

    seq_row = db.scalar(
        select(OrderTokenSequence)
        .where(
            OrderTokenSequence.canteen_id == order.canteen_id,
            OrderTokenSequence.service_date == service_day,
            OrderTokenSequence.prefix == prefix,
        )
        .with_for_update()
    )
    if not seq_row:
        try:
            with db.begin_nested():
                seq_row = OrderTokenSequence(
                    canteen_id=order.canteen_id,
                    service_date=service_day,
                    prefix=prefix,
                    last_sequence=0,
                )
                db.add(seq_row)
                db.flush()
        except Exception:
            seq_row = db.scalar(
                select(OrderTokenSequence)
                .where(
                    OrderTokenSequence.canteen_id == order.canteen_id,
                    OrderTokenSequence.service_date == service_day,
                    OrderTokenSequence.prefix == prefix,
                )
                .with_for_update()
            )
            if not seq_row:
                raise

    pickup_token = existing_token
    if not pickup_token:
        from sqlalchemy import func
        from sqlalchemy.exc import IntegrityError

        for attempt in range(6):
            seq_row.last_sequence += 1
            seq_num = seq_row.last_sequence
            token_code = f"{prefix}{seq_num:03d}"

            while db.scalar(
                select(PickupToken.id).where(
                    PickupToken.canteen_id == order.canteen_id,
                    PickupToken.service_date == service_day,
                    PickupToken.token_code == token_code,
                )
            ):
                seq_row.last_sequence += 1
                seq_num = seq_row.last_sequence
                token_code = f"{prefix}{seq_num:03d}"

            try:
                with db.begin_nested():
                    candidate = PickupToken(
                        order_id=order.id,
                        canteen_id=order.canteen_id,
                        counter_id=order.counter_id,
                        service_date=service_day,
                        token_code=token_code,
                        sequence_number=seq_num,
                        status="ACTIVE",
                    )
                    db.add(candidate)
                    db.flush()
                    pickup_token = candidate
                    break
            except IntegrityError:
                already = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id))
                if already:
                    pickup_token = already
                    break
                max_seq = db.scalar(
                    select(func.coalesce(func.max(PickupToken.sequence_number), 0)).where(
                        PickupToken.canteen_id == order.canteen_id,
                        PickupToken.service_date == service_day,
                    )
                ) or 0
                seq_row.last_sequence = max(seq_row.last_sequence, int(max_seq))
                if attempt == 5:
                    raise
    assert pickup_token is not None

    if not existing_qr:
        raw_qr_token, token_hash = generate_signed_qr_token()
        verification_path = f"/pickup/verify#token={raw_qr_token}"
        qr_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}{verification_path}"
        qr_row = OrderQRCode(
            order_id=order.id,
            pickup_token_id=pickup_token.id,
            token_hash=token_hash,
            verification_path=verification_path,
            qr_payload_encoded=qr_url,
        )
        db.add(qr_row)
        db.flush()
    else:
        qr_row = existing_qr

    # Award loyalty points once if registered customer
    if order.customer_id and order.total_amount >= Decimal("20.00"):
        already_earned = db.scalar(
            select(LoyaltyTransaction.id).where(
                LoyaltyTransaction.order_id == order.id, LoyaltyTransaction.transaction_type == "earn"
            )
        )
        if not already_earned:
            acct = db.scalar(
                select(LoyaltyAccount).where(LoyaltyAccount.user_id == order.customer_id).with_for_update()
            )
            if acct:
                pts = int(order.total_amount // Decimal("20"))
                if pts > 0:
                    acct.points_balance += pts
                    acct.lifetime_points += pts
                    if acct.lifetime_points >= 1000:
                        acct.tier_level = "PLATINUM"
                    elif acct.lifetime_points >= 500:
                        acct.tier_level = "GOLD"
                    elif acct.lifetime_points >= 200:
                        acct.tier_level = "SILVER"
                    db.add(
                        LoyaltyTransaction(
                            loyalty_account_id=acct.id,
                            order_id=order.id,
                            points_delta=pts,
                            transaction_type="earn",
                            description=f"Earned from order {order.order_number}",
                        )
                    )

    return pickup_token, qr_row
