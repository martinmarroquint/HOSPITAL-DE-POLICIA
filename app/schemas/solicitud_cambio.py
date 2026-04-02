# D:\Centro de control Hospital PNP\back\app\schemas\solicitud_cambio.py
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Union
from datetime import date, datetime
from uuid import UUID

class Documento(BaseModel):
    nombre: str
    url: str
    tipo: str
    fecha_subida: datetime

class SolicitudCambioBase(BaseModel):
    tipo: str  # propio, intercambio
    fecha_cambio: date
    motivo: str
    observaciones: Optional[str] = None
    empleado_id: UUID
    empleado2_id: Optional[UUID] = None
    
    # Turnos
    turno_original: Optional[Union[Dict[str, Any], str]] = None
    turno_solicitado: Optional[Union[Dict[str, Any], str]] = None
    
    # Para intercambio
    turno_original_solicitante: Optional[Union[Dict[str, Any], str]] = None
    turno_original_colega: Optional[Union[Dict[str, Any], str]] = None
    turno_solicitante_recibe: Optional[Union[Dict[str, Any], str]] = None
    turno_colega_recibe: Optional[Union[Dict[str, Any], str]] = None

class SolicitudCambioCreate(SolicitudCambioBase):
    validacion_dias_libres: Optional[Dict[str, Any]] = None
    documentos: List[Documento] = []

class SolicitudCambioUpdate(BaseModel):
    estado: str
    comentario_revision: Optional[str] = None

class SolicitudCambioResponse(SolicitudCambioBase):
    id: UUID
    estado: str
    fecha_solicitud: datetime
    validacion_dias_libres: Optional[Dict[str, Any]] = None
    documentos: List[Documento] = []
    historial: List[Dict[str, Any]] = []
    created_by: UUID
    created_at: datetime
    fecha_revision: Optional[datetime] = None
    revisado_por: Optional[UUID] = None
    comentario_revision: Optional[str] = None
    
    # 🆕 CAMPOS DE JERARQUÍA (NUEVOS)
    nivel_actual: Optional[str] = "usuario"
    proximo_nivel: Optional[str] = None
    niveles_pendientes: List[str] = []
    niveles_aprobados: List[str] = []
    
    # Nombres de usuarios
    empleado_nombre: Optional[str] = None
    empleado_grado: Optional[str] = None
    area_nombre: Optional[str] = None
    empleado2_nombre: Optional[str] = None
    empleado2_grado: Optional[str] = None
    revisado_por_nombre: Optional[str] = None

    class Config:
        from_attributes = True