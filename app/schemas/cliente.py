# app/schemas/cliente.py
# SCHEMAS PARA GESTIÓN DE CLIENTES

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from uuid import UUID


class ClienteCreate(BaseModel):
    """Schema para crear un nuevo cliente"""
    nombre: str = Field(..., min_length=3, max_length=255, description="Nombre del cliente/organización")
    razon_social: Optional[str] = Field(None, max_length=255, description="Razón social oficial")
    ruc: Optional[str] = Field(None, max_length=20, description="RUC del cliente")
    email_contacto: Optional[str] = Field(None, description="Email de contacto principal")
    telefono: Optional[str] = Field(None, max_length=50, description="Teléfono de contacto")
    direccion: Optional[str] = Field(None, description="Dirección física")
    plan: str = Field("basico", description="Plan: basico, profesional, enterprise")
    fecha_vencimiento: Optional[date] = Field(None, description="Fecha de vencimiento del plan")


class ClienteUpdate(BaseModel):
    """Schema para actualizar un cliente existente"""
    nombre: Optional[str] = Field(None, min_length=3, max_length=255)
    razon_social: Optional[str] = Field(None, max_length=255)
    ruc: Optional[str] = Field(None, max_length=20)
    email_contacto: Optional[str] = None
    telefono: Optional[str] = Field(None, max_length=50)
    direccion: Optional[str] = None
    plan: Optional[str] = None
    fecha_vencimiento: Optional[date] = None
    activo: Optional[bool] = None

    class Config:
        from_attributes = True


class ClienteResponse(BaseModel):
    """Schema de respuesta para listado de clientes"""
    id: UUID
    nombre: str
    razon_social: Optional[str] = None
    ruc: Optional[str] = None
    email_contacto: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    plan: str
    fecha_vencimiento: Optional[date] = None
    activo: bool
    total_empresas: Optional[int] = 0
    empresas_activas: Optional[int] = 0
    total_usuarios: Optional[int] = 0
    vencida: Optional[bool] = False
    dias_restantes: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClienteDetailResponse(BaseModel):
    """Schema de respuesta detallada para un cliente específico"""
    id: UUID
    nombre: str
    razon_social: Optional[str] = None
    ruc: Optional[str] = None
    email_contacto: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    plan: str
    fecha_vencimiento: Optional[date] = None
    activo: bool
    vencida: bool = False
    dias_restantes: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    empresas: Optional[List[Dict[str, Any]]] = []
    total_empresas: int = 0
    empresas_activas: int = 0

    class Config:
        from_attributes = True


class ClienteStatsResponse(BaseModel):
    """Schema de estadísticas de clientes"""
    total_clientes: int
    clientes_activos: int
    clientes_vencidos: int
    clientes_por_vencer_7d: int = 0
    clientes_por_vencer_30d: int = 0
    total_empresas: int = 0
    por_plan: Dict[str, int] = {}