from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    get_current_principal,
    get_optional_principal,
    require_roles,
)
from app.models.engagement import Rating, Review, SupportMessage, SupportTicket
from app.models.menu import FoodItem
from app.services.audit_service import record_audit_log

router = APIRouter(prefix="/support", tags=["Reviews & Support (No Refunds)"])


class ReviewCreateIn(BaseModel):
    food_item_id: UUID
    order_id: Optional[UUID] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


class TicketCreateIn(BaseModel):
    order_id: Optional[UUID] = None
    canteen_id: Optional[UUID] = None
    guest_name: Optional[str] = None
    guest_phone: Optional[str] = None
    category: str = Field(pattern="^(food_quality|missing_item|incorrect_order|app_help|other)$")
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=2000)
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")


class TicketMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    is_internal: bool = False


class TicketAssignIn(BaseModel):
    assigned_to_user_id: UUID


@router.post("/reviews", status_code=status.HTTP_201_CREATED)
def create_review(
    payload: ReviewCreateIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    food = db.get(FoodItem, payload.food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    rev = Review(
        user_id=principal.user.id,
        order_id=payload.order_id,
        food_item_id=food.id,
        canteen_id=food.canteen_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(rev)

    agg = db.scalar(select(Rating).where(Rating.food_item_id == food.id).with_for_update())
    if not agg:
        agg = Rating(food_item_id=food.id, rating_sum=0, rating_count=0, average_score=0)
        db.add(agg)
        db.flush()
    agg.rating_sum += payload.rating
    agg.rating_count += 1
    avg = Decimal(agg.rating_sum) / Decimal(agg.rating_count)
    agg.average_score = int((avg * 100).quantize(Decimal("1")))
    food.average_rating = avg.quantize(Decimal("0.01"))
    food.rating_count = agg.rating_count
    db.commit()
    db.refresh(rev)
    return rev


@router.get("/items/{food_item_id}/reviews")
def list_item_reviews(food_item_id: UUID, db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Review)
            .where(Review.food_item_id == food_item_id, Review.is_visible.is_(True))
            .order_by(Review.created_at.desc())
            .limit(50)
        ).all()
    )


@router.post("/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreateIn,
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    cnt = db.scalar(select(func.count(SupportTicket.id))) or 0
    tnum = f"SUP-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{int(cnt)+1:05d}"
    ticket = SupportTicket(
        ticket_number=tnum,
        user_id=principal.user.id if principal else None,
        guest_name=payload.guest_name or (principal.user.full_name if principal else "Guest"),
        guest_phone=payload.guest_phone or (principal.user.phone if principal else None),
        order_id=payload.order_id,
        canteen_id=payload.canteen_id,
        category=payload.category,
        subject=payload.subject,
        description=payload.description,
        priority=payload.priority,
        status="open",
    )
    db.add(ticket)
    db.flush()
    db.add(
        SupportMessage(
            ticket_id=ticket.id,
            sender_user_id=principal.user.id if principal else None,
            sender_role="customer",
            message=payload.description,
        )
    )
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("/tickets/my")
def my_tickets(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    return list(
        db.scalars(select(SupportTicket).where(SupportTicket.user_id == principal.user.id).order_by(SupportTicket.created_at.desc())).all()
    )


@router.get("/tickets")
def list_all_tickets(
    status_filter: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    stmt = select(SupportTicket).order_by(SupportTicket.created_at.desc())
    if status_filter:
        stmt = stmt.where(SupportTicket.status == status_filter)
    return list(db.scalars(stmt.limit(200)).all())


@router.get("/tickets/{ticket_id}/messages")
def get_ticket_messages(
    ticket_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    is_admin = principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    if not is_admin and ticket.user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    stmt = select(SupportMessage).where(SupportMessage.ticket_id == ticket.id).order_by(SupportMessage.created_at.asc())
    if not is_admin:
        stmt = stmt.where(SupportMessage.is_internal.is_(False))
    return list(db.scalars(stmt).all())


@router.post("/tickets/{ticket_id}/messages")
def add_ticket_message(
    ticket_id: UUID,
    payload: TicketMessageIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    is_admin = principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    if not is_admin and ticket.user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    msg = SupportMessage(
        ticket_id=ticket.id,
        sender_user_id=principal.user.id,
        sender_role="admin" if is_admin else "customer",
        message=payload.message,
        is_internal=payload.is_internal and is_admin,
    )
    db.add(msg)
    if is_admin and ticket.status == "open":
        ticket.status = "in_progress"
    db.commit()
    db.refresh(msg)
    return msg


@router.post("/tickets/{ticket_id}/assign")
def assign_ticket(
    ticket_id: UUID,
    payload: TicketAssignIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.assigned_to_user_id = payload.assigned_to_user_id
    if ticket.status == "open":
        ticket.status = "assigned"
    db.commit()
    db.refresh(ticket)
    return ticket


@router.post("/tickets/{ticket_id}/resolve")
def resolve_ticket(
    ticket_id: UUID,
    resolution_note: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.status = "resolved"
    ticket.resolved_at = datetime.now(timezone.utc)
    if resolution_note:
        db.add(
            SupportMessage(
                ticket_id=ticket.id,
                sender_user_id=principal.user.id,
                sender_role="admin",
                message=f"Resolved: {resolution_note}",
            )
        )
    record_audit_log(db, action="support.ticket_resolved", entity_type="support_ticket", entity_id=ticket.ticket_number, actor_user_id=principal.user.id)
    db.commit()
    db.refresh(ticket)
    return ticket
