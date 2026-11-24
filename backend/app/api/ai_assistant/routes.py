from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_FOOD_SAFETY_INSPECTOR,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    require_roles,
    scoped_canteen_for_principal,
)
from app.services import ai_assistant_service

router = APIRouter(prefix="/ai-assistant", tags=["AI Canteen Assistant"])

ASSISTANT_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
    ROLE_FOOD_SAFETY_INSPECTOR,
)


class AskAssistantIn(BaseModel):
    canteen_id: UUID
    question: str = Field(min_length=2, max_length=1500)
    conversation_id: Optional[UUID] = None


@router.post("/ask")
def ask_assistant(
    payload: AskAssistantIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(*ASSISTANT_ROLES)),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    return ai_assistant_service.ask_assistant(
        db,
        user_id=principal.user.id,
        user_roles=principal.roles,
        canteen_id=payload.canteen_id,
        question=payload.question,
        conversation_id=payload.conversation_id,
    )


@router.get("/conversations")
def list_conversations(
    limit: int = Query(default=30, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(require_roles(*ASSISTANT_ROLES)),
    db: Session = Depends(get_db),
):
    return ai_assistant_service.list_conversations(db, user_id=principal.user.id, limit=limit)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*ASSISTANT_ROLES)),
    db: Session = Depends(get_db),
):
    return ai_assistant_service.get_conversation_detail(db, conversation_id=conversation_id, user_id=principal.user.id)


@router.get("/audit-logs")
def get_audit_logs(
    canteen_id: Optional[UUID] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    return ai_assistant_service.list_audit_logs(db, canteen_id=scoped_cid, limit=limit)
