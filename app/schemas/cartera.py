# backend/app/schemas/cartera.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import date, datetime
from uuid import UUID


class HorarioItem(BaseModel):
    fecha: str
    dia: int
    dia_semana: str
    turno: str
    turno_texto: str


class EspecialidadResponse(BaseModel):
    id: UUID
    nombre: str
    total_medicos: int


class MedicoResponse(BaseModel):
    medico_dni: str
    medico_nombre: str
    horarios: List[HorarioItem]


class CargaResponse(BaseModel):
    id: UUID
    nombre_archivo: str
    mes: int
    anio: int
    total_medicos: int
    total_especialidades: int
    total_registros: int
    total_errores: int
    estado: str
    created_at: datetime