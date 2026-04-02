# app/schemas/trazabilidad.py
from pydantic import BaseModel, Field, validator, UUID4
from typing import Optional, List, Dict, Any
from datetime import datetime
import enum

# =====================================================
# ENUMS (igual que en models/trazabilidad.py)
# =====================================================
class AccionTrazabilidad(str, enum.Enum):
    CREACION = "creacion"
    ENVIO = "envio"
    APROBACION = "aprobacion"
    RECHAZO = "rechazo"
    OBSERVACION = "observacion"
    CANCELACION = "cancelacion"
    MODIFICACION = "modificacion"
    VISUALIZACION = "visualizacion"
    DESCARGA_QR = "descarga_qr"
    VALIDACION_QR = "validacion_qr"
    SUBIDA_DOCUMENTO = "subida_documento"
    NOTIFICACION = "notificacion"

# =====================================================
# SCHEMAS BASE
# =====================================================
class TrazabilidadBase(BaseModel):
    """Campos base para crear un registro de trazabilidad"""
    solicitud_id: UUID4
    accion: AccionTrazabilidad
    datos: Dict[str, Any] = Field(default_factory=dict)
    comentario: Optional[str] = Field(None, max_length=500)
    ip_origen: Optional[str] = Field(None, max_length=45)
    user_agent: Optional[str] = Field(None, max_length=255)

class TrazabilidadCreate(TrazabilidadBase):
    """Para crear un nuevo registro de trazabilidad"""
    hash_solicitud: str = Field(..., min_length=64, max_length=64)
    hash_anterior: Optional[str] = Field(None, min_length=64, max_length=64)

# =====================================================
# SCHEMAS DE RESPUESTA
# =====================================================
class TrazabilidadResponse(BaseModel):
    """Respuesta completa de un registro de trazabilidad"""
    id: UUID4
    solicitud_id: UUID4
    accion: AccionTrazabilidad
    usuario_id: UUID4
    hash_solicitud: str
    hash_anterior: Optional[str]
    hash_actual: str
    datos: Dict[str, Any]
    comentario: Optional[str]
    ip_origen: Optional[str]
    user_agent: Optional[str]
    created_at: datetime
    
    # Nombres para mostrar
    usuario_nombre: Optional[str] = None
    usuario_email: Optional[str] = None

    class Config:
        from_attributes = True

# =====================================================
# SCHEMAS PARA CADENA DE TRAZABILIDAD
# =====================================================
class NodoTrazabilidad(BaseModel):
    """Un nodo en la cadena de trazabilidad"""
    id: UUID4
    accion: AccionTrazabilidad
    usuario_nombre: str
    created_at: datetime
    hash_actual: str
    hash_anterior: Optional[str]
    comentario: Optional[str]
    datos_resumen: Dict[str, Any] = Field(default_factory=dict)

class CadenaTrazabilidadResponse(BaseModel):
    """Cadena completa de trazabilidad de una solicitud"""
    solicitud_id: UUID4
    solicitud_tipo: str
    solicitud_estado: str
    nodos: List[NodoTrazabilidad]
    integridad_verificada: Optional[bool] = None
    primer_hash: str
    ultimo_hash: str
    
    class Config:
        from_attributes = True

# =====================================================
# SCHEMA PARA VERIFICACIÓN DE INTEGRIDAD
# =====================================================
class VerificacionIntegridadRequest(BaseModel):
    """Solicitud para verificar integridad de una cadena"""
    solicitud_id: UUID4

class VerificacionIntegridadResponse(BaseModel):
    """Resultado de la verificación de integridad"""
    solicitud_id: UUID4
    es_valida: bool
    nodos_verificados: int
    nodos_corruptos: List[int] = Field(default_factory=list)
    mensaje: Optional[str] = None
    hash_esperado: Optional[str] = None
    hash_actual: Optional[str] = None
    
    class Config:
        from_attributes = True

# =====================================================
# SCHEMA PARA VALIDACIÓN CON QR
# =====================================================
class ValidacionQRRequest(BaseModel):
    """Datos del QR para validar un trámite"""
    qr_data: str  # El string completo del QR
    
    @validator('qr_data')
    def qr_no_vacio(cls, v):
        if not v or not v.strip():
            raise ValueError('El QR no puede estar vacío')
        return v.strip()

class ValidacionQRResponse(BaseModel):
    """Resultado de la validación con QR"""
    valido: bool
    solicitud_id: Optional[UUID4] = None
    mensaje: str
    datos_solicitud: Optional[Dict[str, Any]] = None
    trazabilidad: Optional[List[NodoTrazabilidad]] = None
    verificado_en: datetime = Field(default_factory=datetime.now)

# =====================================================
# SCHEMA PARA CERTIFICADO PDF
# =====================================================
class CertificadoRequest(BaseModel):
    """Solicitud para generar certificado PDF"""
    solicitud_id: UUID4
    incluir_trazabilidad: bool = True
    incluir_qr: bool = True

class CertificadoResponse(BaseModel):
    """Respuesta con URL del certificado generado"""
    solicitud_id: UUID4
    url_pdf: str
    fecha_generacion: datetime
    tamaño_bytes: Optional[int] = None
    
    class Config:
        from_attributes = True

# =====================================================
# SCHEMAS DE FILTROS
# =====================================================
class TrazabilidadFiltros(BaseModel):
    """Para filtrar registros de trazabilidad"""
    solicitud_id: Optional[UUID4] = None
    accion: Optional[AccionTrazabilidad] = None
    usuario_id: Optional[UUID4] = None
    fecha_desde: Optional[datetime] = None
    fecha_hasta: Optional[datetime] = None
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
    
    class Config:
        extra = "forbid"

# =====================================================
# SCHEMAS ESTADÍSTICOS
# =====================================================
class EstadisticasTrazabilidad(BaseModel):
    """Estadísticas de trazabilidad para una solicitud"""
    solicitud_id: UUID4
    total_acciones: int
    tiempo_total_horas: Optional[float]
    acciones_por_tipo: Dict[AccionTrazabilidad, int]
    usuarios_involucrados: List[UUID4]
    primera_accion: datetime
    ultima_accion: datetime

# =====================================================
# EJEMPLO DE USO
# =====================================================
"""
# Crear un registro cuando se aprueba una solicitud
trazabilidad = TrazabilidadCreate(
    solicitud_id="uuid-solicitud",
    accion=AccionTrazabilidad.APROBACION,
    comentario="Aprobado por cumplir requisitos",
    hash_solicitud="hash-del-estado-de-la-solicitud",
    hash_anterior="hash-del-registro-anterior",
    ip_origen="192.168.1.100",
    user_agent="Mozilla/5.0..."
)

# Respuesta de cadena completa
cadena = CadenaTrazabilidadResponse(
    solicitud_id="uuid-solicitud",
    solicitud_tipo="propio",
    solicitud_estado="aprobada",
    nodos=[...],
    integridad_verificada=True,
    primer_hash="hash1",
    ultimo_hash="hashN"
)
"""