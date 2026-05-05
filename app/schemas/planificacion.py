from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from uuid import UUID

class Turno(BaseModel):
    codigo: str
    nombre: str
    horas: int
    bgColor: str
    textColor: str

class PlanificacionBase(BaseModel):
    personal_id: UUID
    fecha: date
    turno_codigo: Optional[str] = None
    hora_inicio: Optional[str] = None      # 🆕 Hora de inicio (formato HH:MM)
    hora_fin: Optional[str] = None         # 🆕 Hora de fin (formato HH:MM)
    observacion: Optional[str] = None
    dm_info: Optional[Dict[str, Any]] = None

class PlanificacionCreate(PlanificacionBase):
    pass

class PlanificacionMasiva(BaseModel):
    planificaciones: List[PlanificacionCreate]

class PlanificacionResponse(PlanificacionBase):
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime]
    created_by: Optional[UUID]
    personal_nombre: Optional[str] = None

    class Config:
        from_attributes = True

class ObservacionCreate(BaseModel):
    personal_id: UUID
    fecha: date
    observacion: str

class EstadoPlanificacion(BaseModel):
    fecha: date
    total_turnos: int
    turnos_por_tipo: Dict[str, int]
    personal_con_observaciones: List[Dict[str, Any]]