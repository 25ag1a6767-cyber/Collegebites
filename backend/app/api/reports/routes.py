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
    require_roles,
    scoped_canteen_for_principal,
)
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports & Analytics"])

REPORT_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)


@router.get("/dashboard")
def get_dashboard_report(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    return report_service.get_analytics_report(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/details/orders")
def get_report_orders_detail(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    return report_service.get_order_details_page(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        status_filter=status,
        q=q,
        page=page,
        page_size=page_size,
    )


@router.get("/details/items")
def get_report_items_detail(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    q: Optional[str] = Query(default=None),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    return report_service.get_item_details_page(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        q=q,
        sort_dir=sort,
        page=page,
        page_size=page_size,
    )


@router.get("/details/inventory")
def get_report_inventory_detail(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    q: Optional[str] = Query(default=None),
    low_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    return report_service.get_inventory_details_page(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        q=q,
        low_only=low_only,
        page=page,
        page_size=page_size,
    )


@router.get("/export/csv")
def export_csv(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    report = report_service.get_analytics_report(
        db, canteen_id=scoped_cid, preset=preset, start_date=start_date, end_date=end_date
    )
    csv_text = report_service.export_report_csv(report)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=collegebites-report.csv"},
    )


@router.get("/export/pdf")
def export_pdf(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    report = report_service.get_analytics_report(
        db, canteen_id=scoped_cid, preset=preset, start_date=start_date, end_date=end_date
    )
    pdf_bytes = report_service.export_report_pdf(report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=collegebites-report.pdf"},
    )


@router.get("/export/xlsx")
def export_xlsx(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    report = report_service.get_analytics_report(
        db, canteen_id=scoped_cid, preset=preset, start_date=start_date, end_date=end_date
    )
    xlsx_bytes = report_service.export_report_xlsx(report)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=collegebites-bi-report.xlsx"},
    )
