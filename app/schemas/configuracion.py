"""
Schemas Pydantic para Configuración Dinámica
CON SOPORTE MULTI-EMPRESA
INCLUYE: sede_id en UnidadResponse para geolocalización
INCLUYE: config_planificacion en ClienteConfigResponse
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


# =====================================================
# TURNOS
# =====================================================

class TurnoBase(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=100)
    codigo: Optional[str] = Field(None, max_length=10)
    hora_inicio: Optional[str] = Field(None, pattern=r'^\d{2}:\d{2}$')
    hora_fin: Optional[str] = Field(None, pattern=r'^\d{2}:\d{2}$')
    duracion: Optional[float] = 0
    color: Optional[str] = "#3FB4B4"
    color_texto: Optional[str] = "#FFFFFF"
    tipo: Optional[str] = "productivo"
    valor_computo: Optional[float] = 1.0
    sistema: Optional[bool] = False
    activo: Optional[bool] = True
    orden: Optional[int] = 0


class TurnoCreate(TurnoBase):
    pass


class TurnoUpdate(BaseModel):
    nombre: Optional[str] = None
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None
    duracion: Optional[float] = None
    color: Optional[str] = None
    color_texto: Optional[str] = None
    tipo: Optional[str] = None
    valor_computo: Optional[float] = None
    activo: Optional[bool] = None
    orden: Optional[int] = None


class TurnoResponse(TurnoBase):
    id: UUID
    empresa_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# =====================================================
# REGLAS
# =====================================================

class ReglaBase(BaseModel):
    unidad_medida: Optional[str] = "turnos"
    periodicidad: Optional[str] = "mensual"
    meta_tipo: Optional[str] = "fija"
    meta_valor: Optional[float] = 25.0
    meta_factor: Optional[float] = 0.83
    meta_formula: Optional[str] = None
    minimo_cumplimiento: Optional[float] = 80.0
    minimo_tipo: Optional[str] = "porcentaje"
    tope_maximo: Optional[float] = None
    redondeo_metodo: Optional[str] = "umbral"
    redondeo_valor: Optional[float] = 0.3
    francos_descuentan: Optional[bool] = False
    max_francos_consecutivos: Optional[int] = 2
    exclusiones: Optional[List[str]] = []
    alcance: Optional[str] = "global"
    tolerancia_tardanza: Optional[int] = 15


class ReglaCreate(ReglaBase):
    pass


class ReglaUpdate(ReglaBase):
    pass


class ReglaResponse(ReglaBase):
    id: UUID
    empresa_id: Optional[UUID] = None
    activo: Optional[bool] = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# =====================================================
# ORGANIGRAMA - NIVELES
# =====================================================

class NivelJerarquicoBase(BaseModel):
    nombre: str
    color: Optional[str] = "#3FB4B4"
    orden: Optional[int] = 0
    requiere_jefe: Optional[bool] = True


class NivelJerarquicoCreate(NivelJerarquicoBase):
    pass


class NivelJerarquicoUpdate(BaseModel):
    nombre: Optional[str] = None
    color: Optional[str] = None
    orden: Optional[int] = None
    requiere_jefe: Optional[bool] = None
    activo: Optional[bool] = None


class NivelJerarquicoResponse(NivelJerarquicoBase):
    id: UUID
    empresa_id: Optional[UUID] = None
    activo: Optional[bool] = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# =====================================================
# ORGANIGRAMA - UNIDADES
# =====================================================

class UnidadBase(BaseModel):
    nombre: str
    codigo: Optional[str] = None
    padre_id: Optional[UUID] = None
    nivel_id: Optional[UUID] = None
    sede_id: Optional[UUID] = None
    orden: Optional[int] = 0
    metadata_extra: Optional[Dict[str, Any]] = {}


class UnidadCreate(UnidadBase):
    pass


class UnidadUpdate(BaseModel):
    nombre: Optional[str] = None
    codigo: Optional[str] = None
    padre_id: Optional[UUID] = None
    nivel_id: Optional[UUID] = None
    sede_id: Optional[UUID] = None
    orden: Optional[int] = None
    activo: Optional[bool] = None
    metadata_extra: Optional[Dict[str, Any]] = None


class UnidadResponse(UnidadBase):
    id: UUID
    empresa_id: Optional[UUID] = None
    sede_id: Optional[UUID] = None
    activo: Optional[bool] = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OrganigramaResponse(BaseModel):
    niveles: List[NivelJerarquicoResponse] = []
    unidades: List[UnidadResponse] = []


# =====================================================
# ROLES
# =====================================================

class RolBase(BaseModel):
    nombre: str
    nivel: Optional[int] = 10
    color: Optional[str] = "#6B7280"
    descripcion: Optional[str] = None
    permisos: Optional[List[str]] = []
    es_jefatura: Optional[bool] = False
    alcance_global: Optional[bool] = False


class RolCreate(RolBase):
    pass


class RolUpdate(BaseModel):
    nombre: Optional[str] = None
    nivel: Optional[int] = None
    color: Optional[str] = None
    descripcion: Optional[str] = None
    permisos: Optional[List[str]] = None
    es_jefatura: Optional[bool] = None
    alcance_global: Optional[bool] = None
    activo: Optional[bool] = None


class RolResponse(RolBase):
    id: UUID
    empresa_id: Optional[UUID] = None
    sistema: Optional[bool] = False
    activo: Optional[bool] = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# =====================================================
# CAMPOS DEL PERSONAL
# =====================================================

class CampoPersonalBase(BaseModel):
    campo_id: str
    nombre: str
    tipo: Optional[str] = "texto"
    obligatorio: Optional[bool] = False
    habilitado: Optional[bool] = True
    sistema: Optional[bool] = False
    seccion: Optional[str] = "adicional"
    aplica_a: Optional[Dict[str, bool]] = Field(default={"personal": True, "visitante": False})
    descripcion: Optional[str] = None
    etiqueta: Optional[str] = None
    opciones: Optional[List[str]] = []
    catalogo: Optional[str] = None
    orden: Optional[int] = 0


class CampoPersonalCreate(CampoPersonalBase):
    pass


class CampoPersonalUpdate(BaseModel):
    nombre: Optional[str] = None
    tipo: Optional[str] = None
    obligatorio: Optional[bool] = None
    habilitado: Optional[bool] = None
    seccion: Optional[str] = None
    aplica_a: Optional[Dict[str, bool]] = None
    descripcion: Optional[str] = None
    etiqueta: Optional[str] = None
    opciones: Optional[List[str]] = None
    catalogo: Optional[str] = None
    orden: Optional[int] = None


class CampoPersonalResponse(CampoPersonalBase):
    id: UUID
    empresa_id: Optional[UUID] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CamposPersonalUpdateBulk(BaseModel):
    campos: List[CampoPersonalBase]


# =====================================================
# CATALOGOS
# =====================================================

class CatalogoBase(BaseModel):
    tipo: str
    valor: str
    orden: Optional[int] = 0
    metadata_extra: Optional[Dict[str, Any]] = {}


class CatalogoCreate(CatalogoBase):
    pass


class CatalogoResponse(CatalogoBase):
    id: UUID
    empresa_id: Optional[UUID] = None
    activo: Optional[bool] = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# =====================================================
# ESTADO DE CONFIGURACION
# =====================================================

class EstadoConfigResponse(BaseModel):
    completado: Dict[str, bool]
    porcentaje: int


# =====================================================
# CONFIGURACION DEL CLIENTE
# =====================================================

class ClienteConfigBase(BaseModel):
    nombre_organizacion: Optional[str] = "Hospital PNP"
    nombre_corto: Optional[str] = "Hospital PNP"
    logo_url: Optional[str] = None
    color_primario: Optional[str] = "#3FB4B4"
    color_secundario: Optional[str] = "#2C8C8C"
    color_fondo: Optional[str] = "#F1F5F9"
    color_texto: Optional[str] = "#1F2937"
    pie_pagina: Optional[str] = "Sistema de Gestión de Personal"


class ClienteConfigUpdate(ClienteConfigBase):
    pass


class ClienteConfigResponse(ClienteConfigBase):
    id: UUID
    empresa_id: Optional[UUID] = None
    config_planificacion: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# =====================================================
# CONFIGURACION DE PLANIFICACION (MODO DE OPERACION)
# =====================================================

class PlanificacionConfigBase(BaseModel):
    modo_aprobacion: Optional[str] = "autonomo"
    permite_correccion: Optional[bool] = True
    notificar_pendientes: Optional[bool] = False
    permite_edicion_admin: Optional[bool] = False
    requiere_aprobacion: Optional[bool] = False


class PlanificacionConfigUpdate(PlanificacionConfigBase):
    pass


class PlanificacionConfigResponse(PlanificacionConfigBase):
    class Config:
        from_attributes = True