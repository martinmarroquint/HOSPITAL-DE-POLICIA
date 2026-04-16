# app/schemas/publicacion.py
# SCHEMAS PARA PUBLICACIONES - SIGUIENDO EL PATRÓN EXISTENTE

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


# =====================================================
# SCHEMAS BASE
# =====================================================

class PublicacionBase(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=255)
    tipo: str = Field(..., description="TEXTO, IMAGEN, PDF")
    contenido_texto: Optional[str] = None
    url_archivo: Optional[str] = Field(None, max_length=500)
    descripcion: Optional[str] = None
    categoria: Optional[str] = "general"
    es_automatica: Optional[bool] = False
    
    @validator('tipo')
    def validar_tipo(cls, v):
        tipos_validos = ['TEXTO', 'IMAGEN', 'PDF']
        if v.upper() not in tipos_validos:
            raise ValueError(f"Tipo debe ser uno de: {tipos_validos}")
        return v.upper()
    
    @validator('contenido_texto')
    def validar_contenido_texto(cls, v, values):
        if values.get('tipo') == 'TEXTO' and not v:
            raise ValueError("contenido_texto es requerido para tipo TEXTO")
        return v
    
    @validator('url_archivo')
    def validar_url_archivo(cls, v, values):
        tipo = values.get('tipo')
        if tipo in ['IMAGEN', 'PDF'] and not v:
            raise ValueError(f"url_archivo es requerido para tipo {tipo}")
        return v


class PublicacionCreate(PublicacionBase):
    autor_id: Optional[UUID] = None
    fecha_publicacion: Optional[datetime] = None
    fecha_expiracion: Optional[datetime] = None
    fijado: Optional[bool] = False


class PublicacionUpdate(BaseModel):
    titulo: Optional[str] = Field(None, min_length=1, max_length=255)
    tipo: Optional[str] = None
    contenido_texto: Optional[str] = None
    url_archivo: Optional[str] = Field(None, max_length=500)
    descripcion: Optional[str] = None
    categoria: Optional[str] = None
    fecha_expiracion: Optional[datetime] = None
    activo: Optional[bool] = None
    fijado: Optional[bool] = None
    
    @validator('tipo')
    def validar_tipo(cls, v):
        if v:
            tipos_validos = ['TEXTO', 'IMAGEN', 'PDF']
            if v.upper() not in tipos_validos:
                raise ValueError(f"Tipo debe ser uno de: {tipos_validos}")
            return v.upper()
        return v
    
    class Config:
        from_attributes = True


class PublicacionResponse(PublicacionBase):
    id: UUID
    autor_id: Optional[UUID] = None
    autor_nombre: Optional[str] = None
    autor_area: Optional[str] = None
    autor_iniciales: Optional[str] = None
    fecha_publicacion: datetime
    fecha_expiracion: Optional[datetime] = None
    activo: bool
    fijado: bool
    total_vistas: int
    vistas: Optional[List[UUID]] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# =====================================================
# SCHEMAS PARA VISTAS
# =====================================================

class PublicacionVistaCreate(BaseModel):
    publicacion_id: UUID
    usuario_id: UUID


class PublicacionVistaResponse(BaseModel):
    id: UUID
    publicacion_id: UUID
    usuario_id: UUID
    fecha_vista: datetime
    
    class Config:
        from_attributes = True


class MarcarVistaRequest(BaseModel):
    usuario_id: UUID


# =====================================================
# SCHEMAS PARA ESTADÍSTICAS
# =====================================================

class PublicacionEstadisticas(BaseModel):
    publicacion_id: UUID
    titulo: str
    total_vistas: int
    total_empleados: int
    porcentaje_vistas: float
    usuarios_vieron: List[Dict[str, Any]]
    usuarios_no_vieron: List[Dict[str, Any]]
    
    class Config:
        from_attributes = True


class EstadisticasGlobales(BaseModel):
    total_publicaciones: int
    total_vistas: int
    total_empleados: int
    usuarios_vieron_todo: int
    porcentaje_lectura_completa: float
    
    class Config:
        from_attributes = True


# =====================================================
# SCHEMAS PARA RESPUESTAS PAGINADAS
# =====================================================

class PublicacionListResponse(BaseModel):
    items: List[PublicacionResponse]
    total: int
    page: int
    size: int
    pages: int
    
    class Config:
        from_attributes = True