import base64
import io
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
)
from app.models.menu import FoodAddon, FoodCategory, FoodItem, FoodVariant, MenuSchedule
from app.schemas.menu import (
    FoodAddonCreate,
    FoodAddonOut,
    FoodAddonUpdate,
    FoodCategoryCreate,
    FoodCategoryOut,
    FoodCategoryUpdate,
    FoodItemAddonCreate,
    FoodItemCreate,
    FoodItemOut,
    FoodItemUpdate,
    FoodVariantIn,
    FoodVariantOut,
    FoodVariantUpdate,
    MenuRestoreReviewIn,
    MenuScheduleAssignItemsIn,
    MenuScheduleCreate,
    MenuScheduleOut,
    MenuScheduleUpdate,
)
from app.services import menu_service

router = APIRouter(prefix="/menus", tags=["Menus & Food Catalog"])


@router.get("/canteens/{canteen_id}/categories", response_model=list[FoodCategoryOut])
def get_categories(canteen_id: UUID, include_inactive: bool = False, db: Session = Depends(get_db)):
    return menu_service.list_categories(db, canteen_id, include_inactive=include_inactive)


@router.post("/categories", response_model=FoodCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: FoodCategoryCreate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return menu_service.create_category(db, payload, principal.user.id)


@router.patch("/categories/{category_id}", response_model=FoodCategoryOut)
def update_category(
    category_id: UUID,
    payload: FoodCategoryUpdate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    cat = db.get(FoodCategory, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    enforce_canteen_scope(principal, cat.canteen_id)
    return menu_service.update_category(db, category_id, payload, principal.user.id)


@router.delete("/categories/{category_id}")
def delete_category(
    category_id: UUID,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    cat = db.get(FoodCategory, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    enforce_canteen_scope(principal, cat.canteen_id)
    cat.is_active = False
    db.commit()
    return {"status": "deactivated", "id": str(category_id)}


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
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return menu_service.create_food_item(db, payload, principal.user.id)


@router.patch("/items/{item_id}", response_model=FoodItemOut)
def update_item(
    item_id: UUID,
    payload: FoodItemUpdate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(
            ROLE_SUPER_ADMIN,
            ROLE_COLLEGE_ADMIN,
            ROLE_CANTEEN_MANAGER,
            ROLE_INVENTORY_MANAGER,
            ROLE_KITCHEN_STAFF,
        )
    ),
    db: Session = Depends(get_db),
):
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, item.canteen_id)
    is_manager_or_admin = principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    if not is_manager_or_admin:
        if getattr(item, "pending_restore_approval", False) and payload.is_available is True:
            raise HTTPException(
                status_code=403,
                detail="Restoring availability of an auto-disabled item requires Canteen Manager or College Admin approval",
            )
        if principal.has_role(ROLE_INVENTORY_MANAGER):
            if payload.base_price is not None and Decimal(str(payload.base_price)) != item.base_price:
                raise HTTPException(
                    status_code=403,
                    detail="Inventory managers must request selling price changes through manager approval (/inventory/price-changes)",
                )
            return menu_service.update_food_item(db, item_id, payload, principal.user.id)
        if ROLE_KITCHEN_STAFF in principal.roles:
            # Kitchen staff can only toggle availability
            if payload.is_available is None:
                raise HTTPException(status_code=400, detail="is_available boolean is required")
            restricted = FoodItemUpdate(is_available=payload.is_available)
            return menu_service.update_food_item(db, item_id, restricted, principal.user.id)
    return menu_service.update_food_item(db, item_id, payload, principal.user.id)


@router.delete("/items/{item_id}")
def delete_item(
    item_id: UUID,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, item.canteen_id)
    return menu_service.delete_food_item(db, item_id, principal.user.id)


@router.post("/items/{item_id}/upload-image", response_model=FoodItemOut)
async def upload_item_image(
    item_id: UUID,
    file: UploadFile = File(...),
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, item.canteen_id)
    max_bytes = 512 * 1024
    raw = await file.read(max_bytes + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded image file is empty")
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail="Image exceeds maximum allowed size of 512 KB")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.verify()
        with Image.open(io.BytesIO(raw)) as img2:
            fmt = (img2.format or "").upper()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(status_code=400, detail="Invalid or corrupted image file") from exc

    mime_map = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
    mime = mime_map.get(fmt)
    if not mime:
        raise HTTPException(status_code=400, detail="Unsupported image format; allowed formats are PNG, JPEG, WEBP")
    data_uri = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    return menu_service.set_food_item_primary_image(db, item_id, data_uri, principal.user.id)


@router.post("/items/{item_id}/variants", response_model=FoodVariantOut, status_code=status.HTTP_201_CREATED)
def add_variant(
    item_id: UUID,
    payload: FoodVariantIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, item.canteen_id)
    var = FoodVariant(food_item_id=item.id, **payload.model_dump())
    db.add(var)
    db.commit()
    db.refresh(var)
    return var


@router.patch("/variants/{variant_id}", response_model=FoodVariantOut)
def update_variant(
    variant_id: UUID,
    payload: FoodVariantUpdate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    var = db.get(FoodVariant, variant_id)
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    item = db.get(FoodItem, var.food_item_id)
    if item:
        enforce_canteen_scope(principal, item.canteen_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(var, k, v)
    db.commit()
    db.refresh(var)
    return var


@router.delete("/variants/{variant_id}")
def delete_variant(
    variant_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    var = db.get(FoodVariant, variant_id)
    if not var:
        raise HTTPException(status_code=404, detail="Variant not found")
    item = db.get(FoodItem, var.food_item_id)
    if item:
        enforce_canteen_scope(principal, item.canteen_id)
    db.delete(var)
    db.commit()
    return {"status": "deleted", "id": str(variant_id)}


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


@router.patch("/addons/{addon_id}", response_model=FoodAddonOut)
def update_addon(
    addon_id: UUID,
    payload: FoodAddonUpdate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    addon = db.get(FoodAddon, addon_id)
    if not addon:
        raise HTTPException(status_code=404, detail="Addon not found")
    enforce_canteen_scope(principal, addon.canteen_id)
    return menu_service.update_addon(db, addon, payload, principal.user.id)


@router.post("/items/{item_id}/addons", response_model=FoodAddonOut, status_code=status.HTTP_201_CREATED)
def add_item_addon(
    item_id: UUID,
    payload: FoodItemAddonCreate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, item.canteen_id)
    return menu_service.add_addon_to_food_item(db, item_id, payload, principal.user.id)


@router.delete("/items/{item_id}/addons/{addon_id}")
def remove_item_addon(
    item_id: UUID,
    addon_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    item = db.get(FoodItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Food item not found")
    enforce_canteen_scope(principal, item.canteen_id)
    return menu_service.unlink_addon_from_food_item(db, item_id, addon_id, principal.user.id)


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


@router.patch("/schedules/{schedule_id}", response_model=MenuScheduleOut)
def update_schedule(
    schedule_id: UUID,
    payload: MenuScheduleUpdate,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    sched = db.get(MenuSchedule, schedule_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Menu schedule not found")
    enforce_canteen_scope(principal, sched.canteen_id)
    return menu_service.update_schedule(db, sched, payload, principal.user.id)


@router.put("/schedules/{schedule_id}/items", response_model=MenuScheduleOut)
def assign_schedule_items(
    schedule_id: UUID,
    payload: MenuScheduleAssignItemsIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    sched = db.get(MenuSchedule, schedule_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Menu schedule not found")
    enforce_canteen_scope(principal, sched.canteen_id)
    return menu_service.assign_schedule_items(db, sched, payload.food_item_ids, principal.user.id)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    sched = db.get(MenuSchedule, schedule_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Menu schedule not found")
    enforce_canteen_scope(principal, sched.canteen_id)
    db.delete(sched)
    db.commit()
    return {"status": "deleted", "id": str(schedule_id)}


@router.get("/canteens/{canteen_id}/restore-approvals")
def list_menu_restore_approvals(
    canteen_id: UUID,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return menu_service.list_restore_approvals(db, canteen_id, status_filter=status_filter)


@router.post("/restore-approvals/{request_id}/review")
def review_menu_restore_approval(
    request_id: UUID,
    payload: MenuRestoreReviewIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    from app.models.menu import MenuRestoreApproval

    req = db.get(MenuRestoreApproval, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Menu restore approval request not found")
    enforce_canteen_scope(principal, req.canteen_id)
    return menu_service.review_restore_approval(
        db,
        request_id,
        decision=payload.decision,
        review_notes=payload.review_notes,
        actor_user_id=principal.user.id,
    )


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
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV file must be UTF-8 encoded") from exc
    return menu_service.import_menu_csv(db, canteen_id, decoded, principal.user.id)


@router.get("/allergens")
def list_allergens(db: Session = Depends(get_db)):
    from sqlalchemy import select
    from app.models.menu import Allergen

    rows = db.scalars(select(Allergen).order_by(Allergen.name.asc())).all()
    return [{"id": str(a.id), "name": a.name, "description": a.description} for a in rows]


@router.post("/allergens", status_code=status.HTTP_201_CREATED)
def create_allergen(
    name: str = Query(min_length=2, max_length=80),
    description: Optional[str] = Query(default=None, max_length=255),
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_INVENTORY_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    from sqlalchemy import select
    from app.models.menu import Allergen

    clean = name.strip()
    existing = db.scalar(select(Allergen).where(Allergen.name.ilike(clean)))
    if existing:
        if description is not None:
            existing.description = description
            db.commit()
            db.refresh(existing)
        return {"id": str(existing.id), "name": existing.name, "description": existing.description}
    alg = Allergen(name=clean, description=description)
    db.add(alg)
    db.commit()
    db.refresh(alg)
    return {"id": str(alg.id), "name": alg.name, "description": alg.description}

