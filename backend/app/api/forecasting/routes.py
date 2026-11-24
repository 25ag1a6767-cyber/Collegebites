from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
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
from app.services import forecast_service

router = APIRouter(prefix="/forecasting", tags=["AI Demand Forecasting"])

FC_VIEW_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
)
FC_TRAIN_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)


class ForecastTrainIn(BaseModel):
    canteen_id: UUID
    training_window_days: int = Field(default=60, ge=7, le=365)
    horizon_days: int = Field(default=7, ge=1, le=14)
    force_retrain: bool = False


@router.post("/train")
def train_forecast_model(
    payload: ForecastTrainIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FC_TRAIN_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return forecast_service.train_and_generate_forecasts(
        db,
        canteen_id=payload.canteen_id,
        training_window_days=payload.training_window_days,
        horizon_days=payload.horizon_days,
        force_retrain=payload.force_retrain,
        actor_user_id=principal.user.id,
    )


@router.get("/canteens/{canteen_id}")
def get_canteen_forecasts(
    canteen_id: UUID,
    horizon_days: int = Query(default=7, ge=1, le=14),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FC_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return forecast_service.get_canteen_forecast_summary(db, canteen_id, horizon_days=horizon_days)


@router.get("/canteens/{canteen_id}/models")
def list_models(
    canteen_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*FC_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return forecast_service.list_forecast_models(db, canteen_id)


@router.get("/canteens/{canteen_id}/evaluations")
def get_evaluations(
    canteen_id: UUID,
    lookback_days: int = Query(default=30, ge=1, le=180),
    principal: AuthenticatedPrincipal = Depends(require_roles(*FC_VIEW_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, canteen_id)
    return forecast_service.evaluate_past_forecasts(db, canteen_id, lookback_days=lookback_days)
