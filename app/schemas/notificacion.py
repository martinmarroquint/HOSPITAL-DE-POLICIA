# app/schemas/notificacion.py
# SCHEMAS PARA NOTIFICACIONES - SIGUIENDO EL PATRÓN EXISTENTE

from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID


# =====================================================
# SCHEMAS BASE
# =====================================================

class NotificacionBase(BaseModel):
    tipo: str = Field(..., max_length=30)
    titulo: str = Field(..., min_length=1, max_length=100)
    mensaje: str = Field(..., min_length=1, max_length=255)
    publicacion_id: Optional[UUID] = None
    data: Optional[Dict[str, Any]] = None
    
    @validator('tipo')
    def validar_tipo(cls, v):
        tipos_validos = [
            'nueva_publicacion',
            'cumpleanios',
            'mencion_comentario',
            'recordatorio_no_leidas',
            'cambio_turno',
            'solicitud_pendiente',
            'dm_resuelto'
        ]
        if v not in tipos_validos:
            raise ValueError(f"Tipo debe ser uno de: {tipos_validos}")
        return v


class NotificacionCreate(NotificacionBase):
    usuario_id: UUID


class NotificacionResponse(NotificacionBase):
    id: UUID
    usuario_id: UUID
    leida: bool
    leida_en: Optional[datetime] = None
    creada_en: datetime
    
    class Config:
        from_attributes = True


# =====================================================
# SCHEMAS PARA CONTADORES
# =====================================================

class NotificacionesCountResponse(BaseModel):
    total: int
    no_leidas: int
    
    class Config:
        from_attributes = True


# =====================================================
# SCHEMAS PARA MARCAR COMO LEÍDA
# =====================================================

class MarcarLeidaResponse(BaseModel):
    success: bool
    message: str
    id: UUID
    
    class Config:
        from_attributes = True


class MarcarTodasLeidasResponse(BaseModel):
    success: bool
    message: str
    marcadas: int
    
    class Config:
        from_attributes = True


# =====================================================
# SCHEMAS PARA PREFERENCIAS (OPCIONAL - FUTURO)
# =====================================================

class PreferenciasNotificacionesBase(BaseModel):
    notificaciones_web: bool = True
    notificaciones_email: bool = False
    tipos_permitidos: list = Field(default=[
        "nueva_publicacion",
        "cumpleanios", 
        "cambio_turno",
        "solicitud_pendiente"
    ])
    hora_inicio_silencio: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    hora_fin_silencio: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")


class PreferenciasNotificacionesResponse(PreferenciasNotificacionesBase):
    id: UUID
    usuario_id: UUID
    
    class Config:
        from_attributes = True