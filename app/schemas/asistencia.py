from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID

class AsistenciaBase(BaseModel):
    personal_id: UUID
    timestamp: datetime
    tipo: str  # ENTRADA, SALIDA, PAUSA
    tipo_registro: str  # QR, MANUAL
    turno_codigo: Optional[str] = None
    justificacion: Optional[str] = None
    verificado: bool = False

class AsistenciaCreate(AsistenciaBase):
    pass

class AsistenciaQR(BaseModel):
    qr_data: str
    tipo: str  # ENTRADA, SALIDA, PAUSA

class AsistenciaResponse(AsistenciaBase):
    id: UUID
    created_at: datetime
    created_by: Optional[UUID]
    personal_nombre: Optional[str] = None

    class Config:
        from_attributes = True

class JustificacionCreate(BaseModel):
    personal_id: UUID
    fecha_inicio: date
    fecha_fin: date
    motivo: str
    observaciones: Optional[str] = None
    documento_url: Optional[str] = None

class EstadisticasAsistencia(BaseModel):
    fecha: date
    total_personal: int
    presentes: int
    ausentes: int
    tardanzas: int
    porcentaje_asistencia: float

class IncidenciaAsistencia(BaseModel):
    id: UUID
    personal_id: UUID
    personal_nombre: str
    fecha: date
    tipo_incidencia: str
    descripcion: str
    estado: str