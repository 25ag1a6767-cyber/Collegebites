from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.college import CanteenDetailOut, CanteenOut, CollegeSettingsOut
from app.services import college_service

router = APIRouter(prefix="/canteens", tags=["Canteens & Locations"])


@router.get("/college", response_model=CollegeSettingsOut)
def get_college_info(db: Session = Depends(get_db)):
    return college_service.get_or_create_college_settings(db)


@router.get("", response_model=list[CanteenOut])
def list_canteens(include_inactive: bool = Query(default=False), db: Session = Depends(get_db)):
    return college_service.list_canteens(db, include_inactive=include_inactive)


@router.get("/{canteen_id_or_slug}", response_model=CanteenDetailOut)
def get_canteen_detail(canteen_id_or_slug: str, db: Session = Depends(get_db)):
    return college_service.get_canteen_detail(db, canteen_id_or_slug)
