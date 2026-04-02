# app/schemas/solicitud.py
from pydantic import BaseModel, Field, validator, UUID4
from typing import Optional, List, Dict, Any, Union
from datetime import date, datetime
import enum
import re

# =====================================================
# ENUMS (igual que en models/solicitud.py)
# =====================================================
class TipoSolicitud(str, enum.Enum):
    PROPIO = "propio"
    INTERCAMBIO = "intercambio"
    PLANIFICACION_MENSUAL = "planificacion_mensual"
    VACACIONES = "vacaciones"
    PERMISO = "permiso"
    DESCANSO_MEDICO = "descanso_medico"
    LICENCIA = "licencia"
    CAPACITACION = "capacitacion"
    OTRO = "otro"

class EstadoSolicitud(str, enum.Enum):
    BORRADOR = "borrador"
    PENDIENTE = "pendiente"
    EN_APROBACION = "en_aprobacion"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"
    OBSERVADA = "observada"
    CANCELADA = "cancelada"

# =====================================================
# DOCUMENTO
# =====================================================
class Documento(BaseModel):
    nombre: str
    url: str
    tipo: str
    fecha_subida: datetime

# =====================================================
# SCHEMAS BASE
# =====================================================
class SolicitudBase(BaseModel):
    """Campos base que puede enviar el cliente"""
    tipo: TipoSolicitud
    fecha_cambio: date
    motivo: str = Field(..., min_length=5, max_length=50)
    observaciones: Optional[str] = Field(None, max_length=500)
    empleado_id: UUID4  # ← AGREGADO (ERA EL ERROR)
    empleado2_id: Optional[UUID4] = None
    
    # Datos específicos según tipo
    datos: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('motivo')
    def motivo_no_vacio(cls, v):
        if not v or not v.strip():
            raise ValueError('El motivo no puede estar vacío')
        return v.strip()
    
    @validator('datos')
    def validar_datos_por_tipo(cls, v, values):
        """Valida que los datos sean correctos según el tipo de solicitud"""
        tipo = values.get('tipo')
        if not tipo:
            return v
        
        if tipo == TipoSolicitud.PROPIO:
            if 'turno_original' not in v:
                raise ValueError('Para cambio propio se requiere turno_original')
            if 'turno_solicitado' not in v:
                raise ValueError('Para cambio propio se requiere turno_solicitado')
        
        elif tipo == TipoSolicitud.INTERCAMBIO:
            campos_requeridos = [
                'turno_original_solicitante',
                'turno_original_colega',
                'turno_solicitante_recibe',
                'turno_colega_recibe'
            ]
            for campo in campos_requeridos:
                if campo not in v:
                    raise ValueError(f'Para intercambio se requiere {campo}')
        
        elif tipo == TipoSolicitud.VACACIONES:
            if 'fecha_inicio' not in v or 'fecha_fin' not in v:
                raise ValueError('Para vacaciones se requiere fecha_inicio y fecha_fin')
        
        elif tipo == TipoSolicitud.DESCANSO_MEDICO:
            if 'fecha_inicio' not in v or 'fecha_fin' not in v or 'diagnostico' not in v:
                raise ValueError('Para descanso médico se requiere fecha_inicio, fecha_fin y diagnostico')
        
        return v

class SolicitudCreate(SolicitudBase):
    """Para crear una nueva solicitud"""
    validacion_dias_libres: Optional[Dict[str, Any]] = None
    documentos: List[Documento] = Field(default_factory=list)

# =====================================================
# SCHEMAS DE ACTUALIZACIÓN
# =====================================================
class SolicitudUpdate(BaseModel):
    """Para actualizar una solicitud (solo en borrador)"""
    fecha_cambio: Optional[date] = None
    motivo: Optional[str] = Field(None, min_length=5, max_length=50)
    observaciones: Optional[str] = Field(None, max_length=500)
    empleado2_id: Optional[UUID4] = None
    datos: Optional[Dict[str, Any]] = None
    documentos: Optional[List[Documento]] = None
    estado: Optional[EstadoSolicitud] = None

class SolicitudUpdateEstado(BaseModel):
    """Para cambiar el estado (aprobar, rechazar, etc)"""
    estado: EstadoSolicitud
    comentario_revision: Optional[str] = Field(None, max_length=500)
    
    @validator('estado')
    def validar_estado_permitido(cls, v):
        estados_permitidos = [
            EstadoSolicitud.APROBADA,
            EstadoSolicitud.RECHAZADA,
            EstadoSolicitud.OBSERVADA,
            EstadoSolicitud.CANCELADA
        ]
        if v not in estados_permitidos:
            raise ValueError(f'Estado no permitido. Debe ser uno de: {[e.value for e in estados_permitidos]}')
        return v

# =====================================================
# SCHEMAS DE RESPUESTA
# =====================================================
class SolicitudResponse(SolicitudBase):
    """Respuesta completa de una solicitud"""
    id: UUID4
    estado: EstadoSolicitud
    empleado_id: UUID4
    nivel_actual: int
    nivel_maximo: int
    validacion_dias_libres: Optional[Dict[str, Any]] = None
    documentos: List[Documento] = []
    meta_datos: Dict[str, Any] = Field(default_factory=dict)  # ← CAMBIADO de 'metadata' a 'meta_datos'
    created_by: UUID4
    created_at: datetime
    updated_at: Optional[datetime] = None
    fecha_revision: Optional[datetime] = None
    revisado_por: Optional[UUID4] = None
    comentario_revision: Optional[str] = None
    fecha_aprobacion: Optional[datetime] = None
    aprobado_por: Optional[UUID4] = None
    
    # Nombres para mostrar (populados en el endpoint)
    empleado_nombre: Optional[str] = None
    empleado2_nombre: Optional[str] = None
    creado_por_nombre: Optional[str] = None
    revisado_por_nombre: Optional[str] = None
    aprobado_por_nombre: Optional[str] = None

    class Config:
        from_attributes = True

# =====================================================
# SCHEMAS DE LISTADO (versión resumida)
# =====================================================
class SolicitudListResponse(BaseModel):
    """Versión resumida para listados"""
    id: UUID4
    tipo: TipoSolicitud
    estado: EstadoSolicitud
    fecha_cambio: date
    fecha_solicitud: datetime
    motivo: str
    empleado_id: UUID4
    empleado_nombre: Optional[str] = None
    nivel_actual: int
    nivel_maximo: int
    
    class Config:
        from_attributes = True

# =====================================================
# SCHEMAS DE FILTROS
# =====================================================
class SolicitudFiltros(BaseModel):
    """Para filtrar solicitudes en listados"""
    tipo: Optional[TipoSolicitud] = None
    estado: Optional[EstadoSolicitud] = None
    empleado_id: Optional[UUID4] = None
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    nivel_actual: Optional[int] = None
    
    class Config:
        extra = "forbid"  # No permitir campos extra