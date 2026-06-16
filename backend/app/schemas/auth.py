"""认证相关Schema"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


# ===== 请求Schema =====

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    password: str = Field(..., min_length=6, max_length=100)
    display_name: Optional[str] = None


class TokenRefreshRequest(BaseModel):
    refresh_token: str


# ===== 响应Schema =====

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    display_name: Optional[str] = None
    avatar: Optional[str] = None
    is_active: bool
    is_superuser: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RoleResponse(BaseModel):
    id: UUID
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[dict] = None

    class Config:
        from_attributes = True
