from datetime import datetime
from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str
    details: Optional[dict[str, Any]] = None


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class AuditLogOut(ORMModel):
    id: UUID
    actor_user_id: Optional[UUID]
    actor_role: Optional[str]
    action: str
    entity_type: str
    entity_id: Optional[str]
    ip_address: Optional[str]
    details: Optional[dict[str, Any]]
    created_at: datetime
