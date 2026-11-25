from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http_cache import apply_etag_and_check_304, set_private_no_store
from app.schemas.college import CanteenDetailOut, CanteenOut, CollegeSettingsOut
from app.services import college_service

router = APIRouter(prefix="/canteens", tags=["Canteens & Locations"])


@router.get("/college", response_model=CollegeSettingsOut)
def get_college_info(request: Request, response: Response, db: Session = Depends(get_db)):
    data = college_service.get_college_config_snapshot(db)
    not_mod = apply_etag_and_check_304(request, response, data, s_maxage=300, swr=600)
    if not_mod is not None:
        return not_mod
    return data


@router.get("", response_model=list[CanteenOut])
def list_canteens(
    request: Request,
    response: Response,
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    data = college_service.list_canteens(db, include_inactive=include_inactive)
    if include_inactive:
        set_private_no_store(response)
        return data
    seed = [
        (
            str(getattr(c, "id", c.get("id") if isinstance(c, dict) else "")),
            getattr(c, "is_open_now", c.get("is_open_now") if isinstance(c, dict) else None),
            getattr(c, "crowd_level", c.get("crowd_level") if isinstance(c, dict) else None),
            getattr(c, "active_order_count", c.get("active_order_count") if isinstance(c, dict) else None),
            getattr(c, "ordering_paused", c.get("ordering_paused") if isinstance(c, dict) else None),
        )
        for c in data
    ]
    not_mod = apply_etag_and_check_304(request, response, seed, s_maxage=10, swr=30)
    if not_mod is not None:
        return not_mod
    return data


@router.get("/{canteen_id_or_slug}", response_model=CanteenDetailOut)
def get_canteen_detail(
    canteen_id_or_slug: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    data = college_service.get_canteen_detail(db, canteen_id_or_slug)
    seed = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    not_mod = apply_etag_and_check_304(request, response, seed, s_maxage=10, swr=30)
    if not_mod is not None:
        return not_mod
    return data
