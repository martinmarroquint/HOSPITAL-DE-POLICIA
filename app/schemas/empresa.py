# app/schemas/empresa.py
# VERSIÓN COMPLETA CORREGIDA - CON SOPORTE PARA CLIENTES Y ADMIN_CLIENTE

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from uuid import UUID


# =====================================================
# ESQUEMAS DE EMPRESA
# =====================================================

class EmpresaCreate(BaseModel):
    """Schema para crear una nueva empresa - solo nombre y password son obligatorios"""
    nombre: str = Field(..., min_length=3, max_length=200, description="Nombre completo de la empresa")
    nombre_corto: Optional[str] = Field(None, max_length=50, description="Nombre abreviado o siglas")
    
    # Auto-generables (opcionales)
    subdominio: Optional[str] = Field(None, min_length=3, max_length=50, description="Identificador interno único (auto-generado)")
    dominio_email: Optional[str] = Field(None, max_length=255, description="Dominio de email corporativo (auto-generado)")
    email_contacto: Optional[str] = Field(None, description="Email de contacto (auto-generado)")
    admin_email: Optional[str] = Field(None, description="Email del administrador (auto-generado)")
    
    admin_password: str = Field(..., min_length=8, description="Contraseña del administrador")
    plan: str = Field("basico", description="Plan: basico, profesional, enterprise")
    max_usuarios: int = Field(50, ge=1, description="Límite máximo de usuarios")
    ruc: Optional[str] = Field(None, max_length=20, description="RUC de la empresa")
    telefono: Optional[str] = Field(None, max_length=50, description="Teléfono de contacto")
    direccion: Optional[str] = Field(None, description="Dirección física")
    
    # Relación con cliente
    cliente_id: Optional[UUID] = Field(None, description="ID del cliente al que pertenece la empresa")
    
    # Configuración visual
    logo_url: Optional[str] = Field(None, description="URL del logo")
    color_primario: Optional[str] = Field(None, max_length=20, description="Color primario")
    color_secundario: Optional[str] = Field(None, max_length=20, description="Color secundario")
    pie_pagina: Optional[str] = Field(None, max_length=255, description="Texto del pie de página")

    class Config:
        json_schema_extra = {
            "example": {
                "nombre": "KIDS EMANUEL",
                "nombre_corto": "EMANUEL",
                "admin_password": "MiP@ssw0rd123",
                "plan": "basico",
                "max_usuarios": 50,
                "cliente_id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }


class EmpresaUpdate(BaseModel):
    """Schema para actualizar una empresa - todos los campos son opcionales"""
    nombre: Optional[str] = Field(None, min_length=3, max_length=200)
    nombre_corto: Optional[str] = Field(None, max_length=50)
    subdominio: Optional[str] = Field(None, min_length=3, max_length=50)
    dominio_email: Optional[str] = Field(None, max_length=255)
    email_contacto: Optional[str] = None
    admin_email: Optional[str] = None
    telefono: Optional[str] = Field(None, max_length=50)
    direccion: Optional[str] = None
    ruc: Optional[str] = Field(None, max_length=20)
    activo: Optional[bool] = None
    plan: Optional[str] = None
    max_usuarios: Optional[int] = Field(None, ge=1)
    fecha_vencimiento: Optional[date] = None
    cliente_id: Optional[UUID] = None
    logo_url: Optional[str] = None
    color_primario: Optional[str] = Field(None, max_length=20)
    color_secundario: Optional[str] = Field(None, max_length=20)
    color_fondo: Optional[str] = Field(None, max_length=20)
    color_texto: Optional[str] = Field(None, max_length=20)
    pie_pagina: Optional[str] = Field(None, max_length=255)
    configuracion: Optional[Dict[str, Any]] = None

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
    fecha_vencimiento: Optional[date] = None
    created_at: Optional[datetime] = None
    ultimo_acceso: Optional[datetime] = None
    ultimo_acceso_email: Optional[str] = None
    logo_url: Optional[str] = None
    color_primario: Optional[str] = None
    admin_email: Optional[str] = None
    cliente_id: Optional[UUID] = None
    cliente_nombre: Optional[str] = None

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
    vencida: bool = False
    dias_restantes: Optional[int] = None
    fecha_vencimiento: Optional[date] = None
    
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
    pie_pagina: Optional[str] = None
    
    # Configuración
    configuracion: Optional[Dict[str, Any]] = None
    
    # Cliente
    cliente_id: Optional[UUID] = None
    cliente_nombre: Optional[str] = None
    
    # Admin
    admin: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class EmpresaStatsResponse(BaseModel):
    """Schema de estadísticas globales para el dashboard del super_admin"""
    total_clientes: Optional[int] = 0
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

    class Config:
        from_attributes = True


class MisEmpresasResponse(BaseModel):
    """Schema para el endpoint mis-empresas (admin_cliente)"""
    empresas: List[Dict[str, Any]]

    class Config:
        from_attributes = True


# =====================================================
# ESQUEMAS DE CLIENTE
# =====================================================

class ClienteCreate(BaseModel):
    """Schema para crear un nuevo cliente"""
    nombre: str = Field(..., min_length=3, max_length=255, description="Nombre del cliente/organización")
    razon_social: Optional[str] = Field(None, max_length=255, description="Razón social")
    ruc: Optional[str] = Field(None, max_length=20, description="RUC del cliente")
    email_contacto: Optional[str] = Field(None, description="Email de contacto (se usará para el admin_cliente si no se especifica)")
    telefono: Optional[str] = Field(None, max_length=50, description="Teléfono")
    direccion: Optional[str] = Field(None, description="Dirección")
    plan: str = Field("basico", description="Plan: basico, profesional, enterprise")
    fecha_vencimiento: Optional[date] = None

    class Config:
        json_schema_extra = {
            "example": {
                "nombre": "GRUPO KIDS",
                "razon_social": "GRUPO KIDS S.A.C.",
                "ruc": "12345678901",
                "email_contacto": "admin@grupokids.com",
                "telefono": "+51 999888777",
                "plan": "profesional"
            }
        }


class ClienteUpdate(BaseModel):
    """Schema para actualizar un cliente"""
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
    """Schema de respuesta para clientes"""
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
    admin_email: Optional[str] = None
    admin_id: Optional[UUID] = None
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
    admin: Optional[Dict[str, Any]] = None
    empresas: Optional[List[Dict[str, Any]]] = []
    total_empresas: int = 0
    empresas_activas: int = 0

    class Config:
        from_attributes = True