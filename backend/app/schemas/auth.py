from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.schemas.common import ORMModel


class RegisterCustomerRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, min_length=8, max_length=20)
    password: str = Field(min_length=8, max_length=128)
    college_id_number: Optional[str] = Field(default=None, max_length=64)
    department: Optional[str] = Field(default=None, max_length=120)
    dietary_preference: Optional[str] = Field(default=None, max_length=32)
    referral_code: Optional[str] = Field(default=None, max_length=24)

    @model_validator(mode="after")
    def validate_contact(self):
        if not self.email and not self.phone:
            raise ValueError("Either email or phone number is required")
        return self


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=160)  # email or phone
    password: str = Field(min_length=1, max_length=128)
    device_info: Optional[str] = Field(default=None, max_length=255)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=16)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordResetRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=160)


class PasswordResetRequestResponse(BaseModel):
    message: str
    email_delivery_configured: bool
    expires_in_minutes: int


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(ORMModel):
    id: UUID
    email: Optional[str]
    phone: Optional[str]
    full_name: str
    user_kind: str
    is_active: bool
    is_verified: bool
    roles: list[str] = []
    permissions: list[str] = []
    assigned_canteen_id: Optional[UUID] = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: UserOut


class StaffCreateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    phone: Optional[str] = Field(default=None, min_length=8, max_length=20)
    password: str = Field(min_length=8, max_length=128)
    employee_code: str = Field(min_length=2, max_length=48)
    designation: str = Field(min_length=2, max_length=120)
    role_names: list[str] = Field(min_length=1)
    assigned_canteen_id: Optional[UUID] = None
    assigned_counter_id: Optional[UUID] = None
    assigned_kitchen_id: Optional[UUID] = None


class UserRoleAssignRequest(BaseModel):
    role_names: list[str] = Field(min_length=1)
    canteen_id: Optional[UUID] = None
    is_active: Optional[bool] = None
