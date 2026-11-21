from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
)
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports & Analytics"])

REPORT_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)


@router.get("/dashboard")
def get_dashboard_report(
    canteen_id: Optional[UUID] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    return report_service.get_analytics_report(db, canteen_id=canteen_id, start_date=start_date, end_date=end_date)


@router.get("/export/csv")
def export_csv(
    canteen_id: Optional[UUID] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    report = report_service.get_analytics_report(db, canteen_id=canteen_id, start_date=start_date, end_date=end_date)
    csv_text = report_service.export_report_csv(report)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=collegebites-report.csv"},
    )


@router.get("/export/pdf")
def export_pdf(
    canteen_id: Optional[UUID] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    report = report_service.get_analytics_report(db, canteen_id=canteen_id, start_date=start_date, end_date=end_date)
    pdf_bytes = report_service.export_report_pdf(report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=collegebites-report.pdf"},
    )
