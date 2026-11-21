from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_KITCHEN_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
)
from app.schemas.menu import (
    FoodAddonCreate,
    FoodAddonOut,
    FoodCategoryCreate,
    FoodCategoryOut,
    FoodCategoryUpdate,
    FoodItemCreate,
    FoodItemOut,
    FoodItemUpdate,
    MenuScheduleCreate,
    MenuScheduleOut,
)
from app.services import menu_service

router = APIRouter(prefix="/menus", tags=["Menus & Food Catalog"])


@router.get("/canteens/{canteen_id}/categories", response_model=list[FoodCategoryOut])
def get_categories(canteen_id: UUID, include_inactive: bool = False, db: Session = Depends(get_db)):
    return menu_service.list_categories(db, canteen_id, include_inactive=include_inactive)


@router.post("/categories", response_model=FoodCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: FoodCategoryCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return menu_service.create_category(db, payload, principal.user.id)


@router.patch("/categories/{category_id}", response_model=FoodCategoryOut)
def update_category(
    category_id: UUID,
    payload: FoodCategoryUpdate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    return menu_service.update_category(db, category_id, payload, principal.user.id)


@router.get("/canteens/{canteen_id}/items", response_model=list[FoodItemOut])
def list_items(
    canteen_id: UUID,
    q: Optional[str] = Query(default=None),
    category_id: Optional[UUID] = Query(default=None),
    is_veg: Optional[bool] = Query(default=None),
    min_price: Optional[Decimal] = Query(default=None),
    max_price: Optional[Decimal] = Query(default=None),
    featured: Optional[bool] = Query(default=None),
    popular: Optional[bool] = Query(default=None),
    todays_special: Optional[bool] = Query(default=None),
    recommended: Optional[bool] = Query(default=None),
    available_only: bool = Query(default=False),
    include_inactive: bool = Query(default=False),
    sort_by: str = Query(default="popularity", pattern="^(popularity|price_asc|price_desc|rating)$"),
    db: Session = Depends(get_db),
):
    return menu_service.list_food_items(
        db,
        canteen_id,
        q=q,
        category_id=category_id,
        is_veg=is_veg,
        min_price=min_price,
        max_price=max_price,
        featured=featured,
        popular=popular,
        todays_special=todays_special,
        recommended=recommended,
        available_only=available_only,
        include_inactive=include_inactive,
        sort_by=sort_by,
    )


@router.get("/items/{item_id}", response_model=FoodItemOut)
def get_item(item_id: UUID, db: Session = Depends(get_db)):
    return menu_service.get_food_item(db, item_id)


@router.post("/items", response_model=FoodItemOut, status_code=status.HTTP_201_CREATED)
def create_item(
    payload: FoodItemCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return menu_service.create_food_item(db, payload, principal.user.id)


@router.patch("/items/{item_id}", response_model=FoodItemOut)
def update_item(
    item_id: UUID,
    payload: FoodItemUpdate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF)
    ),
    db: Session = Depends(get_db),
):
    # Kitchen staff can only toggle availability
    if ROLE_KITCHEN_STAFF in principal.roles and not principal.has_role(
        ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER
    ):
        restricted = FoodItemUpdate(is_available=payload.is_available)
        return menu_service.update_food_item(db, item_id, restricted, principal.user.id)
    return menu_service.update_food_item(db, item_id, payload, principal.user.id)


@router.get("/canteens/{canteen_id}/addons", response_model=list[FoodAddonOut])
def list_addons(canteen_id: UUID, db: Session = Depends(get_db)):
    return menu_service.list_addons(db, canteen_id)


@router.post("/addons", response_model=FoodAddonOut, status_code=status.HTTP_201_CREATED)
def create_addon(
    payload: FoodAddonCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return menu_service.create_addon(db, payload, principal.user.id)


@router.get("/canteens/{canteen_id}/schedules", response_model=list[MenuScheduleOut])
def list_schedules(canteen_id: UUID, db: Session = Depends(get_db)):
    return menu_service.list_schedules(db, canteen_id)


@router.post("/schedules", response_model=MenuScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: MenuScheduleCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return menu_service.create_schedule(db, payload, principal.user.id)


@router.get("/canteens/{canteen_id}/export-csv")
def export_csv(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    csv_data = menu_service.export_menu_csv(db, canteen_id)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=menu-{canteen_id}.csv"},
    )


@router.post("/canteens/{canteen_id}/import-csv")
async def import_csv(
    canteen_id: UUID,
    file: UploadFile = File(...),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    raw = await file.read()
    return menu_service.import_menu_csv(db, canteen_id, raw.decode("utf-8-sig"), principal.user.id)
