# app/schemas/auth.py
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user: Optional[dict] = None

class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[UUID] = None
    personal_id: Optional[UUID] = None
    empresa_id: Optional[UUID] = None
    rol_global: Optional[str] = "usuario"
    roles: List[str] = []

class LoginRequest(BaseModel):
    username: str
    password: str

class UserProfile(BaseModel):
    id: UUID
    personal_id: Optional[UUID] = None
    empresa_id: Optional[UUID] = None
    rol_global: Optional[str] = "usuario"
    email: EmailStr
    username: Optional[str] = None
    roles: List[str] = []
    activo: bool = True
    ultimo_acceso: Optional[datetime] = None
    nombre: Optional[str] = None
    grado: Optional[str] = None
    area: Optional[str] = None
    dni: Optional[str] = None
    cip: Optional[str] = None
    areas_que_jefatura: List[str] = []

    class Config:
        from_attributes = True

class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

class UsuarioCreate(BaseModel):
    personal_id: UUID
    email: EmailStr
    password: str = Field(..., min_length=8)
    roles: List[str] = ["usuario"]

class UsuarioUpdate(BaseModel):
    email: Optional[EmailStr] = None
    activo: Optional[bool] = None
    roles: Optional[List[str]] = None
    rol_global: Optional[str] = None

class UsuarioResetPassword(BaseModel):
    nueva_password: str = Field(..., min_length=8)