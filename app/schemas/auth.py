# app/schemas/auth.py
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int

class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[UUID] = None
    roles: List[str] = []

class LoginRequest(BaseModel):
    username: str
    password: str

class UserProfile(BaseModel):
    id: UUID
    personal_id: UUID
    email: EmailStr
    roles: List[str]
    activo: bool
    ultimo_acceso: Optional[datetime]

    class Config:
        from_attributes = True

class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)

# =====================================================
# NUEVOS SCHEMAS PARA GESTIÓN DE USUARIOS AUTH
# =====================================================

class UsuarioCreate(BaseModel):
    personal_id: UUID
    email: EmailStr
    password: str = Field(..., min_length=6)
    roles: List[str] = ["usuario"]

class UsuarioUpdate(BaseModel):
    email: Optional[EmailStr] = None
    activo: Optional[bool] = None
    roles: Optional[List[str]] = None

class UsuarioResetPassword(BaseModel):
    nueva_password: str = Field(..., min_length=6)