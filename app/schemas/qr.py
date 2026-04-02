from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID

class QRGenerarRequest(BaseModel):
    empleado_id: UUID
    duracion: Optional[int] = 15000  # 15 segundos por defecto

class QRGenerarResponse(BaseModel):
    qr_data: str
    qr_id: str
    expira_en: datetime

class QRValidarRequest(BaseModel):
    qr_data: str
    tipo: str  # ENTRADA, SALIDA

class QRValidarResponse(BaseModel):
    valido: bool
    empleado_id: Optional[UUID] = None
    empleado_nombre: Optional[str] = None
    tipo: Optional[str] = None
    timestamp: Optional[datetime] = None
    error: Optional[str] = None
    mensaje: Optional[str] = None

class QRActivoResponse(BaseModel):
    activo: bool
    qr_id: Optional[str] = None
    generado_en: Optional[datetime] = None
    expira_en: Optional[datetime] = None