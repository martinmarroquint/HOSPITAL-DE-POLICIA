# app/schemas/empresa.py
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class EmpresaCreate(BaseModel):
    """Schema para crear una nueva empresa"""
    nombre: str = Field(..., min_length=3, max_length=200, description="Nombre completo de la empresa")
    nombre_corto: Optional[str] = Field(None, max_length=50, description="Nombre abreviado o siglas")
    subdominio: str = Field(..., min_length=3, max_length=50, description="Identificador interno único")
    dominio_email: Optional[str] = Field(None, max_length=255, description="Dominio de email corporativo")
    email_contacto: str = Field(..., description="Email de contacto de la empresa")
    admin_email: str = Field(..., description="Email para el usuario administrador")
    admin_password: str = Field(..., min_length=8, description="Contraseña del administrador")
    plan: str = Field("basico", description="Plan: basico, profesional, enterprise")
    max_usuarios: int = Field(50, ge=1, description="Límite máximo de usuarios")
    ruc: Optional[str] = Field(None, max_length=20, description="RUC de la empresa")
    telefono: Optional[str] = Field(None, max_length=20, description="Teléfono de contacto")
    direccion: Optional[str] = Field(None, description="Dirección física")


class EmpresaUpdate(BaseModel):
    """Schema para actualizar una empresa - todos los campos son opcionales"""
    nombre: Optional[str] = Field(None, min_length=3, max_length=200)
    nombre_corto: Optional[str] = Field(None, max_length=50)
    dominio_email: Optional[str] = Field(None, max_length=255)
    email_contacto: Optional[str] = None
    telefono: Optional[str] = Field(None, max_length=20)
    direccion: Optional[str] = None
    ruc: Optional[str] = Field(None, max_length=20)
    activo: Optional[bool] = None
    plan: Optional[str] = None
    max_usuarios: Optional[int] = Field(None, ge=1)
    fecha_vencimiento: Optional[datetime] = None

    class Config:
        from_attributes = True


class EmpresaResponse(BaseModel):
    """Schema de respuesta básica para listado de empresas"""
    id: UUID
    nombre: str
    nombre_corto: Optional[str] = None
    subdominio: str
    dominio_email: Optional[str] = None
    ruc: Optional[str] = None
    email_contacto: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    activo: bool
    plan: str
    max_usuarios: int
    total_usuarios: int
    total_personal: Optional[int] = None
    personal_activo: Optional[int] = None
    completitud: Optional[float] = None
    vencida: Optional[bool] = None
    dias_restantes: Optional[int] = None
    fecha_vencimiento: Optional[datetime] = None
    created_at: Optional[datetime] = None
    ultimo_acceso: Optional[datetime] = None
    ultimo_acceso_email: Optional[str] = None
    logo_url: Optional[str] = None
    color_primario: Optional[str] = None
    admin_email: Optional[str] = None

    class Config:
        from_attributes = True


class EmpresaDetailResponse(BaseModel):
    """Schema de respuesta detallada para una empresa específica"""
    id: UUID
    nombre: str
    nombre_corto: Optional[str] = None
    subdominio: str
    dominio_email: Optional[str] = None
    ruc: Optional[str] = None
    email_contacto: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    activo: bool
    plan: str
    max_usuarios: int
    
    # Métricas
    total_auth: int
    total_personal: int
    personal_activo: int
    personal_inactivo: int
    areas_configuradas: int
    completitud: float
    
    # Vencimiento
    vencida: bool
    dias_restantes: Optional[int] = None
    fecha_vencimiento: Optional[datetime] = None
    
    # Fechas
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    ultimo_acceso: Optional[datetime] = None
    ultimo_acceso_email: Optional[str] = None
    
    # Apariencia
    logo_url: Optional[str] = None
    color_primario: Optional[str] = None
    color_secundario: Optional[str] = None
    color_fondo: Optional[str] = None
    color_texto: Optional[str] = None
    
    # Configuración y dominio
    configuracion: Optional[Dict[str, Any]] = None
    
    # Admin
    admin: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class EmpresaStatsResponse(BaseModel):
    """Schema de estadísticas globales para el dashboard"""
    total_empresas: int
    empresas_activas: int
    empresas_suspendidas: int
    empresas_vencidas: int
    empresas_por_vencer_7d: Optional[int] = 0
    empresas_por_vencer_15d: Optional[int] = 0
    empresas_por_vencer_30d: Optional[int] = 0
    empresas_sin_actividad: Optional[int] = 0
    nuevas_este_mes: Optional[int] = 0
    total_usuarios: int
    total_personal: Optional[int] = 0
    por_plan: Dict[str, int]