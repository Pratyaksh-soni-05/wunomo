from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    tenant_name: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    user_id: str
    role: str

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    role: str
    tenant_id: str
    is_active: bool

    class Config:
        from_attributes = True