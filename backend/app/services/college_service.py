from datetime import date, datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.time_utils import now_college, today_college
from app.models.college import (
    Canteen,
    CollegeHoliday,
    CollegeSettings,
    Counter,
    DiningTable,
    Kitchen,
    KitchenStation,
    OperatingHour,
    PickupLocation,
)
from app.models.order import Order
from app.schemas.college import (
    CanteenCreate,
    CanteenDetailOut,
    CanteenOut,
    CanteenUpdate,
    CollegeSettingsUpdate,
    CounterCreate,
    CounterUpdate,
    DiningTableCreate,
    DiningTableUpdate,
    HolidayCreate,
    HolidayUpdate,
    KitchenCreate,
    KitchenStationCreate,
    KitchenUpdate,
    OperatingHourItem,
    PickupLocationCreate,
)
from app.services.audit_service import record_audit_log

ACTIVE_CROWD_STATUSES = ("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING")


def compute_canteen_live_status(
    db: Session,
    canteen: Canteen,
    now: Optional[datetime] = None,
    *,
    precomputed_active_count: Optional[int] = None,
) -> tuple[bool, str, int, int]:
    """Compute real-time openness, crowd level, ETA, and active order count."""
    college_row = db.scalar(select(CollegeSettings))
    tz_name = college_row.college_timezone if college_row else None
    now_local = now or now_college(tz_name)
    today = now_local.date()
    current_time = now_local.time()
    weekday = now_local.weekday()

    if precomputed_active_count is not None:
        active_count = precomputed_active_count
    else:
        active_count = (
            db.scalar(
                select(func.count(Order.id)).where(
                    Order.canteen_id == canteen.id,
                    Order.status.in_(ACTIVE_CROWD_STATUSES),
                )
            )
            or 0
        )

    if not canteen.is_active or canteen.is_temporarily_closed or canteen.ordering_paused:
        return False, "TEMPORARILY_UNAVAILABLE", canteen.default_prep_time_minutes, int(active_count)

    # Check all matching holidays on today's date
    holidays = db.scalars(
        select(CollegeHoliday).where(
            CollegeHoliday.is_active.is_(True),
            CollegeHoliday.holiday_date == today,
            or_(CollegeHoliday.canteen_id == canteen.id, CollegeHoliday.canteen_id.is_(None)),
        )
    ).all()
    for holiday in holidays:
        if holiday.is_full_day:
            return False, "TEMPORARILY_UNAVAILABLE", canteen.default_prep_time_minutes, int(active_count)
        if holiday.start_time and holiday.end_time and holiday.start_time <= current_time <= holiday.end_time:
            return False, "TEMPORARILY_UNAVAILABLE", canteen.default_prep_time_minutes, int(active_count)

    # Check operating hours if configured for today
    op_hour = db.scalar(
        select(OperatingHour).where(
            OperatingHour.canteen_id == canteen.id,
            OperatingHour.day_of_week == weekday,
        )
    )
    is_open = True
    if op_hour:
        if op_hour.is_closed:
            is_open = False
        elif not (op_hour.open_time <= current_time <= op_hour.close_time):
            is_open = False

    if not is_open:
        crowd = "TEMPORARILY_UNAVAILABLE"
    elif active_count >= canteen.max_concurrent_orders and canteen.auto_throttle_enabled:
        crowd = "TEMPORARILY_UNAVAILABLE"
    elif active_count >= canteen.crowd_very_high_threshold:
        crowd = "VERY_HIGH"
    elif active_count >= canteen.crowd_high_threshold:
        crowd = "HIGH"
    elif active_count >= canteen.crowd_moderate_threshold:
        crowd = "MODERATE"
    else:
        crowd = "LOW"

    extra_queue_minutes = int(active_count // 4) * 2
    if crowd in ("HIGH", "VERY_HIGH"):
        extra_queue_minutes += canteen.peak_hour_buffer_minutes
    eta = max(3, canteen.default_prep_time_minutes + extra_queue_minutes)

    return is_open, crowd, eta, int(active_count)


def serialize_canteen(
    db: Session, canteen: Canteen, *, precomputed_active_count: Optional[int] = None
) -> CanteenOut:
    is_open, crowd, eta, active_count = compute_canteen_live_status(
        db, canteen, precomputed_active_count=precomputed_active_count
    )
    out = CanteenOut.model_validate(canteen)
    out.is_open_now = is_open
    out.crowd_level = crowd
    out.estimated_wait_minutes = eta
    out.active_order_count = active_count
    return out


def get_or_create_college_settings(db: Session) -> CollegeSettings:
    settings_row = db.scalar(select(CollegeSettings))
    if not settings_row:
        settings_row = CollegeSettings()
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row


def update_college_settings(
    db: Session, payload: CollegeSettingsUpdate, actor_user_id: UUID, ip_address: Optional[str] = None
) -> CollegeSettings:
    row = get_or_create_college_settings(db)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    record_audit_log(
        db,
        action="college_settings.updated",
        entity_type="college_settings",
        entity_id=str(row.id),
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        details=payload.model_dump(exclude_unset=True, mode="json"),
    )
    db.commit()
    db.refresh(row)
    return row


def list_canteens(db: Session, include_inactive: bool = False) -> list[CanteenOut]:
    stmt = select(Canteen).order_by(Canteen.name.asc())
    if not include_inactive:
        stmt = stmt.where(Canteen.is_active.is_(True))
    rows = db.scalars(stmt).all()
    if not rows:
        return []
    counts_rows = db.execute(
        select(Order.canteen_id, func.count(Order.id))
        .where(Order.canteen_id.in_([c.id for c in rows]), Order.status.in_(ACTIVE_CROWD_STATUSES))
        .group_by(Order.canteen_id)
    ).all()
    count_map = {cid: int(cnt) for cid, cnt in counts_rows}
    return [serialize_canteen(db, c, precomputed_active_count=count_map.get(c.id, 0)) for c in rows]


def get_canteen_detail(db: Session, canteen_id_or_slug: str) -> CanteenDetailOut:
    canteen: Optional[Canteen] = None
    try:
        cid = UUID(canteen_id_or_slug)
        canteen = db.get(Canteen, cid)
    except ValueError:
        canteen = db.scalar(select(Canteen).where(Canteen.slug == canteen_id_or_slug))
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")

    base = serialize_canteen(db, canteen)
    counters = db.scalars(select(Counter).where(Counter.canteen_id == canteen.id).order_by(Counter.code)).all()
    kitchens = db.scalars(select(Kitchen).where(Kitchen.canteen_id == canteen.id).order_by(Kitchen.code)).all()
    tables = db.scalars(select(DiningTable).where(DiningTable.canteen_id == canteen.id).order_by(DiningTable.table_number)).all()
    op_hours = db.scalars(
        select(OperatingHour).where(OperatingHour.canteen_id == canteen.id).order_by(OperatingHour.day_of_week)
    ).all()
    college_row = db.scalar(select(CollegeSettings))
    today = today_college(college_row.college_timezone if college_row else None)
    holidays = db.scalars(
        select(CollegeHoliday)
        .where(
            CollegeHoliday.is_active.is_(True),
            CollegeHoliday.holiday_date >= today,
            or_(CollegeHoliday.canteen_id == canteen.id, CollegeHoliday.canteen_id.is_(None)),
        )
        .order_by(CollegeHoliday.holiday_date)
    ).all()

    return CanteenDetailOut(
        **base.model_dump(),
        counters=counters,
        kitchens=kitchens,
        tables=tables,
        operating_hours=op_hours,
        upcoming_holidays=holidays,
    )


def create_canteen(
    db: Session, payload: CanteenCreate, actor_user_id: UUID, ip_address: Optional[str] = None
) -> CanteenOut:
    existing = db.scalar(select(Canteen).where(or_(Canteen.slug == payload.slug, Canteen.code == payload.code)))
    if existing:
        raise HTTPException(status_code=409, detail="Canteen slug or code already exists")
    canteen = Canteen(**payload.model_dump())
    db.add(canteen)
    db.flush()

    # Auto-create default Counter 1 and Main Kitchen so newly added locations work immediately
    db.add(Counter(canteen_id=canteen.id, name="Counter 1", code="C1", counter_type="both"))
    db.add(Kitchen(canteen_id=canteen.id, name=f"{canteen.name} Kitchen", code="K1"))

    record_audit_log(
        db,
        action="canteen.created",
        entity_type="canteen",
        entity_id=str(canteen.id),
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        details={"slug": canteen.slug, "code": canteen.code},
    )
    db.commit()
    db.refresh(canteen)
    return serialize_canteen(db, canteen)


def update_canteen(
    db: Session, canteen_id: UUID, payload: CanteenUpdate, actor_user_id: UUID, ip_address: Optional[str] = None
) -> CanteenOut:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(canteen, k, v)
    record_audit_log(
        db,
        action="canteen.updated",
        entity_type="canteen",
        entity_id=str(canteen.id),
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        details=payload.model_dump(exclude_unset=True, mode="json"),
    )
    db.commit()
    db.refresh(canteen)
    return serialize_canteen(db, canteen)


def add_counter(db: Session, canteen_id: UUID, payload: CounterCreate, actor_user_id: UUID) -> Counter:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    dup = db.scalar(select(Counter).where(Counter.canteen_id == canteen_id, Counter.code == payload.code))
    if dup:
        raise HTTPException(status_code=409, detail="Counter code already exists in this canteen")
    counter = Counter(canteen_id=canteen_id, **payload.model_dump())
    db.add(counter)
    record_audit_log(
        db,
        action="counter.created",
        entity_type="counter",
        entity_id=payload.code,
        actor_user_id=actor_user_id,
        details={"canteen_id": str(canteen_id)},
    )
    db.commit()
    db.refresh(counter)
    return counter


def add_kitchen(db: Session, canteen_id: UUID, payload: KitchenCreate, actor_user_id: UUID) -> Kitchen:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    dup = db.scalar(select(Kitchen).where(Kitchen.canteen_id == canteen_id, Kitchen.code == payload.code))
    if dup:
        raise HTTPException(status_code=409, detail="Kitchen code already exists in this canteen")
    kitchen = Kitchen(canteen_id=canteen_id, **payload.model_dump())
    db.add(kitchen)
    record_audit_log(
        db,
        action="kitchen.created",
        entity_type="kitchen",
        entity_id=payload.code,
        actor_user_id=actor_user_id,
        details={"canteen_id": str(canteen_id)},
    )
    db.commit()
    db.refresh(kitchen)
    return kitchen


def add_dining_table(db: Session, canteen_id: UUID, payload: DiningTableCreate, actor_user_id: UUID) -> DiningTable:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    dup = db.scalar(
        select(DiningTable).where(DiningTable.canteen_id == canteen_id, DiningTable.table_number == payload.table_number)
    )
    if dup:
        raise HTTPException(status_code=409, detail="Table number already exists in this canteen")
    table = DiningTable(canteen_id=canteen_id, **payload.model_dump())
    db.add(table)
    record_audit_log(
        db,
        action="table.created",
        entity_type="table",
        entity_id=payload.table_number,
        actor_user_id=actor_user_id,
        details={"canteen_id": str(canteen_id)},
    )
    db.commit()
    db.refresh(table)
    return table


def upsert_operating_hours(
    db: Session, canteen_id: UUID, items: list[OperatingHourItem], actor_user_id: UUID
) -> list[OperatingHour]:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    results: list[OperatingHour] = []
    for item in items:
        row = db.scalar(
            select(OperatingHour).where(
                OperatingHour.canteen_id == canteen_id, OperatingHour.day_of_week == item.day_of_week
            )
        )
        if row:
            row.open_time = item.open_time
            row.close_time = item.close_time
            row.is_closed = item.is_closed
        else:
            row = OperatingHour(canteen_id=canteen_id, **item.model_dump())
            db.add(row)
        results.append(row)
    record_audit_log(
        db,
        action="operating_hours.updated",
        entity_type="canteen",
        entity_id=str(canteen_id),
        actor_user_id=actor_user_id,
    )
    db.commit()
    return results


def create_holiday(db: Session, payload: HolidayCreate, actor_user_id: UUID) -> CollegeHoliday:
    holiday = CollegeHoliday(**payload.model_dump())
    db.add(holiday)
    record_audit_log(
        db,
        action="holiday.created",
        entity_type="college_holiday",
        entity_id=payload.title,
        actor_user_id=actor_user_id,
        details={"holiday_date": payload.holiday_date.isoformat()},
    )
    db.commit()
    db.refresh(holiday)
    return holiday


def update_counter(db: Session, counter_id: UUID, payload: CounterUpdate, actor_user_id: UUID) -> Counter:
    counter = db.get(Counter, counter_id)
    if not counter:
        raise HTTPException(status_code=404, detail="Counter not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(counter, k, v)
    record_audit_log(db, action="counter.updated", entity_type="counter", entity_id=str(counter.id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(counter)
    return counter


def update_kitchen(db: Session, kitchen_id: UUID, payload: KitchenUpdate, actor_user_id: UUID) -> Kitchen:
    kitchen = db.get(Kitchen, kitchen_id)
    if not kitchen:
        raise HTTPException(status_code=404, detail="Kitchen not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(kitchen, k, v)
    record_audit_log(db, action="kitchen.updated", entity_type="kitchen", entity_id=str(kitchen.id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(kitchen)
    return kitchen


def add_kitchen_station(db: Session, kitchen_id: UUID, payload: KitchenStationCreate, actor_user_id: UUID) -> KitchenStation:
    kitchen = db.get(Kitchen, kitchen_id)
    if not kitchen:
        raise HTTPException(status_code=404, detail="Kitchen not found")
    st = KitchenStation(kitchen_id=kitchen_id, **payload.model_dump())
    db.add(st)
    record_audit_log(db, action="kitchen_station.created", entity_type="kitchen_station", entity_id=payload.name, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(st)
    return st


def add_pickup_location(db: Session, canteen_id: UUID, payload: PickupLocationCreate, actor_user_id: UUID) -> PickupLocation:
    cnt = db.get(Counter, payload.counter_id)
    if not cnt or cnt.canteen_id != canteen_id:
        raise HTTPException(status_code=400, detail="Counter does not belong to selected canteen")
    loc = PickupLocation(canteen_id=canteen_id, **payload.model_dump())
    db.add(loc)
    record_audit_log(db, action="pickup_location.created", entity_type="pickup_location", entity_id=payload.display_code, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(loc)
    return loc


def update_dining_table(db: Session, table_id: UUID, payload: DiningTableUpdate, actor_user_id: UUID) -> DiningTable:
    table = db.get(DiningTable, table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Dining table not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(table, k, v)
    record_audit_log(db, action="table.updated", entity_type="table", entity_id=str(table.id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(table)
    return table


def update_holiday(db: Session, holiday_id: UUID, payload: HolidayUpdate, actor_user_id: UUID) -> CollegeHoliday:
    hol = db.get(CollegeHoliday, holiday_id)
    if not hol:
        raise HTTPException(status_code=404, detail="Holiday not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(hol, k, v)
    record_audit_log(db, action="holiday.updated", entity_type="college_holiday", entity_id=str(hol.id), actor_user_id=actor_user_id)
    db.commit()
    db.refresh(hol)
    return hol
