from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import date, datetime
from uuid import UUID

class Domicilio(BaseModel):
    direccion: str
    distrito: str
    provincia: str
    departamento: str
    referencia: Optional[str] = None

class Profesional(BaseModel):
    nombre: str
    colegiatura: str
    especialidad: str
    centro_salud: str

class DescansoMedicoBase(BaseModel):
    paciente_id: UUID
    diagnostico_cie: Optional[str] = None
    diagnostico_desc: str
    fecha_inicio: date
    fecha_fin: date
    dias: int
    domicilio: Domicilio
    profesional: Profesional
    observaciones: Optional[str] = None
    anotaciones: Optional[str] = None

class DescansoMedicoCreate(DescansoMedicoBase):
    pass

class DescansoMedicoUpdate(BaseModel):
    estado: Optional[str] = None
    observaciones: Optional[str] = None
    anotaciones: Optional[str] = None

class DescansoMedicoResponse(DescansoMedicoBase):
    id: UUID
    estado: str
    imagen_url: Optional[str]
    created_at: datetime
    created_by: Optional[UUID]
    paciente_nombre: Optional[str] = None

    class Config:
        from_attributes = True